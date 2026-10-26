"""
批量处理工具模块
================

提供两个通用能力，供各区域 processor 复用：

1. ``JsonStore`` —— 线程安全的 JSON 文件缓存。
   旧实现每新增一条缓存就全量重写整个 JSON 文件（.cache.json 已 1MB+），
   缓存越大单次写入越慢，累积 IO 呈 O(N^2)。改为：
     - 写入先进内存（加锁）；
     - 累计 N 条新条目、或每隔 T 秒，由后台线程防抖落盘；
     - atexit 保证进程正常退出前最终落盘；
     - 接口兼容 dict 的 ``in`` / ``[]`` 读写，原调用点几乎零改动。

2. ``run_batch`` —— 保持顺序的行级并发执行器。
   LLM 调用是 IO 密集型，串行处理是最大耗时瓶颈。本执行器：
     - 用滑动窗口提交行任务，输入顺序 = 输出顺序 = 回调顺序；
     - progress_cb / on_row_done 始终在主线程调用（Streamlit 安全）；
     - stop_flag_getter 可随时暂停（未开始的任务会被取消）；
     - max_workers=1 时走串行路径，行为与旧版完全一致。
"""

import atexit
import json
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


# ==================== JsonStore ====================
class JsonStore:
    """线程安全的 JSON 文件存储（防抖批量落盘）。

    用法（与旧 dict 用法兼容）::

        store = JsonStore("fault_mapping.json")
        if key in store:
            return store[key]
        store[key] = value        # 只写内存，自动标记脏
        # 落盘由后台线程 / atexit 自动完成，无需手动调用
    """

    def __init__(self, path, flush_every_n: int = 10, flush_every_sec: float = 10.0):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = {}
        self._dirty = 0
        self._last_flush = time.monotonic()
        self._flush_every_n = flush_every_n
        self._flush_every_sec = flush_every_sec
        self._stop_event = threading.Event()

        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
            except Exception:
                self._data = {}

        # 后台防抖落盘线程（守护线程，随进程退出）
        threading.Thread(target=self._flusher_loop, daemon=True,
                         name=f"jsonstore-flush-{self.path.name}").start()
        # 进程正常退出前最终落盘
        atexit.register(self.flush)

    # ---------- dict 兼容读 ----------
    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def has(self, key) -> bool:
        with self._lock:
            return key in self._data

    def __contains__(self, key) -> bool:
        with self._lock:
            return key in self._data

    def __getitem__(self, key):
        with self._lock:
            return self._data[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def snapshot(self) -> dict:
        """返回内存数据的浅拷贝（调用方自行读，不加锁）。"""
        with self._lock:
            return dict(self._data)

    # ---------- dict 兼容写 ----------
    def put(self, key, value) -> None:
        with self._lock:
            self._data[key] = value
            self._dirty += 1

    def __setitem__(self, key, value) -> None:
        self.put(key, value)

    # ---------- 落盘 ----------
    def flush(self, force: bool = False) -> None:
        """把内存数据写入磁盘。锁内快照、锁外写盘，尽量不阻塞其他线程。"""
        with self._lock:
            if self._dirty == 0 and not force:
                return
            data = dict(self._data)
            self._dirty = 0
            self._last_flush = time.monotonic()
        try:
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            # 缓存写失败不影响主流程，脏标记已清零，下批新条目会带上旧数据重试
            pass

    def _flusher_loop(self) -> None:
        while not self._stop_event.wait(2.0):
            with self._lock:
                due = self._dirty > 0 and (
                    self._dirty >= self._flush_every_n
                    or (time.monotonic() - self._last_flush) >= self._flush_every_sec
                )
            if due:
                self.flush()


# ==================== run_batch ====================
def run_batch(df,
              handle_row,
              max_workers: int = 1,
              progress_cb=None,
              on_row_done=None,
              stop_flag_getter=None) -> list:
    """按顺序处理 DataFrame 的每一行，可选并发。

    参数
    ----
    df : pd.DataFrame
    handle_row : callable(pos, row) -> dict
        单行处理函数，``pos`` 为行序号（从 0 开始）。
        函数内部需自行 try/except 保证不抛异常
        （各区域的错误兜底逻辑不同，由调用方封装）。
    max_workers : int
        并发线程数。<=1 时走串行路径（与旧行为完全一致）。
    progress_cb : callable(done, total)，可选。
    on_row_done : callable(out_dict)，可选。每完成一行调用一次。
    stop_flag_getter : callable() -> bool，可选。返回 True 时停止提交新行，
        已开始运行的行会跑完但结果会被丢弃，尚未开始的行会被取消。

    返回
    ----
    list[dict]：按输入顺序排列的处理结果。
    """
    total = len(df)

    if not max_workers or max_workers <= 1 or total <= 1:
        # ---------- 串行路径 ----------
        results = []
        for pos, (_, row) in enumerate(df.iterrows()):
            if stop_flag_getter and stop_flag_getter():
                break
            out = handle_row(pos, row)
            results.append(out)
            if on_row_done:
                on_row_done(out)
            if progress_cb:
                progress_cb(pos + 1, total)
        return results

    # ---------- 并发路径：滑动窗口提交 + 按顺序消费 ----------
    results = []
    row_iter = iter(df.iterrows())
    pending = deque()
    pos_counter = 0
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        def submit_next() -> bool:
            nonlocal pos_counter
            try:
                _, row = next(row_iter)
            except StopIteration:
                return False
            pending.append(executor.submit(handle_row, pos_counter, row))
            pos_counter += 1
            return True

        # 预热：先填满窗口
        for _ in range(max_workers):
            if not submit_next():
                break

        done = 0
        while pending:
            if stop_flag_getter and stop_flag_getter():
                # 取消尚未开始的行；已在运行的最多 max_workers-1 条会跑完但结果丢弃
                for fut in pending:
                    fut.cancel()
                break
            fut = pending.popleft()
            out = fut.result()          # 按顺序等待，保证输出顺序与输入一致
            results.append(out)
            done += 1
            if on_row_done:
                on_row_done(out)
            if progress_cb:
                progress_cb(done, total)
            submit_next()               # 补充一个任务，维持并发度
    finally:
        executor.shutdown(wait=True)

    return results

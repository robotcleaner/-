"""
二返 / 三返 / 重复 工单分类器
=============================

按 SN 聚合整批工单（可叠加往批历史），判定每行的「返修类别」：

- 首次出现的 SN              → 不打标（保留原类别）
- SN + 日期 均相同           → 「重复」
    （描述 + 维修详情相似度 ≥ 70% 记为完全重复 A，否则为同日重复 D，
      类别同为「重复」）
- SN 相同、日期不同          → 第 2 个日期 → 「二返」，第 3 个及以后 → 「三返」
    与上一次返修的故障类型一致 → 「（重现）」，不一致 → 「（新故障）」

并发流式处理下的设计（配合 run_batch）：
- build_plan 预扫描只依赖原始字段，不依赖 LLM 结果；
- 「重现 / 新故障」需要前驱行的故障类型：
    - 前驱是往批历史行 → 直接使用历史故障类型；
    - 前驱是本批行     → 处理时按需即时计算（LLM 结果有缓存，
      不会重复付费），无需等待前驱完成、无死锁问题；
- 标签在 on_row_done 落盘前就已确定，断点续跑的 CSV 里即最终类别。
"""

import re
import threading
from difflib import SequenceMatcher

SIM_THRESHOLD = 0.7


def normalize_sn(sn) -> str:
    """SN 归一化：去空白、大写。"""
    return str(sn or "").strip().upper()


def normalize_date_str(d) -> str:
    """日期归一化为 'YYYY-MM-DD'；无法解析返回 ''。"""
    if d is None:
        return ""
    s = str(d).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return ""
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
    if m:
        y, mo, dd = m.groups()
        try:
            return f"{int(y):04d}-{int(mo):02d}-{int(dd):02d}"
        except ValueError:
            return ""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def _sim(a: str, b: str) -> float:
    """描述+维修详情的相似度（忽略空白与大小写）。"""
    na = re.sub(r"\s+", "", str(a or "").lower())
    nb = re.sub(r"\s+", "", str(b or "").lower())
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


class RepeatClassifier:
    """返修分类器：预扫描生成结构标签，处理阶段补故障对比后缀。"""

    def __init__(self, history=None, sim_threshold: float = SIM_THRESHOLD):
        """
        参数
        ----
        history : list[dict]，往批已处理行，键为
                  sn / date / desc / detail / fault（desc/detail 可省）
        sim_threshold : float，「完全重复」的相似度阈值（默认 0.7）
        """
        self.threshold = sim_threshold
        self._by_sn = {}
        self._lock = threading.Lock()
        for rec in (history or []):
            sn = normalize_sn(rec.get("sn"))
            date = normalize_date_str(rec.get("date"))
            if not sn or not date:
                continue
            self._by_sn.setdefault(sn, []).append({
                "date": date,
                "desc": str(rec.get("desc") or ""),
                "detail": str(rec.get("detail") or ""),
                "fault": str(rec.get("fault") or "").strip(),
                "pos": None,          # 历史行不在本批
            })

    # ------------------------------------------------------------------
    def build_plan(self, records):
        """预扫描本批行，生成每行的返修标签计划。

        参数
        ----
        records : list[dict]，本批全部行（按文件顺序），键为
                  pos / sn / date / desc / detail（均为原始字段）

        返回
        ----
        dict: {pos: {
            'label':      None | '重复' | '二返' | '三返',
            'pred_pos':   前驱行在本批的 pos（前驱为历史行则 None），
            'pred_fault': 前驱行的故障类型（前驱为历史行时已知，否则 None），
            'case':       'A' | 'D' | None（完全重复 / 同日重复，仅供分析），
        }}
        """
        plan = {}
        batch = {}   # sn -> [occurrence]（本批已登记行）

        # 按日期顺序扫描：即使文件未按日期排序，前驱关系也按日期判定
        ordered = sorted(
            records,
            key=lambda r: (normalize_date_str(r.get("date")) or "9999-99-99",
                           r.get("pos", 0)),
        )

        for rec in ordered:
            pos = rec.get("pos")
            sn = normalize_sn(rec.get("sn"))
            date = normalize_date_str(rec.get("date"))
            desc = str(rec.get("desc") or "")
            detail = str(rec.get("detail") or "")

            if not sn or not date:
                plan[pos] = {"label": None, "pred_pos": None,
                             "pred_fault": None, "case": None}
                continue

            preds = self._by_sn.get(sn, []) + batch.get(sn, [])
            same_date = [p for p in preds if p["date"] == date]

            if same_date:
                # —— A / D：SN + 日期相同 ——
                best = max(_sim(desc + "\n" + detail,
                                p["desc"] + "\n" + p["detail"])
                           for p in same_date)
                plan[pos] = {
                    "label": "重复",
                    "pred_pos": None,
                    "pred_fault": None,
                    "case": "A" if best >= self.threshold else "D",
                }
            elif preds:
                # —— B / C：SN 相同、日期不同 ——
                pred = sorted(preds, key=lambda p: p["date"])[-1]
                distinct_dates = len({p["date"] for p in preds} | {date})
                plan[pos] = {
                    "label": "三返" if distinct_dates >= 3 else "二返",
                    "pred_pos": pred["pos"],
                    "pred_fault": pred["fault"] if pred["pos"] is None else None,
                    "case": None,
                }
            else:
                # —— 首次出现 ——
                plan[pos] = {"label": None, "pred_pos": None,
                             "pred_fault": None, "case": None}

            batch.setdefault(sn, []).append(
                {"date": date, "desc": desc, "detail": detail,
                 "fault": "", "pos": pos})

        return plan

    # ------------------------------------------------------------------
    @staticmethod
    def resolve_label(base_label: str, fault: str, pred_fault) -> str:
        """给 二返 / 三返 补（重现）/（新故障）后缀。"""
        if base_label not in ("二返", "三返"):
            return base_label
        f = str(fault or "").strip()
        pf = str(pred_fault or "").strip()
        if f and pf and f == pf:
            return base_label + "（重现）"
        return base_label + "（新故障）"


def apply_label(out: dict, pos, plan: dict, rows_snapshot: list,
                process_row_fn, fault_getter=None) -> dict:
    """把返修标签应用到已处理的行上（就地修改 out['类别']）。

    参数
    ----
    out : 已处理的行 dict（含 故障类型（一级） / 类别）
    pos : 该行在本批中的序号
    plan : RepeatClassifier.build_plan 的返回值
    rows_snapshot : [(idx, row), ...] 本批全部原始行（用于按需计算前驱故障）
    process_row_fn : callable(row) -> dict，区域自身的单行处理函数
                     （LLM 有缓存，按需重算不会重复付费）
    fault_getter : callable(pos) -> str | None，可选，查本批已完成行的故障类型
    """
    info = plan.get(pos)
    if not info or not info.get("label"):
        return out

    label = info["label"]
    if label in ("二返", "三返"):
        pred_fault = info.get("pred_fault")
        if not pred_fault:
            pred_pos = info.get("pred_pos")
            if fault_getter is not None:
                try:
                    pred_fault = fault_getter(pred_pos)
                except Exception:
                    pred_fault = None
            if not pred_fault and pred_pos is not None \
                    and 0 <= pred_pos < len(rows_snapshot):
                # 前驱行尚未处理完成：按需即时计算（结果进 LLM 缓存，
                # 前驱行真正被处理时直接命中缓存，不重复付费）
                try:
                    pred_out = process_row_fn(rows_snapshot[pred_pos][1])
                    pred_fault = str(
                        pred_out.get("故障类型（一级）", "") or "").strip()
                except Exception:
                    pred_fault = ""
        label = RepeatClassifier.resolve_label(
            label, out.get("故障类型（一级）", ""), pred_fault)

    out["类别"] = label
    # 标记同步追加到「处理方式」列：重复 / 二返（重现） / 更换备件
    # （保留原处理方式，便于在工单表里直接按处理方式筛出返修单）
    out["处理方式"] = merge_method(out.get("处理方式", ""), label)
    return out


# ==================== 处理方式列合并 ====================
_REPEAT_NUM = "二三四五六七八九十"


def is_repeat_label(val) -> bool:
    """判断是否为返修类标签（重复 / 二返 / 三返 / 四返…）。"""
    s = str(val or "").strip()
    if not s:
        return False
    if s == "重复":
        return True
    return len(s) >= 2 and s[0] in _REPEAT_NUM and s[1] == "返"


def merge_method(method, label) -> str:
    """把返修标签追加到处理方式前面，幂等（已含则替换，不叠加）。"""
    m = str(method or "").strip()
    lb = str(label or "").strip()
    if not is_repeat_label(lb):
        return m

    # 先剥掉已有的返修标记（可能来自处理阶段的类别列），避免「二返 / 重复 / …」
    base = m
    if " / " in m:
        head, rest = m.split(" / ", 1)
        if is_repeat_label(head):
            base = rest.strip()
    elif is_repeat_label(m):
        base = ""

    if not base:
        return lb
    return f"{lb} / {base}"


def backfill_method_marks(df, label_col: str = "类别",
                          method_col: str = "处理方式"):
    """把已有结果里「类别」的返修标签补写进「处理方式」（纯字符串，无 LLM）。

    返回 (新 DataFrame, 被补写的行数)。用于断点文件里改造前生成的历史行。
    """
    if label_col not in df.columns or method_col not in df.columns:
        return df, 0
    labels = df[label_col].tolist()
    methods = df[method_col].tolist()
    changed = 0
    for i, (m, lb) in enumerate(zip(methods, labels)):
        new_m = merge_method(m, lb)
        old_m = "" if m is None or (isinstance(m, float) and m != m) else str(m).strip()
        if new_m != old_m:
            methods[i] = new_m
            changed += 1
    if changed:
        df = df.copy()
        df[method_col] = methods
    return df, changed


def relabel_repeat(df, label_col: str = "类别", method_col: str = "处理方式",
                   date_col: str = "日期", sn_col: str = "SN",
                   desc_col: str = "故障描述", detail_col: str = "维修详情",
                   fault_col: str = "故障类型（一级）"):
    """用当前规则重判已有结果里的返修标签（纯本地计算，不调 LLM）。

    背景：断点文件是多次运行累积的，早期版本（没有「同 SN 同日 → 重复」规则）
    留下的标签会一直保留，导致本该是「重复」的单显示成「二返」。

    规则与处理阶段完全一致：
      - 同 SN + 同日期                    → 重复
      - 同 SN + 不同日期，第 2/3+ 个日期   → 二返 / 三返
        与前驱故障类型一致 →（重现），否则（新故障）

    保守策略：新规则判定为「首现」（无标签）时**保留原值**，避免把基类
    （保内/保外/DOA/NFF）误清空。

    返回 (新 DataFrame, 修正行数, 修正明细列表)。
    """
    need = [label_col, date_col, sn_col]
    if any(c not in df.columns for c in need):
        return df, 0, []

    def _col(name):
        return df[name].tolist() if name in df.columns else [""] * len(df)

    sns, dates = _col(sn_col), _col(date_col)
    descs, details, faults = _col(desc_col), _col(detail_col), _col(fault_col)

    records = [{"pos": i, "sn": sns[i], "date": dates[i],
                "desc": descs[i], "detail": details[i]}
               for i in range(len(df))]
    plan = RepeatClassifier().build_plan(records)

    labels = ["" if v is None else str(v).strip() for v in df[label_col].tolist()]
    methods = ["" if v is None else str(v).strip() for v in _col(method_col)]
    changed, details_out = 0, []

    for pos, info in plan.items():
        new = info.get("label")
        if not new:
            continue          # 首现：保留原值
        if new in ("二返", "三返"):
            pred_fault = info.get("pred_fault")
            if not pred_fault:
                pred_pos = info.get("pred_pos")
                if pred_pos is not None and 0 <= pred_pos < len(faults):
                    pred_fault = faults[pred_pos]
            new = RepeatClassifier.resolve_label(new, faults[pos], pred_fault)

        if new == labels[pos]:
            continue
        details_out.append({"工单号": _col("工单号")[pos] if "工单号" in df.columns else "",
                            "SN": sns[pos], "日期": dates[pos],
                            "原标签": labels[pos], "新标签": new})
        labels[pos] = new
        if method_col in df.columns:
            methods[pos] = merge_method(methods[pos], new)
        changed += 1

    if changed:
        df = df.copy()
        df[label_col] = labels
        if method_col in df.columns:
            df[method_col] = methods
    return df, changed, details_out

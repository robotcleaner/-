# -*- coding: utf-8 -*-
"""一键备份：把「不在 git 里」的运行时数据打包成带日期的 zip。

为什么需要它
------------
这三类文件按规矩不进 git（含真实工单 / 缓存 / 密钥），因此是**唯一副本**，
误删之后没法从 GitHub 找回来：

    state/partial_result_*.csv   断点续跑结果（真实工单，含 SN）
    state/.cache.json            LLM 翻译缓存（重跑要花钱）
    data/fault_mapping*.json     故障对照表缓存

用法
----
    python tools/backup.py                备份到 backup/，保留最近 10 份
    python tools/backup.py --keep 20      保留最近 20 份
    python tools/backup.py --out D:/bak   指定输出目录
    python tools/backup.py --list         只看现有备份，不备份

双击根目录的 backup.bat 等价于第一种用法。
"""
import argparse
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
DATA_DIR = ROOT / "data"
DEFAULT_OUT = ROOT / "backup"
DEFAULT_KEEP = 10
PREFIX = "backup_"


def collect_files():
    """返回要备份的 [(绝对路径, zip 内相对路径), ...]。"""
    items = []

    if STATE_DIR.is_dir():
        for p in sorted(STATE_DIR.iterdir()):
            if p.is_file() and not p.name.endswith(".tmp"):
                items.append((p, f"state/{p.name}"))

    if DATA_DIR.is_dir():
        for p in sorted(DATA_DIR.glob("fault_mapping*.json")):
            if p.is_file():
                items.append((p, f"data/{p.name}"))

    return items


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def make_backup(out_dir: Path, keep: int) -> Path | None:
    files = collect_files()
    if not files:
        print("  没有找到可备份的数据（state/ 和 data/ 都是空的？）")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"{PREFIX}{stamp}.zip"

    total = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, arc in files:
            try:
                zf.write(src, arc)
                total += src.stat().st_size
            except Exception as exc:                      # noqa: BLE001
                print(f"  [跳过] {arc}：{exc}")

    size = target.stat().st_size
    print(f"  已备份 {len(files)} 个文件（原始 {human(total)} → 压缩后 {human(size)}）")
    print(f"  文件：{target}")

    prune(out_dir, keep)
    return target


def prune(out_dir: Path, keep: int) -> None:
    """只保留最新的 keep 份，其余删除。"""
    olds = sorted(out_dir.glob(f"{PREFIX}*.zip"), key=lambda p: p.name, reverse=True)
    extra = olds[keep:]
    for p in extra:
        try:
            p.unlink()
            print(f"  已清理旧备份：{p.name}")
        except Exception as exc:                          # noqa: BLE001
            print(f"  [清理失败] {p.name}：{exc}")


def list_backups(out_dir: Path) -> None:
    if not out_dir.is_dir():
        print(f"  还没有备份目录：{out_dir}")
        return
    items = sorted(out_dir.glob(f"{PREFIX}*.zip"), key=lambda p: p.name, reverse=True)
    if not items:
        print("  还没有任何备份。")
        return
    print(f"  现有 {len(items)} 份备份（{out_dir}）：")
    for p in items:
        ts = p.stat().st_mtime
        when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        print(f"    {p.name}   {human(p.stat().st_size)}   {when}")


def restore_hint(zip_path: Path) -> None:
    print()
    print("  恢复方法：把 zip 里的 state/ 和 data/ 解压回项目根目录覆盖即可。")
    print(f"  （即解压到：{ROOT}）")


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="备份 state/ 与 data/ 的运行时数据")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录（默认项目下 backup/）")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="保留最近几份（默认 10）")
    ap.add_argument("--list", action="store_true", help="只列出已有备份")
    args = ap.parse_args()

    out_dir = Path(args.out).expanduser()

    print()
    print("  " + "=" * 52)
    print("    数据备份：断点结果 / 翻译缓存 / 故障对照表")
    print("  " + "=" * 52)
    print()

    if args.list:
        list_backups(out_dir)
        print()
        return 0

    target = make_backup(out_dir, max(1, args.keep))
    if target is None:
        return 1

    print()
    list_backups(out_dir)
    restore_hint(target)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

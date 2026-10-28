"""断点文件（partial_result*.csv）日期口径修正。

背景：断点文件里的行是历史运行结果。如果日期口径变过（例如澳洲从
"创建日期" 改成 "Auxiliary Field: Closed Date"），续跑时这些旧行会被
原样复用，导出的日期仍然是旧口径。

做法：按【当前口径】从本次上传的源表重新取一次日期，按工单号回填到
断点数据里。不调用大模型、成本为零、幂等（重复执行结果一致）。
"""
from __future__ import annotations

import pandas as pd


def _rules(region: str):
    """返回 (源表工单号列名, 日期提取函数)；不支持的地区返回 None。"""
    if region.startswith("澳洲"):
        from processor import get_ticket_date
        return "Ticket Number", get_ticket_date
    if "KOLON" in region:
        from processor_kolon import get_ticket_date_kolon
        return "접수번호", get_ticket_date_kolon
    if "ITC" in region:
        from processor_itc import get_ticket_date_itc
        return "RMA", get_ticket_date_itc
    if "NGK" in region or "日本" in region:
        from processor_jp import get_ticket_date_jp
        return "RMA", get_ticket_date_jp
    from processor_kr import get_ticket_date_kr
    return "접수번호", get_ticket_date_kr


def refresh_partial_dates(partial_df, df_raw, region: str):
    """把断点文件中的「日期」按当前口径刷新一遍。

    返回 (新 partial_df, 被修正的行数)。无法匹配的行保持原值。
    """
    if partial_df is None or len(partial_df) == 0:
        return partial_df, 0
    if df_raw is None or len(df_raw) == 0:
        return partial_df, 0
    if "日期" not in partial_df.columns or "工单号" not in partial_df.columns:
        return partial_df, 0

    try:
        src_ticket_col, date_fn = _rules(region)
    except Exception:
        return partial_df, 0
    if src_ticket_col not in df_raw.columns:
        return partial_df, 0

    # 源表：工单号 → 当前口径日期
    mapping = {}
    for _, row in df_raw.iterrows():
        tid = str(row.get(src_ticket_col, "") or "").strip()
        if not tid or tid.lower() in ("nan", "none", "nat"):
            continue
        d = date_fn(row)
        if d:
            mapping[tid] = d
    if not mapping:
        return partial_df, 0

    tickets = [str(t or "").strip() for t in partial_df["工单号"].tolist()]
    dates = list(partial_df["日期"].tolist())
    changed = 0
    for i, tid in enumerate(tickets):
        new_date = mapping.get(tid)
        if not new_date:
            continue
        old = "" if dates[i] is None else str(dates[i]).strip()
        if old in ("", "nan", "NaT"):
            old = ""
        if old != new_date:
            dates[i] = new_date
            changed += 1

    if changed:
        partial_df = partial_df.copy()
        partial_df["日期"] = dates
    return partial_df, changed


def write_partial(partial_df, path) -> bool:
    """把修正后的断点数据原子写回文件（避免写到一半损坏）。"""
    import os

    tmp = f"{path}.tmp"
    try:
        partial_df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, str(path))
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False

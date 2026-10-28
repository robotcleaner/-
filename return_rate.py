# -*- coding: utf-8 -*-
"""二返率计算（移植自「二返率计算/2.py」）。

与处理阶段的 RepeatClassifier 的区别：
- RepeatClassifier 用于**生成**类别列（同 SN 同日 → 重复；异日第 2/3 次 → 二返/三返）；
- 本模块用于**事后统计**：对已处理结果按 SN + 日期重新判定
  重复 / 二返 / 三返，并输出型号维度的二返率。

判定规则（按优先级）：
1. 完全重复：同 SN、同日期、同故障描述、同维修详情 → 重复
2. 窗口内重复：同 SN，日期间隔 ≤ dup_window_days（默认 5 天）→ 重复
3. 返修：同 SN，历史日期在 return_window_days（默认 90 天）内且间隔 > dup_window_days
   → 二返 / 三返 / 四返…；故障类型与历史一致时加「（故障重现）」
4. 其余：不标记

命令行用法（保持原脚本习惯）：
    python return_rate.py 已处理工单.xlsx
    python return_rate.py 已处理工单.xlsx -o 输出目录 --dup-days 5 --return-days 90
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

# 判定用到的标准列
COL_SN = "SN"
COL_DATE = "日期"
COL_DESC = "故障描述"
COL_DETAIL = "维修详情"
COL_FAULT = "故障类型（一级）"
COL_METHOD = "处理方式"
COL_MODEL = "型号"
COL_TICKET = "工单号"

MARK_COL = "处理标记"
RELATED_COL = "关联工单号"

_CN_NUM = {1: "二", 2: "三", 3: "四", 4: "五", 5: "六",
           6: "七", 7: "八", 8: "九", 9: "十"}

_SKIP_SN = ("", "nan", "none", "nat", "spare part")


# ==================== 日期 ====================
def normalize_date_any(val):
    """各种格式 → 'YYYY-MM-DD'；无法解析返回 None。"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, (int, float)):
        try:
            return (pd.Timestamp("1899-12-30")
                    + pd.Timedelta(days=int(val))).strftime("%Y-%m-%d")
        except Exception:
            return None
    s = str(val).strip()
    if s in ("", "nan", "None", "NaT"):
        return None
    # 兼容「2026/10/06 10:10:39 am」这类带时间与时段的写法
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d",
                "%d/%m/%Y", "%Y.%m.%d", "%Y年%m月%d日",
                "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    try:
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def _s(val) -> str:
    """安全转字符串（NaN → ''）。"""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()


# ==================== 分类 ====================
def classify_return(df: pd.DataFrame,
                    dup_window_days: int = 5,
                    return_window_days: int = 90,
                    overwrite_method: bool = False) -> pd.DataFrame:
    """给已处理结果打「重复 / 二返 / 三返」标记。

    Args:
        df: 已处理的标准化工单表（需含 SN / 日期 / 故障描述 / 维修详情 /
            故障类型（一级）/ 工单号 / 型号 等列，缺失列按空值处理）。
        dup_window_days: 同 SN 日期间隔 ≤ 该值视为重复。
        return_window_days: 返修判定的历史回看窗口。
        overwrite_method: True 时用标记覆盖「处理方式」列（与原脚本一致）。

    Returns:
        新 DataFrame，含 MARK_COL（处理标记）与 RELATED_COL（关联工单号）。
    """
    work = df.reset_index(drop=True).copy()
    for col in (COL_SN, COL_DATE, COL_DESC, COL_DETAIL, COL_FAULT,
                COL_TICKET, COL_MODEL, COL_METHOD):
        if col not in work.columns:
            work[col] = ""

    work["_dt"] = pd.to_datetime(
        work[COL_DATE].apply(normalize_date_any), errors="coerce")
    work["_pos"] = range(len(work))

    marks = [""] * len(work)
    related = [""] * len(work)

    # 按日期升序扫描（无日期的排最后），保证「第几次出现」顺序正确
    order = work.sort_values(["_dt", "_pos"], na_position="last")["_pos"].tolist()

    sn_records: dict[str, list[dict]] = {}

    for pos in order:
        row = work.iloc[pos]
        sn_key = _s(row[COL_SN]).lower()
        if sn_key in _SKIP_SN:
            continue

        date = row["_dt"]
        desc = _s(row[COL_DESC])
        repair = _s(row[COL_DETAIL])
        fault_type = _s(row[COL_FAULT])
        ticket = _s(row[COL_TICKET])

        prior = sn_records.get(sn_key, [])

        # ① 完全重复：同日期 + 同描述 + 同维修详情
        is_exact_dup = any(
            r["date"] == date and r["desc"] == desc and r["repair"] == repair
            for r in prior
        )

        # ② 窗口内重复
        is_within_dup_window = False
        dup_tickets = []
        if pd.notna(date):
            for r in prior:
                if r["date"] is not None and pd.notna(r["date"]):
                    if abs((date - r["date"]).days) <= dup_window_days:
                        is_within_dup_window = True
                        if r["ticket"]:
                            dup_tickets.append(r["ticket"])

        # ③ 返修窗口内的历史（用于二返/三返）
        prior_in_window = []
        if pd.notna(date):
            start = date - pd.Timedelta(days=return_window_days)
            prior_in_window = [
                r for r in prior
                if r["date"] is not None and pd.notna(r["date"])
                and start <= r["date"] < date
            ]

        prior_dates_for_return = set()
        return_tickets = []
        if pd.notna(date):
            for r in prior_in_window:
                if abs((date - r["date"]).days) > dup_window_days:
                    prior_dates_for_return.add(r["date"])
                    if r["ticket"]:
                        return_tickets.append(r["ticket"])

        # 判定优先级：完全重复 > 窗口内重复 > 返修
        if is_exact_dup or is_within_dup_window:
            marks[pos] = "重复"
            if dup_tickets:
                related[pos] = " / ".join(dict.fromkeys(dup_tickets))
        elif len(prior_dates_for_return) >= 1:
            return_no = len(prior_dates_for_return) + 1
            label = _CN_NUM.get(return_no - 1, f"第{return_no}次")
            prior_faults = {
                r["fault_type"] for r in prior_in_window
                if abs((date - r["date"]).days) > dup_window_days
            }
            if fault_type and fault_type in prior_faults:
                marks[pos] = f"{label}返（故障重现）"
            else:
                marks[pos] = f"{label}返"
            if return_tickets:
                related[pos] = " / ".join(dict.fromkeys(return_tickets))

        sn_records.setdefault(sn_key, []).append({
            "date": date, "desc": desc, "repair": repair,
            "fault_type": fault_type, "ticket": ticket,
        })

    work[MARK_COL] = marks
    work[RELATED_COL] = related
    work = work.drop(columns=["_dt", "_pos"])

    if overwrite_method:
        original = work[COL_METHOD].astype(str).where(work[COL_METHOD].notna(), "")
        work[COL_METHOD] = [m if m else o for m, o in zip(marks, original)]

    return work


# ==================== 统计 ====================
def calc_return_rate(df_result: pd.DataFrame) -> pd.DataFrame:
    """按型号统计返修率 / 二返率 / 重复率。"""
    stats = df_result.copy()
    if MARK_COL in stats.columns:
        mark = stats[MARK_COL].fillna("").astype(str)
    else:
        mark = pd.Series([""] * len(stats), index=stats.index)
    stats["_is_return"] = mark.str.contains("返", na=False)
    stats["_is_second"] = mark.str.startswith("二返", na=False)
    stats["_is_dup"] = mark.eq("重复")

    if COL_MODEL in stats.columns:
        model = stats[COL_MODEL].astype(str).str.strip()
    else:
        model = pd.Series([""] * len(stats), index=stats.index)
    stats["_model"] = [m if m and m != "nan" else "(未识别)" for m in model]

    if COL_TICKET not in stats.columns:
        stats[COL_TICKET] = ""

    grouped = stats.groupby("_model").agg(
        总工单数=(COL_TICKET, "count"),
        返修数=("_is_return", "sum"),
        二返数=("_is_second", "sum"),
        重复数=("_is_dup", "sum"),
    ).reset_index().rename(columns={"_model": COL_MODEL})

    total = grouped["总工单数"].replace(0, pd.NA)
    grouped["返修率(%)"] = (grouped["返修数"] / total * 100).round(2)
    grouped["二返率(%)"] = (grouped["二返数"] / total * 100).round(2)
    grouped["重复率(%)"] = (grouped["重复数"] / total * 100).round(2)
    grouped = grouped.sort_values(["返修数", "总工单数"], ascending=False)
    return grouped.reset_index(drop=True)


def build_detail(df_result: pd.DataFrame) -> pd.DataFrame:
    """仅保留被标记为 重复/二返/三返… 的明细行。

    排序：先按标记归组（重复 → 二返 → 三返 → …），组内按 SN + 日期，
    这样「重复」不会被混在二返里看不见。
    """
    if MARK_COL not in df_result.columns:
        return df_result.head(0)
    marked = df_result[df_result[MARK_COL].fillna("").astype(str) != ""].copy()
    mark = marked[MARK_COL].fillna("").astype(str)

    # 组序：重复 0；二返 1；三返 2；四返 3 …（按「返」前的汉字次数不好推，
    # 直接用出现顺序：重复最前，其余按标记文本稳定排序）
    marked["_grp"] = mark.map(lambda m: 0 if m == "重复" else 1)
    marked["_ord"] = mark.map(
        lambda m: {"重复": 0, "二返": 2, "三返": 3, "四返": 4,
                   "五返": 5, "六返": 6}.get(m[:2], 9))

    cols = [COL_TICKET, "区域", "代理", COL_MODEL, "产品BU", COL_DATE, COL_SN,
            COL_FAULT, COL_DESC, COL_DETAIL, COL_METHOD, MARK_COL, RELATED_COL]
    cols = [c for c in cols if c in marked.columns]

    sort_keys = ["_grp", "_ord"]
    if COL_SN in marked.columns:
        sort_keys.append(COL_SN)
    if COL_DATE in marked.columns:
        sort_keys.append(COL_DATE)
    marked = marked.sort_values(sort_keys, kind="stable")
    return marked[cols].reset_index(drop=True)


def mark_breakdown(df_result: pd.DataFrame) -> pd.DataFrame:
    """标记分布小表（重复 / 二返 / 三返 … 各多少条）。"""
    if MARK_COL not in df_result.columns:
        return pd.DataFrame(columns=[MARK_COL, "工单数", "占比(%)"])
    mark = df_result[MARK_COL].fillna("").astype(str)
    marked = mark[mark != ""]
    if marked.empty:
        return pd.DataFrame(columns=[MARK_COL, "工单数", "占比(%)"])
    total = len(df_result)
    out = (marked.value_counts().rename_axis(MARK_COL)
           .reset_index(name="工单数"))
    out["占比(%)"] = (out["工单数"] / total * 100).round(2)
    return out


def summarize(df_result: pd.DataFrame) -> dict:
    """整体汇总（用于界面指标卡）。"""
    total = len(df_result)
    mark = (df_result[MARK_COL].fillna("").astype(str)
            if MARK_COL in df_result.columns else pd.Series([""] * total))
    return_count = int(mark.str.contains("返").sum())
    second_count = int(mark.str.startswith("二返").sum())
    dup_count = int(mark.eq("重复").sum())
    pct = (lambda n: round(n / total * 100, 2) if total else 0.0)
    return {
        "总工单数": total,
        "返修数": return_count,
        "返修率(%)": pct(return_count),
        "二返数": second_count,
        "二返率(%)": pct(second_count),
        "重复数": dup_count,
        "重复率(%)": pct(dup_count),
    }


# ==================== 命令行（保持原脚本用法）====================
def _read_any(path: str) -> pd.DataFrame:
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")
    return pd.read_excel(path)


def main():
    parser = argparse.ArgumentParser(
        description="二返率计算：对已处理工单统计 重复 / 二返 / 三返",
    )
    parser.add_argument("input", nargs="?", default=None, help="已处理工单 xlsx/csv")
    parser.add_argument("-o", "--output-dir", default=".", help="输出目录")
    parser.add_argument("--dup-days", type=int, default=5,
                        help="重复判定窗口天数（默认 5）")
    parser.add_argument("--return-days", type=int, default=90,
                        help="返修判定窗口天数（默认 90）")
    args = parser.parse_args()

    if not args.input or not os.path.exists(args.input):
        print("用法: python return_rate.py <已处理工单.xlsx> [-o 输出目录]")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    df = _read_any(args.input)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"读取 {args.input}：{len(df)} 行")

    result = classify_return(df, args.dup_days, args.return_days)
    detail = build_detail(result)
    rate = calc_return_rate(result)
    info = summarize(result)

    out = args.output_dir
    result.drop(columns=[MARK_COL, RELATED_COL], errors="ignore").to_excel(
        os.path.join(out, "二返重复_处理结果.xlsx"), index=False)
    detail.to_excel(os.path.join(out, "二返重复_明细报告.xlsx"), index=False)
    rate.to_excel(os.path.join(out, "二返率统计.xlsx"), index=False)

    print("\n===== 汇总 =====")
    for k, v in info.items():
        print(f"{k}: {v}")
    print(f"\n已输出到 {os.path.abspath(out)}")


if __name__ == "__main__":
    main()

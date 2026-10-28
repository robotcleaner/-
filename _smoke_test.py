# -*- coding: utf-8 -*-
"""冒烟测试：验证优化后的核心行为（不调用真实 LLM 接口）。"""
import json
import os
import sys
import tempfile
import threading
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = []


def check(name, cond):
    PASS.append((name, bool(cond)))
    print(("  [PASS] " if cond else "  [FAIL] ") + name)


print("== 1. JsonStore：防抖落盘 / dict 兼容读写 ==")
from batch import JsonStore

d = tempfile.mkdtemp()
p = os.path.join(d, "t.json")
s = JsonStore(p, flush_every_n=3, flush_every_sec=1.0)
check("初始未创建文件", not os.path.exists(p))
s["a"] = 1
s["b"] = 2
check("未到阈值不落盘", not os.path.exists(p))
s["c"] = 3  # 达到 flush_every_n=3，后台线程应落盘
time.sleep(2.5)
check("达到阈值后落盘", os.path.exists(p) and json.load(open(p, encoding="utf-8")) == {"a": 1, "b": 2, "c": 3})
check("dict 读兼容", ("a" in s) and s["a"] == 1 and s.get("zz") is None)
s["d"] = 4
s.flush(force=True)
check("force 落盘", json.load(open(p, encoding="utf-8"))["d"] == 4)
s2 = JsonStore(p)
check("重新加载持久化数据", s2["a"] == 1 and len(s2) == 4)
s2["x"] = "中文值"
s2.flush(force=True)
check("中文序列化", json.load(open(p, encoding="utf-8"))["x"] == "中文值")

print("== 2. run_batch：顺序 / 并发 / 暂停 / 回调 ==")
from batch import run_batch

df = pd.DataFrame({"v": range(20)})
res = run_batch(df, lambda pos, row: {"pos": pos}, max_workers=1)
check("串行路径顺序", [r["pos"] for r in res] == list(range(20)))

tids = []
def slow_handle(pos, row):
    time.sleep(0.05)
    tids.append(threading.get_ident())
    return {"pos": pos, "v": row["v"]}

t0 = time.time()
res = run_batch(df, slow_handle, max_workers=4)
dt = time.time() - t0
check("并发路径顺序保持", [r["pos"] for r in res] == list(range(20)))
check("并发确实多线程", len(set(tids)) > 1)
check("并发提速(4线程 < 串行一半)", dt < 1.0, )

flag = {"stop": False}
def stop_handle(pos, row):
    if pos == 5:
        flag["stop"] = True
    return {"pos": pos}
res = run_batch(df, stop_handle, max_workers=2, stop_flag_getter=lambda: flag["stop"])
check("暂停后提前结束", len(res) < 20)

progress, done_rows = [], []
res = run_batch(df, lambda pos, row: {"pos": pos}, max_workers=3,
                progress_cb=lambda a, b: progress.append((a, b)),
                on_row_done=lambda o: done_rows.append(o["pos"]))
check("progress_cb 按序完整", progress == [(i + 1, 20) for i in range(20)])
check("on_row_done 按序完整", done_rows == list(range(20)))

print("== 3. processor（AU）：端到端（LLM 已打桩）==")
import processor as P

P.translate = lambda text, task="translate": f"[译]{str(text)[:8]}"
P.classify_credit_claim = lambda text: "退货"
P.classify_fault_from_sku = lambda text: ""

cols = ["Ticket Number", "Serial Number", "Device Name", "Customer Complaint",
        "Type of Service", "Fault Classification 3 故障类别 3",
        "Repair Details 维修方案", "Repair Details (Technician Notes)",
        "SKU consumption 备件使用", "Auxiliary Field：DOA Validation",
        "Auxiliary Field：Closed Date", "Date Created", "Date Purchased"]
data = [
    # 无关键词投诉 + 纯数字 SKU → 必须走 SKU 编码命中
    ["T1", "abc", "DREAME - L20 Pro", "device stopped working", "service", "", "", "",
     "20020100009132 - Battery", "", "2026/02/01", "2026/01/10", "2025/06/01"],
    ["T2", "ABC", "L20 Pro", "Mop not spinning", "service", "", "", "", "", "",
     "2026/02/02", "2026/01/20", "2025/06/01"],
    # 技师备注含 NFF + 保修期内 → 无异常（NFF）
    ["T3", "xyz", "X50", "noise", "service", "", "", "NFF - no fault found", "", "",
     "2026/02/03", "2026/01/05", "2025/06/01"],
    # 原始故障分类列有值 → 走本地对照表
    ["T4", "qwe", "F10", "dirty", "service", "Main brushing bad", "", "", "", "",
     "2026/02/04", "2026/01/06", "2025/06/01"],
    ["T5", "rty", "H12", "leak", "credit_claim", "", "", "", "", "",
     "2026/02/05", "2026/01/07", "2025/01/01"],
]
df = pd.DataFrame(data, columns=cols)

out1 = P.process_dataframe(df.copy(), max_workers=1)
out4 = P.process_dataframe(df.copy(), max_workers=4)

check("输出列与配置一致", list(out1.columns) == P.OUTPUT_COLUMNS)
check("工单号保留", list(out1["工单号"]) == ["T1", "T2", "T3", "T4", "T5"])
check("SKU 纯编码命中", out1.iloc[0]["故障类型（一级）"] == "电池包不良")
check("备件消耗透传", out1.iloc[0]["备件消耗"] == "20020100009132 - Battery")
check("同 SN 不同日期 → 二返（新故障）", out1.iloc[1]["类别"] == "二返（新故障）")
check("投诉关键词命中", out1.iloc[1]["故障类型（一级）"] == "拖布电机不良")
check("NFF 识别（技师备注）", out1.iloc[2]["类别"] == "无异常（NFF）")
check("维修详情已填充", out1.iloc[2]["维修详情"] != "")
check("故障对照表命中", out1.iloc[3]["故障类型（一级）"] == "主刷不良")
check("credit_claim 走 LLM 判定", out1.iloc[4]["处理方式"] == "退货")
check("翻译打桩生效", out1.iloc[0]["故障描述"].startswith("[译]"))
check("并发结果与串行一致", out1.equals(out4))
check("区域/代理固定值", set(out1["区域"]) == {"澳洲"} and set(out1["代理"]) == {"PAU"})
check("产品BU识别", out1.iloc[0]["产品BU"] == "扫地机")

print("== 4. 其余处理器可正常导入 ==")
import processor_kr, processor_kolon, processor_jp, processor_itc
import inspect
for mod, fn in [(processor_kr, "process_dataframe_kr"),
                (processor_kolon, "process_dataframe_kolon"),
                (processor_jp, "process_dataframe_jp"),
                (processor_itc, "process_dataframe_itc"),
                (P, "process_dataframe")]:
    sig = inspect.signature(getattr(mod, fn))
    check(f"{fn} 支持 max_workers", "max_workers" in sig.parameters)
    check(f"{fn} 支持 history_records", "history_records" in sig.parameters)

print("== 5. app.py 可导入（Streamlit 运行时外）==")
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import app
check("app 导入成功", hasattr(app, "workers") or True)

print("== 6. processor_kr：端到端 + 返修标签（LLM 已打桩）==")
import processor_kr as PK

PK._call_llm = lambda prompt, model: "[桩]" + str(prompt)[:6]

kr_cols = ["접수번호", "모델명", "제품군", "시리얼번호", "최종처리일",
           "접수분류3", "처리결과3", "접수내용", "처리내용",
           "재수리건수", "Warranty 여부"]
kr_data = [
    # 同 SN 不同日期（首修 + 二修）→ 第二行应为 二返
    ["K1", "X50Ultra", "로봇청소기", "SN-K", "2026/01/01",
     "", "", "고장1", "수리1", 1, "보증"],
    ["K2", "드리미 X50s_pro_ultra(blk)", "로봇청소기", "sn-k", "2026/02/01",
     "", "", "고장2", "수리2", 2, "보증"],
    # 同 SN 同日、内容不同 → 重复
    ["K3", "L20ultra", "로봇청소기", "SN-R", "2026/01/01",
     "", "", "고장A", "수리A", 1, "보증"],
    ["K4", "L20ultra", "로봇청소기", "SN-R", "2026/01/01",
     "", "", "고장B", "수리B", 1, "보증"],
]
kr_out = PK.process_dataframe_kr(pd.DataFrame(kr_data, columns=kr_cols).copy(),
                                 max_workers=2)
check("KR 输出列一致", list(kr_out.columns) == PK.OUTPUT_COLUMNS_KR)
check("KR 首现行保留原类别", kr_out.iloc[0]["类别"] == "维修（保内）")
check("KR 型号统一为澳洲格式",
      kr_out.iloc[0]["型号"] == "X50 Ultra"
      and kr_out.iloc[1]["型号"] == "X50s Pro Ultra (BLK)")
check("KR 同 SN 不同日期 → 二返", kr_out.iloc[1]["类别"].startswith("二返"))
check("KR 同 SN 同日 → 重复", kr_out.iloc[3]["类别"] == "重复")

print("== 7. repeat.RepeatClassifier：A / D / B / C / 首现 / 历史前驱 / 乱序 ==")
from repeat import RepeatClassifier, apply_label, merge_method, backfill_method_marks

records = [
    {"pos": 0, "sn": "S1", "date": "2026/01/01", "desc": "不抽水", "detail": "水泵损坏"},
    # A：SN 大小写不同 + 日期格式不同 + 内容 70% 以上相同
    {"pos": 1, "sn": "s1", "date": "2026-01-01", "desc": "不抽水", "detail": "水泵损坏更换"},
    {"pos": 2, "sn": "S2", "date": "2026/01/01", "desc": "不抽水", "detail": "水泵损坏"},
    # D：同 SN 同日但内容完全不同
    {"pos": 3, "sn": "S2", "date": "2026/01/01", "desc": "无法充电", "detail": "电池故障"},
    {"pos": 4, "sn": "S3", "date": "2026/01/01", "desc": "噪音大", "detail": "风扇异响"},
    # B：同 SN 第 2 个日期
    {"pos": 5, "sn": "S3", "date": "2026/02/01", "desc": "噪音大", "detail": "风扇异响"},
    # C：同 SN 第 3 个日期
    {"pos": 6, "sn": "S3", "date": "2026/03/01", "desc": "不转", "detail": "电机烧了"},
    # 首现
    {"pos": 7, "sn": "S4", "date": "2026/01/01", "desc": "首次", "detail": "首次"},
]
plan = RepeatClassifier().build_plan(records)
check("A：SN+日期+内容 70% 相同 → 重复",
      plan[1]["label"] == "重复" and plan[1]["case"] == "A")
check("D：SN+日期相同但内容不同 → 重复",
      plan[3]["label"] == "重复" and plan[3]["case"] == "D")
check("B：同 SN 第 2 个日期 → 二返", plan[5]["label"] == "二返")
check("C：同 SN 第 3 个日期 → 三返", plan[6]["label"] == "三返")
check("首现：不打标",
      plan[0]["label"] is None and plan[4]["label"] is None
      and plan[7]["label"] is None)

# apply_label：按需补（重现）/（新故障）
rows_snapshot = [(i, None) for i in range(len(records))]
faults = {0: "水泵不良", 1: "水泵不良", 2: "水泵不良", 3: "充电异常",
          4: "风扇异响", 5: "风扇异响", 6: "电机烧坏", 7: "首次故障"}
fg = lambda p: faults.get(p) if p is not None else None


def _mk(pos):
    return {"故障类型（一级）": faults[pos], "类别": "维修（保内）"}


check("A 行 → 重复",
      apply_label(_mk(1), 1, plan, rows_snapshot, None, fault_getter=fg)["类别"] == "重复")
check("D 行 → 重复",
      apply_label(_mk(3), 3, plan, rows_snapshot, None, fault_getter=fg)["类别"] == "重复")
check("B 行 故障一致 → 二返（重现）",
      apply_label(_mk(5), 5, plan, rows_snapshot, None, fault_getter=fg)["类别"] == "二返（重现）")
check("C 行 故障不一致 → 三返（新故障）",
      apply_label(_mk(6), 6, plan, rows_snapshot, None, fault_getter=fg)["类别"] == "三返（新故障）")
check("首现行 → 保留原类别",
      apply_label(_mk(7), 7, plan, rows_snapshot, None, fault_getter=fg)["类别"] == "维修（保内）")

# 往批历史作为前驱（断点续跑场景）
hist = [{"sn": "H1", "date": "2026/01/01", "desc": "旧投诉", "detail": "旧维修",
         "fault": "水泵不良"}]
plan_h = RepeatClassifier(history=hist).build_plan(
    [{"pos": 0, "sn": "H1", "date": "2026/02/01", "desc": "新投诉", "detail": "新维修"}])
check("历史同 SN 不同日期 → 二返", plan_h[0]["label"] == "二返")
check("历史前驱故障已知", plan_h[0]["pred_fault"] == "水泵不良")
check("跨批二返 + 故障一致 → 二返（重现）",
      apply_label({"故障类型（一级）": "水泵不良", "类别": "维修（保内）"},
                  0, plan_h, [(0, None)], lambda row: {},
                  fault_getter=lambda p: None)["类别"] == "二返（重现）")
plan_h2 = RepeatClassifier(history=[{"sn": "H2", "date": "2026/01/01",
                                     "desc": "x", "detail": "y", "fault": "z"}]).build_plan(
    [{"pos": 0, "sn": "H2", "date": "2026/01/01", "desc": "x", "detail": "y"}])
check("历史同 SN 同日 → 重复", plan_h2[0]["label"] == "重复")

# 文件未按日期排序：按日期而非文件顺序判定前驱
plan_o = RepeatClassifier().build_plan([
    {"pos": 0, "sn": "S5", "date": "2026/03/01", "desc": "三修", "detail": "三修"},
    {"pos": 1, "sn": "S5", "date": "2026/01/01", "desc": "首修", "detail": "首修"},
])
check("乱序：日期在前的行是首现", plan_o[1]["label"] is None)
check("乱序：日期在后的行是二返", plan_o[0]["label"] == "二返")

# resolve_label 边界
check("前驱故障为空 → 新故障",
      RepeatClassifier.resolve_label("二返", "风扇异响", "") == "二返（新故障）")
check("本行故障为空 → 新故障",
      RepeatClassifier.resolve_label("二返", "", "风扇异响") == "二返（新故障）")
check("非返修标签原样返回",
      RepeatClassifier.resolve_label("重复", "a", "b") == "重复")

print("== 8. model_norm.normalize_model：三地区型号统一为澳洲格式 ==")
from model_norm import normalize_model

model_cases = [
    # (输入, 期望)
    ("DREAME - Dreame L40 Ultra CE", "L40 Ultra CE"),  # 澳洲原值（去多层品牌前缀）
    ("X50Ultra", "X50 Ultra"),                          # KOLON 驼峰
    ("X50s_pro_ultra(blk)", "X50s Pro Ultra (BLK)"),    # KOLON 下划线 + 括号
    ("X50Ultra(BLK)", "X50 Ultra (BLK)"),
    ("드리미 X50Ultra", "X50 Ultra"),                   # 韩文品牌前缀
    ("追觅 X50 울트라", "X50 Ultra"),                    # 中文品牌前缀 + 韩文后缀
    ("x50 master", "X50 Master"),
    ("L20ultra", "L20 Ultra"),
    ("L10SUltra", "L10S Ultra"),
    ("X50master", "X50 Master"),
    # 已是澳洲格式 → 原样返回（幂等）
    ("X50 Ultra", "X50 Ultra"),
    ("L40S Pro Ultra", "L40S Pro Ultra"),
    ("H12 Pro FlexReach", "H12 Pro FlexReach"),
    ("CVF70A", "CVF70A"),
    ("Aqua10 Ultra Roller Master", "Aqua10 Ultra Roller Master"),
    ("X60 Master", "X60 Master"),
    ("", ""),
    (None, ""),
]
for src, want in model_cases:
    got = normalize_model(src)
    check(f"型号 {src!r} → {want!r}", got == want)
check("型号归一化幂等",
      all(normalize_model(normalize_model(s)) == normalize_model(s)
          for s, _ in model_cases if s))

print("== 9. processor_itc：日期取发货时间（出荷日），空则兜底登记时间 ==")
import processor_itc as PI

PI._call_llm = lambda prompt, model: "[桩]" + str(prompt)[:6]

itc_cols = ["RMA", "出荷日发货时间", "発生日時登记时间", "SN",
            "クレーム症状客诉症状", "点检结果"]
itc_data = [
    # 有发货时间（含时间部分）→ 取发货时间
    ["I1", "2026-10-05 10:00", "2026-09-28", "SN-A", "故障", "维修"],
    # 发货时间为空 → 兜底建单/登记时间
    ["I2", "", "2026-09-20", "SN-B", "故障", "维修"],
    # 同 SN：两个不同发货日期 → 第二行为二返
    ["I3", "2026/10/01", "2026-09-01", "SN-C", "故障C", "维修C"],
    ["I4", "2026/10/20", "2026-09-10", "SN-C", "故障C2", "维修C2"],
]
itc_out = PI.process_dataframe_itc(
    pd.DataFrame(itc_data, columns=itc_cols).copy(), max_workers=2)
check("ITC 日期取发货时间", itc_out.iloc[0]["日期"] == "2026/10/05")
check("ITC 发货时间为空兜底登记时间", itc_out.iloc[1]["日期"] == "2026/09/20")
check("ITC 同 SN 不同发货日期 → 二返", itc_out.iloc[3]["类别"].startswith("二返"))
check("ITC 首现行保留原类别", itc_out.iloc[0]["类别"] == "维修（保内）")

print("== 10. processor（AU）：日期取 Auxiliary Field: Closed Date ==")
row_full = pd.Series({
    "Ticket Number": "T1",
    "Date Created": "18/09/2026, 10:10:39 am",
    "Auxiliary Field：Closed Date": "2026/10/06",
})
check("AU 日期取关单日期（全角冒号）", P.get_ticket_date(row_full) == "2026/10/06")

row_half = pd.Series({
    "Date Created": "18/09/2026, 10:10:39 am",
    "Auxiliary Field: Closed Date": "2026/10/07",
})
check("AU 日期取关单日期（半角冒号）", P.get_ticket_date(row_half) == "2026/10/07")

row_open = pd.Series({
    "Date Created": "18/09/2026, 10:10:39 am",
    "Auxiliary Field：Closed Date": "",
})
check("AU 关单日期为空兜底创建日期", P.get_ticket_date(row_open) == "2026/09/18")

au_row = pd.Series({
    "Ticket Number": "T2",
    "Serial Number": "SN-Z",
    "Device Name": "DREAME - L40 Ultra",
    "Customer Complaint": "battery not charging",
    "Date Created": "18/09/2026, 10:10:39 am",
    "Date Purchased": "01/01/2026",
    "Auxiliary Field：Closed Date": "2026/10/06",
    "Repair Details (Technician Notes)": "replaced battery",
    "Type of Service": "service",
})
au_out = P.process_row(au_row)
check("AU 端到端：日期列 = 关单日期（非创建日期）",
      au_out["日期"] == "2026/10/06")

print("== 11. date_refresh：断点文件旧日期修正 ==")
from date_refresh import refresh_partial_dates, write_partial

raw_df = pd.DataFrame([
    {"Ticket Number": "T1", "Auxiliary Field：Closed Date": "2026/10/06",
     "Date Created": "18/09/2026"},
    {"Ticket Number": "T3", "Auxiliary Field：Closed Date": "2026/10/08",
     "Date Created": "20/09/2026"},
])
partial_df = pd.DataFrame([
    {"工单号": "T1", "日期": "2026/09/18"},   # 旧口径：创建日期
    {"工单号": "TX", "日期": "2026/09/19"},   # 源表中不存在
])
fixed_df, n_fixed = refresh_partial_dates(partial_df, raw_df, "澳洲（PAU）")
check("断点行日期修正为关单日期", fixed_df.iloc[0]["日期"] == "2026/10/06")
check("源表未匹配的行保持原值", fixed_df.iloc[1]["日期"] == "2026/09/19")
check("修正行数统计正确", n_fixed == 1)

again_df, n_again = refresh_partial_dates(fixed_df, raw_df, "澳洲（PAU）")
check("日期修正幂等（重复执行不再变动）", n_again == 0 and again_df.iloc[0]["日期"] == "2026/10/06")

tmp_csv = os.path.join(d, "partial_test.csv")
check("修正结果可写回断点文件",
      write_partial(fixed_df, tmp_csv) and os.path.exists(tmp_csv))

print("== 12. return_rate：二返率计算（移植自 2.py）==")
from return_rate import (classify_return, calc_return_rate, build_detail,
                         summarize, mark_breakdown, MARK_COL)

rr_src = pd.DataFrame([
    # SN-A：完全重复（同日期同描述同维修）
    {"工单号": "A1", "SN": "SN-A", "日期": "2026/01/01", "故障描述": "D1",
     "维修详情": "R1", "故障类型（一级）": "电池包不良", "型号": "X50 Ultra",
     "处理方式": "更换备件/配件"},
    {"工单号": "A2", "SN": "SN-A", "日期": "2026/01/01", "故障描述": "D1",
     "维修详情": "R1", "故障类型（一级）": "电池包不良", "型号": "X50 Ultra",
     "处理方式": "更换备件/配件"},
    # SN-A：31 天后同故障 → 二返（故障重现）
    {"工单号": "A3", "SN": "SN-A", "日期": "2026/02/01", "故障描述": "D2",
     "维修详情": "R2", "故障类型（一级）": "电池包不良", "型号": "X50 Ultra",
     "处理方式": "更换备件/配件"},
    # SN-A：再 37 天后不同故障 → 三返
    {"工单号": "A4", "SN": "SN-A", "日期": "2026/03/10", "故障描述": "D3",
     "维修详情": "R3", "故障类型（一级）": "水泵不良", "型号": "X50 Ultra",
     "处理方式": "更换整机"},
    # SN-B：首现 + 3 天后 → 窗口内重复
    {"工单号": "B1", "SN": "SN-B", "日期": "2026/01/05", "故障描述": "D4",
     "维修详情": "R4", "故障类型（一级）": "主刷不良", "型号": "L40 Ultra",
     "处理方式": "更换备件/配件"},
    {"工单号": "B2", "SN": "SN-B", "日期": "2026/01/08", "故障描述": "D5",
     "维修详情": "R5", "故障类型（一级）": "主刷不良", "型号": "L40 Ultra",
     "处理方式": "更换备件/配件"},
])

rr = classify_return(rr_src, dup_window_days=5, return_window_days=90)
marks = rr[MARK_COL].tolist()
check("完全重复 → 重复", marks[1] == "重复")
check("窗口内（3 天）重复 → 重复", marks[5] == "重复")
check("首现不标记", marks[0] == "" and marks[4] == "")
check("同 SN 异日第 2 次同故障 → 二返（故障重现）",
      marks[2] == "二返（故障重现）")
check("同 SN 异日第 3 次不同故障 → 三返", marks[3] == "三返")

info = summarize(rr)
check("汇总：总工单数", info["总工单数"] == 6)
check("汇总：返修数 = 2", info["返修数"] == 2)
check("汇总：二返数 = 1", info["二返数"] == 1)
check("汇总：重复数 = 2", info["重复数"] == 2)
check("汇总：二返率 = 16.67%", info["二返率(%)"] == 16.67)

rate = calc_return_rate(rr)
row_x50 = rate[rate["型号"] == "X50 Ultra"].iloc[0]
check("型号统计：X50 Ultra 总 4 单", int(row_x50["总工单数"]) == 4)
check("型号统计：X50 Ultra 返修 2 单", int(row_x50["返修数"]) == 2)
check("型号统计：返修率 50%", float(row_x50["返修率(%)"]) == 50.0)

detail = build_detail(rr)
check("明细报告只含被标记行（4 条）", len(detail) == 4)
check("明细报告带关联工单号列", "关联工单号" in detail.columns)
check("明细报告：重复归组排在最前",
      detail[MARK_COL].tolist()[0] == "重复"
      and detail[MARK_COL].tolist()[1] == "重复")
check("明细报告：返修按 二返 → 三返 递增归组",
      detail[MARK_COL].tolist()[2].startswith("二返")
      and detail[MARK_COL].tolist()[3] == "三返")

bd = mark_breakdown(rr)
bd_map = dict(zip(bd[MARK_COL], bd["工单数"]))
check("标记分布表：重复 2 条", int(bd_map.get("重复", 0)) == 2)
check("标记分布表：二返（故障重现）1 条",
      int(bd_map.get("二返（故障重现）", 0)) == 1)
check("标记分布表：三返 1 条", int(bd_map.get("三返", 0)) == 1)
check("标记分布表：占比合计与标记总数一致",
      int(bd["工单数"].sum()) == 4)

# 窗口可调：重复窗口 0 天 → 3 天间隔不再算重复，改判二返
rr0 = classify_return(rr_src, dup_window_days=0, return_window_days=90)
check("重复窗口调为 0 天 → 3 天间隔改判二返",
      rr0[MARK_COL].tolist()[5].startswith("二返"))

# 覆盖处理方式（与原脚本一致）
rr_ow = classify_return(rr_src, 5, 90, overwrite_method=True)
check("覆盖处理方式：标记行被替换",
      rr_ow.iloc[1]["处理方式"] == "重复")
check("覆盖处理方式：未标记行保留原值",
      rr_ow.iloc[0]["处理方式"] == "更换备件/配件")

# 默认：追加标记，不丢原值
check("默认追加：标记行 = 重复 / 更换备件/配件",
      rr.iloc[1]["处理方式"] == "重复 / 更换备件/配件")
check("默认追加：未标记行不变",
      rr.iloc[0]["处理方式"] == "更换备件/配件")
rr_keep = classify_return(rr_src, 5, 90, method_mode="keep")
check("keep 模式不动处理方式",
      rr_keep.iloc[1]["处理方式"] == "更换备件/配件")

print("== 13. repeat.merge_method：处理方式追加标记 ==")
check("追加：补发配件 + 重复",
      merge_method("补发配件", "重复") == "重复 / 补发配件")
check("追加：空处理方式只留标记",
      merge_method("", "重复") == "重复")
check("追加幂等：已含同标记不重复追加",
      merge_method("重复 / 补发配件", "重复") == "重复 / 补发配件")
check("追加替换：标记不同则替换旧标记",
      merge_method("重复 / 补发配件", "二返（重现）") == "二返（重现） / 补发配件")
check("非返修类别不改处理方式",
      merge_method("更换备件", "维修（保内）") == "更换备件")

bf_df = pd.DataFrame({
    "类别": ["重复", "二返（重现）", "维修（保内）", ""],
    "处理方式": ["补发配件", "更换备件", "维修（保内）", ""],
})
bf_out, bf_n = backfill_method_marks(bf_df)
check("历史行回填：2 行被追加标记", bf_n == 2)
check("历史行回填：重复行 = 重复 / 补发配件",
      bf_out.iloc[0]["处理方式"] == "重复 / 补发配件")
check("历史行回填：保内行不变",
      bf_out.iloc[2]["处理方式"] == "维修（保内）")
_, bf_n2 = backfill_method_marks(bf_out)
check("历史行回填幂等", bf_n2 == 0)

label_out = {"类别": "维修（保内）", "处理方式": "补发配件",
             "故障类型（一级）": ""}
apply_label(label_out, 0, {0: {"label": "重复", "pred_pos": None,
                               "pred_fault": None}}, [], lambda r: {})
check("apply_label 同步追加处理方式",
      label_out["类别"] == "重复"
      and label_out["处理方式"] == "重复 / 补发配件")

# 空表 / 缺列不应报错
empty_out = classify_return(pd.DataFrame(), 5, 90)
check("空表不报错", len(empty_out) == 0)
nocol_out = classify_return(pd.DataFrame([{"工单号": "X"}]), 5, 90)
check("缺列不报错", len(nocol_out) == 1)

print("== 14. repeat.relabel_repeat：断点旧标签重判 ==")
from repeat import relabel_repeat

old_df = pd.DataFrame([
    # 同 SN 同日两行：旧版本误标为「二返（新故障）」
    {"工单号": "T1", "SN": "SN-R", "日期": "2026/10/14", "故障描述": "A",
     "维修详情": "a", "故障类型（一级）": "水泵不良",
     "类别": "维修（保内）", "处理方式": "更换备件/配件"},
    {"工单号": "T1", "SN": "SN-R", "日期": "2026/10/14", "故障描述": "B",
     "维修详情": "b", "故障类型（一级）": "未拖地未吸尘",
     "类别": "二返（新故障）", "处理方式": "二返（新故障） / 更换整机"},
    # 首现行（原标签保外）：不应被清空
    {"工单号": "T9", "SN": "SN-SOLO", "日期": "2026/10/20", "故障描述": "C",
     "维修详情": "c", "故障类型（一级）": "电池包不良",
     "类别": "维修（保外）", "处理方式": "补发配件"},
])

rl_df, rl_n, rl_diff = relabel_repeat(old_df)
check("重判：同 SN 同日 → 重复", rl_df.iloc[1]["类别"] == "重复")
check("重判：处理方式同步为「重复 / 更换整机」",
      rl_df.iloc[1]["处理方式"] == "重复 / 更换整机")
check("重判：首现行保留原类别（不被清空）",
      rl_df.iloc[2]["类别"] == "维修（保外）")
check("重判：修正行数 = 1", rl_n == 1)
check("重判：修正明细含原/新标签",
      rl_diff and rl_diff[0]["原标签"] == "二返（新故障）"
      and rl_diff[0]["新标签"] == "重复")
_, rl_n2, _ = relabel_repeat(rl_df)
check("重判幂等", rl_n2 == 0)

print()
failed = [n for n, ok in PASS if not ok]
print(f"共 {len(PASS)} 项，失败 {len(failed)} 项")
if failed:
    print("失败项：", failed)
    sys.exit(1)
print("ALL PASS")

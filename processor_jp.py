# processor_jp.py
import io
import json
import re
import pandas as pd
from datetime import datetime
from pathlib import Path

from config_jp import (
    COLUMN_MAP_JP, OUTPUT_COLUMNS_JP,
    FIXED_REGION_JP, FIXED_AGENT_JP,
    PROCESS_RESULT_FIXED_JP,
    JP_PROMPT_TRANSLATE,
    JP_PROMPT_FAULT_FROM_TEXT,
    JP_PROMPT_PROCESS_RESULT,
)
from config import PRODUCT_BU_MAP
from llm_client import _call_llm, MODEL_TRANSLATE, MODEL_CLASSIFY


# ==================== 加载官方故障对照表 ====================
FAULT_TABLE_FILE = "产品故障分类中英韩日文.xlsx"
JP_TO_CN_FAULT_STD = {}       # {日文原文: 中文标准值}
JP_FAULT_CN_LIST = []          # 所有中文标准值列表（用于大模型候选）
JP_KEYWORD_MAP = {}            # {关键词: 中文标准值}（从日文列提取关键词）

if Path(FAULT_TABLE_FILE).exists():
    try:
        df_fault = pd.read_excel(FAULT_TABLE_FILE, sheet_name="故障分类")
        for _, r in df_fault.iterrows():
            jp = str(r.get("故障现象日文", "")).strip()
            cn = str(r.get("故障现象中文", "")).strip()
            if jp and cn and jp.lower() not in ("nan", "none", ""):
                JP_TO_CN_FAULT_STD[jp] = cn
                JP_FAULT_CN_LIST.append(cn)
        JP_FAULT_CN_LIST = sorted(set(JP_FAULT_CN_LIST))
    except Exception as e:
        print(f"[JP] 加载故障对照表失败：{e}")

# 日文关键词应急表（覆盖超高频表达）
JP_KEYWORD_EMERGENCY = {
    # 漏水类
    "漏水": "基站/主机漏水", "水漏れ": "基站/主机漏水", "水が漏れ": "基站/主机漏水",
    # 出水类
    "不出水": "拖地时不出水", "水が出ない": "拖地时不出水", "水が出ません": "拖地时不出水",
    "水が出なく": "拖地时不出水", "給水": "基站/基座不出水",
    # 充电类
    "充電でき": "充电异常", "充電しない": "充电异常", "充電できません": "充电异常",
    "充電できず": "充电异常", "充不上电": "充电异常",
    # 开机类
    "電源が入": "无法开机", "電源つかない": "无法开机", "起動でき": "无法开机",
    "不开机": "无法开机", "电源没反应": "无法开机",
    # 传感器类
    "LDS": "LDS激光传感器异常", "レーザーセンサー": "LDS激光传感器异常",
    "撞板": "撞板传感器不良", "衝突センサー": "撞板传感器不良",
    "悬崖": "悬崖传感器异常", "段差センサー": "悬崖传感器异常",
    "超音波": "地毯传感器异常", "地毯": "地毯传感器异常",
    # 电机类
    "边刷": "边刷电机异常", "サイドブラシ": "边刷电机异常",
    "主刷": "主刷电机异常", "メインブラシ": "主刷电机异常",
    "抹布": "抹布电机异常", "モップモーター": "抹布电机异常",
    "驱动轮": "驱动轮异常", "ホイール": "驱动轮异常",
    "万向轮": "万向轮异常", "補助輪": "万向轮异常",
    "风机": "主机风机异常", "ファン": "主机风机异常",
    # 水箱类
    "清水箱": "清水箱异常", "清水タンク": "清水箱异常",
    "污水箱": "污水箱异常", "汚水タンク": "污水箱异常",
    "尘袋": "尘袋异常", "ダストバッグ": "尘袋异常",
    "尘盒": "尘盒异常", "ダストボックス": "尘盒异常",
    "滤芯": "滤芯异常", "フィルター": "滤芯异常",
    # 联网类
    "WIFI": "无法联网", "Wi-Fi": "无法联网", "ネットワーク": "无法联网",
    "联网": "无法联网", "WiFi": "无法联网",
    # 回充类
    "回充": "无法回充", "自動充電": "无法回充",
    # 建图类
    "マッピング": "建图异常", "建图": "建图异常", "地図": "建图异常",
    # 声音类
    "異音": "异音", "噪音": "噪音", "騒音": "噪音",
    # APP类
    "エラー": "APP异常", "APP": "APP异常", "アプリ": "APP异常",
    # 其他
    "吸力": "吸力变小/无吸力", "吸引": "吸力变小/无吸力",
    "異味": "异味发臭", "臭": "异味发臭",
}


# ==================== 工具 ====================
def _is_blank(s) -> bool:
    if s is None:
        return True
    t = str(s).strip()
    if not t:
        return True
    if t.lower() in ("nan", "none", "null", "nat", "/", "-"):
        return True
    return False


def _normalize_col_name(col: str) -> str:
    s = str(col)
    s = s.replace("\ufeff", "").replace("\u3000", "").strip()
    s = s.replace("\n", "").replace("\r", "").replace("\t", "").strip()
    return s


def _normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.rename(columns={c: _normalize_col_name(c) for c in df.columns}, inplace=True)
    return df


def _get_col(row, name):
    for c in row.index:
        if name in str(c):
            return row.get(c, "")
    return ""


def _normalize_jp_text(text: str) -> str:
    """日文归一化：去标点、去空格、转小写"""
    s = str(text).strip()
    s = re.sub(r"[。、，,.\s\u3000]+", "", s)
    return s.lower()


# ==================== 本地缓存 ====================
JP_CACHE_FILE = "fault_mapping_jp.json"
_jp_cache = {}
if Path(JP_CACHE_FILE).exists():
    try:
        _jp_cache = json.loads(Path(JP_CACHE_FILE).read_text(encoding="utf-8"))
    except Exception:
        _jp_cache = {}


def _save_jp_cache():
    Path(JP_CACHE_FILE).write_text(
        json.dumps(_jp_cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ==================== 日译中 ====================
def jp_translate(text: str) -> str:
    if _is_blank(text):
        return ""
    key = f"__TR__{str(text).strip()}"
    if key in _jp_cache:
        return _jp_cache[key]
    prompt = JP_PROMPT_TRANSLATE.format(text=str(text).strip()[:3000])
    result = _call_llm(prompt, MODEL_TRANSLATE)
    if not result or len(result) > 3000:
        return ""
    if "无法翻译" in result or "请提供" in result:
        return ""
    _jp_cache[key] = result
    _save_jp_cache()
    return result


# ==================== 故障类型（核心改造）====================
def translate_fault_class(text: str) -> str:
    """
    4 级优先：
    ① 精确匹配官方日文标准值
    ② 官方日文标准值"包含"客诉原文
    ③ 关键词应急表
    ④ 大模型从官方中文候选列表里选
    """
    if _is_blank(text):
        return ""
    t_orig = str(text).strip()
    t_norm = _normalize_jp_text(t_orig)

    # ① 精确匹配
    for jp_std, cn_std in JP_TO_CN_FAULT_STD.items():
        if _normalize_jp_text(jp_std) == t_norm:
            return cn_std

    # ② 包含匹配（双向）
    for jp_std, cn_std in JP_TO_CN_FAULT_STD.items():
        jp_norm = _normalize_jp_text(jp_std)
        if jp_norm and (jp_norm in t_norm or t_norm in jp_norm):
            return cn_std

    # ③ 关键词应急表
    for kw, cn_std in JP_KEYWORD_EMERGENCY.items():
        if kw.lower() in t_orig.lower():
            return cn_std

    # ④ 大模型兜底（从候选列表选）
    key = f"__FC3__{t_orig}"
    if key in _jp_cache:
        return _jp_cache[key]

    candidates = " / ".join(JP_FAULT_CN_LIST) if JP_FAULT_CN_LIST else (
        "APP异常 / 充电异常 / 无法开机 / 无法联网 / 无法回充 / "
        "基站/主机漏水 / 拖地时不出水 / 边刷电机异常 / 主刷电机异常 / "
        "抹布电机异常 / 驱动轮异常 / 万向轮异常 / 清水箱异常 / 污水箱异常 / "
        "尘袋异常 / 滤芯异常 / 建图异常 / 异音 / 噪音 / 吸力变小/无吸力"
    )

    prompt = (
        "你是家电维修故障分类专家。下面是一段日文的客诉描述。\n"
        "请从【标准故障现象】中选出最贴近的一个，只输出这一个中文短语，不要解释。\n\n"
        f"【标准故障现象】：\n{candidates}\n\n"
        f"日本客诉原文：\n{t_orig[:1000]}"
    )
    result = _call_llm(prompt, MODEL_CLASSIFY)
    if not result:
        return ""
    result = result.replace("【", "").replace("】", "").strip()

    # 只接受候选列表里的值
    for cand in JP_FAULT_CN_LIST:
        if cand in result:
            _jp_cache[key] = cand
            _save_jp_cache()
            return cand

    # 兜底：截断输出
    result = result[:12]
    if "未知" in result or "无法" in result:
        return ""
    _jp_cache[key] = result
    _save_jp_cache()
    return result


def fault_from_text(text: str) -> str:
    """维修详情/初步方案 走同一个逻辑"""
    return translate_fault_class(text)


# ==================== 处理方式 ====================
def translate_process_result(complaint_jp: str, repair_jp: str) -> str:
    if _is_blank(complaint_jp) and _is_blank(repair_jp):
        return ""
    key = f"__PR__{complaint_jp}||{repair_jp}"
    if key in _jp_cache:
        return _jp_cache[key]

    prompt = JP_PROMPT_PROCESS_RESULT.format(
        complaint=str(complaint_jp or "")[:1000],
        repair=str(repair_jp or "")[:1500],
    )
    result = _call_llm(prompt, MODEL_CLASSIFY)
    if not result:
        return ""
    for fixed in PROCESS_RESULT_FIXED_JP:
        if fixed in result:
            _jp_cache[key] = fixed
            _save_jp_cache()
            return fixed
    return ""


# ==================== 产品BU ====================
def get_product_bu(device_name: str) -> str:
    if _is_blank(device_name):
        return ""
    name = str(device_name).upper()
    for key in sorted(PRODUCT_BU_MAP.keys(), key=len, reverse=True):
        if key.upper() in name:
            return PRODUCT_BU_MAP[key]
    return ""


# ==================== 日期 ====================
def parse_date_jp(val):
    if pd.isna(val) or val is None or str(val).strip() == "":
        return None
    s = str(val).strip()
    if " " in s:
        s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def normalize_date_jp(val) -> str:
    d = parse_date_jp(val)
    return d.strftime("%Y/%m/%d") if d else ""


# ==================== 类别 ====================
def determine_category_jp(solution: str, note: str = "") -> str:
    text = f"{solution} {note}".strip()
    if not text:
        return "待确认"
    if "保内" in text:
        return "保内"
    if "DOA" in text.upper():
        return "保内"
    if "保外" in text:
        return "保外"
    if "退款" in text or "退机" in text:
        return "保外"
    if "其他" in text:
        return "其他"
    return "待确认"


# ==================== 工单状态 ====================
def determine_status(arrival: str, done_flag: str) -> str:
    done = str(done_flag or "").strip()
    if done in ("✔", "√", "Y", "y", "TRUE", "True"):
        return "已完成"
    arr = str(arrival or "").strip().upper()
    if arr == "Y":
        return "进行中"
    return "待处理"


# ==================== 单行处理 ====================
def process_row_jp(row: pd.Series) -> dict:
    out = {}
    for src, dst in COLUMN_MAP_JP.items():
        out[dst] = _get_col(row, src)

    out["区域"] = FIXED_REGION_JP
    out["代理"] = FIXED_AGENT_JP
    out["产品BU"] = get_product_bu(out.get("型号", ""))
    out["日期"] = normalize_date_jp(out.get("日期", ""))

    fault_text = str(out.get("用户描述日文", "") or "").strip()
    repair_text = str(out.get("维修详情日文", "") or "").strip()
    solution_text = str(out.get("初步方案", "") or "").strip()
    note_text = str(out.get("备注", "") or "").strip()

    # 故障类型（一级）：4 级优先
    out["故障类型（一级）"] = ""
    if not _is_blank(fault_text):
        out["故障类型（一级）"] = translate_fault_class(fault_text)
    if _is_blank(out["故障类型（一级）"]) and not _is_blank(repair_text):
        out["故障类型（一级）"] = fault_from_text(repair_text)
    if _is_blank(out["故障类型（一级）"]) and not _is_blank(solution_text):
        out["故障类型（一级）"] = fault_from_text(solution_text)

    # 处理方式
    out["处理方式"] = translate_process_result(fault_text, repair_text)

    # 类别
    out["类别"] = determine_category_jp(solution_text, note_text)

    # 故障描述（日译中）
    out["故障描述"] = jp_translate(fault_text) if not _is_blank(fault_text) else ""

    # 维修详情
    detail_parts = []
    if not _is_blank(repair_text):
        detail_parts.append(jp_translate(repair_text))
    if not _is_blank(note_text):
        detail_parts.append(jp_translate(note_text))
    out["维修详情"] = " | ".join([p for p in detail_parts if p])

    # 物流单号
    send_back = str(out.get("寄回单号", "") or "").strip()
    send_out = str(out.get("发货单号", "") or "").strip()
    out["物流单号"] = " / ".join([x for x in [send_back, send_out]
                                  if x and x.lower() not in ("nan", "/", "-")])

    # 到货状态
    arr = str(out.get("到货状态", "") or "").strip().upper()
    out["到货状态"] = "已到货" if arr == "Y" else "未到货"

    # 故障部件/料号
    part = str(out.get("故障部件", "") or "").strip()
    pno = str(out.get("料号", "") or "").strip()
    out["故障部件/料号"] = " / ".join([x for x in [part, pno]
                                        if x and x.lower() not in ("nan", "/", "-")])

    # 工单状态
    out["工单状态"] = determine_status(arr, out.get("完成标记", ""))

    # 唯一键（避免 RMA 重复）
    rma_str = str(out.get("工单号", "") or "").strip()
    sn_str = str(out.get("SN", "") or "").strip()
    out["唯一键"] = f"{rma_str}__{sn_str}"

    return out


# ==================== 批量处理 ====================
def process_dataframe_jp(df, progress_cb=None,
                         on_row_done=None, stop_flag_getter=None):
    df = _normalize_df_columns(df)

    rows = []
    total = len(df)
    for i, (_, row) in enumerate(df.iterrows()):
        if stop_flag_getter and stop_flag_getter():
            break
        try:
            out = process_row_jp(row)
            rows.append(out)
            if on_row_done:
                on_row_done(out)
        except Exception as e:
            empty = {col: "" for col in OUTPUT_COLUMNS_JP}
            empty["工单号"] = _get_col(row, "RMA") or "ERROR"
            empty["唯一键"] = f"ERROR__{i}"
            rows.append(empty)
            if on_row_done:
                on_row_done(empty)
        if progress_cb:
            progress_cb(i + 1, total)

    result = pd.DataFrame(rows)
    for col in OUTPUT_COLUMNS_JP:
        if col not in result.columns:
            result[col] = ""
    return result[OUTPUT_COLUMNS_JP]
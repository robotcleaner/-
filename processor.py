import csv
import json
import re
import threading
import pandas as pd
from datetime import datetime
from pathlib import Path
from config import (
    COLUMN_MAP, OUTPUT_COLUMNS,
    PROCESS_METHOD_MAP,
    PRODUCT_BU_MAP, FIXED_REGION, FIXED_AGENT,
    FAULT_MAPPING_FILE, DEFAULT_FAULT_MAPPING,
    SKU_TO_FAULT,
    WARRANTY_TABLE_FILE, DEFAULT_WARRANTY_YEARS,
    REFURB_WINDOW_DAYS, MAX_WORKERS,
)
from llm_client import translate, classify_credit_claim, classify_fault_from_sku
from batch import JsonStore, run_batch
from model_norm import normalize_model
from repeat import RepeatClassifier, apply_label

# ==================== 预编译匹配表（避免每行重复排序/扫描）====================
# 产品 BU 前缀：长前缀优先，统一大写比较
_PRODUCT_BU_ITEMS = sorted(
    ((k.upper(), v) for k, v in PRODUCT_BU_MAP.items()),
    key=lambda kv: len(kv[0]), reverse=True,
)

# ==================== 工具：空值判断 ====================
def _is_blank(s) -> bool:
    if s is None:
        return True
    t = str(s).strip()
    if not t:
        return True
    if t.lower() in ("nan", "none", "null", "nat"):
        return True
    return False

# ==================== 纯数字 SKU 映射字典 (针对无文字说明的备件) ====================
# 提取自澳洲常见原厂备件号，匹配不到文字时直接查这个表
PURE_SKU_MAP = {
    # 电池
    "20020100003497": "电池包不良", "20020100003520": "电池包不良", 
    "20020100009132": "电池包不良", "20020100010996": "电池包不良",
    "20020100016268": "电池包不良", "20020100018579": "电池包不良",
    
    # 拖布电机/拖布盘
    "20020100009120": "拖布电机不良", "20020100007674": "拖布电机不良", 
    "20020100011722": "拖布电机不良", "20020100012883": "拖布电机不良", 
    "20020100017105": "拖布电机不良", "20020100022597": "拖布电机不良",
    "20010100000872": "拖布不良", "20020100008191": "拖布不良",
    
    # 主刷/主刷盖
    "20010100000878": "主刷不良", "20010100000871": "主刷盖不良",
    "20010100000796": "主刷盖不良", "20020100014023": "主刷盖不良",
    "20020100024072": "主刷盖不良", "20020100009606": "主刷电机不良",
    "20020100010626": "主刷电机不良", "20020100015017": "主刷电机不良",
    
    # 边刷/边刷电机
    "20010100001070": "边刷不良", "20010100000717": "边刷不良",
    "20020100005940": "边刷电机不良", "20020100011747": "边刷电机不良",
    "20020100016219": "边刷电机不良", "20020100016454": "边刷电机不良",
    
    # LDS激光/线激光
    "20020100007669": "LDS组件不良", "20020100009632": "LDS组件不良",
    "20020100015831": "LDS组件不良", "20020100016452": "LDS组件不良",
    "20020100017107": "LDS组件不良", "20020100019646": "LDS组件不良",
    
    # 主板/核心板
    "20020100010855": "主板不良", "20020100019034": "主板不良",
    "20020100019036": "主板不良", "20020100021323": "主板不良",
    
    # 水泵/污水泵
    "20020100003737": "水泵不良", "20020100009599": "水泵不良",
    "20020100008121": "污水泵不良", "20020100007481": "污水泵不良",
    
    # 风机/集尘电机
    "20020100003415": "风机不良", "20020100008182": "风机不良",
    "20020100009595": "风机不良", "20020100014622": "风机不良",
    
    # 尘盒/尘袋/滤网
    "20020100008211": "尘盒不良", "20020100009137": "尘盒不良",
    "20010100000898": "滤网不良", "20010100001065": "滤网不良",
    
    # 轮子/驱动轮
    "20020100003480": "万向轮不良", "20020100000108": "万向轮不良",
    "20020100003723": "万向轮不良", "20020100009346": "驱动轮不良",
    "20020100014045": "驱动轮不良", "20020100011727": "驱动轮不良",
    
    # 清水箱/污水箱
    "20020100007573": "清水箱不良", "20020100009772": "污水箱不良",
    "20020100020801": "污水箱不良", "20020100024549": "污水箱不良",
    
    # 充电组件
    "20020100008111": "主机回充组件不良", "20020100009655": "主机回充组件不良",
    "20020100009653": "基站充电组件不良", "20020100012414": "基站充电组件不良",
}

# 预编译：纯数字 SKU 与关键词均按长度降序，长 key 优先匹配
_PURE_SKU_ITEMS = sorted(PURE_SKU_MAP.items(), key=lambda kv: len(kv[0]), reverse=True)
_SKU_TO_FAULT_ITEMS = sorted(SKU_TO_FAULT.items(), key=lambda kv: len(kv[0]), reverse=True)

# ==================== 质保表 ====================
def _read_warranty_rows(path: Path):
    """读取质保表原始行；兼容「真 CSV」与「扩展名被改成 .csv 的 Excel」。"""
    # ① 先按文本 CSV 读
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            rows = [r for r in csv.reader(f) if any(str(c).strip() for c in r)]
        if rows:
            return rows
    except (UnicodeDecodeError, OSError):
        pass

    # ② 兜底：按 Excel 读（部分文件的 .csv 实际是 xls 二进制）
    try:
        df = pd.read_excel(path)
        return [[str(v) for v in r] for r in df.values.tolist()]
    except Exception:
        return []


def load_warranty_table() -> dict:
    path = Path(WARRANTY_TABLE_FILE)
    table = {}
    if not path.exists():
        return table

    try:
        rows = _read_warranty_rows(path)
    except Exception:
        return table

    for row in rows:
        cells = [str(c).strip() for c in row]
        # 单列被逗号拼在一起的情况： "A1 Pro,3"
        if len(cells) == 1 and "," in cells[0]:
            cells = [c.strip() for c in cells[0].split(",", 1)]
        if len(cells) < 2:
            continue

        model, yr = cells[0], cells[1]
        if not model or model.lower() in ("model", "型号", "nan"):
            continue
        if yr.lower() in ("nan", "none"):
            yr = ""
        try:
            table[model] = float(yr) if yr else DEFAULT_WARRANTY_YEARS
        except ValueError:
            table[model] = DEFAULT_WARRANTY_YEARS
    return table

_warranty_table = load_warranty_table()
# 预编译：按 key 长度降序，避免每次查询都重新排序
_WARRANTY_KEYS_BY_LEN = sorted(_warranty_table.keys(), key=len, reverse=True)

def lookup_warranty_years(model: str) -> float:
    if _is_blank(model):
        return DEFAULT_WARRANTY_YEARS
    m = str(model).strip()
    if m in _warranty_table:
        return _warranty_table[m]
    for key in _WARRANTY_KEYS_BY_LEN:
        if key and key in m:
            return _warranty_table[key]
    for key in _WARRANTY_KEYS_BY_LEN:
        if key and m in key:
            return _warranty_table[key]
    return DEFAULT_WARRANTY_YEARS

# ==================== 本地故障对照表 ====================
def load_fault_mapping() -> dict:
    path = Path(FAULT_MAPPING_FILE)
    if not path.exists():
        path.write_text(
            json.dumps(DEFAULT_FAULT_MAPPING, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return dict(DEFAULT_FAULT_MAPPING)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_FAULT_MAPPING)

def save_fault_mapping(mapping: dict = None):
    """兼容旧接口：立即落盘故障对照表（一般无需调用，JsonStore 会自动落盘）。"""
    _fault_map.flush(force=True)


def flush_fault_mapping():
    """立即落盘故障对照表（若有脏数据）。"""
    _fault_map.flush()


# 故障对照表改用 JsonStore：线程安全 + 防抖落盘（旧实现每新增一条就全量重写 65KB+ 文件）
_fault_map = JsonStore(FAULT_MAPPING_FILE)
if not Path(FAULT_MAPPING_FILE).exists():
    # 首次运行：把预置对照表写入
    for _k, _v in DEFAULT_FAULT_MAPPING.items():
        _fault_map[_k] = _v
    _fault_map.flush(force=True)


def get_fault_cn(fault_en: str) -> str:
    if _is_blank(fault_en):
        return ""
    key = str(fault_en).strip()
    if key.lower() in ("unknown", "other", "n/a", "na", "未知", "其他"):
        return ""
        
    if key in _fault_map:
        return _fault_map[key]
    
    cn = translate(key, task="fault_class")
    if cn and cn not in ("未知", "其他", "未知故障"):
        _fault_map[key] = cn
        return cn
    return ""

def fault_from_sku(sku_text: str) -> str:
    if _is_blank(sku_text):
        return ""
    text = str(sku_text).strip()

    # ① 纯数字/编码精确匹配 (针对纯数字的备件消耗)
    for pure_code, fault_name in _PURE_SKU_ITEMS:
        if pure_code in text:
            return fault_name

    # ② 中英文文字关键词匹配
    for key, fault_name in _SKU_TO_FAULT_ITEMS:
        if key in text:
            return fault_name

    # ③ 查历史缓存
    cache_key = f"__SKU__{text}"
    if cache_key in _fault_map:
        return _fault_map[cache_key]

    # ④ LLM 兜底
    cn = classify_fault_from_sku(text)
    if cn and cn not in ("未知", "其他", "未知故障"):
        _fault_map[cache_key] = cn
        return cn

    return ""

# ==================== 日期 ====================
def parse_date(val):
    if pd.isna(val) or val is None or str(val).strip() == "":
        return None
    s = str(val).strip()[:10]
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def normalize_date(val) -> str:
    d = parse_date(val)
    return d.strftime("%Y/%m/%d") if d else ""

# ==================== 产品BU ====================
def get_product_bu(device_name: str) -> str:
    if _is_blank(device_name):
        return ""
    name = str(device_name).upper()
    for key, bu in _PRODUCT_BU_ITEMS:
        if key in name:
            return bu
    return ""

# ==================== 型号 ====================
def extract_model(device_name: str) -> str:
    if _is_blank(device_name):
        return ""
    name = str(device_name).strip()
    name = re.sub(r"^DREAME\s*-\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^Dreame\s+", "", name, flags=re.IGNORECASE)
    return name.strip()

# ==================== NFF 判定 ====================
NFF_KEYWORDS_NON_QUALITY = [
    "买配件", "购买配件", "购买机器", "购买耗材", "买整机", "补购", "加购",
    "buy", "purchase", "咨询产品", "询问产品", "问一下产品",
    "如何使用产品", "怎么用产品", "用户手册", "保修政策", "保修咨询",
    "inquiry", "consult", "无质量问题", "非质量问题", "仅备件", "仅咨询",
    "仅购买", "非维修", "非故障", "spare part only", "inquiry only", 
    "purchase only", "no quality issue",
]

# 预编译：非质量关键词一次性匹配（替代每行遍历列表）
_NON_QUALITY_RE = re.compile("|".join(re.escape(kw) for kw in NFF_KEYWORDS_NON_QUALITY))

def _has_nff_signal(text) -> bool:
    if _is_blank(text): return False
    t = str(text).upper()
    return "NFF" in t or "NO FAULT FOUND" in t

def _has_non_quality_signal(text) -> bool:
    if _is_blank(text): return False
    return _NON_QUALITY_RE.search(str(text)) is not None

def _decide_nff(fault3, repair_details, tech_notes, complaint) -> bool:
    if _has_nff_signal(tech_notes): return True
    if not _is_blank(tech_notes): return False

    if _has_nff_signal(repair_details): return True
    if not _is_blank(repair_details): return False

    if _has_nff_signal(fault3): return True
    if not _is_blank(fault3): return False

    if _has_non_quality_signal(complaint): return True

    return False

# ==================== 类别 ====================
# 注意：二返/三返/重复 由 repeat.RepeatClassifier 统一判定（按 SN + 日期），
# 这里只负责首次出现工单的基础类别。
def determine_category(warranty_years: float, date_created, date_purchased,
                       doa_validation: str, fault3: str, repair_details: str,
                       tech_notes: str, complaint: str) -> str:
    if date_created and date_purchased:
        days = (date_created - date_purchased).days
        limit = (warranty_years or DEFAULT_WARRANTY_YEARS) * 365
        if days > limit:
            return "维修（保外）"

    if str(doa_validation).strip().upper() == "DOA":
        return "DOA"

    if _decide_nff(fault3, repair_details, tech_notes, complaint):
        return "无异常（NFF）"

    return "维修（保内）"

# ==================== 单行处理 ====================
def process_row(row: pd.Series) -> dict:
    out = {}

    for src, dst in COLUMN_MAP.items():
        out[dst] = row.get(src, "")

    out["工单号"] = out.get("工单号", "")
    out["区域"] = FIXED_REGION
    out["代理"] = FIXED_AGENT
    out["型号"] = normalize_model(out.get("设备名称", ""))
    out["产品BU"] = get_product_bu(out.get("设备名称", ""))
    out["日期"] = normalize_date(out.get("关单日期", ""))
    out["SN"] = out.get("SN", "")

    # 注意：COLUMN_MAP 已把原始列名改写为标准字段名（如
    # "SKU consumption 备件使用" -> "SKU_consumption"），这里必须按
    # 【标准字段名】读取；旧代码误用原始列名，导致 SKU 消耗 / 维修方案 /
    # 技师备注 / DOA 标识永远读为空（相关匹配逻辑全部失效）。
    # 保留原始列名作为兜底，兼容两种映射。
    def _pick(*names) -> str:
        for n in names:
            v = out.get(n, "")
            if not _is_blank(v):
                return str(v).strip()
        return ""

    fault3 = _pick("Fault_Classification_3", "Fault Classification 3 故障类别 3", "Fault Classification 3")
    sku_text = _pick("SKU_consumption", "SKU consumption 备件使用", "SKU consumption")
    complaint_raw = _pick("用户描述原文", "Customer Complaint")
    repair_details_raw = _pick("Repair_Details", "Repair Details 维修方案", "Repair Details")
    tech_notes_raw = _pick("Repair_Details_Technician_Notes",
                           "Repair Details (Technician Notes)")
    doa_validation = _pick("DOA_Validation", "Auxiliary Field：DOA Validation", "DOA Validation")

    # ================== 核心逻辑：优先匹配原始故障，其次必须优先匹配 SKU！ ==================
    matched_fault = ""
    
    # 1. 原始表填了具体故障
    if not _is_blank(fault3):
        matched_fault = get_fault_cn(fault3)
        
    # 2. 如果没有，【强制优先看 SKU 消耗】（这里会检查文字，也会查纯数字编码）
    if not matched_fault and not _is_blank(sku_text):
        matched_fault = fault_from_sku(sku_text)
        
    # 3. 如果 SKU 没匹配出来，看 维修方案(Repair Details)
    if not matched_fault and not _is_blank(repair_details_raw):
        matched_fault = fault_from_sku(repair_details_raw)
        
    # 4. 如果还没，看 维修备注(Technician Notes)
    if not matched_fault and not _is_blank(tech_notes_raw):
        matched_fault = fault_from_sku(tech_notes_raw)
        
    # 5. 强扫用户描述关键字
    if not matched_fault and not _is_blank(complaint_raw):
        text_lower = complaint_raw.lower()
        if "battery" in text_lower or "charge" in text_lower: matched_fault = "电池包不良"
        elif "water" in text_lower and ("pump" in text_lower or "dispense" in text_lower): matched_fault = "水泵不良"
        elif "mop" in text_lower and ("spin" in text_lower or "turn" in text_lower): matched_fault = "拖布电机不良"
        elif "brush" in text_lower: matched_fault = "主刷不良"
        elif "lidar" in text_lower or "laser" in text_lower or "map" in text_lower: matched_fault = "LDS组件不良"
        elif "dock" in text_lower or "station" in text_lower: matched_fault = "基站充电组件不良"
        elif "wheel" in text_lower: matched_fault = "驱动轮不良"
        
    # 6. 实在找不到，让 AI 总结（限制字数防烧钱）
    if not matched_fault and not _is_blank(complaint_raw):
        ai_fault = translate(complaint_raw[:100], task="fault_from_complaint")
        if ai_fault and ai_fault not in ("未知", "其他", "未知故障"):
            matched_fault = ai_fault

    # 7. 终极兜底：只要不是 NFF，直接分类
    if not matched_fault:
        if _decide_nff(fault3, repair_details_raw, tech_notes_raw, complaint_raw):
            matched_fault = "无异常（NFF）"
        elif not _is_blank(sku_text):
            short_sku = sku_text[:15].replace("\n", " ") + "..." if len(sku_text) > 15 else sku_text.replace("\n", " ")
            matched_fault = f"更换备件({short_sku})"
        elif not _is_blank(complaint_raw):
            short_desc = complaint_raw[:15].replace("\n", " ") + "..." if len(complaint_raw) > 15 else complaint_raw.replace("\n", " ")
            matched_fault = f"其他问题({short_desc})"
        else:
            matched_fault = "其他硬件不良"

    out["故障类型（一级）"] = matched_fault
    # =========================================================

    # 处理方式判断
    raw_service = str(out.get("Type of Service原值", "") or "").strip().lower()
    if raw_service == "credit_claim":
        text = "\n".join([complaint_raw, repair_details_raw, tech_notes_raw])
        out["处理方式"] = classify_credit_claim(text)
    else:
        out["处理方式"] = PROCESS_METHOD_MAP.get(raw_service, "")

    # 类别判断（首次出现的基础类别；二返/三返/重复 由 RepeatClassifier 覆盖）
    date_created = parse_date(out.get("创建日期", ""))
    date_purchased = parse_date(out.get("购买日期", ""))
    warranty_years = lookup_warranty_years(out["型号"])

    out["类别"] = determine_category(
        warranty_years=warranty_years,
        date_created=date_created,
        date_purchased=date_purchased,
        doa_validation=doa_validation,
        fault3=fault3,
        repair_details=repair_details_raw,
        tech_notes=tech_notes_raw,
        complaint=complaint_raw,
    )

    # 故障描述（限制长度防烧钱）
    complaint_short = complaint_raw[:150] + "..." if len(complaint_raw) > 150 else complaint_raw
    out["故障描述"] = (
        translate(complaint_short, task="complaint")
        if not _is_blank(complaint_raw) else ""
    )

    # 维修详情（限制长度防烧钱）
    tech_short = tech_notes_raw[:150] + "..." if len(tech_notes_raw) > 150 else tech_notes_raw
    out["维修详情"] = (
        translate(tech_short, task="tech_notes")
        if not _is_blank(tech_notes_raw) else ""
    )

    # 备件消耗（原封不动）
    out["备件消耗"] = sku_text

    return out

# ==================== 批量处理 ====================
# 返修判定使用的原始列（SN + 日期 + 描述 + 维修详情）
_REPEAT_COLS = {
    "sn": "Serial Number",
    "date": "Date Created",
    "desc": "Customer Complaint",
    "detail": "Repair Details (Technician Notes)",
}


def process_dataframe(df: pd.DataFrame,
                      progress_cb=None,
                      on_row_done=None,
                      stop_flag_getter=None,
                      max_workers: int = MAX_WORKERS,
                      history_records=None) -> pd.DataFrame:

    df = df.dropna(how='all').copy()
    if "Ticket Number" in df.columns:
        df = df[df["Ticket Number"].notna() & (df["Ticket Number"].astype(str).str.strip() != "")].copy()

    # ===== 返修分类预扫描（重复 / 二返 / 三返）=====
    rows_snapshot = list(df.iterrows())
    records = [
        {"pos": pos,
         "sn": row.get(_REPEAT_COLS["sn"], ""),
         "date": row.get(_REPEAT_COLS["date"], ""),
         "desc": row.get(_REPEAT_COLS["desc"], ""),
         "detail": row.get(_REPEAT_COLS["detail"], "")}
        for pos, (_, row) in enumerate(rows_snapshot)
    ]
    repeat_plan = RepeatClassifier(history=history_records).build_plan(records)

    completed_faults = {}
    _cf_lock = threading.Lock()

    def handle_row(pos, row):
        try:
            out = process_row(row)
        except Exception as e:
            print(f"单行报错跳过 [工单号: {row.get('Ticket Number', '')}]：", e)
            out = {col: "" for col in OUTPUT_COLUMNS}
            out["工单号"] = row.get("Ticket Number", "ERROR")

        apply_label(out, pos, repeat_plan, rows_snapshot,
                    process_row, fault_getter=lambda p: (
                        completed_faults.get(p) if p is not None else None))

        with _cf_lock:
            completed_faults[pos] = str(
                out.get("故障类型（一级）", "") or "").strip()
        return out

    rows = run_batch(
        df, handle_row,
        max_workers=max_workers,
        progress_cb=progress_cb,
        on_row_done=on_row_done,
        stop_flag_getter=stop_flag_getter,
    )

    result = pd.DataFrame(rows)
    for col in OUTPUT_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    return result[OUTPUT_COLUMNS]
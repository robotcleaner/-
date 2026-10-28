import os
from dotenv import load_dotenv

load_dotenv()


def _get_secret(name: str, default: str = "") -> str:
    """读取配置，优先级：环境变量 → .env → Streamlit secrets。

    线上部署（Streamlit Community Cloud）时密钥存在 st.secrets 里，
    而不是环境变量，所以这里做一层兜底。
    """
    val = os.getenv(name, "")
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


# ===== 硅基流动配置 =====
SILICONFLOW_API_KEY = _get_secret("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
MODEL_TRANSLATE = "deepseek-ai/DeepSeek-V3"
MODEL_CLASSIFY  = "deepseek-ai/DeepSeek-V3"

TEMPERATURE = 0.1
MAX_TOKENS  = 2000
TIMEOUT     = 60
MAX_RETRY   = 3

# ===== 并发处理数 =====
# LLM 调用是 IO 密集型，串行处理是主要耗时瓶颈；多线程并发可数倍提速。
# 可用环境变量 TICKET_WORKERS 覆盖（1 = 串行）。
try:
    MAX_WORKERS = max(1, int(os.getenv("TICKET_WORKERS", "4")))
except ValueError:
    MAX_WORKERS = 4

# ===== 固定值 =====
FIXED_REGION = "澳洲"
FIXED_AGENT  = "PAU"

# ===== 断点续跑相关 =====
PARTIAL_RESULT_FILE = "partial_result.csv"

# ===== 原始表 → 输出表 的列映射（优化版 - 支持多区域）=====
COLUMN_MAP = {
    # === 澳洲区域专用映射（针对10月上原始工单AU.xlsx）===
    # 基础信息字段（澳洲）
    "Ticket Number":                            "工单号",
    "Serial Number":                            "SN",
    "Device Name":                              "设备名称",
    
    # 故障描述（澳洲）
    "Customer Complaint":                       "用户描述原文",
    
    # 质保信息（澳洲）
    "Ticket Type":                              "质保",
    "Type of Service":                          "Type of Service原值",
    
    # 故障分类（澳洲 - 注意实际列名包含中文字符）
    "Fault Classification 1 故障类别 1":        "Fault_Classification_1",
    "Fault Classification 2 故障类别 2":        "Fault_Classification_2", 
    "Fault Classification 3 故障类别 3":        "Fault_Classification_3",
    
    # 维修信息（澳洲）
    "Service Level":                            "Service_Level",
    "Repair Start Date 开始维修日期":            "Repair_Start_Date",
    "Repair Details 维修方案":                   "Repair_Details",
    "Repair Details (Technician Notes)":        "Repair_Details_Technician_Notes",
    
    # 备件信息（澳洲）
    "SKU consumption 备件使用":                  "SKU_consumption",
    
    # === 通用字段映射 ===
    # 辅助字段（兼容中文冒号）
    "Auxiliary Field：Status":                  "Status",
    "Auxiliary Field：Received  Date 2":        "Received_Date_2",  
    "Auxiliary Field：Repair TAT":              "Repair_TAT",
    "Auxiliary Field：Repair SLA":              "Repair_SLA",
    "Auxiliary Field：DOA Validation":          "DOA_Validation",
    "Auxiliary Field：Product Type":            "Product_Type",
    "Auxiliary Field：Closed Date":             "关单日期",
    "Auxiliary Field：Channel":                 "Channel",
    
    # 日期字段（澳洲）
    "Date Created":                             "创建日期",
    "Date Purchased":                           "购买日期",
}

# ===== 智能字段匹配规则（用于动态映射）=====
COLUMN_PATTERN_RULES = {
    # 按优先级匹配列名
    "ticket.*number": "Ticket Number",
    "serial.*number": "Serial Number",
    "customer.*complaint": "Customer Complaint",
    "device.*name": "Device Name",
    "fault.*classification.*1.*故障": "Fault Classification 1 故障类别 1",
    "fault.*classification.*2.*故障": "Fault Classification 2 故障类别 2", 
    "fault.*classification.*3.*故障": "Fault Classification 3 故障类别 3",
    "repair.*start.*date": "Repair Start Date 开始维修日期",
    "repair.*details.*维修": "Repair Details 维修方案",
    "sku.*consumption": "SKU consumption 备件使用",
}

# ===== 最终输出顺序（已新增“备件消耗”）=====
OUTPUT_COLUMNS = [
    "工单号",
    "区域",
    "代理",
    "型号",
    "产品BU",
    "日期",
    "SN",
    "故障类型（一级）",
    "处理方式",
    "类别",
    "故障描述",
    "维修详情",
    "备件消耗",
]

# ===== 质保表文件 =====
WARRANTY_TABLE_FILE = "warranty_table.csv"
DEFAULT_WARRANTY_YEARS = 1
REFURB_WINDOW_DAYS = 90

# ===== 处理方式映射 =====
PROCESS_METHOD_MAP = {
    "service":          "更换备件/配件",
    "spare_parts_only": "补发配件",
    "replacement":      "更换整机",
    "refund":           "退货",
}

CATEGORY_VALUES = ["DOA", "维修（保内）", "维修（保外）", "无异常（NFF）",
                   "重复", "二返（重现）", "二返（新故障）",
                   "三返（重现）", "三返（新故障）", "多返"]

# ===== 产品BU 型号前缀表 =====
PRODUCT_BU_MAP = {
    "L10": "扫地机", "L20": "扫地机", "L30": "扫地机", "L40": "扫地机", "L50": "扫地机", "L60": "扫地机",
    "X40": "扫地机", "X50": "扫地机", "X60": "扫地机", "D9": "扫地机", "D10": "扫地机", "D20": "扫地机",
    "D30": "扫地机", "F10": "扫地机", "F20": "扫地机", "Aqua10": "扫地机", "Aqua20": "扫地机", "Matrix10": "扫地机",
    "W10": "扫地机",
    "H11": "洗地机", "H12": "洗地机", "H13": "洗地机", "H14": "洗地机", "H15": "洗地机", "H16": "洗地机",
    "G10": "洗地机", "G12": "洗地机", "T16": "洗地机", "N10": "洗地机",
    "Z10": "吸尘器", "Z20": "吸尘器", "Z30": "吸尘器", "Z50": "吸尘器", "V11": "吸尘器", "R10": "吸尘器", "R20": "吸尘器",
    "T30": "吸尘器", "U20": "吸尘器", "Aero Straight": "吸尘器",
    "X1": "吸尘器", "X2": "吸尘器", "X3": "吸尘器", "AirStyle": "个护", "Glory": "个护", "Pocket": "个护",
    "Gusto": "个护", "Hair Miracle": "个护", "Dazzle": "个护", "Gleam": "个护", "A1": "割草机", "Z1": "泳池机",
    "PM20": "空净", "PM10": "空净", "FP10": "空净", "AP10": "空净", "AF30": "厨电", "PT60": "厨电",
    "PS30": "宠物", "PY10": "宠物", "PY20": "宠物", "PW10": "宠物", "XE10": "宠物",
}

# ===== 故障本地对照表路径 =====
FAULT_MAPPING_FILE = "fault_mapping.json"

# ===== 初始预置故障对照表（已暴力扩充常见英文）=====
DEFAULT_FAULT_MAPPING = {
    "The rag motor is faulty.": "拖布电机不良",
    "Motherboard malfunction": "主板不良",
    "LDS component malfunction": "LDS组件不良",
    "Fan malfunction": "风机不良",
    "Battery pack malfunction": "电池包不良",
    "Base station water pump board malfunction": "基站水泵板不良",
    "Dust collection duct blockage": "集尘风道堵塞",
    "NFF": "未发现故障",
    "No Fault Found": "未发现故障",
    "Main brushing bad": "主刷不良",
    "Filter screen installed in reverse": "滤网反向安装",
    "Side brush defect": "边刷不良",
    "Poor water pump": "水泵不良",
    "Base station recharge component malfunction": "基站回充组件不良",
    "The main unit's recharge component is faulty.": "主机回充组件不良",
    "Drive wheel malfunction": "驱动轮不良",
    "Defective caster wheel bracket": "万向轮支架不良",
    "Poor filter": "滤网不良",
    "Poor mop": "拖布不良",
    "Defective mop tray": "拖布盘不良",
    "Sewage pump malfunction": "污水泵不良",
    "Dust box malfunction": "尘盒不良",
    "Dust box damaged": "尘盒破损",
    "Dust bag malfunction": "尘袋不良",
    "Dust bag damaged; water ingress": "尘袋破损；进水",
    "Liquid level detection component malfunction": "液位检测组件不良",
    "Water tank malfunction": "水箱不良",
    "Solenoid valve malfunction": "电磁阀不良",
    "Three-way valve malfunction": "三通阀不良",
    "Peristaltic pump malfunction": "蠕动泵不良",
    "Main brush motor malfunction": "主刷电机不良",
    "Side brush motor malfunction": "边刷电机不良",
    "Rotary brush motor malfunction": "旋转刷电机不良",
    "WIFI board malfunction": "WIFI板不良",
    "Keypad malfunction": "按键板不良",
    "Core board defect": "核心板不良",
    "Malfunctioning casters": "万向轮不良",
    "Broken main brush cover": "主刷盖不良",
    "Main brush cover malfunction": "主刷盖不良",
    "Damaged mop tray": "拖布盘不良",
    "Mop tray entangled foreign object alarm": "拖布盘缠绕异物告警",
    "Base station leaking water": "基站漏水",
    "Water leak": "漏水",
    "Poor water pipes": "水管不良",
    "Duct blockage": "风道堵塞",
    "Dirt Detection Malfunction": "脏污检测不良",
    "Failed to switch suction level": "切换吸力档位失败",
    "Accessories cannot be installed": "配件无法安装",
    "Cannot turn on": "无法开机",
    "Unable to turn on": "无法开机",
    "Not charging": "无法充电",
    "Slow charging": "充电慢",
    "Weak suction force": "吸力弱",
    "No suction": "无吸力",
    "Don't suck dust": "不吸尘",
    "No water comes out when washing the mop.": "洗拖布不出水",
    "Base station self-cleaning without water": "基站自清洁不出水",
    "The base station is not discharging water; the water output is low.": "基站不出水；出水量少",
    "The mop head is not turning": "拖布盘不转",
    "The mop head has fallen off; there is no magnetism.": "拖布盘脱落；无磁力",
    "The mop cannot be raised or lowered.": "拖布无法升降",
    "Repeated charging and docking": "回充反复对接",
    "Base station button malfunction": "基站按键异常",
    "Base station indicator light is off": "基站指示灯不亮",
    "Unable to connect to the internet": "无法联网",
    "Unable to start dust collection": "无法启动集尘",
    "Unable to save map": "无法保存地图",
    "Map incomplete": "地图不完整",
    "Map missing": "地图丢失",
    "Map skew; overall offset; overlay map": "地图歪斜；整体偏移；叠图",
    "Map cannot be switched": "地图无法切换",
    "Map creation failed": "建图失败",
    "App crashes; App plugin malfunctions": "APP闪退；APP插件异常",
    "Host button malfunction": "主机按键异常",
    "Dust collection seat leaks dust": "集尘座漏灰",
    "Dust collection valve deformed and discolored": "集尘阀门变形变色",
    "False alarm: Dust bag not installed": "误报尘袋未安装",
    "False alarm: Water tank not installed": "误报清水箱未安装",
    "False alarm: Wastewater tank not installed": "误报污水箱未安装",
    "False alarm: Cleaning solution not installed": "误报清洁液未安装",
    "False alarm: host trapped": "误报主机被困",
    "The dustbin is not installed (filter magnet is in place).": "尘盒提示未安装",
    "Alarm during scrolling; scrolling without rotation": "边刷告警；边刷不转",
    "Side brush deformed; damaged": "边刷变形；破损",
    "Side brush detached": "边刷脱落",
    "Obstacle crossing failure": "越障失败",
    "Cliff sensor malfunction alarm": "悬崖传感器异常告警",
    "Edge sensor alarm": "沿边传感器告警",
    "Wheel dangling warning": "轮子悬空告警",
    "Spinning in place": "原地转圈",
    "Path skew": "路径歪斜",
    "Laser sensor collision alarm": "激光传感器撞板告警",
    "LDS laser sensor alarm": "LDS激光传感器告警",
    "Internal error": "内部错误",
    "System crash (the machine pauses unexpectedly during the cleaning process)": "死机",
    "Continuous dust collection without stopping when powered on": "通电持续集尘不停止",
    "Keys are not working; keys are unresponsive": "按键无效",
    "The roller brush is not turning": "滚刷不转",
    "Unable to power on; buttons unresponsive.": "无法开机；按键无反应",
    "Fast battery drain; short battery life": "掉电快；续航短",
    "Battery pack is defective": "电池异常",
    "Defective adapter": "适配器不良",
    "No water coming out of base station/base": "基站不出水",
    "Water does not come out when mopping the floor": "拖地不出水",
    "Noise": "噪音",
    "Abnormal dust collection fan": "集尘风机异常",
    "Base Station Wash Mop Abnormal": "基站洗拖布异常",
    "Defective recharging": "无法回充",
    "Defective dirty water pump": "污水泵异常",
    "Defective water pump": "水泵异常",
    "There is a watermark when mopping the floor; the mark is obvious": "拖地有水印",
    "Water droplets on the ground": "地面有水滴",
    "Unable to reach the designated area for cleaning": "无法到达指定区域清扫",
    "Odor stinks": "异味发臭",
    "Loud noise": "噪音大",
    "Damage the floor": "损伤地板",
    "Poor obstacle avoidance effect": "避障效果不佳",
    "Water supply and drainage - wastewater not pumped out (wastewater is present in the cleaning tray).": "污水排不出",
    "Software related": "软件问题",
    "Main brush entanglement warning": "主刷缠绕告警",
    "Dust collection valve deformed and discolored": "集尘阀变形",
    "The base station is not discharging water": "基站不出水",
    "Mop head is not turning": "拖布不转",
    "Unknown": "未知故障",
    "Other": "其他故障",
}

# ===== SKU → 故障类型（一级） 对照表 =====
SKU_TO_FAULT = {
    # 中文
    "拖把垫": "拖布不良", "拖布": "拖布不良", "主刷电机": "主刷电机不良", "主刷盖": "主刷盖不良",
    "主刷罩": "主刷罩不良", "主刷腔": "主刷不良", "主刷": "主刷不良", "滚筒": "滚筒不良",
    "滚刷": "滚刷不良", "侧刷": "边刷不良", "边刷": "边刷不良", "万向轮": "万向轮不良",
    "全向轮": "万向轮不良", "主轮": "驱动轮不良", "驱动轮": "驱动轮不良", "LDS": "LDS组件不良",
    "激光": "线激光不良", "主板": "主板不良", "核心板": "核心板不良", "电池": "电池包不良",
    "集尘电机": "集尘电机不良", "风机": "风机不良", "风扇": "风机不良", "污水泵": "污水泵不良",
    "水泵": "水泵不良", "清水箱": "清水箱不良", "污水箱": "污水箱不良", "水箱": "水箱不良",
    "尘袋": "尘袋不良", "尘盒": "尘盒不良", "滤网": "滤网不良", "滤芯": "滤芯不良",
    "传感器": "传感器不良", "撞板": "撞板不良", "充电片": "充电片支架不良", "充电线": "充电线束不良",
    "基站主板": "基站主板不良", "电源板": "基站电源板不良", "电磁阀": "电磁阀不良",
    "三通阀": "三通阀不良", "单向阀": "单向阀不良", "显示屏": "显示屏不良", "按键": "按键板不良",

    # 英文（精准匹配）
    "Main brush cavity": "主刷不良", "Main Brush Cover": "主刷盖不良", "Main Brush (Rubber)": "主刷不良",
    "Main Brush": "主刷不良", "Mop pad gearcase": "拖布电机不良", "Mop Pad Holder": "拖布盘不良",
    "Mop Pad": "拖布不良", "Mop pad": "拖布不良", "Mop motor": "拖布电机不良", "Rag motor": "拖布电机不良",
    "Rag": "拖布不良", "Side Brush Gearcase": "边刷电机不良", "Side brush motor": "边刷电机不良",
    "Side Brush": "边刷不良", "Side brush": "边刷不良", "Roller Brush": "滚筒刷不良", "Roller brush": "滚筒刷不良",
    "Roller motor": "滚筒电机不良", "LDS assembly": "LDS组件不良", "LDS module": "LDS组件不良",
    "LDS": "LDS组件不良", "Line laser": "线激光不良", "line laser": "线激光不良",
    "Motherboard": "主板不良", "Mainboard": "主板不良", "MLB": "主板不良", "Core board": "核心板不良",
    "Battery pack": "电池包不良", "Battery": "电池包不良", "battery": "电池包不良",
    "Blower with harness": "风机不良", "Blower": "风机不良", "Fan assembly": "风机不良",
    "Fan": "风机不良", "fan": "风机不良", "Dust collecting motor": "集尘电机不良",
    "Sewage pump": "污水泵不良", "Clean water pump": "水泵不良", "Water pump": "水泵不良",
    "Used Water Tank": "污水箱不良", "Clean Water Tank": "清水箱不良", "Dirty Water Tank": "污水箱不良",
    "Water tank": "水箱不良", "Dust box": "尘盒不良", "Dust Box": "尘盒不良",
    "Dust bag": "尘袋不良", "Dust Bag": "尘袋不良", "Filter": "滤网不良", "filter": "滤网不良",
    "HEPA": "滤网不良", "Ultrasonic": "超声波不良", "Cliff sensor": "悬崖传感器异常",
    "PSD": "下视不良", "Bumper": "保险杠总成不良", "Charging harness": "充电线束不良",
    "Auto Water Refilling": "主机回充组件不良", "Station recharging assembly": "基站充电组件不良",
    "Infrared Recharge": "基站红外充电组件不良", "Station main board": "基站主板不良",
    "Station power board": "基站电源板不良", "Base station power board": "基站电源板不良",
    "Solenoid valve": "电磁阀不良", "Three way valve": "三通阀不良", "One-way valve": "单向阀不良",
    "Valve": "阀门不良", "Display": "显示屏不良", "Button board": "按键板不良", "Keypad": "按键板不良",
    "Screen": "屏幕异常", "Detergent": "洗涤剂存储盒组件不良", "Cleaning tray": "清洗盘不良",
    "Washboard": "清洗盘不良", "Universal wheel": "万向轮不良", "Omni wheel": "万向轮不良",
    "Drive wheel": "驱动轮不良", "Main wheel": "驱动轮不良", "Top cap": "顶盖组件不良",
}
"""
产品型号格式统一
================

各国原始工单的型号写法不一致（澳洲 "DREAME - Dreame L40 Ultra CE"、
KOLON "X50s_pro_ultra" / "X50Ultra(BLK)"、韩国 "X60 Master" …），
统一归一为**澳洲工单的型号格式**：去掉品牌前缀后，词与词之间以单个
空格分隔、后缀规范大小写，例如：

    DREAME - Dreame L40 Ultra CE   →  L40 Ultra CE
    X50s_pro_ultra                 →  X50s Pro Ultra
    X50Ultra(BLK)                  →  X50 Ultra (BLK)
    x50 master                     →  X50 Master

归一化是幂等的：已经是澳洲格式的值原样返回。
"""

import re

# ===== 品牌前缀（大小写不敏感，可叠加，如 "DREAME - Dreame X"）=====
BRAND_PREFIXES = [
    "DREAME - ", "DREAME- ", "DREAME-", "DREAME – ", "DREAME ",
    "Dreame - ", "Dreame- ", "Dreame-", "Dreame ",
    "드리미 - ", "드리미-", "드리미 ",
    "디어름 - ", "디어름 ",
    "追觅 - ", "追觅-", "追觅 ",
]

# ===== 后缀 / 限定词规范大小写 =====
CANON_TOKENS = {
    "ultra": "Ultra", "pro": "Pro", "master": "Master", "plus": "Plus",
    "max": "Max", "lite": "Lite", "mini": "Mini", "air": "Air",
    "gen1": "Gen1", "gen2": "Gen2", "gen3": "Gen3", "gen4": "Gen4",
    "heat": "Heat", "station": "Station", "vacuum": "Vacuum",
    "ce": "CE", "blk": "BLK", "wht": "WHT", "w&d": "W&D", "wd": "W&D",
    "tracker": "Tracker", "track": "Track", "s": "S", "x": "X",
    "eu": "EU", "us": "US", "kr": "KR", "jp": "JP", "au": "AU",
}

# ===== 韩文后缀 → 英文（与澳洲格式对齐；样本不足，取最通用的几个）=====
KR_TOKENS = {
    "울트라": "Ultra", "마스터": "Master", "프로": "Pro",
    "플러스": "Plus", "히트": "Heat", "스테이션": "Station",
    "맥스": "Max", "라이트": "Lite",
}

# 型号码：x50 → X50、l10s → L10s（首字母大写，其余保持原样）
_MODEL_CODE_RE = re.compile(r"^[a-z]\d+[a-z]?$")

# camelCase 分词规则（保守，避免误伤 FlexReach 这类既有单词）：
#   R1 数字后紧跟新单词：X50Ultra → X50 Ultra
#   R2 缩写结束：L10SUltra → L10S Ultra、HEPAFilter → HEPA Filter
#   R3 数字后紧跟小写词：X50master → X50 master、L20ultra → L20 ultra
_SPLIT_RE = re.compile(
    r"(?<=\d)(?=[A-Z][a-z])"      # R1
    r"|(?<=[A-Z])(?=[A-Z][a-z])"  # R2
    r"|(?<=\d)(?=[a-z]{2,})"      # R3
)


def _canon_token(tok: str) -> str:
    """单个 token 的规范大小写；括号 token 如 (BLK) 处理内部。"""
    if len(tok) >= 2 and tok.startswith("(") and tok.endswith(")"):
        inner = _canon_token(tok[1:-1])
        return f"({inner})"
    key = tok.lower()
    if key in CANON_TOKENS:
        return CANON_TOKENS[key]
    if key in KR_TOKENS:
        return KR_TOKENS[key]
    if _MODEL_CODE_RE.match(key):
        return tok[0].upper() + tok[1:]
    return tok


def normalize_model(name) -> str:
    """把任意国家的型号写法归一为澳洲工单格式。"""
    if name is None:
        return ""
    s = str(name).strip()
    if not s or s.lower() in ("nan", "nat", "none", "null"):
        return ""

    # 1) 去品牌前缀（可能叠加，循环去除）
    changed = True
    while changed:
        changed = False
        low = s.lower()
        for p in BRAND_PREFIXES:
            if low.startswith(p.lower()):
                s = s[len(p):].strip()
                changed = True
                break

    # 2) 下划线 / 连字符 → 空格
    s = s.replace("_", " ").replace("-", " ")

    # 3) camelCase 分词（保守规则，见 _SPLIT_RE 注释）
    s = _SPLIT_RE.sub(" ", s)

    # 4) 括号独立成 token：X50 Ultra(BLK) → X50 Ultra (BLK)
    s = re.sub(r"\s*\(\s*", " (", s)
    s = re.sub(r"\s*\)\s*", ") ", s)

    # 5) 压缩空白
    s = re.sub(r"\s+", " ", s).strip()

    # 6) 逐 token 规范大小写
    return " ".join(_canon_token(t) for t in s.split(" ") if t)

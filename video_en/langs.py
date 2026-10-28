# -*- coding: utf-8 -*-
"""目标语言配置表

新增一种语言只需要在 LANGS 里加一项，翻译 / 配音 / 字幕 / 界面会自动跟着变。
（源语言固定为中文普通话）
"""
from __future__ import annotations

# 语言种类标记，供译文校验和排版用
SCRIPT_LATIN = "latin"
SCRIPT_JA = "ja"
SCRIPT_KO = "ko"
SCRIPT_CJK = "cjk"

LANGS = {
    "en": {
        "code": "en",
        "name": "英语",
        "short": "英文",
        "suffix": "en",
        # 各翻译后端的语言代码
        "mymemory": "en",
        "baidu": "en",          # 百度：en=英语
        "google": "en",
        "argos": "en",
        # 字幕
        "font": "Arial",
        "char_w": 0.52,         # 估算每字符宽度（相对字号）
        "size_ratio": 0.039,    # 字号 = 短边 × 该系数（720 → 28px）
        "max_line": 58,         # 仅目标语言时单条最多字符
        "max_line_bi": 70,      # 双语模式下最多字符
        "script": SCRIPT_LATIN,
        # 配音
        "cps": 15.0,            # 估算语速：字符/秒
        # 领域术语（中文=目标语言）。不给的话模型不知道这是扫地机器人，
        # 会把「拖布」译成 lace（蕾丝）、「刮条」译成 scraper/glider。
        "terms": {
            "拖布": "mop pad",
            "拖布组件": "mop pad assembly",
            "释放键": "release button",
            "污水箱": "waste water tank",
            "污水槽": "waste water tank",
            "刮条": "squeegee",
            "卡扣": "retaining clip",
        },
        "pyttsx3": ("english", "en-", "en_us", "en-gb", "zira", "david"),
        "default_voice": "en-US-AndrewNeural",
        "voices": {
            "en-US-AndrewNeural": "英文男声 Andrew（推荐）",
            "en-US-AriaNeural": "英文女声 Aria",
            "en-US-GuyNeural": "英文男声 Guy（新闻风）",
            "en-US-JennyNeural": "英文女声 Jenny",
            "en-GB-SoniaNeural": "英式女声 Sonia",
            "en-AU-NatashaNeural": "澳式女声 Natasha",
        },
    },
    "ja": {
        "code": "ja",
        "name": "日语",
        "short": "日文",
        "suffix": "ja",
        "mymemory": "ja",
        "baidu": "jp",          # 百度：jp=日语（不是 ja）
        "google": "ja",
        "argos": "ja",
        "font": "Yu Gothic",
        "char_w": 1.0,
        "size_ratio": 0.036,    # 720 → 26px（日文字形饱满，比英文略小更协调）
        "max_line": 40,
        "max_line_bi": 44,
        "script": SCRIPT_JA,
        "cps": 6.6,
        "terms": {
            "拖布": "モップパッド",
            "拖布组件": "モップパッドアセンブリ",
            "释放键": "取り外しボタン",
            "污水箱": "汚水タンク",
            "污水槽": "汚水タンク",
            "刮条": "スクイジー",
            "卡扣": "固定クリップ",
        },
        "pyttsx3": ("japanese", "ja-", "ja_jp", "haruka", "ayumi", "ichiro"),
        "default_voice": "ja-JP-NanamiNeural",
        "voices": {
            "ja-JP-NanamiNeural": "日文女声 Nanami（推荐）",
            "ja-JP-KeitaNeural": "日文男声 Keita",
            "ja-JP-AoiNeural": "日文女声 Aoi（年轻）",
            "ja-JP-DaichiNeural": "日文男声 Daichi",
            "ja-JP-MayuNeural": "日文女声 Mayu",
        },
    },
    "ko": {
        "code": "ko",
        "name": "韩语",
        "short": "韩文",
        "suffix": "ko",
        "mymemory": "ko",
        "baidu": "kor",         # 百度：kor=韩语
        "google": "ko",
        "argos": "ko",
        "font": "Malgun Gothic",
        "char_w": 1.0,
        "size_ratio": 0.036,    # 720 → 26px
        "max_line": 40,
        "max_line_bi": 44,
        "script": SCRIPT_KO,
        "cps": 6.3,
        "terms": {
            "拖布": "모프 패드",
            "拖布组件": "모프 패드 어셈블리",
            "释放键": "분리 버튼",
            "污水箱": "오수 탱크",
            "污水槽": "오수 탱크",
            "刮条": "스퀴지",
            "卡扣": "고정 클립",
        },
        "pyttsx3": ("korean", "ko-", "ko_kr", "heami", "yuna"),
        "default_voice": "ko-KR-SunHiNeural",
        "voices": {
            "ko-KR-SunHiNeural": "韩文女声 SunHi（推荐）",
            "ko-KR-InJoonNeural": "韩文男声 InJoon",
            "ko-KR-JiMinNeural": "韩文女声 JiMin",
            "ko-KR-HyunsuNeural": "韩文男声 Hyunsu",
        },
    },
}

DEFAULT_LANG = "en"
ORDER = ("en", "ja", "ko")          # 界面下拉框顺序


def get(code: str = "") -> dict:
    """取语言配置；未知代码回退到英语"""
    return LANGS.get((code or "").strip().lower(), LANGS[DEFAULT_LANG])


def voice_of(cfg: dict) -> str:
    """取该语言下可用的配音嗓音；配置里的嗓音不属于当前语言时用默认值"""
    lang = get(cfg.get("target_lang", DEFAULT_LANG))
    voice = (cfg.get("tts_voice") or "").strip()
    if voice in lang["voices"]:
        return voice
    return lang["default_voice"]


def suffix_of(cfg: dict) -> str:
    return get(cfg.get("target_lang", DEFAULT_LANG))["suffix"]


def name_of(cfg: dict, short: bool = False) -> str:
    lang = get(cfg.get("target_lang", DEFAULT_LANG))
    return lang["short"] if short else lang["name"]

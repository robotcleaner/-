# -*- coding: utf-8 -*-
"""配置管理：读写程序目录下的 config.json"""
from __future__ import annotations
import json
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

DEFAULT_CONFIG = {
    # ffmpeg：留空则自动查找 PATH / 程序 bin 目录
    "ffmpeg_path": "",
    # 目标语言：en=英语 / ja=日语 / ko=韩语（源语言固定为中文普通话）
    "target_lang": "en",
    # 语音识别模型：tiny / base / small / medium / large-v3
    # 中文视频建议 small 及以上（tiny/base 对中文识别错误率很高）
    "whisper_model": "small",
    # 字幕模式：bilingual=双语（中文在上、目标语言在下） / en=仅目标语言
    #           en_below=仅目标语言，压在原视频自带中文字幕下方
    # 注：模式名里的 en 是历史命名，实际输出语言由 target_lang 决定
    "subtitle_mode": "bilingual",
    # 自动避让原视频自带的（烧录）中文字幕：检测到就只叠加英文，避免中文重复
    "auto_avoid_source_subs": True,
    # TTS 后端：edge=微软在线语音（推荐） / offline=系统离线语音
    "tts_backend": "edge",
    "tts_voice": "en-US-AndrewNeural",
    # 配音语速偏好（百分点）：0=自动匹配内容；负数更慢更自然；正数更快
    "tts_pace_bias": 0,
    # 输出分辨率
    "resolution": "1280x720",
    # 是否保留原声作为背景音
    "keep_original_audio": False,
    "original_audio_volume": 0.12,
    # 翻译后端：mymemory(免密钥，开箱即用) / zhipu(智谱，免费且质量最好) /
    #           baidu / llm / google / argos(离线)
    # 默认 mymemory 是为了让同事拿到就能跑，不用先去申请任何 Key
    "translate_backend": "mymemory",
    "baidu_appid": "",
    "baidu_key": "",
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_api_key": "",
    "llm_model": "deepseek-chat",
    # MyMemory 免费翻译：填邮箱可把每日额度从 5000 字符提到 50000
    "mymemory_email": "",
    # 智谱 GLM（glm-4-flash 完全免费），只需填 API Key
    "zhipu_api_key": "",
    # HuggingFace 下载源（默认国内镜像，可改回 https://huggingface.co）
    "hf_endpoint": "https://hf-mirror.com",
    # 输出目录（留空则使用程序目录下 output/）
    "output_dir": "",
    # 编码参数
    "crf": 20,
    "preset": "medium",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

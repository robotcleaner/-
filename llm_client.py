# llm_client.py
import hashlib
import json
import os
from pathlib import Path
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

# ==================== 配置加载（兼容本地 + 云端）====================
def _load_secret(key: str, default: str = "") -> str:
    """优先从 st.secrets 读，本地开发 fallback 到环境变量"""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


SILICONFLOW_API_KEY = _load_secret("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = _load_secret("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
MODEL_TRANSLATE = _load_secret("MODEL_TRANSLATE", "deepseek-ai/DeepSeek-V3")
MODEL_CLASSIFY  = _load_secret("MODEL_CLASSIFY",  "deepseek-ai/DeepSeek-V3")

TEMPERATURE = 0.1
MAX_TOKENS  = 2000
TIMEOUT     = 60
MAX_RETRY   = 3

client = OpenAI(
    api_key=SILICONFLOW_API_KEY,
    base_url=SILICONFLOW_BASE_URL,
    timeout=TIMEOUT,
)

# ==================== 内存缓存（替代 .cache.json）====================
_cache = {}


def _cache_key(text: str, task: str) -> str:
    return hashlib.md5(f"{task}::{text}".encode("utf-8")).hexdigest()


def _is_empty(text) -> bool:
    if text is None:
        return True
    s = str(text).strip()
    if not s:
        return True
    if s.lower() in ("nan", "none", "null", "nat"):
        return True
    return False


@retry(stop=stop_after_attempt(MAX_RETRY),
       wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_llm(prompt: str, model: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    return resp.choices[0].message.content.strip()


def translate(text: str, task: str = "translate") -> str:
    if _is_empty(text):
        return ""
    key = _cache_key(text, task)
    if key in _cache:
        return _cache[key]

    from prompts import PROMPTS
    prompt = PROMPTS[task].format(text=text)
    result = _call_llm(prompt, MODEL_TRANSLATE)

    if not result or len(result) > 2000:
        return ""
    if "无法翻译" in result or "请提供" in result:
        return ""

    _cache[key] = result
    return result


def classify_fault_from_sku(sku_text: str) -> str:
    if _is_empty(sku_text):
        return ""
    key = _cache_key(sku_text, "fault_from_sku")
    if key in _cache:
        return _cache[key]

    from prompts import PROMPTS
    prompt = PROMPTS["fault_from_sku"].format(text=str(sku_text)[:2000])
    result = _call_llm(prompt, MODEL_CLASSIFY)

    if not result or len(result) > 30:
        return ""
    result = result.replace("【", "").replace("】", "").strip()[:12]
    if "未知" in result or "无法" in result:
        return ""

    _cache[key] = result
    return result


def classify_credit_claim(text: str) -> str:
    if _is_empty(text):
        return "更换备件/配件"
    key = _cache_key(text, "credit_claim")
    if key in _cache:
        return _cache[key]

    from prompts import PROMPTS
    prompt = PROMPTS["credit_claim"].format(text=str(text)[:2000])
    result = _call_llm(prompt, MODEL_CLASSIFY)
    result = result.replace("【", "").replace("】", "").strip()

    if "退货" in result:
        result = "退货"
    elif "更换整机" in result:
        result = "更换整机"
    else:
        result = "更换备件/配件"

    _cache[key] = result
    return result

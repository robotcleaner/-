import hashlib
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from paths import state_path
from config import (
    SILICONFLOW_BASE_URL, get_api_key,
    MODEL_TRANSLATE, MODEL_CLASSIFY,
    TEMPERATURE, MAX_TOKENS, TIMEOUT, MAX_RETRY,
)
from prompts import PROMPTS
from batch import JsonStore

# 客户端改为「按需创建」：旧实现在 import 阶段就 new OpenAI()，
# 一旦密钥没配好（本地没 .env / 云端没 Secrets），整个页面直接抛红字堆栈，
# 用户完全看不出该怎么修。现在改成调用时才创建，缺密钥由界面给出明确提示。
_client = None
_client_key = ""

NO_KEY_HINT = (
    "未配置 SILICONFLOW_API_KEY。\n"
    "· 本地：在项目根目录的 .env 里写 SILICONFLOW_API_KEY=sk-你的key\n"
    "· Streamlit Cloud：Settings → Secrets 里写 SILICONFLOW_API_KEY = \"sk-你的key\"，"
    "保存后点 Reboot app"
)


def get_client():
    """返回 OpenAI 客户端；缺密钥时抛带操作指引的 RuntimeError。"""
    global _client, _client_key
    key = get_api_key()
    if not key:
        raise RuntimeError(NO_KEY_HINT)
    # 密钥变了（比如换了新 Key）就重建客户端
    if _client is None or key != _client_key:
        _client = OpenAI(
            api_key=key,
            base_url=SILICONFLOW_BASE_URL,
            timeout=TIMEOUT,
        )
        _client_key = key
    return _client


def has_api_key() -> bool:
    return bool(get_api_key())

# ==================== 磁盘缓存 ====================
# 旧实现：每新增一条翻译就全量重写 .cache.json（已 1MB+），缓存越大越慢，
# 累积磁盘 IO 呈 O(N^2)。现由 JsonStore 防抖落盘：
#   - 写入只进内存（加锁，多线程安全）；
#   - 累计 10 条新条目或每隔 10 秒由后台线程落盘一次；
#   - atexit 保证进程退出前最终落盘。
CACHE_FILE = state_path(".cache.json")
_cache = JsonStore(CACHE_FILE)


def _cache_key(text: str, task: str) -> str:
    return hashlib.md5(f"{task}::{text}".encode("utf-8")).hexdigest()


def _save_cache():
    """兼容旧接口：立即全量落盘（一般无需调用，JsonStore 会自动落盘）。"""
    _cache.flush(force=True)


def flush_cache():
    """立即落盘缓存（若有脏数据）。"""
    _cache.flush()


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
    resp = get_client().chat.completions.create(
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

    prompt = PROMPTS[task].format(text=text)
    result = _call_llm(prompt, MODEL_TRANSLATE)

    if not result or len(result) > 2000:
        result = ""
    if "无法翻译" in result or "请提供" in result:
        result = ""

    # 含空结果一起缓存：避免同一段异常文本反复付费调用
    _cache[key] = result
    return result


def classify_fault_from_sku(sku_text: str) -> str:
    """从备件 SKU 推断故障类型（LLM 兜底，缓存由 JsonStore 统一管理）"""
    if _is_empty(sku_text):
        return ""
    key = _cache_key(sku_text, "fault_from_sku")
    if key in _cache:
        return _cache[key]

    prompt = PROMPTS["fault_from_sku"].format(text=str(sku_text)[:2000])
    result = _call_llm(prompt, MODEL_CLASSIFY)

    if not result or len(result) > 30:
        result = ""
    # 只保留前 12 个字符，避免模型话多
    result = result.replace("【", "").replace("】", "").strip()[:12]
    if "未知" in result or "无法" in result:
        result = ""

    _cache[key] = result
    return result


def classify_credit_claim(text: str) -> str:
    """判断 credit_claim 是 退货 / 更换整机 / 更换备件/配件"""
    if _is_empty(text):
        return "更换备件/配件"
    key = _cache_key(text, "credit_claim")
    if key in _cache:
        return _cache[key]

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

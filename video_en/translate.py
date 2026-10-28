# -*- coding: utf-8 -*-
"""中文 → 目标语言翻译（多后端：mymemory / zhipu / baidu / llm / google / argos）"""
from __future__ import annotations
import re
import time

import langs


class TranslateError(RuntimeError):
    pass


class FatalTranslateError(TranslateError):
    """配置类错误（密钥无效/未授权），重试无意义，直接中止"""
    pass


# 智谱 GLM：glm-4-flash 目前完全免费且不限量，OpenAI 兼容接口
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_MODEL = "glm-4-flash"


# 百度错误码中属于「配置错误」的，重试不会成功
BAIDU_FATAL_CODES = {
    "52003",  # 未授权用户（APP ID 不存在或未开通服务）
    "54001",  # 签名错误（密钥不对）
    "54004",  # 账户余额不足
    "54005",  # 长query请求频繁（通常为超长文本）
    "58000",  # 客户端IP非法
    "58001",  # 译文语言方向不支持
    "58002",  # 服务当前已关闭
}


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")


def foreign_script(text: str, lang_code: str) -> str:
    """译文里混进来的其他语言文字，没有则返回空串。

    大模型偶尔会把某一行的语言「串台」——实测 glm-4-flash 在韩语批次里
    把第一行整句译成了日语（`缓やかに上に引き上げて…取り外します`），
    也会把「脱布」这类原文原样留在韩语里。只判断「有没有目标语言文字」
    是拦不住的（混了日文的句子照样含韩文），必须再查一遍杂质。
    """
    script = langs.get(lang_code)["script"]
    if script == langs.SCRIPT_KO:
        if _KANA_RE.search(text):
            return "混进了日文假名"
        if _CJK_RE.search(text):
            return "混进了汉字（中文没译干净）"
    elif script == langs.SCRIPT_JA:
        if _HANGUL_RE.search(text):
            return "混进了韩文"
    else:
        if _KANA_RE.search(text):
            return "混进了日文假名"
        if _HANGUL_RE.search(text):
            return "混进了韩文"
    return ""


def looks_translated(text: str, lang_code: str = "en"):
    """校验译文是不是真的译成了目标语言。返回 (ok, 原因)

    翻译接口在失败/限流时会静默把原文还回来，若不校验，最终视频里就只有
    中文字幕（用户看到的「不是英文/日文」），所以这里必须严格判定。
    """
    s = (text or "").strip()
    if not s:
        return False, "译文为空"
    script = langs.get(lang_code)["script"]

    if script == langs.SCRIPT_JA:
        # 日语一定含假名；纯汉字说明要么没翻、要么还是中文
        if not _KANA_RE.search(s):
            return False, "译文里没有假名，说明没译成日语（多半把原文还回来了）"
        bad = foreign_script(s, lang_code)
        return (False, bad) if bad else (True, "")

    if script == langs.SCRIPT_KO:
        if not _HANGUL_RE.search(s):
            return False, "译文里没有韩文字母，说明没译成韩语（多半把原文还回来了）"
        bad = foreign_script(s, lang_code)
        return (False, bad) if bad else (True, "")

    # 拉丁字母语言（英语等）
    latin = len(_LATIN_RE.findall(s))
    cjk = len(_CJK_RE.findall(s))
    if cjk and latin <= cjk:
        return False, "译文仍是中文（翻译接口把原文还回来了）"
    if latin < 2 or latin < len(s) * 0.25:
        return False, "译文里几乎没有英文"
    bad = foreign_script(s, lang_code)
    return (False, bad) if bad else (True, "")


def looks_english(text: str):
    """向后兼容：等价于 looks_translated(text, "en")"""
    return looks_translated(text, "en")


def _mymemory(text: str, email: str = "", lang_code: str = "en") -> str:
    """MyMemory 免费接口：免密钥、国内可直连。

    匿名每天约 5000 字符；在 config.json 里填 mymemory_email 可提到 50000。
    """
    import requests
    target = langs.get(lang_code)["mymemory"]
    params = {"q": text[:450], "langpair": "zh-CN|" + target}
    if email:
        params["de"] = email
    resp = requests.get("https://api.mymemory.translated.net/get",
                        params=params, timeout=20)
    resp.raise_for_status()
    try:
        j = resp.json()
    except ValueError:
        raise TranslateError("MyMemory 返回非 JSON")
    if str(j.get("responseStatus")) != "200":
        raise TranslateError("MyMemory 错误 %s: %s"
                             % (j.get("responseStatus"),
                                j.get("responseDetails")))
    out = (j.get("responseData") or {}).get("translatedText", "") or ""
    if "MYMEMORY WARNING" in out.upper() or "QUOTA" in out.upper():
        raise FatalTranslateError(
            "MyMemory 今日免费额度已用完（匿名约 5000 字符/天）。"
            "可在 config.json 里填 mymemory_email 提到 50000 字符/天，"
            "或改用百度 / DeepSeek 后端")
    return out


def _google(text: str, lang_code: str = "en") -> str:
    from deep_translator import GoogleTranslator
    out = GoogleTranslator(source="zh-CN",
                           target=langs.get(lang_code)["google"]).translate(text)
    if not out:
        raise TranslateError("Google 翻译返回空（网络不可达或被限流）")
    return out


def _baidu(text: str, appid: str, key: str, lang_code: str = "en") -> str:
    import hashlib
    import random
    import requests
    salt = str(random.randint(32768, 65536))
    sign = hashlib.md5((appid + text + salt + key).encode("utf-8")).hexdigest()
    resp = requests.post(
        "https://api.fanyi.baidu.com/api/trans/vip/translate",
        data={"q": text, "from": "zh", "to": langs.get(lang_code)["baidu"],
              "appid": appid, "salt": salt, "sign": sign},
        timeout=20)
    resp.raise_for_status()
    try:
        j = resp.json()
    except ValueError:
        raise TranslateError("百度接口返回非 JSON: %s"
                             % str(getattr(resp, "text", ""))[:120])
    if "error_code" in j:
        code = str(j.get("error_code"))
        msg = "百度翻译错误 %s: %s" % (code, j.get("error_msg"))
        if code in BAIDU_FATAL_CODES:
            raise FatalTranslateError(msg)
        raise TranslateError(msg)
    return "".join(t["dst"] for t in j.get("trans_result", []))


# 各目标语言的「纯净度」要求。模型偶尔会把某一行串成别的语言，
# 必须在提示词里点名禁止（只写「翻译成韩语」不足以拦住）。
#
# 韩语那条特别长是有原因的：韩语里汉字词极多（缓慢=완만、向上=상방），
# 模型会直接把汉字写出来，还顺手带上日文送假名 —— 实测首句被译成
# 「모프 패드 분리 버튼을 누르고缓かに上方向으로 들어 올려…」。
# 只说「不许出现汉字」没用，必须给出「错误写法/正确写法」这一对例子。
_LANG_GUARD = {
    "en": "只能使用英文字母、数字和常规标点；不要出现汉字、日文假名或韩文。",
    "ja": "只能使用日文（汉字 + 平假名 + 片假名）；不要出现韩文，也不要照抄中文原句。",
    "ko": "只能使用韩文字母（谚文）和必要的数字、英文缩写；"
          "绝对不要出现日文假名，也不要出现汉字。"
          "遇到汉字词请写韩文拼写，不要写出汉字本身"
          "（要写 천천히、위쪽、완만하게，不要写 缓慢、向上、缓かに）。",
}


def _terms_hint(lang_code: str) -> str:
    """把该语言的术语表拼成提示词里的一段。

    不给术语表时，模型不知道这是扫地机器人：韩语会把「拖布」译成
    레이스（lace，蕾丝）、把「刮条」译成 글라이더（glider，滑翔机）；
    英文同理译成 lace。给了目标语言的标准说法后术语就稳定了。
    注意术语必须写成「中文=目标语言」，写成中文解释反而会让模型
    更容易保留中文原词（实测「刮条」→「철거 도구」拆解工具）。
    """
    terms = langs.get(lang_code).get("terms") or {}
    if not terms:
        return ""
    pairs = "、".join("%s=%s" % (zh, tgt) for zh, tgt in terms.items())
    return ("这是扫地机器人拖布组件的拆装与清洁教程，请严格使用下列术语"
            "（原文里的「脱布」是语音识别错字，就是「拖布」）：%s。" % pairs)


def _build_prompt(texts, lang_code: str, single: bool = False) -> str:
    """拼提示词。single=True 为单句补救版（无编号、措辞更硬）。

    两版必须真的不同：整批提示词在 temperature=0 下是确定性的，
    同一句再问一遍只会原样返回，补救就没意义了。
    """
    lang = langs.get(lang_code)
    guard = _LANG_GUARD.get(lang_code, _LANG_GUARD["en"])
    terms = _terms_hint(lang_code)
    if single:
        return (
            "把下面这一句中文翻译成%(name)s。只输出译文本身，不要编号、不要解释。\n"
            "语言要求：%(guard)s\n"
            "%(terms)s\n"
            "中文原句：%(body)s\n%(name)s译文："
        ) % {"name": lang["name"], "guard": guard, "terms": terms,
             "body": texts[0]}
    body = "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(texts))
    return (
        "你是专业的中文→%(name)s翻译。请把下面的中文台词翻译成自然、口语化的"
        "%(name)s，语气像产品视频的官方旁白。\n"
        "语言要求：%(guard)s\n"
        "每一行都必须是纯%(name)s，任何一行混入其他语言文字都算错误。\n"
        "%(terms)s\n"
        "只返回「编号. 译文」，每行一条，保持编号格式，不要解释、不要空行。\n"
        "待翻译：\n%(body)s"
    ) % {"name": lang["name"], "guard": guard, "terms": terms, "body": body}


def _llm_chat(base_url: str, api_key: str, model: str, prompt: str,
              temperature: float = 0.0) -> str:
    import requests
    resp = requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + api_key},
        json={"model": model,
              "messages": [{"role": "user", "content": prompt}],
              "temperature": temperature},
        timeout=90)
    if resp.status_code != 200:
        raise TranslateError("接口返回 HTTP %s：%s"
                             % (resp.status_code,
                                (getattr(resp, "text", "") or "")[:200]))
    try:
        j = resp.json()
    except ValueError:
        raise TranslateError("接口返回非 JSON：%s"
                             % (getattr(resp, "text", "") or "")[:150])
    if j.get("error"):
        raise TranslateError("接口错误：%s" % j["error"])
    try:
        return j["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise TranslateError("接口返回格式异常：%s" % str(j)[:200])


def _llm_batch(texts, base_url: str, api_key: str, model: str,
               lang_code: str = "en"):
    """整批翻译。

    temperature 固定 0：实测 0.2 时 glm-4-flash 会随机把某一行整句译成
    日语（韩语批次的第一行变成「缓やかに上に引き上げて…取り外します」），
    降到 0 后同一输入多次调用结果完全一致，串语言不再出现。
    """
    content = _llm_chat(base_url, api_key, model,
                        _build_prompt(texts, lang_code), 0.0)
    out = {}
    for line in content.splitlines():
        m = re.match(r"\s*(\d+)\s*[.、:：]\s*(.+)", line)
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    results = [out.get(i + 1, "") for i in range(len(texts))]
    if not any(results):
        raise TranslateError("LLM 返回格式无法解析")
    return results


def _llm_one(text: str, base_url: str, api_key: str, model: str,
             lang_code: str = "en") -> str:
    """单句重译（补救用）。

    必须和整批提示词不同：批量提示词在 temperature=0 下是确定性的，
    同一句再问一遍只会原样返回，所以这里改成单句、无编号、更硬的措辞，
    并把温度抬到 0.3 换取不同的采样结果。
    """
    lang = langs.get(lang_code)
    prompt = (
        "把下面这一句中文翻译成%(name)s。只输出译文本身，不要编号、不要解释。\n"
        "语言要求：%(guard)s\n"
        "%(terms)s\n"
        "中文原句：%(text)s\n%(name)s译文："
    ) % {"name": lang["name"],
         "guard": _LANG_GUARD.get(lang_code, _LANG_GUARD["en"]),
         "terms": _terms_hint(lang_code), "text": text}
    content = _llm_chat(base_url, api_key, model, prompt, 0.3).strip()
    # 有些模型仍会自作主张加「1. 」前缀
    content = re.sub(r"^\s*\d+\s*[.、:：]\s*", "", content)
    return content.strip()


def _repair(s, lang_code: str, one_call, log=print) -> bool:
    """把一条不合格的译文重译到合格为止，返回是否成功"""
    for attempt in range(3):
        try:
            r = one_call(s.text_zh)
        except Exception as e:
            log("    重译失败: %s" % e)
            continue
        good, why = looks_translated(r, lang_code)
        if good:
            s.text_en = r.strip()
            return True
        log("    第 %d 次重译仍不合格（%s）" % (attempt + 1, why))
    return False



def _argos_setup(lang_code: str = "en", log=print):
    import argostranslate.package as pkg
    import argostranslate.translate as at
    target = langs.get(lang_code)["argos"]
    try:
        installed = at.get_installed_languages()
        if any(l.code == target for l in installed):
            return
    except Exception:
        pass
    log("更新离线翻译包索引（仅首次）…")
    pkg.update_package_index()
    for p in pkg.get_available_packages():
        if p.from_code == "zh" and p.to_code == target:
            log("下载并安装离线翻译包 %s（约 100MB，仅首次）…" % p.package_name)
            pkg.install_from_path(p.download())
            return
    raise TranslateError("未找到 zh→%s 离线翻译包" % target)


def _argos_one(text: str, lang_code: str = "en") -> str:
    import argostranslate.translate as at
    return at.translate(text, "zh", langs.get(lang_code)["argos"])


def test_backend(cfg: dict) -> str:
    """实测翻译后端是否真的能用，返回目标语言示例；不可用时抛异常。

    用于界面「检查环境」：提前发现密钥没填 / 网络不通 / 接口返回原文，
    而不是等用户跑完语音识别才失败。
    """
    backend = cfg.get("translate_backend", "baidu")
    lang_code = cfg.get("target_lang", "en")
    sample = "你好，这是一次翻译连通性测试。"
    if backend == "baidu":
        if not (cfg.get("baidu_appid", "").strip()
                and cfg.get("baidu_key", "").strip()):
            raise TranslateError("未填写 APP ID / 密钥")
        raw = _baidu(sample, cfg["baidu_appid"], cfg["baidu_key"], lang_code)
    elif backend == "mymemory":
        raw = _mymemory(sample, cfg.get("mymemory_email", ""), lang_code)
    elif backend == "argos":
        _argos_setup(lang_code, lambda m: None)
        raw = _argos_one(sample, lang_code)
    elif backend == "zhipu":
        if not cfg.get("zhipu_api_key", "").strip():
            raise TranslateError("未填写智谱 API Key（到 bigmodel.cn 免费注册）")
        raw = _llm_batch([sample], ZHIPU_BASE_URL,
                         cfg["zhipu_api_key"].strip(), ZHIPU_MODEL,
                         lang_code)[0]
    elif backend == "llm":
        if not cfg.get("llm_api_key", "").strip():
            raise TranslateError("未填写 API Key")
        raw = _llm_batch([sample], cfg.get("llm_base_url", ""),
                         cfg.get("llm_api_key", ""),
                         cfg.get("llm_model", "deepseek-chat"), lang_code)[0]
    else:
        raw = _google(sample, lang_code)
    ok, why = looks_translated(raw, lang_code)
    if not ok:
        raise TranslateError(why)
    return raw.strip()


def translate_segments(segments, cfg: dict, log=print) -> None:
    backend = cfg.get("translate_backend", "baidu")
    lang_code = cfg.get("target_lang", "en")
    lang = langs.get(lang_code)
    tname = lang["name"]
    total = len(segments)
    log("开始翻译（中文 → %s，后端: %s），共 %d 条字幕"
        % (tname, backend, total))

    if backend == "baidu":
        if not (cfg.get("baidu_appid", "").strip()
                and cfg.get("baidu_key", "").strip()):
            raise FatalTranslateError(
                "百度翻译需要 APP ID 和密钥：请在界面「翻译后端」下方填写，"
                "或到 fanyi-api.baidu.com 免费申请（标准版每月 5 万字符）；"
                "也可临时切换为 MyMemory / 智谱 GLM 后端")

    if backend in ("llm", "zhipu"):
        if backend == "zhipu":
            if not cfg.get("zhipu_api_key", "").strip():
                raise FatalTranslateError(
                    "智谱 GLM 需要 API Key：到 https://bigmodel.cn 免费注册，"
                    "在「API Keys」新建一个复制过来即可（glm-4-flash 完全免费）")

            def _call(texts):
                return _llm_batch(texts, ZHIPU_BASE_URL,
                                  cfg["zhipu_api_key"].strip(), ZHIPU_MODEL,
                                  lang_code)

            def _call_one(text):
                return _llm_one(text, ZHIPU_BASE_URL,
                                cfg["zhipu_api_key"].strip(), ZHIPU_MODEL,
                                lang_code)
        else:
            if not cfg.get("llm_api_key", "").strip():
                raise FatalTranslateError(
                    "LLM 翻译需要 API Key：请填写 Base URL / API Key / 模型名，"
                    "或改用其他翻译后端")

            def _call(texts):
                return _llm_batch(texts, cfg.get("llm_base_url", ""),
                                  cfg.get("llm_api_key", "").strip(),
                                  cfg.get("llm_model", "deepseek-chat"),
                                  lang_code)

            def _call_one(text):
                return _llm_one(text, cfg.get("llm_base_url", ""),
                                cfg.get("llm_api_key", "").strip(),
                                cfg.get("llm_model", "deepseek-chat"),
                                lang_code)

        batch = 25
        last_err = ""
        for i in range(0, total, batch):
            chunk = segments[i:i + batch]
            try:
                results = _call([s.text_zh for s in chunk])
            except Exception as e:
                last_err = e
                log("  批次翻译失败: %s" % e)
                results = [""] * len(chunk)
            bad = []
            for s, r in zip(chunk, results):
                good, why = looks_translated(r, lang_code)
                s.text_en = r.strip() if good else ""
                if not good:
                    bad.append((s, why))
            # 整批里个别行会「串语言」（实测韩语批次的第一行被整句译成日语），
            # 或残留中文（「缓慢하게」）。单独重译这几行，比丢掉重跑整批便宜。
            for s, why in bad:
                log("  第 %.1fs 的译文不合格（%s），单条重译…" % (s.start, why))
                if not _repair(s, lang_code, _call_one, log):
                    log("    重译 3 次仍不合格，这一条只显示中文字幕")
            good_n = sum(1 for s in chunk if s.text_en)
            if i == 0 and good_n == 0:
                raise FatalTranslateError(
                    "「%s」第一批就全部失败，已中止。\n最后一次错误：%s\n"
                    "请检查 API Key 是否正确、账户是否已开通。"
                    % ("智谱 GLM" if backend == "zhipu" else "LLM", last_err))
            log("  翻译进度 %d/%d" % (min(i + batch, total), total))
        failed = sum(1 for s in segments if not s.text_en)
        if failed:
            log("[警告] %d/%d 条字幕没译出%s" % (failed, total, tname))
        else:
            log("翻译完成：%d 条全部译成%s" % (total, tname))
        return

    if backend == "argos":
        try:
            _argos_setup(lang_code, log)
        except Exception as e:
            log("离线翻译包准备失败: %s" % e)
            log("  原因通常是访问不到 GitHub（argos 的模型索引和安装包都在 GitHub 上），")
            log("  国内网络基本都会失败。建议直接改用 MyMemory（免密钥）或百度翻译。")

    consec_fail = 0
    for i, s in enumerate(segments):
        got = ""
        last_err = ""
        for attempt in range(4):
            try:
                if backend == "baidu":
                    raw = _baidu(s.text_zh, cfg.get("baidu_appid", ""),
                                 cfg.get("baidu_key", ""), lang_code)
                elif backend == "mymemory":
                    raw = _mymemory(s.text_zh, cfg.get("mymemory_email", ""),
                                    lang_code)
                elif backend == "argos":
                    raw = _argos_one(s.text_zh, lang_code)
                else:
                    raw = _google(s.text_zh, lang_code)
                ok, why = looks_translated(raw, lang_code)
                if not ok:
                    raise TranslateError(why)
                got = raw.strip()
                break
            except FatalTranslateError as e:
                raise FatalTranslateError(
                    "%s\n请检查 APP ID / 密钥是否正确、服务是否已开通。" % e)
            except Exception as e:
                last_err = e
                if attempt < 3:
                    # 指数退避，规避限流（Google 免费接口约 5 次/秒）
                    time.sleep([1.5, 4.0, 10.0][attempt])
        s.text_en = got

        if got:
            consec_fail = 0
        else:
            consec_fail += 1
            log("  第 %d 条没译出%s: %s… (%s)"
                % (i + 1, tname, s.text_zh[:20], last_err))
            if consec_fail >= 3:
                raise FatalTranslateError(
                    "翻译后端「%s」连续 %d 条失败，已中止（避免继续空跑）。\n"
                    "最后一次错误：%s\n"
                    "请确认网络能访问该翻译服务，或在界面把「翻译后端」换成"
                    "MyMemory / 智谱 GLM / 百度后重试。" % (backend,
                                                            consec_fail,
                                                            last_err))

        # 百度标准版 QPS=1，逐条之间稍作间隔，避免 54003 频率限制
        if backend == "baidu":
            time.sleep(0.4)
        elif backend == "mymemory":
            time.sleep(0.3)
        if (i + 1) % 10 == 0 or i + 1 == total:
            log("  翻译进度 %d/%d" % (i + 1, total))

    failed = sum(1 for s in segments if not s.text_en)
    if failed:
        log("[警告] %d/%d 条字幕没译出%s，这些位置只显示中文字幕"
            % (failed, total, tname))
    else:
        log("翻译完成：%d 条全部译成%s" % (total, tname))

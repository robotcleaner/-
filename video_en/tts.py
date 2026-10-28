# -*- coding: utf-8 -*-
"""目标语言 TTS 合成（edge-tts 在线 / pyttsx3 离线）"""
from __future__ import annotations
import os
import time

import langs

# 各语言可用嗓音（界面下拉框用）
EDGE_VOICES_BY_LANG = {code: dict(cfg["voices"])
                       for code, cfg in langs.LANGS.items()}

# 向后兼容：老代码 from tts import EDGE_VOICES
EDGE_VOICES = EDGE_VOICES_BY_LANG["en"]


def voices_for(lang_code: str = "en") -> dict:
    return EDGE_VOICES_BY_LANG.get(lang_code) or EDGE_VOICES_BY_LANG["en"]


def estimate_rate_pct(text: str, target_dur: float,
                      lang_code: str = "en") -> int:
    """根据目标时长估算 TTS 语速百分比（单段兜底用，正常走全局语速）"""
    cps = langs.get(lang_code)["cps"]
    est = max(len(text) / cps, 0.4)
    pct = int((est / max(target_dur, 0.3) - 1) * 100)
    return max(-15, min(25, pct))


# 全局语速允许范围（百分比）
# 下限允许略微放慢（译文比中文短时别硬拖），上限压住"像快进"的速度。
# 中日韩→英/日/韩 普遍会变长（实测 1.1~1.6 倍），所以日韩的上限放宽一些，
# 但整片只用同一个值，绝不逐段各调各的。
PACE_LIMITS = {
    "en": (-6, 18),
    "ja": (-6, 28),
    "ko": (-6, 28),
}


def plan_global_rate(segments, lang_code: str = "en",
                     bias: int = 0) -> int:
    """给整条视频算一个**统一**的语速，避免有的段飞快、有的段正常。

    做法：先按每段的「译文长度 / 该段时长」估算它想用多快的语速，
    取中位数作为全片语速，再夹到该语言的合理区间里。
    中位数不会被个别特别赶的句子带偏，整体听感最接近真人旁白。
    """
    ratios = []
    cps = langs.get(lang_code)["cps"]
    for seg in segments:
        text = getattr(seg, "text_en", "") or ""
        if not text.strip():
            continue
        target = max(seg.end - seg.start, 0.3)
        est = max(len(text) / cps, 0.4)
        ratios.append(est / target)
    if not ratios:
        return 0
    ratios.sort()
    mid_i = len(ratios) // 2
    if len(ratios) % 2:
        mid = ratios[mid_i]
    else:
        mid = (ratios[mid_i - 1] + ratios[mid_i]) / 2.0
    pct = int(round((mid - 1) * 100)) + int(bias or 0)
    lo, hi = PACE_LIMITS.get(lang_code, (-6, 12))
    return max(lo, min(hi, pct))


def _edge_synth(text: str, out: str, voice: str, rate: str = None) -> None:
    import asyncio
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate)
    asyncio.run(comm.save(out))


def _offline_synth(text: str, out: str, rate: str = None,
                   lang_code: str = "en") -> None:
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 165)
    keys = langs.get(lang_code)["pyttsx3"]
    try:
        for v in engine.getProperty("voices"):
            name = (v.name or "").lower()
            vid = (getattr(v, "id", "") or "").lower()
            if any(k in name or k in vid for k in keys):
                engine.setProperty("voice", v.id)
                break
    except Exception:
        pass
    engine.save_to_file(text, out)
    engine.runAndWait()
    try:
        engine.stop()
    except Exception:
        pass
    # 系统没装该语言的语音包时，SAPI 不会报错，只会写一个几十字节的空壳文件，
    # 后面 ffprobe 解析就会炸。这里先兜住，给一句能看懂的话。
    if not os.path.isfile(out) or os.path.getsize(out) < 2048:
        raise RuntimeError("系统没有%s离线语音包，无法用离线语音朗读"
                           % langs.get(lang_code)["name"])


def offline_voice_available(lang_code: str = "en") -> bool:
    """系统里有没有该语言的 pyttsx3 语音（Windows 上就是 SAPI 语音包）"""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        keys = langs.get(lang_code)["pyttsx3"]
        found = False
        for v in engine.getProperty("voices"):
            name = (v.name or "").lower()
            vid = (getattr(v, "id", "") or "").lower()
            if any(k in name or k in vid for k in keys):
                found = True
                break
        try:
            engine.stop()
        except Exception:
            pass
        return found
    except Exception:
        return False


# 低于这个版本的 edge-tts 会被微软拒绝（403），实测 7.2.8 必失败、7.3.1 正常
MIN_EDGE_VERSION = (7, 3, 0)


def edge_version() -> str:
    try:
        import edge_tts
        return str(getattr(edge_tts, "__version__", "0"))
    except Exception:
        return "0"


def _ver_tuple(s: str):
    out = []
    for part in str(s).split(".")[:3]:
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def edge_outdated_hint() -> str:
    """在线语音组件版本过旧时返回一句提示，否则返回空串"""
    v = edge_version()
    if _ver_tuple(v) < MIN_EDGE_VERSION:
        return ("在线语音组件 edge-tts 版本过旧（%s），微软会拒绝它的请求（403）。"
                "请在本程序目录运行：pip install -U edge-tts" % v)
    return ""


def synth_segment(text: str, out: str, voice: str, backend: str,
                  target_dur: float = None, lang_code: str = "en",
                  rate_pct: int = None) -> None:
    """rate_pct：全片统一语速；不传则按该段时长单独估算（老行为，仅兜底）"""
    if backend == "offline":
        _offline_synth(text, out, lang_code=lang_code)
        return
    if rate_pct is None:
        rate_pct = (estimate_rate_pct(text, target_dur, lang_code)
                    if target_dur else 0)
    rate = "%+d%%" % rate_pct
    last = None
    for attempt in range(3):
        try:
            _edge_synth(text, out, voice, rate)
            return
        except Exception as e:
            last = e
            if attempt < 2:
                # 403 基本是微软对短时间大量请求的限流，退避久一点再试
                if "403" in str(e):
                    time.sleep([2.0, 6.0][attempt])
                else:
                    time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("edge-tts 合成失败: %s" % last)


def _short_err(e) -> str:
    """把长异常压成一句人话，日志里好看"""
    s = str(e).replace("\n", " ")
    if "403" in s:
        return "微软在线语音限流 403"
    return s[:80]


def synthesize_all(segments, tmp_dir: str, cfg: dict, log=print,
                   progress=None):
    """为每个片段合成目标语言语音并对齐字幕时间轴。

    三轮策略：
      1) 在线（edge-tts）逐段合成；
      2) 失败的段冷却 8 秒后统一重试一次（403 多是短时限流，等一下就好）；
      3) 仍失败的，用系统离线语音兜底；系统没装该语言语音包就明确提示，不留坏文件。

    progress(frac, msg)：frac 为 0~1 的进度比例。
    返回 [(wav_path, start_sec)]"""
    import ffmpeg_utils as fx
    backend = cfg.get("tts_backend", "edge")
    lang_code = cfg.get("target_lang", "en")
    lang = langs.get(lang_code)
    tname = lang["short"]
    voice = langs.voice_of(cfg)
    n = len(segments)
    need = sum(1 for s in segments if s.text_en)
    items = []
    pending = []          # 在线合成失败的段：[(i, seg)]
    # 全片统一语速：不让每段各说各的速度（忽快忽慢最别扭）
    pace = plan_global_rate(segments, lang_code,
                            bias=cfg.get("tts_pace_bias", 0))
    if need:
        log("配音语速：全程统一 %+d%%（产品旁白的正常节奏）" % pace)

    if backend != "offline":
        hint = edge_outdated_hint()
        if hint:
            log("[警告] " + hint)

    def report(i, extra=""):
        if progress:
            progress((i + 1) / n, "合成%s配音 %d/%d%s"
                     % (tname, i + 1, n, extra))

    def slack_of(i, seg):
        """这一段能用多久：本段时长 + 下一段开始前的一点空档。

        中文一句话翻成外语往往更长，硬压进原时长就得狂加速；
        字幕之间通常有空隙，借用一部分，语速就不用飙起来。
        """
        dur = max(seg.end - seg.start, 0.3)
        gap = 0.0
        if i + 1 < len(segments):
            gap = max(0.0, segments[i + 1].start - seg.end)
        return dur + min(0.6, gap * 0.75)

    def fit(i, seg, raw):
        """把一段音频压到允许时长内；失败只影响这一段，不能拖垮整个任务"""
        fitted = os.path.join(tmp_dir, "fit_%04d.wav" % i)
        allow = max(slack_of(i, seg) - 0.05, 0.3)
        try:
            try:
                raw_dur = fx.probe_duration(raw)
            except Exception:
                raw_dur = 0
            fx.fit_audio(raw, fitted, allow)
            if raw_dur and raw_dur > allow * 1.25:
                log("  片段 %d 译文偏长（%.1fs / 可用 %.1fs），已按统一语速朗读，"
                    "结尾略作精简" % (i + 1, raw_dur, allow))
        except Exception as e:
            log("  片段 %d 音频处理失败，该段留空: %s" % (i + 1, _short_err(e)))
            return False
        items.append((fitted, seg.start))
        return True

    # ---------- 第一轮：在线合成 ----------
    for i, seg in enumerate(segments):
        if not seg.text_en:
            # 没有译文时不要用目标语言嗓音去念中文（会变成乱码/怪音），该段留空
            report(i, "（该段无译文，留空）")
            continue
        if backend == "offline":
            raw = os.path.join(tmp_dir, "raw_%04d.wav" % i)
            try:
                _offline_synth(seg.text_en, raw, lang_code=lang_code)
                fit(i, seg, raw)
            except Exception as e:
                log("  片段 %d 离线语音失败，该段留空: %s"
                    % (i + 1, _short_err(e)))
            report(i)
            continue
        raw = os.path.join(tmp_dir, "raw_%04d.mp3" % i)
        try:
            synth_segment(seg.text_en, raw, voice, backend,
                          seg.end - seg.start, lang_code, rate_pct=pace)
            fit(i, seg, raw)
        except Exception as e:
            pending.append((i, seg))
            log("  片段 %d 在线语音失败（%s），稍后统一重试"
                % (i + 1, _short_err(e)))
        report(i)
        time.sleep(0.6)      # 段间停顿，降低触发微软限流的概率

    # ---------- 第二轮：冷却后重试 ----------
    if pending:
        log("[提示] %d 段在线语音失败，等 8 秒后重试…" % len(pending))
        time.sleep(8)
        still = []
        for i, seg in pending:
            raw = os.path.join(tmp_dir, "raw_%04d.mp3" % i)
            try:
                synth_segment(seg.text_en, raw, voice, backend,
                              seg.end - seg.start, lang_code, rate_pct=pace)
                if fit(i, seg, raw):
                    log("  片段 %d 重试成功" % (i + 1))
            except Exception as e:
                still.append((i, seg))
                log("  片段 %d 重试仍失败（%s）" % (i + 1, _short_err(e)))
            time.sleep(1.2)
        pending = still

    # ---------- 第三轮：离线兜底 ----------
    if pending:
        if offline_voice_available(lang_code):
            log("[提示] %d 段仍失败，改用系统离线语音补上（音色会略有差异）"
                % len(pending))
            done = []
            for i, seg in pending:
                raw = os.path.join(tmp_dir, "raw_%04d.wav" % i)
                try:
                    _offline_synth(seg.text_en, raw, lang_code=lang_code)
                    if fit(i, seg, raw):
                        done.append(i + 1)
                except Exception as e:
                    log("  片段 %d 离线补音失败: %s" % (i + 1, _short_err(e)))
            if done:
                log("[提示] 第 %s 段用了离线语音，音色与其余段不同；"
                    "想要统一音色可隔几分钟重跑一次。"
                    % "、".join(str(x) for x in done))
            pending = [(i, s) for i, s in pending if i + 1 not in done]
        else:
            log("[警告] 系统没有装%s离线语音包，这几段无法用离线语音补，"
                "只能只有字幕没有人声。" % lang["name"])
            log("        解决办法：①等几分钟重跑（在线限流会恢复）；"
                "②Windows 设置→时间和语言→语言→添加%s语音包；"
                "③把 TTS 后端改成离线语音前先装语音包。" % lang["name"])

    if need and not items:
        extra = edge_outdated_hint()
        raise RuntimeError(
            "全部 %d 段配音都失败了。\n%s\n建议：1) 在本程序目录运行 "
            "pip install -U edge-tts 再试；2) 或把「TTS 后端」换成"
            "「系统离线语音」（需系统装有%s语音包）。"
            % (need, extra or "（在线语音请求被拒绝）", lang["name"]))
    if need and len(items) < need:
        log("[警告] %d/%d 段配音未成功，这些位置只有字幕没有人声"
            % (need - len(items), need))
    return items

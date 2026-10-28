# -*- coding: utf-8 -*-
"""单视频本地化流水线：ASR → 翻译 → TTS → 字幕 → 720P 烧录（目标语言可配置）"""
from __future__ import annotations
import os
import re
import shutil
import tempfile

import ffmpeg_utils as fx
import asr
import langs
import translate
import tts
import subtitles
import subdetect
from ven_config import APP_DIR


class PipelineError(RuntimeError):
    pass


RESOLUTIONS = {
    "1280x720": "720P 横屏 (1280×720)",
    "720x1280": "720P 竖屏 (720×1280)",
    "long720": "长边 720（保持比例）",
}

# 本程序输出的文件名后缀：xxx_en.mp4 / xxx_ja.mp4 / xxx_ko.mp4
_OUTPUT_SUFFIX = re.compile(r"_(en|ja|ko)$", re.IGNORECASE)


def looks_like_output(path: str) -> bool:
    """输入是不是本程序之前生成的成品（避免拿成品再加工，字幕越叠越多）"""
    stem = os.path.splitext(os.path.basename(path or ""))[0]
    return bool(_OUTPUT_SUFFIX.search(stem))


def reprocess_hint(path: str) -> str:
    return (
        "输入视频「%s」看起来已经是本程序生成的成品（文件名以 _en / _ja / _ko 结尾）。\n\n"
        "这个成品里已经烧录了一层字幕（原片中文 + 上次生成的外语），"
        "再处理一次会出现「中文 + 外语 + 新外语」三行字幕叠在一起。\n\n"
        "建议改用「原始中文视频」重新生成。\n"
        "如果确实要在这个成品上继续处理，请确认后再继续。"
        % os.path.basename(path)
    )


def resolve_output_size(input_path: str, res_key: str):
    """根据配置与源视频计算输出宽高（偶数）"""
    if res_key == "long720":
        w, h = fx.probe_resolution(input_path)
        if w <= 0 or h <= 0:
            return 1280, 720
        if w >= h:
            H = 720
            W = int(round(w * 720 / h / 2.0)) * 2
        else:
            W = 720
            H = int(round(h * 720 / w / 2.0)) * 2
        return W, H
    W, H = map(int, res_key.split("x"))
    return W, H


def process_single_video(input_path: str, output_path: str, cfg: dict,
                         log=print, progress=None):
    def P(pct, msg):
        if progress:
            progress(pct, msg)
        log("[%3d%%] %s" % (pct, msg))

    if not os.path.isfile(input_path):
        raise PipelineError("找不到输入文件: " + input_path)
    # 拿上一次的成品当输入，会在原有字幕上再叠一层，变成三四种语言
    if looks_like_output(input_path) and not cfg.get("allow_reprocessed"):
        raise PipelineError(reprocess_hint(input_path))
    # 统一转绝对路径：后面 ffmpeg 会在临时目录下执行，相对路径会解析错
    input_path = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)
    fx.find_ffmpeg(cfg.get("ffmpeg_path", ""))

    if not fx.has_audio(input_path):
        raise PipelineError("该视频没有音频轨，无法进行语音识别")

    dur = fx.probe_duration(input_path)
    log("输入: %s  时长 %.1fs" % (input_path, dur))

    W, H = resolve_output_size(input_path, cfg.get("resolution", "1280x720"))

    lang_code = cfg.get("target_lang", langs.DEFAULT_LANG)
    tshort = langs.get(lang_code)["short"]

    # 先看原视频有没有自带（烧录）中文字幕：有的话就只叠加目标语言，避免中文字幕重复
    mode = cfg.get("subtitle_mode", "bilingual")
    band = None
    if cfg.get("auto_avoid_source_subs", True) and mode in ("bilingual", "en"):
        P(4, "检查原视频是否自带中文字幕")
        try:
            band = subdetect.detect_subtitle_band(input_path, W, H, log=log)
        except Exception as e:
            log("  [原字幕检测] 跳过（%s）" % e)
            band = None
        if band:
            band_h = band[1] - band[0]
            if band_h > H * 0.085:
                # 单行字幕在 720P 下约 30px；超过 60px 基本是两行叠在一起了
                log("[提示] 画面底部字幕区域偏高（%dpx，约 %.1f 行），"
                    "原片可能已经叠了两行字幕（比如拿成品又处理了一次）；"
                    "如果不需要，请改用原始视频。" % (band_h, band_h / max(H * 0.042, 1)))
            log("[提示] 原视频自带中文字幕（画面 y=%d~%d），已自动改为只叠加%s字幕，"
                "位置放在原字幕下方。如需强制双语，请在界面把"
                "「自动避让原字幕」取消勾选。" % (band[0], band[1], tshort))
            mode = "en_below"
    elif mode == "en_below":
        try:
            band = subdetect.detect_subtitle_band(input_path, W, H, log=log)
        except Exception:
            band = None
        if not band:
            log("[提示] 未检测到原视频自带字幕，「仅%s·原字幕下方」"
                "将退化为普通「仅%s」。" % (tshort, tshort))

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="ven_tmp_", dir=out_dir)
    try:
        P(3, "提取音频")
        wav16 = os.path.join(tmp, "audio_16k.wav")
        fx.extract_audio(input_path, wav16, 16000, 1)

        P(10, "中文语音识别（Whisper）")

        def _dl(done, total):
            # 只对 model.bin 这类大文件报进度，小文件一闪而过不必刷新
            if total and total > 10 * 1048576:
                frac = min(1.0, done / float(total))
                P(10 + int(frac * 8),
                  "下载语音模型 %.0f%%  (%.0f / %.0f MB)"
                  % (frac * 100, done / 1048576.0, total / 1048576.0))

        segments = asr.transcribe(
            wav16, cfg.get("whisper_model", "small"), log,
            hf_endpoint=cfg.get("hf_endpoint", ""),
            models_dir=os.path.join(APP_DIR, "models"),
            progress=_dl)
        if not segments:
            raise PipelineError("未识别到中文语音，请确认视频中有中文讲话内容")
        log("共 %d 条字幕，首条示例: %s" % (len(segments), segments[0].text_zh[:40]))

        P(45, "翻译为中文 → %s" % tshort)
        translate.translate_segments(segments, cfg, log)

        P(58, "合成%s配音并对齐时间轴" % tshort)
        items = tts.synthesize_all(
            segments, tmp, cfg, log,
            progress=lambda frac, msg: P(58 + int(frac * 22), msg))

        P(82, "生成%s字幕"
           % {"bilingual": "双语", "en": tshort,
              "en_below": "%s（原字幕下方）" % tshort}.get(mode, tshort))
        ass_path = os.path.join(tmp, "subs.ass")
        subtitles.write_ass(segments, ass_path, W, H, mode,
                            source_band=band, lang=lang_code)

        P(86, "混音")
        mixed = os.path.join(tmp, "dub_track.wav")
        orig = None
        if cfg.get("keep_original_audio"):
            orig = os.path.join(tmp, "orig.wav")
            fx.extract_audio(input_path, orig, 48000, 2)
        fx.mix_track(items, dur, mixed, original_audio=orig,
                     original_volume=cfg.get("original_audio_volume", 0.12))

        P(92, "编码输出（%dx%d，烧录字幕）" % (W, H))
        fx.burn_subtitles(input_path, mixed, ass_path, output_path,
                          W, H, dur, crf=int(cfg.get("crf", 20)),
                          preset=cfg.get("preset", "medium"), log=log)
        P(100, "完成: " + output_path)
        return output_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

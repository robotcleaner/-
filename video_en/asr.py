# -*- coding: utf-8 -*-
"""中文语音识别（faster-whisper，带时间轴）"""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass
class Segment:
    start: float
    end: float
    text_zh: str = ""
    # 目标语言译文。字段名沿用历史的 text_en（兼容旧代码/测试），
    # 实际语言由 config 的 target_lang 决定（英/日/韩…）
    text_en: str = ""

    @property
    def text_target(self) -> str:
        return self.text_en

    @text_target.setter
    def text_target(self, value: str) -> None:
        self.text_en = value


def merge_segments(segs, max_chars: int = 42, max_gap: float = 0.4,
                   max_dur: float = 9.0):
    """合并过短的识别片段，让字幕/配音更自然"""
    merged = []
    for s in segs:
        if merged:
            last = merged[-1]
            gap = s.start - last.end
            if (gap <= max_gap
                    and len(last.text_zh) + len(s.text_zh) <= max_chars
                    and (s.end - last.start) <= max_dur):
                last.end = s.end
                last.text_zh = (last.text_zh + " " + s.text_zh).strip()
                continue
        merged.append(Segment(s.start, s.end, s.text_zh))
    return merged


def resolve_model_path(model_size: str, models_dir: str) -> str:
    """优先使用本地手动放置的模型目录 models/<型号>-local/（含 model.bin），
    否则返回型号名，由 faster-whisper 走 HuggingFace 缓存下载。"""
    local = os.path.join(models_dir, model_size + "-local")
    if os.path.isfile(os.path.join(local, "model.bin")):
        return local
    return model_size


# faster-whisper 加载本地目录所需的最小文件集
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
# 模型源，按速度排序：ModelScope（国内约 7MB/s）> hf-mirror > huggingface
MODEL_SOURCES = (
    "https://modelscope.cn/models/pengzhendong/faster-whisper-{size}"
    "/resolve/master",
    "https://hf-mirror.com/Systran/faster-whisper-{size}/resolve/main",
    "https://huggingface.co/Systran/faster-whisper-{size}/resolve/main",
)


def _download_file(url: str, dest: str, progress=None, timeout: int = 30,
                   retries: int = 10):
    """单文件下载：断点续传 + 多次自动重连。

    HF 的 CDN 在长连接上经常中途掐断（IncompleteRead），一次下载很难跑完，
    所以这里失败就带着已下载的字节数重连，最多 retries 轮。
    """
    import time
    import requests
    tmp = dest + ".part"
    last_err = None
    for attempt in range(retries):
        pos = os.path.getsize(tmp) if os.path.isfile(tmp) else 0
        headers = {"Range": "bytes=%d-" % pos} if pos > 0 else {}
        try:
            with requests.get(url, headers=headers, stream=True,
                              timeout=(15, timeout),
                              allow_redirects=True) as r:
                if r.status_code == 416:        # 临时文件已是完整内容
                    os.replace(tmp, dest)
                    return
                if r.status_code not in (200, 206):
                    raise RuntimeError("HTTP %s" % r.status_code)
                total = int(r.headers.get("Content-Length") or 0)
                if r.status_code == 206 and pos:
                    total += pos
                else:
                    pos = 0
                done = pos
                with open(tmp, "ab" if pos else "wb") as f:
                    for chunk in r.iter_content(256 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            os.replace(tmp, dest)
            return
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(min(2 + attempt, 8))
    raise RuntimeError("重试 %d 次仍失败：%s" % (retries, last_err))


def download_model(model_size: str, models_dir: str, endpoint: str = "",
                   log=print, progress=None) -> str:
    """把 faster-whisper 模型文件直接下到 models/<size>-local/。

    不走 huggingface_hub：新版 hub 会校验响应头里的 repo-commit / etag，
    镜像站（hf-mirror）缺这些 header 时会抛
    `FileMetadataError: Distant resource does not seem to be on huggingface.co`，
    在界面上表现为「找不到文件、检查网络」，但网络其实是通的。
    这里自己走 HTTP，顺带支持多源回退与断点续传。
    """
    repo = "Systran/faster-whisper-%s" % model_size
    # ModelScope 优先（国内快），其次用户自填镜像，最后官方
    sources = [tpl.format(size=model_size) for tpl in MODEL_SOURCES]
    if endpoint:
        u = (endpoint.rstrip("/")
             + "/Systran/faster-whisper-%s/resolve/main" % model_size)
        if u not in sources:
            sources.insert(1, u)

    target = os.path.join(models_dir, model_size + "-local")
    os.makedirs(target, exist_ok=True)
    log("准备语音识别模型 %s（首次约 460MB，之后离线复用）" % model_size)

    from urllib.parse import urlparse
    for fname in MODEL_FILES:
        dest = os.path.join(target, fname)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            continue
        last_err = None
        for base in sources:
            url = "%s/%s" % (base, fname)
            try:
                log("  下载 %s ← %s" % (fname, urlparse(base).netloc))
                _download_file(url, dest, progress)
                last_err = None
                break
            except Exception as e:
                last_err = e
                log("    %s 失败: %s" % (urlparse(base).netloc, e))
        if last_err is not None:
            raise RuntimeError(
                "模型文件 %s 下载失败（%s）。\n"
                "可尝试：① 检查网络后重试（已下载部分会续传）；"
                "② 先用 tiny / base 模型跑通；"
                "③ 手动下载 %s 里的 %s，放到 %s"
                % (fname, last_err, repo, ", ".join(MODEL_FILES), target))
    log("模型已就绪: %s" % target)
    return target


def _decode_wav(wav_path: str, log=print):
    """用标准库 wave 把 16k wav 解码成 numpy float32 数组。

    绕开 faster-whisper 内置的 decode_audio()：该函数调用
    av.open(..., metadata_errors="ignore")，与部分 PyAV 版本
    （如 19.x）不兼容会抛 TypeError。直接把 ndarray 传给
    model.transcribe() 即可跳过内部解码，且 VAD 过滤仍可用。
    """
    import wave
    import numpy as np
    with wave.open(wav_path, "rb") as w:
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)
    if sampwidth == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        data /= 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32)
        data /= 2147483648.0
    elif sampwidth == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError("不支持的 wav 采样位宽: %d 字节" % sampwidth)
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    if framerate != 16000:
        log("警告: 音频采样率 %d Hz 非 16k，做线性重采样" % framerate)
        n_old = data.shape[0]
        n_new = int(round(n_old * 16000.0 / framerate))
        if n_new > 0 and n_old > 1:
            x_old = np.linspace(0.0, 1.0, n_old)
            x_new = np.linspace(0.0, 1.0, n_new)
            data = np.interp(x_new, x_old, data).astype(np.float32)
    return np.ascontiguousarray(data, dtype=np.float32)


def transcribe(audio_wav: str, model_size: str = "small", log=print,
               hf_endpoint: str = "", models_dir: str = None,
               progress=None):
    """对 16k 单声道 wav 做中文识别，返回带时间轴的 Segment 列表"""
    from faster_whisper import WhisperModel
    if not models_dir:
        models_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "models")
    os.makedirs(models_dir, exist_ok=True)

    model_path = resolve_model_path(model_size, models_dir)
    if model_path == model_size:
        # 本地没有该模型：自己下载，绕开 huggingface_hub 的镜像兼容问题
        try:
            model_path = download_model(model_size, models_dir, hf_endpoint,
                                        log, progress)
        except Exception as e:
            avail = sorted(d[:-6] for d in os.listdir(models_dir)
                           if d.endswith("-local")
                           and os.path.isfile(os.path.join(
                               models_dir, d, "model.bin")))
            hint = ("\n\n已下载好的模型：%s —— 可在界面「语音识别模型」里改选它们"
                    % "、".join(avail)) if avail else ""
            raise RuntimeError("%s%s" % (e, hint))

    log("加载 Whisper 模型: %s" % model_path)
    model = WhisperModel(model_path, device="cpu", compute_type="int8",
                         download_root=models_dir)
    audio_arr = _decode_wav(audio_wav, log)
    log("音频已解码: %.1fs" % (audio_arr.shape[0] / 16000.0))
    try:
        seg_iter, _info = model.transcribe(
            audio_arr, language="zh", beam_size=5, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300))
        segs = [Segment(s.start, s.end, s.text.strip())
                for s in seg_iter if s.text.strip()]
    except Exception as e:
        log("VAD 模式失败(%s)，改用普通模式重试" % e)
        seg_iter, _info = model.transcribe(audio_arr, language="zh", beam_size=5)
        segs = [Segment(s.start, s.end, s.text.strip())
                for s in seg_iter if s.text.strip()]
    log("识别到 %d 个语音片段，正在合并短句…" % len(segs))
    return merge_segments(segs)

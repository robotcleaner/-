# -*- coding: utf-8 -*-
"""ffmpeg / ffprobe 工具封装"""
from __future__ import annotations
import json
import os
import shutil
import subprocess


class FFmpegError(RuntimeError):
    pass


_ffmpeg = None
_ffprobe = None


def find_ffmpeg(ffmpeg_path: str = "") -> str:
    """按优先级查找 ffmpeg：配置路径 > 环境变量 > 程序 bin 目录 > PATH"""
    global _ffmpeg, _ffprobe
    if _ffmpeg and os.path.isfile(_ffmpeg):
        return _ffmpeg
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if ffmpeg_path:
        candidates.append(ffmpeg_path)
    env = os.environ.get("FFMPEG_BIN", "")
    if env:
        candidates.append(env)
    candidates += [
        os.path.join(here, "bin", "ffmpeg.exe"),
        os.path.join(here, "bin", "ffmpeg"),
    ]
    found = next((c for c in candidates if c and os.path.isfile(c)), None)
    if not found:
        found = shutil.which("ffmpeg")
    if not found:
        raise FFmpegError(
            "未找到 ffmpeg。\n"
            "请安装 ffmpeg 并加入系统 PATH（Windows: winget install Gyan.FFmpeg），\n"
            "或将 ffmpeg.exe / ffprobe.exe 放入程序 bin 目录。")
    _ffmpeg = found
    d = os.path.dirname(found)
    for name in ("ffprobe.exe", "ffprobe"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            _ffprobe = p
            break
    if not _ffprobe:
        _ffprobe = shutil.which("ffprobe") or found
    return _ffmpeg


def run(cmd: list, log=None, cwd: str = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise FFmpegError("ffmpeg 执行失败:\n" + tail)
    if log and proc.stderr:
        for line in proc.stderr.strip().splitlines()[-3:]:
            log("  [ffmpeg] " + line)
    return proc


def _probe(args: list, path: str) -> str:
    find_ffmpeg()
    cmd = [_ffprobe, "-v", "error"] + args + [path]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise FFmpegError("无法读取文件信息: %s\n%s" % (path, proc.stderr[-500:]))
    return proc.stdout


def probe_duration(path: str) -> float:
    out = _probe(["-show_entries", "format=duration", "-of", "json"], path)
    try:
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        raise FFmpegError("无法解析视频时长: " + path)


def probe_resolution(path: str):
    """返回 (宽, 高)，失败返回 (0, 0)"""
    out = _probe(["-select_streams", "v:0", "-show_entries",
                  "stream=width,height", "-of", "csv=p=0"], path)
    try:
        w, h = out.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:
        return 0, 0


def has_audio(path: str) -> bool:
    out = _probe(["-select_streams", "a", "-show_entries",
                  "stream=index", "-of", "csv=p=0"], path)
    return bool(out.strip())


def extract_audio(video: str, out_wav: str, sr: int = 16000,
                  channels: int = 1) -> str:
    find_ffmpeg()
    cmd = [_ffmpeg, "-y", "-i", video, "-vn", "-ac", str(channels),
           "-ar", str(sr), "-f", "wav", out_wav]
    run(cmd)
    return out_wav


def _atempo_chain(speed: float) -> str:
    factors = []
    s = max(speed, 1e-6)
    while s > 2.0:
        factors.append(2.0)
        s /= 2.0
    while s < 0.5:
        factors.append(0.5)
        s /= 0.5
    factors.append(round(s, 4))
    return ",".join("atempo=%s" % f for f in factors)


def fit_audio(in_path: str, out_path: str, target_dur: float,
              max_speed: float = 1.25) -> str:
    """把音频变速/裁剪到不超过 target_dur 秒，统一输出 48k 立体声 wav

    max_speed：最多加速到多少倍。超过就只加到这个倍数再淡出截断——
    以前放到 2.6 倍，听起来像快进，完全不像旁白。
    """
    find_ffmpeg()
    dur = probe_duration(in_path)
    filters = []
    if dur > target_dur + 0.02:
        speed = dur / max(target_dur, 0.05)
        if speed > max_speed:
            # 语速差距过大：只加速到上限，剩下裁掉并淡出，宁可少几个字也不快进
            filters.append(_atempo_chain(max_speed))
            filters.append("atrim=0:%.3f,afade=t=out:st=%.3f:d=0.25"
                           % (target_dur, max(target_dur - 0.25, 0.0)))
        else:
            filters.append(_atempo_chain(speed))
    af = ",".join(filters) if filters else "anull"
    cmd = [_ffmpeg, "-y", "-i", in_path, "-af", af,
           "-ar", "48000", "-ac", "2", "-f", "wav", out_path]
    run(cmd)
    return out_path


def make_silence(out_path: str, duration: float) -> str:
    find_ffmpeg()
    cmd = [_ffmpeg, "-y", "-f", "lavfi", "-i",
           "anullsrc=channel_layout=stereo:sample_rate=48000:duration=%.3f" % duration,
           "-ar", "48000", "-ac", "2", "-f", "wav", out_path]
    run(cmd)
    return out_path


def mix_track(items, total_dur: float, out_path: str,
              original_audio: str = None, original_volume: float = 0.12,
              batch: int = 12) -> str:
    """items: [(wav_path, start_sec)] → 按字幕时间轴混音为一条英文配音轨"""
    find_ffmpeg()
    input_args = ["-f", "lavfi", "-i",
                  "anullsrc=channel_layout=stereo:sample_rate=48000:duration=%.3f"
                  % total_dur]
    filters = []
    acc = "[0:a]"
    n = 1
    if original_audio:
        input_args += ["-i", original_audio]
        filters.append("[%d:a]volume=%s[o]" % (n, original_volume))
        filters.append(acc + "[o]amix=inputs=2:normalize=0:duration=first:"
                       "dropout_transition=0[b]")
        acc = "[b]"
        n += 1
    for k in range(0, len(items), batch):
        chunk = items[k:k + batch]
        refs = [acc]
        for j, (wav, start) in enumerate(chunk):
            input_args += ["-i", wav]
            ms = int(round(start * 1000))
            filters.append("[%d:a]adelay=%d|%d[d%d_%d]" % (n, ms, ms, k, j))
            refs.append("[d%d_%d]" % (k, j))
            n += 1
        filters.append("".join(refs) + "amix=inputs=%d:normalize=0:"
                       "duration=first:dropout_transition=0[m%d]"
                       % (len(refs), k))
        acc = "[m%d]" % k
    if filters:
        cmd = [_ffmpeg, "-y"] + input_args + [
            "-filter_complex", ";".join(filters), "-map", acc,
            "-ar", "48000", "-ac", "2", "-f", "wav", out_path]
    else:
        # 没有任何片段时直接输出静音基底
        cmd = [_ffmpeg, "-y"] + input_args + [
            "-map", "0:a", "-ar", "48000", "-ac", "2", "-f", "wav", out_path]
    run(cmd)
    return out_path


def burn_subtitles(video: str, audio_wav: str, ass_path: str, out_path: str,
                   W: int, H: int, duration: float, crf: int = 20,
                   preset: str = "medium", log=None) -> str:
    """缩放 + 烧录字幕 + 替换音轨，编码输出。
    注意：ffmpeg 的 subtitles 滤镜对 Windows 绝对路径（盘符冒号）解析有问题，
    这里用「相对文件名 + cwd」的方式规避。"""
    find_ffmpeg()
    ass_dir = os.path.dirname(os.path.abspath(ass_path))
    ass_name = os.path.basename(ass_path)
    vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,"
          "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,"
          "subtitles='%s'" % (W, H, W, H, ass_name))
    cmd = [_ffmpeg, "-y", "-i", video, "-i", audio_wav,
           "-vf", vf, "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-t", "%.3f" % duration, "-movflags", "+faststart", out_path]
    run(cmd, log, cwd=ass_dir)
    return out_path

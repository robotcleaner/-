# -*- coding: utf-8 -*-
"""检测「原视频自带（烧录）字幕」的纵向位置。

原理：烧录字幕几乎都是「亮字 + 深色描边」或「深字 + 亮色描边」，
       笔画两侧都紧邻反色。而物体边缘只在一侧有反差，因此可以排除。
       再按行统计命中比例、跨帧取中位数，得到一条稳定的水平带。
"""
from __future__ import annotations
import subprocess

import ffmpeg_utils as fx

try:
    import numpy as np
except Exception:  # numpy 是 faster-whisper 的依赖，正常都在
    np = None


def _grab_gray(video: str, w: int, h: int, dur: float,
               max_frames: int = 48):
    """抽若干帧为灰度小图。优先只解码关键帧（最快），失败则按固定帧率采样。"""
    fx.find_ffmpeg()
    size = w * h
    attempts = [
        (["-skip_frame", "nokey"], ["-fps_mode", "passthrough"]),
        (["-skip_frame", "nokey"], ["-vsync", "0"]),
    ]
    for pre, post in attempts:
        cmd = ([fx._ffmpeg, "-v", "error"] + pre + ["-i", video] + post
               + ["-an", "-vf", "scale=%d:%d,format=gray" % (w, h),
                  "-f", "rawvideo", "-"])
        frames = _read_frames(cmd, size, max_frames)
        if len(frames) >= 3:
            return frames
    # 兜底：按固定帧率采样（老版本 ffmpeg 也能用）
    fps = max(0.05, min(1.0, max_frames / max(dur, 1.0)))
    cmd = [fx._ffmpeg, "-v", "error", "-i", video, "-an",
           "-vf", "fps=%.4f,scale=%d:%d,format=gray" % (fps, w, h),
           "-frames:v", str(max_frames), "-f", "rawvideo", "-"]
    return _read_frames(cmd, size, max_frames)


def _read_frames(cmd, size, max_frames):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)
    except Exception:
        return []
    frames = []
    try:
        while len(frames) < max_frames:
            buf = p.stdout.read(size)
            if not buf or len(buf) < size:
                break
            frames.append(np.frombuffer(buf, np.uint8))
    except Exception:
        pass
    finally:
        try:
            p.stdout.close()
            p.wait(timeout=10)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    return frames


def _stroke_mask(g, h, w, radius):
    """亮字（上下都是暗）或暗字（上下都是亮）的像素掩膜"""
    a = g.reshape(h, w).astype(np.int16)
    pad = np.pad(a, ((radius, radius), (0, 0)), mode="edge")
    mins, maxs = [], []
    for k in range(1, radius + 1):
        mins.append(pad[radius - k:radius - k + h])
        mins.append(pad[radius + k:radius + k + h])
        maxs.append(pad[radius - k:radius - k + h])
        maxs.append(pad[radius + k:radius + k + h])
    up_dark = np.minimum.reduce(mins[0::2])
    dn_dark = np.minimum.reduce(mins[1::2])
    up_lit = np.maximum.reduce(maxs[0::2])
    dn_lit = np.maximum.reduce(maxs[1::2])
    white_text = (a > 172) & (up_dark < 98) & (dn_dark < 98)
    black_text = (a < 82) & (up_lit > 162) & (dn_lit > 162)
    return white_text | black_text


def _runs(flags, gap=3):
    """把布尔数组里连续的 True 归并成区间，容忍 gap 行的空洞"""
    out = []
    start = None
    last = None
    for i, v in enumerate(flags):
        if not v:
            continue
        if start is None:
            start = last = i
        elif i - last <= gap + 1:
            last = i
        else:
            out.append((start, last))
            start = last = i
    if start is not None:
        out.append((start, last))
    return out


def detect_subtitle_band(video: str, W: int = 1280, H: int = 720,
                         log=None, max_frames: int = 48):
    """返回原视频自带字幕的 (上沿, 下沿) 像素坐标（按 W×H 输出画面），
    没检测到返回 None。"""
    if np is None:
        return None
    hw, hh = max(160, W // 2), max(90, H // 2)
    try:
        dur = fx.probe_duration(video)
    except Exception:
        dur = 0.0
    frames = _grab_gray(video, hw, hh, dur, max_frames)
    if len(frames) < 3:
        if log:
            log("  [原字幕检测] 取样帧不足，跳过检测")
        return None

    radius = max(3, int(round(hh / 90.0)))
    x0, x1 = int(hw * 0.06), int(hw * 0.94)
    rows = []
    for f in frames:
        m = _stroke_mask(f, hh, hw, radius)[:, x0:x1]
        rows.append(m.mean(axis=1))
    prof = np.median(np.array(rows), axis=0)

    lo = int(hh * 0.50)                       # 只看画面下半部分
    peak = float(prof[lo:].max()) if lo < hh else 0.0
    if peak < 0.012:                          # 太稀疏，认为没有烧录字幕
        if log:
            log("  [原字幕检测] 未发现烧录字幕（峰值 %.3f）" % peak)
        return None

    thr = max(0.28 * peak, 0.006)
    flags = np.zeros(hh, bool)
    flags[lo:] = prof[lo:] >= thr
    cands = _runs(flags, gap=3)
    if not cands:
        return None
    # 取「质量最大」的一条带（不额外外扩，避免浪费下方空间）
    top, bot = max(cands, key=lambda r: float(prof[r[0]:r[1] + 1].sum()))

    band_h = (bot - top + 1) * 2              # 换回输出分辨率
    if band_h < 10 or band_h > max(120, H * 0.22):
        if log:
            log("  [原字幕检测] 带高 %dpx 不合理，按未检测到处理" % band_h)
        return None
    y_top, y_bot = top * 2, min(H - 1, (bot + 1) * 2)
    if y_top < int(H * 0.45):
        if log:
            log("  [原字幕检测] 位置偏上（y=%d），不像字幕" % y_top)
        return None
    return y_top, y_bot

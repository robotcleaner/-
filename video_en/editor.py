# -*- coding: utf-8 -*-
"""多视频剪辑合成：裁剪 + 排序 + 拼接，可选继续外语配音字幕"""
from __future__ import annotations
import os
import shutil
import tempfile
from dataclasses import dataclass

import ffmpeg_utils as fx
import pipeline as pipeline_mod
from ven_config import APP_DIR


class EditError(RuntimeError):
    pass


@dataclass
class Clip:
    path: str
    start: float = 0.0
    end: float = 0.0  # <=0 表示到结尾

    def label(self) -> str:
        name = os.path.basename(self.path)
        return "%s  [%s → %s]" % (name, _fmt_sec(self.start),
                                  _fmt_sec(self.end) if self.end > 0 else "结尾")


def _fmt_sec(t: float) -> str:
    t = max(t, 0.0)
    m = int(t // 60)
    s = t - m * 60
    return "%d:%05.2f" % (m, s)


def parse_time(s, duration: float = 0.0) -> float:
    """解析 '12.5' / '01:23.5' / '1:02:03' 等时间写法"""
    s = str(s).strip()
    if not s:
        return 0.0
    if ":" in s:
        t = 0.0
        for p in s.split(":"):
            t = t * 60 + float(p)
        return t
    return float(s)


def merge_clips(clips, output_path: str, cfg: dict, log=print, progress=None,
                dub: bool = False, dub_output: str = None):
    def P(pct, msg):
        if progress:
            progress(pct, msg)
        log("[%3d%%] %s" % (pct, msg))

    fx.find_ffmpeg(cfg.get("ffmpeg_path", ""))
    clips = [c for c in clips if c.path and os.path.isfile(c.path)]
    if not clips:
        raise EditError("请至少添加一个视频片段")

    durs = [fx.probe_duration(c.path) for c in clips]
    for c, d in zip(clips, durs):
        if c.start < 0:
            c.start = 0.0
        if c.end <= 0 or c.end > d:
            c.end = d
        if c.end <= c.start:
            raise EditError("片段入点/出点无效: %s" % c.path)
    clip_durs = [c.end - c.start for c in clips]
    total = sum(clip_durs)

    W, H = pipeline_mod.resolve_output_size(
        clips[0].path, cfg.get("resolution", "1280x720"))
    log("合成 %d 个片段，总时长 %.1fs，输出 %dx%d"
        % (len(clips), total, W, H))

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="ven_edit_", dir=out_dir)
    try:
        silence = None
        for i, c in enumerate(clips):
            if not fx.has_audio(c.path):
                if silence is None:
                    silence = fx.make_silence(os.path.join(tmp, "silence.wav"),
                                              total + 1.0)
        input_args = []
        filters = []
        vrefs, arefs = [], []
        n = len(clips)  # 静音输入排在所有片段输入之后
        for i, c in enumerate(clips):
            input_args += ["-i", c.path]
            filters.append(
                "[%d:v]trim=start=%.3f:end=%.3f,setpts=PTS-STARTPTS,"
                "scale=%d:%d:force_original_aspect_ratio=decrease,"
                "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
                "format=yuv420p[v%d]"
                % (i, c.start, c.end, W, H, W, H, i))
            vrefs.append("[v%d]" % i)
            if fx.has_audio(c.path):
                filters.append(
                    "[%d:a]atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,"
                    "aformat=sample_fmts=fltp:sample_rates=48000:"
                    "channel_layouts=stereo,apad=whole_dur=%.3f[a%d]"
                    % (i, c.start, c.end, clip_durs[i], i))
            else:
                if silence is None:
                    raise EditError("片段无音频且无法生成静音轨: %s" % c.path)
                input_args += ["-i", silence]
                filters.append(
                    "[%d:a]atrim=start=0:end=%.3f,asetpts=PTS-STARTPTS,"
                    "aformat=sample_fmts=fltp:sample_rates=48000:"
                    "channel_layouts=stereo,apad=whole_dur=%.3f[a%d]"
                    % (n, clip_durs[i], clip_durs[i], i))
                n += 1
            arefs.append("[a%d]" % i)
        # concat 的输入必须按 [v0][a0][v1][a1]... 交错排列
        interleaved = []
        for i in range(len(clips)):
            interleaved.append(vrefs[i])
            interleaved.append(arefs[i])
        filters.append("".join(interleaved) +
                       "concat=n=%d:v=1:a=1[vout][aout]" % len(clips))

        P(10, "拼接 %d 个片段" % len(clips))
        cmd = [fx.find_ffmpeg(cfg.get("ffmpeg_path", "")), "-y"] + input_args + [
            "-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
            output_path]
        fx.run(cmd, log)
        P(60, "剪辑合成完成: " + output_path)

        if dub:
            if not dub_output:
                base, ext = os.path.splitext(output_path)
                dub_output = base + "_en" + (ext or ".mp4")
            P(65, "剪辑完成，开始外语配音字幕…")
            pipeline_mod.process_single_video(output_path, dub_output, cfg,
                                              log, progress)
            return dub_output
        return output_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

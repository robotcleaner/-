# -*- coding: utf-8 -*-
"""ASS 字幕生成

三种模式：
  bilingual  双语（中文在上、目标语言在下，同一字幕块）
  en         仅目标语言（原视频没有字幕时用）
  en_below   仅目标语言，且压在原视频自带中文字幕的下方（原视频已有烧录字幕时用）

目标语言由 langs.LANGS 决定（字体 / 字号 / 每行字数 / 字符宽度都跟着变）。
"""
from __future__ import annotations
import math

import langs

_SENT = "。！？!?；;"
_CLAUSE = "，,、：:"
_LINE_H = 1.22


def _fmt(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return "%d:%02d:%05.2f" % (h, m, s)


def _clean(text: str) -> str:
    return (text.replace("{", "(").replace("}", ")")
                .replace("\r", " ").replace("\n", " ").strip())


def _metrics(W: int, H: int, lang_code: str = "en"):
    """字号按画面短边计算，横屏/竖屏都不会过大或过小"""
    base = min(W, H)
    ratio = langs.get(lang_code)["size_ratio"]
    t_size = max(16, int(round(base * ratio)))     # 英 720->28 / 日韩 720->24
    zh_size = max(15, int(round(base * 0.031)))    # 720 -> 22
    margin_v = max(16, int(round(base * 0.048)))   # 720 -> 35
    outline = max(2.0, base * 0.0036)              # 720 -> 2.6
    return t_size, zh_size, margin_v, outline


def _tokens(text: str):
    """按句读/空格切成小片，片尾保留分隔符（纯空白的片并入前一片，避免丢空格）"""
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _SENT or ch in _CLAUSE or ch == " ":
            if buf.strip():
                out.append(buf)
            elif buf and out:
                out[-1] += buf
            buf = ""
    if buf.strip():
        out.append(buf)
    return out or [text]


def _split_n(text: str, n: int):
    """把 text 切成恰好 n 片（在句读/空格处切，尽量均分，不硬断字）"""
    text = text.strip()
    if n <= 1 or not text:
        return [text] + [""] * max(0, n - 1)
    toks = _tokens(text)
    # 片数不够时，把最长的片再对半切开（优先在空格/标点后断）
    guard = 0
    while len(toks) < n and guard < n * 4:
        guard += 1
        i = max(range(len(toks)), key=lambda j: len(toks[j]))
        t = toks[i]
        if len(t) < 4:
            break
        mid = len(t) // 2
        cut = -1
        for sep in (" ", "，", ",", "、", "：", ":"):
            cut = t.rfind(sep, 0, mid)
            if cut > 0:
                cut += 1
                break
        if cut <= 0:
            cut = mid
        toks[i:i + 1] = [t[:cut], t[cut:]]

    total = float(sum(len(t) for t in toks))
    # 片数刚好等于 token 数时，直接一片一个 token（中文常见：一句一块）
    if len(toks) <= n:
        return [t.strip() for t in toks] + [""] * (n - len(toks))
    parts, cur, done = [], "", 0.0
    for i, t in enumerate(toks):
        cur += t
        left = n - len(parts)
        # 每一片只吃掉「剩余文本」的平均份额，保证后面还留得下；最后一片不切
        if left > 1 and i < len(toks) - 1 \
                and len(cur) >= (total - done) / float(left):
            parts.append(cur)
            done += len(cur)
            cur = ""
    if cur.strip():
        parts.append(cur)

    # 片数兜底：多了就并到末尾，少了就补空
    if len(parts) > n:
        parts = parts[:n - 1] + ["".join(parts[n - 1:])]
    while len(parts) < n:
        parts.append("")
    # 只在首尾去空白，保证相邻片拼接时不会丢空格
    return [p.lstrip() if i == 0 else p.rstrip() if i == len(parts) - 1 else p
            for i, p in enumerate(parts)]


def _display_events(segments, mode: str, lang_code: str = "en"):
    """把过长的一条字幕拆成多条显示事件（不影响配音时间轴）"""
    L = langs.get(lang_code)
    if mode == "bilingual":
        lim_zh, lim_t = 30, L["max_line_bi"]
    else:
        # 目标语言单独成行时切得更短：底部空间有限，句子短了字号才能大
        lim_zh, lim_t = 34, L["max_line"]
    events = []
    for seg in segments:
        zh = _clean(seg.text_zh)
        en = _clean(seg.text_en)
        n_zh = max(1, int(math.ceil(len(zh) / float(lim_zh)))) if zh else 1
        n_en = max(1, int(math.ceil(len(en) / float(lim_t)))) if en else 1
        k = max(n_zh, n_en)
        if k <= 1:
            events.append([seg.start, seg.end, zh, en])
            continue
        zs = _split_n(zh, k) if zh else [""] * k
        es = _split_n(en, k) if en else [""] * k
        while len(zs) < k:
            zs.append("")
        while len(es) < k:
            es.append("")
        # 时间按英文字数分配（英文通常更长，按它分才不会出现一闪而过）
        weights = [max(1, len(e)) for e in es] if en else \
                  [max(1, len(z)) for z in zs]
        tot_w = float(sum(weights))
        span = max(0.2, seg.end - seg.start)
        t = seg.start
        for i in range(k):
            d = span * weights[i] / tot_w
            end = seg.end if i == k - 1 else min(seg.end, t + d)
            events.append([t, end, zs[i].strip(), es[i].strip()])
            t = end
    return events


def _lines_of(text: str, font: int, avail_w: float,
              char_w: float = 0.52) -> int:
    if not text:
        return 1
    cpl = max(6, int(avail_w / (char_w * font)))
    return max(1, int(math.ceil(len(text) / float(cpl))))


def _fit_font(texts, avail_h: float, avail_w: float, max_font: int,
              min_font: int = 14, char_w: float = 0.52) -> int:
    """在给定高度内，选一个能让所有译文都不溢出的最大字号"""
    for f in range(max_font, min_font - 1, -1):
        if all(_lines_of(t, f, avail_w, char_w) * f * _LINE_H <= avail_h
               for t in texts):
            return f
    return min_font


def write_ass(segments, path: str, W: int = 1280, H: int = 720,
              mode: str = "bilingual", source_band=None,
              lang: str = "en") -> str:
    """mode: bilingual / en / en_below
       source_band: (上沿, 下沿) 原视频自带字幕的像素位置，仅 en_below 用到
       lang: 目标语言代码（en / ja / ko）"""
    L = langs.get(lang)
    t_font = L["font"]
    char_w = L["char_w"]
    en_size, zh_size, margin_v, outline = _metrics(W, H, lang)
    events = _display_events(segments, mode, lang)

    align = 2
    if mode == "en_below" and source_band:
        band_top, band_bot = int(source_band[0]), int(source_band[1])
        below = H - band_bot
        if below >= max(28, int(en_size * 0.9)):
            # 原字幕下方有空间：贴着画面底部放，字号按可用高度自动收缩
            margin_v = 4
            avail_h = max(16, below - margin_v - 4)
            align = 2
        else:
            # 下方太窄：改放到原字幕上方，仍然紧贴原字幕
            margin_v = max(6, H - band_top + 10)
            avail_h = max(16, int(H * 0.10))
            align = 2
        avail_w = W - 72
        en_size = _fit_font([e[3] for e in events], avail_h, avail_w,
                            en_size, min_font=max(13, int(en_size * 0.5)),
                            char_w=char_w)
        zh_size = 0
    elif mode == "en_below":
        # 没检测到原字幕位置，退化为普通「仅英文」
        mode = "en"

    header = (
        "[Script Info]\n"
        "Title: VideoEn Subtitles\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n"
        "PlayResX: %d\n"
        "PlayResY: %d\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # 单一 Sub 样式：底部居中、加粗、纯黑描边 + 半透明阴影，保证清晰
        "Style: Sub,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,"
        "-1,0,0,0,100,100,0,0,1,%.1f,%.1f,%d,36,36,%d,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
        % (W, H, t_font, en_size, outline, outline * 0.55, align, margin_v))

    lines = [header]
    for start, end, zh, en in events:
        if mode == "bilingual":
            if en and zh:
                # 同一条字幕内换行：第一行中文（稍小、淡白），第二行目标语言（更大、纯白）
                text = ("{\\fnMicrosoft YaHei\\fs%d\\c&H00F2F2F2&}%s\\N"
                        "{\\fn%s\\fs%d\\c&H00FFFFFF&}%s"
                        % (zh_size, zh, t_font, en_size, en))
            else:
                text = en or zh
        else:
            # 仅目标语言模式绝不回退成中文：en_below 下会跟原字幕重复，
            # 普通 en 模式下也会让人误以为「没翻成目标语言」
            text = en
        if text:
            lines.append("Dialogue: 0,%s,%s,Sub,,0,0,0,,%s"
                         % (_fmt(start), _fmt(end), text))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path

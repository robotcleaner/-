# -*- coding: utf-8 -*-
"""视频英文化（网页版）

复用 video_en/ 下的本地流水线：ASR（faster-whisper）→ 翻译 → TTS →
字幕 → ffmpeg 烧录。原 tkinter 桌面版仍在 video_en/ 之外的项目里，
这里只做「上传 → 处理 → 下载」的主流程。
"""
import importlib.util
import os
import sys
import tempfile
import traceback

import streamlit as st

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VEN_DIR = os.path.join(BASE_DIR, "video_en")
for _p in (BASE_DIR, os.path.join(BASE_DIR, "core"), VEN_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

st.title("🎬 中文视频英文化")
st.caption("上传中文视频 → 语音识别 → 翻译 + 配音 + 烧录字幕 → 下载成品")


# ==================== 环境检查 ====================
def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


ffmpeg_ok, ffmpeg_err = False, ""
try:
    import ffmpeg_utils as fx
    fx.find_ffmpeg("")
    ffmpeg_ok = True
except Exception as e:  # noqa: BLE001
    ffmpeg_err = str(e)

has_asr = _has_module("faster_whisper")
has_tts = _has_module("edge_tts")

c1, c2, c3 = st.columns(3)
c1.metric("ffmpeg", "✅ 已就绪" if ffmpeg_ok else "❌ 未找到")
c2.metric("语音识别", "✅ 已安装" if has_asr else "❌ 未安装")
c3.metric("在线配音", "✅ 已安装" if has_tts else "❌ 未安装")

if not ffmpeg_ok:
    st.error("未找到 ffmpeg，视频处理无法进行。")
    st.code(ffmpeg_err or "请安装 ffmpeg 并加入 PATH", language="text")
if not has_asr:
    st.error("缺少语音识别依赖 faster-whisper。")
    st.code("pip install faster-whisper", language="bash")
if not has_tts:
    st.warning("缺少在线配音依赖 edge-tts，配音会失败（字幕仍可生成）。")
    st.code("pip install edge-tts", language="bash")

if not (ffmpeg_ok and has_asr):
    st.info("装好上面的依赖后刷新页面即可使用。也可以继续用桌面版（双击 run.bat）。")
    st.stop()


# ==================== 读取配置 ====================
import langs  # noqa: E402
import pipeline as ven_pipeline  # noqa: E402
from tts import voices_for  # noqa: E402
from ven_config import load_config, save_config  # noqa: E402

cfg = load_config()

TRANS_ITEMS = [
    ("mymemory", "MyMemory（免费免密钥，默认）"),
    ("zhipu", "智谱 GLM-4-Flash（免费，需 API Key）"),
    ("baidu", "百度翻译（需 APP ID / 密钥）"),
    ("llm", "其他大模型 / OpenAI 兼容"),
    ("google", "Google 翻译（国内通常打不开）"),
    ("argos", "离线 Argos（需能访问 GitHub）"),
]
MODE_ITEMS = [
    ("bilingual", "双语（中文在上，译文在下）"),
    ("en", "仅译文"),
    ("en_below", "仅译文 · 叠在原中文字幕下方"),
]
MODEL_ITEMS = ["tiny", "base", "small", "medium", "large-v3"]


# ==================== 上传 ====================
uploaded = st.file_uploader(
    "上传中文视频（.mp4 / .mov / .mkv 等）",
    type=["mp4", "mov", "mkv", "avi", "flv", "wmv", "m4v"],
)

work_dir = os.path.join(tempfile.gettempdir(), "video_en_work")
os.makedirs(work_dir, exist_ok=True)

input_path = ""
if uploaded is not None:
    if ven_pipeline.looks_like_output(uploaded.name):
        st.warning(
            "这个文件名以 `_en / _ja / _ko` 结尾，看起来是本工具生成的成品。"
            "在成品上再处理会叠出多层字幕，建议改用原始中文视频。"
        )
    safe_name = os.path.basename(uploaded.name)
    input_path = os.path.join(work_dir, safe_name)
    if st.session_state.get("ven_input_name") != safe_name:
        with open(input_path, "wb") as f:
            f.write(uploaded.getbuffer())
        st.session_state["ven_input_name"] = safe_name
        st.session_state.pop("ven_output", None)

    try:
        dur = fx.probe_duration(input_path)
        size_mb = os.path.getsize(input_path) / 1048576
        st.success(f"已上传：{safe_name} · 时长 {dur:.0f} 秒 · {size_mb:.1f} MB")
        st.video(input_path)
    except Exception as e:  # noqa: BLE001
        st.warning(f"读取视频信息失败：{e}")


# ==================== 参数 ====================
with st.expander("⚙️ 处理参数", expanded=True):
    r1c1, r1c2, r1c3 = st.columns(3)
    lang = r1c1.selectbox(
        "目标语言", list(langs.ORDER),
        index=list(langs.ORDER).index(cfg.get("target_lang", "en"))
        if cfg.get("target_lang") in langs.ORDER else 0,
        format_func=lambda c: langs.get(c)["name"],
    )
    mode = r1c2.selectbox(
        "字幕模式", [k for k, _ in MODE_ITEMS],
        index=[k for k, _ in MODE_ITEMS].index(
            cfg.get("subtitle_mode", "bilingual"))
        if cfg.get("subtitle_mode") in dict(MODE_ITEMS) else 0,
        format_func=lambda k: dict(MODE_ITEMS)[k],
    )
    model = r1c3.selectbox(
        "识别模型", MODEL_ITEMS,
        index=MODEL_ITEMS.index(cfg.get("whisper_model", "small"))
        if cfg.get("whisper_model") in MODEL_ITEMS else 2,
        help="中文建议 small 及以上；模型越大越准也越慢（首次会下载）",
    )

    r2c1, r2c2, r2c3 = st.columns(3)
    trans_backend = r2c1.selectbox(
        "翻译后端", [k for k, _ in TRANS_ITEMS],
        index=[k for k, _ in TRANS_ITEMS].index(
            cfg.get("translate_backend", "mymemory"))
        if cfg.get("translate_backend") in dict(TRANS_ITEMS) else 0,
        format_func=lambda k: dict(TRANS_ITEMS)[k],
    )
    voices = voices_for(lang)
    voice_labels = list(voices.keys())
    default_voice = cfg.get("tts_voice", "")
    voice = r2c2.selectbox(
        "配音音色", voice_labels,
        index=voice_labels.index(default_voice)
        if default_voice in voice_labels else 0,
        format_func=lambda v: voices[v],
    )
    resolution = r2c3.selectbox(
        "输出分辨率", list(ven_pipeline.RESOLUTIONS.keys()),
        index=list(ven_pipeline.RESOLUTIONS.keys()).index(
            cfg.get("resolution", "1280x720"))
        if cfg.get("resolution") in ven_pipeline.RESOLUTIONS else 0,
        format_func=lambda k: ven_pipeline.RESOLUTIONS[k],
    )

    r3c1, r3c2, r3c3 = st.columns(3)
    keep_audio = r3c1.checkbox("保留原声做背景音",
                               value=bool(cfg.get("keep_original_audio")))
    orig_volume = r3c2.slider(
        "原声音量", 0.0, 0.5, float(cfg.get("original_audio_volume", 0.12)),
        0.01, disabled=not keep_audio)
    auto_avoid = r3c3.checkbox(
        "自动避让原视频自带的字幕",
        value=bool(cfg.get("auto_avoid_source_subs", True)),
        help="检测到原片已有中文字幕时，只叠加译文，避免中文重复",
    )

    key_cols = st.columns(3)
    zhipu_key = key_cols[0].text_input(
        "智谱 API Key", value=cfg.get("zhipu_api_key", ""), type="password",
        help="翻译后端选「智谱」时必填")
    baidu_id = key_cols[1].text_input(
        "百度 APP ID", value=cfg.get("baidu_appid", ""))
    baidu_key = key_cols[2].text_input(
        "百度密钥", value=cfg.get("baidu_key", ""), type="password")

    if trans_backend == "llm":
        lc1, lc2, lc3 = st.columns(3)
        llm_url = lc1.text_input("LLM Base URL",
                                 value=cfg.get("llm_base_url", ""))
        llm_key = lc2.text_input("LLM API Key",
                                 value=cfg.get("llm_api_key", ""),
                                 type="password")
        llm_model = lc3.text_input("LLM 模型名",
                                   value=cfg.get("llm_model", ""))
    else:
        llm_url = cfg.get("llm_base_url", "")
        llm_key = cfg.get("llm_api_key", "")
        llm_model = cfg.get("llm_model", "")


# ==================== 开始处理 ====================
if st.button("🚀 开始生成", type="primary", disabled=not input_path):
    new_cfg = dict(cfg)
    new_cfg.update({
        "target_lang": lang,
        "subtitle_mode": mode,
        "whisper_model": model,
        "translate_backend": trans_backend,
        "tts_voice": voice,
        "tts_backend": "edge" if has_tts else "offline",
        "resolution": resolution,
        "keep_original_audio": keep_audio,
        "original_audio_volume": orig_volume,
        "auto_avoid_source_subs": auto_avoid,
        "zhipu_api_key": zhipu_key,
        "baidu_appid": baidu_id,
        "baidu_key": baidu_key,
        "llm_base_url": llm_url,
        "llm_api_key": llm_key,
        "llm_model": llm_model,
        "allow_reprocessed": True,
    })
    try:
        save_config(new_cfg)
    except Exception:
        pass

    stem = os.path.splitext(os.path.basename(input_path))[0]
    out_path = os.path.join(work_dir, f"{stem}_{langs.suffix_of(new_cfg)}.mp4")

    progress = st.progress(0.0)
    status = st.empty()
    log_box = st.empty()
    lines = []

    def log(msg):
        lines.append(str(msg))
        log_box.code("\n".join(lines[-14:]), language="text")

    def prog(pct, msg):
        progress.progress(max(0.0, min(1.0, float(pct) / 100.0)))
        status.info(f"**{pct}%** · {msg}")

    started = __import__("time").time()
    try:
        with st.spinner("处理中…（首次运行会下载语音模型，请耐心等待）"):
            ven_pipeline.process_single_video(input_path, out_path, new_cfg,
                                              log=log, progress=prog)
        progress.progress(1.0)
        status.success(f"✅ 完成，用时 {__import__('time').time() - started:.0f} 秒")
        st.session_state["ven_output"] = out_path
    except Exception as e:  # noqa: BLE001
        status.error(f"处理失败：{e}")
        st.code(traceback.format_exc(), language="text")


# ==================== 结果 ====================
out_path = st.session_state.get("ven_output")
if out_path and os.path.isfile(out_path):
    st.divider()
    st.subheader("📥 成品")
    st.video(out_path)
    size_mb = os.path.getsize(out_path) / 1048576
    with open(out_path, "rb") as f:
        st.download_button(
            f"⬇️ 下载视频（{size_mb:.1f} MB）",
            data=f.read(),
            file_name=os.path.basename(out_path),
            mime="video/mp4",
            type="primary",
        )

st.divider()
st.caption(
    "提示：视频处理比较吃 CPU 和时间，短视频（1~3 分钟）体验最好；"
    "长视频建议在本机运行。首次使用某个识别模型时会下载模型文件（small 约 500MB）。"
)

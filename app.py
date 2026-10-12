import io
import os
import pandas as pd
import streamlit as st

from processor import process_dataframe as process_dataframe_au
from config import OUTPUT_COLUMNS as OUTPUT_COLUMNS_AU

from processor_kr import process_dataframe_kr
from config_kr import OUTPUT_COLUMNS_KR

from processor_kolon import process_dataframe_kolon, find_header_row
from config_kolon import OUTPUT_COLUMNS_KOLON

from processor_jp import process_dataframe_jp
from config_jp import OUTPUT_COLUMNS_JP


st.set_page_config(
    page_title="维修工单自动处理",
    page_icon="🔧",
    layout="wide",
)

st.title("🔧 维修工单自动处理工具")
st.caption("上传海外维修商原始工单 → 自动翻译 + 分类 + 格式化 → 输出标准化工单")

# ========== 区域选择 ==========
region = st.selectbox(
    "选择区域 / 服务商",
    options=["澳洲（PAU）", "韩国（SK）", "韩国（KOLON）", "日本（JP）"],
    index=0,
)

if region.startswith("澳洲"):
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_AU
    process_dataframe = process_dataframe_au
    TICKET_NUMBER_COL = "Ticket Number"
    IS_KOLON = False
    CACHE_KEY = "partial_au"
elif "KOLON" in region:
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_KOLON
    process_dataframe = process_dataframe_kolon
    TICKET_NUMBER_COL = "접수번호"
    IS_KOLON = True
    CACHE_KEY = "partial_kolon"
elif "日本" in region:
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_JP
    process_dataframe = process_dataframe_jp
    TICKET_NUMBER_COL = "唯一键"
    IS_KOLON = False
    CACHE_KEY = "partial_jp"
else:
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_KR
    process_dataframe = process_dataframe_kr
    TICKET_NUMBER_COL = "접수번호"
    IS_KOLON = False
    CACHE_KEY = "partial_kr"

st.info(f"当前区域：**{region}**，输出列数：{len(OUTPUT_COLUMNS)}")

# ========== Session State 初始化 ==========
if "stop_flag" not in st.session_state:
    st.session_state.stop_flag = False
if "processing" not in st.session_state:
    st.session_state.processing = False
if CACHE_KEY not in st.session_state:
    st.session_state[CACHE_KEY] = pd.DataFrame(columns=OUTPUT_COLUMNS)

with st.sidebar:
    st.header("⚙️ 使用说明")
    st.markdown("""
    1. 上传原始工单 `.xlsx`
    2. 点击「开始处理」
    3. 可随时点「⏹ 暂停」
    4. 可随时点「📥 导出已处理部分」
    5. 重新上传同一文件 → 点开始 → 自动跳过已处理
    """)
    st.divider()
    st.caption("模型：硅基流动 DeepSeek-V3")

# ========== 上传 ==========
uploaded = st.file_uploader(
    "上传原始工单（.xlsx）",
    type=["xlsx"],
    accept_multiple_files=False,
)

if uploaded is not None:
    try:
        if IS_KOLON:
            uploaded.seek(0)
            xlsx_bytes = uploaded.read()
            uploaded.seek(0)
            skip_rows = find_header_row(xlsx_bytes)
            st.caption(f"KOLON 自动探测表头：跳过前 {skip_rows} 行")
            df_raw = pd.read_excel(io.BytesIO(xlsx_bytes), engine="openpyxl",
                                   skiprows=skip_rows)
        else:
            df_raw = pd.read_excel(uploaded, engine="openpyxl")
    except Exception as e:
        st.error(f"读取失败：{e}")
        st.stop()

    st.success(f"已读取 {len(df_raw)} 条工单，共 {len(df_raw.columns)} 列")
    with st.expander("预览原始数据（前 5 行）"):
        st.dataframe(df_raw.head(5), use_container_width=True)

    # ========== 内存断点续跑 ==========
    partial_df = st.session_state[CACHE_KEY]
    if len(partial_df) > 0:
        out_ticket_col = "唯一键" if "日本" in region else "工单号"
        if out_ticket_col in partial_df.columns:
            done_ids = set(partial_df[out_ticket_col].astype(str))
        else:
            done_ids = set()
        st.info(f"📂 本次会话已处理 **{len(partial_df)}** 条（内存中）")
    else:
        done_ids = set()

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("🚀 开始处理", type="primary",
                     disabled=st.session_state.processing):
            st.session_state.stop_flag = False
            st.session_state.processing = True
            st.rerun()

    with col2:
        if st.button("⏹ 暂停", disabled=not st.session_state.processing):
            st.session_state.stop_flag = True
            st.session_state.processing = False
            st.warning("已暂停。可随时导出。")

    with col3:
        if len(partial_df) > 0:
            export_df = partial_df[[c for c in OUTPUT_COLUMNS if c in partial_df.columns]]
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                export_df.to_excel(writer, index=False, sheet_name="已处理")
            buffer.seek(0)
            st.download_button(
                label=f"📥 导出已处理部分（{len(export_df)} 条）",
                data=buffer,
                file_name="已处理部分.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    if st.session_state.processing:
        df_to_process = df_raw.copy()
        if done_ids and TICKET_NUMBER_COL in df_to_process.columns:
            df_to_process = df_to_process[
                ~df_to_process[TICKET_NUMBER_COL].astype(str).isin(done_ids)
            ]

        st.markdown(f"**本次需要处理：{len(df_to_process)} 条**")
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        def cb(done, total):
            pct = done / total if total else 0
            progress_bar.progress(pct)
            status_text.text(f"处理进度：{done} / {total}")

        def on_row_done(out_dict):
            filtered = {col: out_dict.get(col, "") for col in OUTPUT_COLUMNS}
            df_one = pd.DataFrame([filtered])
            st.session_state[CACHE_KEY] = pd.concat(
                [st.session_state[CACHE_KEY], df_one], ignore_index=True
            )

        def stop_getter():
            return st.session_state.stop_flag

        try:
            result_df = process_dataframe(
                df_to_process,
                progress_cb=cb,
                on_row_done=on_row_done,
                stop_flag_getter=stop_getter,
            )
            st.session_state.processing = False
            progress_bar.progress(1.0)
            status_text.text("✅ 本次处理完成")

            all_df = st.session_state[CACHE_KEY]
            all_df = all_df[[c for c in OUTPUT_COLUMNS if c in all_df.columns]]
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                all_df.to_excel(writer, index=False, sheet_name="优化后工单")
            buffer.seek(0)
            st.download_button(
                label=f"📥 下载全部已处理（{len(all_df)} 条）",
                data=buffer,
                file_name="优化后工单.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        except Exception as e:
            st.session_state.processing = False
            st.error(f"处理中断：{e}")

with st.sidebar:
    st.divider()
    if st.button("🗑 清空本次会话已处理

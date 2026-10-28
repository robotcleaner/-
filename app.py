import io
import os
from pathlib import Path
import pandas as pd
import streamlit as st

from processor import process_dataframe as process_dataframe_au
from config import OUTPUT_COLUMNS as OUTPUT_COLUMNS_AU, MAX_WORKERS

from processor_kr import process_dataframe_kr
from config_kr import OUTPUT_COLUMNS_KR

from processor_kolon import process_dataframe_kolon, find_header_row
from config_kolon import OUTPUT_COLUMNS_KOLON

# 日本模块（NGK）
from processor_jp import process_dataframe_jp
from config_jp import OUTPUT_COLUMNS_JP

# 日本模块（ITC）
from processor_itc import process_dataframe_itc, find_header_row as find_header_row_itc
from config_itc import OUTPUT_COLUMNS_ITC

# 二返率统计（移植自「二返率计算/2.py」）
from return_rate import (
    classify_return, calc_return_rate, build_detail, summarize, mark_breakdown,
    MARK_COL, RELATED_COL,
)


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
    options=["澳洲（PAU）", "韩国（SK）", "韩国（KOLON）", "日本（NGK）", "日本（ITC）"],
    index=0,
)

if region.startswith("澳洲"):
    PARTIAL_FILE = "partial_result_au.csv"
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_AU
    process_dataframe = process_dataframe_au
    TICKET_NUMBER_COL = "Ticket Number"
    OUTPUT_TICKET_COL = "工单号"
    IS_KOLON = False
elif "KOLON" in region:
    PARTIAL_FILE = "partial_result_kolon.csv"
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_KOLON
    process_dataframe = process_dataframe_kolon
    TICKET_NUMBER_COL = "접수번호"
    OUTPUT_TICKET_COL = "工单号"
    IS_KOLON = True
elif "ITC" in region:
    PARTIAL_FILE = "partial_result_itc.csv"
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_ITC
    process_dataframe = process_dataframe_itc
    TICKET_NUMBER_COL = "RMA"
    OUTPUT_TICKET_COL = "工单号"
    IS_KOLON = True   # 复用 KOLON 的"自动探测表头"分支
elif "NGK" in region or "日本" in region:
    PARTIAL_FILE = "partial_result_jp.csv"
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_JP
    process_dataframe = process_dataframe_jp
    TICKET_NUMBER_COL = "唯一键"
    OUTPUT_TICKET_COL = "唯一键"
    IS_KOLON = False
else:
    PARTIAL_FILE = "partial_result_kr.csv"
    OUTPUT_COLUMNS = OUTPUT_COLUMNS_KR
    process_dataframe = process_dataframe_kr
    TICKET_NUMBER_COL = "접수번호"
    OUTPUT_TICKET_COL = "工单号"
    IS_KOLON = False

st.info(f"当前区域：**{region}**，输出列数：{len(OUTPUT_COLUMNS)}")

# 断点文件路径（各区域独立）
partial_path = Path(PARTIAL_FILE)

if "stop_flag" not in st.session_state:
    st.session_state.stop_flag = False
if "processing" not in st.session_state:
    st.session_state.processing = False

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
    workers = st.slider(
        "并发处理数", min_value=1, max_value=8, value=MAX_WORKERS,
        help="翻译/分类为网络 IO 密集型任务，适当并发可数倍提速；"
             "如遇接口限流报错，请调低并发数",
    )
    st.caption(f"模型：硅基流动 DeepSeek-V3（并发 {workers}）")

# ========== 上传 ==========
uploaded = st.file_uploader(
    "上传原始工单（.xlsx）",
    type=["xlsx"],
    accept_multiple_files=False,
)

if uploaded is not None:
    # 读文件
    try:
        if IS_KOLON:
            # KOLON / ITC：先自动探测表头行，再按探测结果跳过
            uploaded.seek(0)
            xlsx_bytes = uploaded.read()
            uploaded.seek(0)
            if "ITC" in region:
                skip_rows = find_header_row_itc(xlsx_bytes)
                st.caption(f"ITC 自动探测表头：跳过前 {skip_rows} 行")
            else:
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

    # ========== 断点续跑 ==========
    if Path(PARTIAL_FILE).exists():
        try:
            partial_df = pd.read_csv(PARTIAL_FILE, encoding="utf-8-sig", on_bad_lines='skip')
            if OUTPUT_TICKET_COL in partial_df.columns:
                done_ids = set(partial_df[OUTPUT_TICKET_COL].astype(str))
            else:
                done_ids = set()
            st.info(f"📂 检测到 `{PARTIAL_FILE}`，已处理 **{len(partial_df)}** 条")
        except Exception:
            partial_df = None
            done_ids = set()
    else:
        partial_df = None
        done_ids = set()

    # ========== 日期口径修正 ==========
    # 断点文件里的旧行可能用的是旧日期来源（如澳洲曾用创建日期）。
    # 这里按当前口径从本次上传的源表重新取一次，按工单号回填，零成本。
    if partial_df is not None and len(partial_df) > 0:
        try:
            from date_refresh import refresh_partial_dates, write_partial
            partial_df, fixed = refresh_partial_dates(partial_df, df_raw, region)
            if fixed:
                st.warning(f"🔧 已按当前日期口径修正断点文件中 {fixed} 行的日期")
                if write_partial(partial_df, partial_path):
                    st.caption("已同步写回断点文件")
        except Exception as e:
            st.caption(f"日期口径修正跳过：{e}")

    # ========== 往批历史（用于 重复 / 二返 / 三返 判定）==========
    # 断点文件里是已处理完的标准化行：其 SN + 日期 可作为"该 SN 之前
    # 是否出现过"的历史依据；故障类型（一级）用于对比是否「重现」。
    history_records = None
    if partial_df is not None and len(partial_df) > 0:
        try:
            history_records = [
                {
                    "sn": r.get("SN", ""),
                    "date": r.get("日期", ""),
                    "desc": r.get("故障描述", ""),
                    "detail": r.get("维修详情", ""),
                    "fault": r.get("故障类型（一级）", ""),
                }
                for _, r in partial_df.iterrows()
            ]
            # 过滤空 SN / NaN（避免 "nan" 字符串被当成真实 SN 分组）
            history_records = [
                h for h in history_records
                if str(h.get("sn") or "").strip()
                and str(h.get("sn")).strip().lower() not in ("nan", "none", "nat")
            ] or None
        except Exception:
            history_records = None

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
        if partial_df is not None and len(partial_df) > 0:
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
            # 表头仅在文件不存在或为空时写入，避免重复表头/错位
            need_header = (not partial_path.exists()
                           or partial_path.stat().st_size == 0)
            df_one.to_csv(
                PARTIAL_FILE,
                mode="a",
                header=need_header,
                index=False,
                encoding="utf-8-sig",
            )

        def stop_getter():
            return st.session_state.stop_flag

        try:
            result_df = process_dataframe(
                df_to_process,
                progress_cb=cb,
                on_row_done=on_row_done,
                stop_flag_getter=stop_getter,
                max_workers=workers,
                history_records=history_records,
            )
            st.session_state.processing = False
            progress_bar.progress(1.0)
            status_text.text("✅ 本次处理完成")

            if Path(PARTIAL_FILE).exists():
                all_df = pd.read_csv(PARTIAL_FILE, encoding="utf-8-sig", on_bad_lines='skip')
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

# ==================== 二返率统计（独立分析）====================
st.divider()
st.header("📊 二返率统计")
st.caption(
    "对已处理结果按 SN + 日期重新判定 重复 / 二返 / 三返，并统计型号维度二返率。"
    "（与处理阶段的「类别」列独立，窗口可调）"
)

rate_src = st.radio(
    "数据来源",
    ["当前区域的已处理结果", "上传已处理工单文件"],
    horizontal=True,
)

df_rate = None
if rate_src == "当前区域的已处理结果":
    if partial_path.exists():
        try:
            df_rate = pd.read_csv(partial_path, encoding="utf-8-sig",
                                  on_bad_lines="skip")
            st.caption(f"已读取 `{PARTIAL_FILE}`：{len(df_rate)} 行")
        except Exception as e:
            st.error(f"读取失败：{e}")
    else:
        st.info(f"未找到 `{PARTIAL_FILE}`，请先处理工单，或改用「上传已处理工单文件」。")
else:
    up_rate = st.file_uploader("上传已处理工单（.xlsx / .csv）",
                               type=["xlsx", "csv"], key="rate_upload")
    if up_rate is not None:
        try:
            if up_rate.name.lower().endswith(".csv"):
                df_rate = pd.read_csv(up_rate, encoding="utf-8-sig",
                                      on_bad_lines="skip")
            else:
                df_rate = pd.read_excel(up_rate, engine="openpyxl")
            df_rate.columns = [str(c).strip() for c in df_rate.columns]
            st.caption(f"已读取：{len(df_rate)} 行")
        except Exception as e:
            st.error(f"读取失败：{e}")

if df_rate is not None and len(df_rate) > 0:
    c1, c2, c3 = st.columns([1, 1, 1.4])
    dup_days = c1.number_input(
        "重复判定窗口（天）", min_value=0, max_value=60, value=5, step=1,
        help="同 SN 日期间隔 ≤ 该值视为重复；填 0 表示仅同日算重复")
    ret_days = c2.number_input(
        "返修判定窗口（天）", min_value=7, max_value=730, value=90, step=1,
        help="向前回看多少天内的同 SN 历史工单")
    overwrite = c3.checkbox(
        "用标记覆盖「处理方式」列", value=False,
        help="勾选后与原二返率脚本的输出一致；默认保留原处理方式，另加「处理标记」列")

    missing_cols = [c for c in ("SN", "日期") if c not in df_rate.columns]
    if missing_cols:
        st.error(f"缺少必要列：{missing_cols}，无法判定。请上传本工具输出的已处理工单。")
    else:
        rr = classify_return(df_rate, int(dup_days), int(ret_days),
                             overwrite_method=bool(overwrite))
        info = summarize(rr)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("总工单数", info["总工单数"])
        m2.metric("返修（二返及以上）",
                  f'{info["返修数"]} 条', f'{info["返修率(%)"]}%')
        m3.metric("其中二返", f'{info["二返数"]} 条', f'{info["二返率(%)"]}%')
        m4.metric("重复", f'{info["重复数"]} 条', f'{info["重复率(%)"]}%')

        detail_df = build_detail(rr)
        rate_df = calc_return_rate(rr)
        full_df = rr.drop(columns=[MARK_COL, RELATED_COL], errors="ignore")
        breakdown = mark_breakdown(rr)

        tab_detail, tab_rate, tab_all = st.tabs(
            ["📋 明细报告", "📈 型号二返率", "🗂 全量结果"])
        with tab_detail:
            n_dup = int((detail_df[MARK_COL].astype(str) == "重复").sum()) \
                if MARK_COL in detail_df.columns else 0
            n_ret = len(detail_df) - n_dup
            st.caption(
                f"被标记的工单共 **{len(detail_df)}** 条"
                f"（重复 {n_dup} 条 / 返修 {n_ret} 条）。"
                "「重复」排在最前，其后按 二返 → 三返 → … 归组。"
            )

            if len(breakdown):
                bd_cols = st.columns(max(len(breakdown), 1))
                for i, (_, r) in enumerate(breakdown.iterrows()):
                    bd_cols[i].metric(str(r[MARK_COL]), f'{int(r["工单数"])} 条')

            sel = st.radio(
                "筛选", ["全部", "仅重复", "仅二返", "仅三返"],
                horizontal=True, key="rate_detail_filter",
            )
            view = detail_df
            if MARK_COL in detail_df.columns and sel != "全部":
                key = {"仅重复": "重复", "仅二返": "二返", "仅三返": "三返"}[sel]
                view = detail_df[
                    detail_df[MARK_COL].astype(str).str.startswith(key)]
            st.dataframe(view, use_container_width=True, height=420)
        with tab_rate:
            st.dataframe(rate_df, use_container_width=True, height=420)
        with tab_all:
            st.dataframe(full_df, use_container_width=True, height=420)

        def _to_xlsx(df_, sheet="Sheet1"):
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_.to_excel(writer, index=False, sheet_name=sheet)
            buf.seek(0)
            return buf

        XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
                     ".spreadsheetml.sheet")
        b1, b2, b3 = st.columns(3)
        b1.download_button("📥 全量结果.xlsx", _to_xlsx(full_df),
                           "二返重复_处理结果.xlsx", mime=XLSX_MIME,
                           key="dl_rate_all")
        b2.download_button("📥 明细报告.xlsx", _to_xlsx(detail_df),
                           "二返重复_明细报告.xlsx", mime=XLSX_MIME,
                           key="dl_rate_detail")
        b3.download_button("📥 二返率统计.xlsx", _to_xlsx(rate_df),
                           "二返率统计.xlsx", mime=XLSX_MIME,
                           key="dl_rate_rate")

with st.sidebar:
    st.divider()
    if st.button("🗑 清空已处理记录"):
        if Path(PARTIAL_FILE).exists():
            os.remove(PARTIAL_FILE)
            st.success("已清空")
        else:
            st.info("没有可清空的记录")
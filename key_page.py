"""重点产品故障排名（独立页面）。

挂载在「工单处理」分组下，与主流程解耦：主流程只负责把原始工单整理成标准表，
本页面负责拿**已整理好的工单**（上传 .xlsx/.csv，或直接读当前区域的断点结果）
生成 BU / 型号 / 故障数量 / TOP 故障类型占比 的排名表，可导出 Excel。

口径与参考文件《重点产品故障数量和类型.xlsx》一致：
    占比      = 该型号故障数 ÷ 该 BU 全部工单数
    TOP 百分比 = 该故障类型 ÷ 该型号自身工单数
"""

import io
import sys
from pathlib import Path

# 业务模块在 core/ 下：把 core 加入 sys.path
_ROOT = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_ROOT / "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd
import streamlit as st

from paths import state_path
from key_products import (
    build_key_products, write_excel_with_key_sheet, write_key_sheet_only,
    summarize_key_products, KEY_SHEET_NAME, KEY_COLUMNS,
    DEFAULT_TOP_MODELS, DEFAULT_TOP_FAULTS, DEFAULT_CATEGORIES,
)

# 各区域断点结果文件（与 app.py 保持一致）
REGION_FILES = {
    "澳洲（PAU）": state_path("partial_result_au.csv"),
    "韩国（SK）": state_path("partial_result_kr.csv"),
    "韩国（KOLON）": state_path("partial_result_kolon.csv"),
    "日本（NGK）": state_path("partial_result_jp.csv"),
    "日本（ITC）": state_path("partial_result_itc.csv"),
}

# 上传文件的列名容错：不同来源的已处理工单列名可能略有差异
COL_CANDIDATES = {
    "bu": ("产品BU", "BU", "品类", "产品线"),
    "model": ("型号", "机型", "Model", "Product Model"),
    "fault": ("故障类型（一级）", "故障类型(一级)", "故障类型", "Fault Type"),
    "cat": ("类别", "Category", "分类"),
}


def _pick_col(df: pd.DataFrame, keys) -> str | None:
    """按候选顺序找第一个存在的列名。"""
    for k in keys:
        if k in df.columns:
            return k
    return None


def _read_upload(file) -> pd.DataFrame:
    """读上传的已处理工单（xlsx / xls / csv）。"""
    name = (getattr(file, "name", "") or "").lower()
    if name.endswith(".csv"):
        return pd.read_csv(file, dtype=str, encoding="utf-8-sig")
    return pd.read_excel(file, dtype=str)


def _read_region_file(region: str) -> pd.DataFrame | None:
    """读当前区域的断点结果；文件不存在返回 None。"""
    path = Path(REGION_FILES.get(region, ""))
    if not path.exists() or path.stat().st_size == 0:
        return None
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig", on_bad_lines="skip")


st.title("🏆 重点产品故障排名")
st.caption(
    "上传**已整理好的工单**（主流程导出的「优化后工单.xlsx」或任意含"
    "型号 / 产品BU / 故障类型的表），按 BU 生成型号故障数量与 TOP 故障类型占比。"
)

# ==================== 数据来源 ====================
src = st.radio(
    "数据来源",
    ["上传已处理工单", "当前区域的已处理记录"],
    horizontal=True,
    help="上传模式与主流程完全解耦；「当前区域」直接读本机断点文件，不用重新上传",
)

df_src: pd.DataFrame | None = None
src_label = ""

if src == "上传已处理工单":
    up = st.file_uploader(
        "上传已处理工单（.xlsx / .xls / .csv）",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=False,
    )
    if up is not None:
        try:
            df_src = _read_upload(up)
            src_label = getattr(up, "name", "上传文件")
        except Exception as e:
            st.error(f"读取失败：{e}")
else:
    region = st.selectbox("选择区域", list(REGION_FILES), index=0)
    df_src = _read_region_file(region)
    if df_src is None:
        st.info(
            f"未找到 `{REGION_FILES[region]}`。请先在「工单处理」页处理该区域工单，"
            "或改用「上传已处理工单」。"
        )
    else:
        src_label = REGION_FILES[region]

if df_src is None:
    st.stop()

st.success(f"已读取 **{len(df_src)}** 行（来源：`{src_label}`）")

# ==================== 列校验 ====================
col_bu = _pick_col(df_src, COL_CANDIDATES["bu"])
col_model = _pick_col(df_src, COL_CANDIDATES["model"])
col_fault = _pick_col(df_src, COL_CANDIDATES["fault"])

_missing = []
if col_model is None:
    _missing.append("型号")
if col_fault is None:
    _missing.append("故障类型（一级）")

if _missing:
    st.error(
        f"缺少必要列：{'、'.join(_missing)}。"
        f"当前文件共 {len(df_src.columns)} 列：{'、'.join(map(str, df_src.columns))}"
    )
    st.caption(
        "请上传**已整理好的工单**（主流程输出的标准表），而不是原始工单。"
    )
    st.stop()

if col_bu is None:
    st.warning("文件里没有 BU 列，将按型号前缀自动推断 BU（推断不出的归入「未分类」）。")

# ==================== 参数 ====================
st.divider()
c1, c2 = st.columns(2)
with c1:
    n_models = st.number_input(
        "每个 BU 取故障数前 N 个型号", min_value=1, max_value=50,
        value=DEFAULT_TOP_MODELS, step=1,
    )
with c2:
    n_faults = st.number_input(
        "每个型号列前 N 个故障类型", min_value=1, max_value=10,
        value=DEFAULT_TOP_FAULTS, step=1,
    )

# 类别范围：默认只算 维修（保内）+ DOA
col_cat = _pick_col(df_src, COL_CANDIDATES["cat"])
sel_cats: list[str] | None = None
if col_cat is None:
    st.caption("文件里没有「类别」列，无法按类别筛选，将统计全部工单。")
else:
    _cat_opts = [c for c in dict.fromkeys(
        df_src[col_cat].fillna("").astype(str).str.strip()) if c]
    _default = [c for c in DEFAULT_CATEGORIES if c in _cat_opts] or _cat_opts
    sel_cats = st.multiselect(
        "只统计这些类别",
        _cat_opts,
        default=_default,
        help="默认只算 维修（保内）+ DOA，即排除 保外 / 无异常（NFF）/ 重复 / 二返 / 三返。"
             "清空则统计全部类别。",
    )
    if not sel_cats:
        st.caption("未选择类别 = 统计全部类别。")
        sel_cats = None

# 先把全部 BU 算出来（占比不受 BU 筛选影响），再按用户选择过滤
key_all = build_key_products(
    df_src, top_models=int(n_models), top_faults=int(n_faults),
    bu_col=col_bu or "产品BU", model_col=col_model, fault_col=col_fault,
    category_col=col_cat or "类别", include_categories=sel_cats,
)

if len(key_all) == 0:
    st.warning("没有可统计的数据（型号全为空？）。")
    st.stop()

bu_options = list(dict.fromkeys(key_all["类别"]))
sel_bus = st.multiselect(
    "只看这些 BU（默认全部）", bu_options, default=bu_options,
    help="只影响展示与导出，不影响占比的计算口径",
)
if not sel_bus:
    st.info("至少选择一个 BU。")
    st.stop()

key_df = key_all[key_all["类别"].isin(sel_bus)].reset_index(drop=True)

# ==================== 结果 ====================
_sum = summarize_key_products(key_df)
m1, m2, m3 = st.columns(3)
m1.metric("覆盖 BU", _sum["bus"])
m2.metric("重点型号数", _sum["models"])
m3.metric("这些型号的故障合计", _sum["total"])

if col_cat is not None:
    if sel_cats:
        _mask = df_src[col_cat].fillna("").astype(str).str.strip().isin(sel_cats)
        st.caption(
            f"统计范围：类别 = {' / '.join(sel_cats)}，"
            f"纳入 **{int(_mask.sum())}** / {len(df_src)} 行"
            f"（已排除其余类别）"
        )
    else:
        st.caption(f"统计范围：全部类别，共 {len(df_src)} 行")

_view = key_df.copy()
_view["占比"] = _view["占比"].map(lambda x: f"{x:.0%}")
st.dataframe(_view, width="stretch", height=520)

st.divider()
d1, d2 = st.columns(2)
with d1:
    _b1 = io.BytesIO()
    write_key_sheet_only(key_df, _b1)
    _b1.seek(0)
    st.download_button(
        f"📥 下载排名表（单 sheet，{len(key_df)} 行）",
        data=_b1,
        file_name=f"{KEY_SHEET_NAME}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
with d2:
    _b2 = io.BytesIO()
    write_excel_with_key_sheet(
        df_src[[c for c in df_src.columns]], _b2,
        main_sheet="工单明细", key_df=key_df,
    )
    _b2.seek(0)
    st.download_button(
        f"📥 下载排名 + 工单明细（2 个 sheet，{len(df_src)} 行）",
        data=_b2,
        file_name=f"{KEY_SHEET_NAME}_含明细.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

with st.expander("口径说明"):
    st.markdown(
        f"""
- **统计范围**：默认只算「类别」= **维修（保内）** 和 **DOA**，
  即排除 维修（保外）/ 无异常（NFF）/ 重复 / 二返 / 三返。可在上方多选框调整。
- **占比**：该型号故障数 ÷ **该 BU 全部工单数**（同样只算纳入范围的类别）。
  同一 BU 内各型号占比之和小于 100% 属正常。
- **TOP 里的百分比**：该故障类型 ÷ **该型号自身工单数**，与上面的占比不是同一个分母。
- **未发现故障 / NFF**：计入故障数量，但不参与故障类型排名。
- **型号写法差异**（大小写、多余空格）会自动合并为同一型号。
- **BU 缺失**：按 `config.PRODUCT_BU_MAP` 的前缀表推断，推断不出归入「未分类」。
- 表列固定为：`{" / ".join(KEY_COLUMNS)}`，与参考文件《重点产品故障数量和类型.xlsx》一致。
        """
    )

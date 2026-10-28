# -*- coding: utf-8 -*-
"""统一入口：左侧按分组切换「工单处理」/「视频英文化」。

启动方式：
    streamlit run main.py

（部署到 Streamlit Cloud 时，Main file path 填 main.py）
"""
import sys
from pathlib import Path

import streamlit as st

# 业务模块在 core/ 下，页面脚本也会各自注入；这里统一兜一层，保证 import 一定能找到
_ROOT = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_ROOT / "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

st.set_page_config(
    page_title="工具集 · 工单处理 / 视频英文化",
    page_icon="🧰",
    layout="wide",
)

pages = {
    "工单处理": [
        st.Page("app.py", title="工单处理", icon="🔧", default=True),
        st.Page("key_page.py", title="重点产品故障排名", icon="🏆"),
    ],
    "视频工具": [
        st.Page("video_page.py", title="视频英文化", icon="🎬"),
    ],
}

st.navigation(pages).run()

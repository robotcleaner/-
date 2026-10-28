# -*- coding: utf-8 -*-
"""统一入口：左侧切换「工单处理」/「视频英文化」两个工具。

启动方式：
    streamlit run main.py

（部署到 Streamlit Cloud 时，Main file path 填 main.py）
"""
import streamlit as st

st.set_page_config(
    page_title="工具集 · 工单处理 / 视频英文化",
    page_icon="🧰",
    layout="wide",
)

pages = [
    st.Page("app.py", title="工单处理", icon="🔧", default=True),
    st.Page("video_page.py", title="视频英文化", icon="🎬"),
]

st.navigation(pages).run()

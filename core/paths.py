# -*- coding: utf-8 -*-
"""统一的目录定位：数据文件 / 运行时状态。

目录结构
--------
项目根/
├── core/    业务模块（配置、处理器、缓存、统计）
├── data/    数据与缓存（故障对照表、质保表、参考 Excel）
├── state/   运行时状态（断点续跑结果、LLM 翻译缓存）
└── tools/   调试 / 一次性脚本

所有路径都以本文件位置为基准，不依赖启动时的工作目录，
因此「双击 run.bat」「命令行 streamlit run」「云端部署」都能找到同一份文件。
"""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT_DIR / "core"
DATA_DIR = ROOT_DIR / "data"
STATE_DIR = ROOT_DIR / "state"


def _ensure(p: Path) -> Path:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def data_path(name: str) -> str:
    """data/ 下的文件路径（自动建目录，返回字符串，可直接给 open / pandas 用）。"""
    return str(_ensure(DATA_DIR) / name)


def state_path(name: str) -> str:
    """state/ 下的文件路径（自动建目录）。"""
    return str(_ensure(STATE_DIR) / name)

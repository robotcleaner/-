# -*- coding: utf-8 -*-
"""一键启动器（由 run.bat 调用，也可直接 `python launch.py`）。

做四件事：
1. 检查核心依赖，缺了自动 pip 安装；
2. 若本工具已在 8501 运行，直接打开浏览器，不重复起服务；
3. 自动挑一个空闲端口（默认 8501，最多试到 8510）；
4. 启动 Streamlit，**关掉窗口即停止服务**。

用法：
    python launch.py          # 默认 8501
    python launch.py 8600     # 指定端口
"""
import importlib.util
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 工单工具必需的核心依赖（模块名 → pip 包名）
CORE_DEPS = {
    "streamlit": "streamlit>=1.30.0",
    "pandas": "pandas>=2.0.0",
    "openpyxl": "openpyxl>=3.1.0",
    "dotenv": "python-dotenv>=1.0.0",
    "openai": "openai>=1.30.0",
    "tenacity": "tenacity>=8.2.0",
}

DEFAULT_PORT = 8501
MAX_PORT = 8510


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def ensure_deps() -> bool:
    missing = [m for m in CORE_DEPS if not _has(m)]
    if not missing:
        return True
    print("  缺少依赖：" + ", ".join(CORE_DEPS[m] for m in missing))
    print("  正在自动安装（首次约 1-3 分钟，请耐心等待）...")
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    cmd += [CORE_DEPS[m] for m in missing]
    print("  > " + " ".join(cmd[3:]))
    try:
        rc = subprocess.call(cmd)
    except Exception as exc:                       # noqa: BLE001
        print(f"  安装失败：{exc}")
        return False
    if rc != 0:
        print("  依赖安装失败，请把上面的报错发出来。")
        return False
    bad = [m for m in CORE_DEPS if not _has(m)]
    if bad:
        print("  安装后仍缺少：" + ", ".join(bad))
        return False
    print("  依赖安装完成。")
    return True


def port_free(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


def streamlit_here(port: int) -> bool:
    """该端口上是否是 Streamlit 服务（健康检查返回 ok）。"""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/_stcore/health", timeout=1.0
        ) as r:
            return r.read().strip().lower() == b"ok"
    except Exception:
        return False


def pick_port(start: int) -> int:
    for p in range(start, MAX_PORT + 1):
        if port_free(p):
            return p
    return start


def open_browser(url: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(url)                      # noqa: S606  用默认浏览器打开
        else:
            import webbrowser
            webbrowser.open(url)
    except Exception:
        pass


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    print()
    print("  " + "=" * 58)
    print("    工具集：工单处理 / 重点产品故障排名 / 视频英文化")
    print("  " + "=" * 58)
    print()

    if not ensure_deps():
        return 1

    req_port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            req_port = int(sys.argv[1])
        except ValueError:
            pass

    # 已经开着了：直接打开浏览器，不重复起服务
    if not port_free(DEFAULT_PORT) and streamlit_here(DEFAULT_PORT):
        url = f"http://127.0.0.1:{DEFAULT_PORT}"
        print(f"  检测到工具已在运行，正在打开浏览器：{url}")
        open_browser(url)
        time.sleep(1.5)
        return 0

    port = pick_port(req_port)
    if port != req_port:
        print(f"  端口 {req_port} 被其他程序占用，改用 {port}")
    url = f"http://127.0.0.1:{port}"

    print(f"  启动中... 浏览器会自动打开：{url}")
    print("  关闭这个窗口 = 停止服务（已下载的文件不受影响）")
    print()

    os.chdir(ROOT)
    try:
        from streamlit.web import cli as stcli
    except Exception as exc:                       # noqa: BLE001
        print(f"  无法加载 Streamlit：{exc}")
        return 1

    sys.argv = [
        "streamlit", "run", str(ROOT / "main.py"),
        "--server.port", str(port),
        "--browser.gatherUsageStats", "false",
    ]
    try:
        stcli.main()
    except KeyboardInterrupt:
        pass
    print()
    print("  服务已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

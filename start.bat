@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Toolbox: Ticket Processor + Video Localizer
echo  Entry: main.py  (left nav switches tools)
echo ============================================
echo.

python -m streamlit run main.py --server.port 8501

echo.
echo Server stopped. Press any key to close.
pause >nul

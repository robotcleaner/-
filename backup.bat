@echo off
rem ============================================================
rem  Double-click to back up runtime data (state/ + data/ caches).
rem  Those files are NOT tracked by git, so this zip is the only copy.
rem  Keep this file ASCII-only; Chinese output comes from tools\backup.py
rem ============================================================
cd /d "%~dp0"
title Backup - Ticket Toolbox

set "PY="

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    for %%P in ("C:\Python313\python.exe" "C:\Python312\python.exe" "C:\Python311\python.exe" "C:\Python310\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe") do (
        if not defined PY if exist %%P set "PY=%%~P"
    )
)

if not defined PY (
    echo.
    echo   [!] Python not found. Install Python 3.10+ first.
    echo.
    pause
    exit /b 1
)

%PY% "%~dp0tools\backup.py" %*
if errorlevel 1 pause
echo.
echo   Press any key to close.
pause >nul

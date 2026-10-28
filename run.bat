@echo off
rem ============================================================
rem  Double-click this file to start the toolbox.
rem  No Python / command line knowledge needed.
rem  Close the black window to stop the server.
rem  NOTE: keep this file ASCII-only (Chinese text is printed
rem        by launch.py, which handles encoding correctly).
rem ============================================================
cd /d "%~dp0"
title Toolbox - Ticket / Video

set "PY="

rem 1) Windows py launcher
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)

rem 2) python from PATH
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

rem 3) common install locations
if not defined PY (
    for %%P in ("C:\Python313\python.exe" "C:\Python312\python.exe" "C:\Python311\python.exe" "C:\Python310\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe") do (
        if not defined PY if exist %%P set "PY=%%~P"
    )
)

if not defined PY (
    echo.
    echo   [!] Python not found.
    echo       Install Python 3.10+ from https://www.python.org/downloads/
    echo       During setup, check "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

%PY% "%~dp0launch.py" %*
if errorlevel 1 pause

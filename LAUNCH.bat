@echo off
title APEX v10 ULTRA - Launcher
color 0B & cls
echo.
echo  ================================================================
echo    TELEGRAM APEX v10 ULTRA - Launcher
echo  ================================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause & exit /b 1
)
for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PYVER=%%V
echo [INFO] Using Python %PYVER%
echo.

:: ── Check which packages are already installed ────────────────────────
echo [INFO] Checking installed packages...
set MISSING=

python -c "import telethon" >nul 2>&1
if errorlevel 1 set MISSING=%MISSING% telethon

python -c "import PIL" >nul 2>&1
if errorlevel 1 set MISSING=%MISSING% pillow

python -c "import cryptg" >nul 2>&1
if errorlevel 1 set MISSING=%MISSING% cryptg

python -c "import pyaes" >nul 2>&1
if errorlevel 1 set MISSING=%MISSING% pyaes

python -c "import rsa" >nul 2>&1
if errorlevel 1 set MISSING=%MISSING% rsa

python -c "import flask" >nul 2>&1
if errorlevel 1 set MISSING=%MISSING% flask

python -c "import webview" >nul 2>&1
if errorlevel 1 set MISSING=%MISSING% pywebview

:: ── Only install what is missing ──────────────────────────────────────
if "%MISSING%"=="" (
    echo [OK] All packages already installed - skipping install.
) else (
    echo [INFO] Installing missing packages:%MISSING%
    python -m pip install --upgrade pip --quiet
    python -m pip install %MISSING% --quiet
    if errorlevel 1 (
        echo [WARN] Some packages failed to install. Trying anyway...
    ) else (
        echo [OK] Missing packages installed.
    )
)

echo.
echo [INFO] Starting APEX v10...
echo [INFO] A browser window will open automatically.
echo [INFO] Press Ctrl+C to stop.
echo.

python TelegramAPEX_v9.py

if errorlevel 1 (
    echo.
    echo [ERROR] APEX exited with an error. Check the output above.
    pause
)

@echo off
title APEX v10 ULTRA - EXE Builder
color 0B & cls
echo.
echo  ================================================================
echo    TELEGRAM APEX v10 ULTRA - Building Standalone EXE
echo  ================================================================
echo.

:: ── Always run from the BAT file's own folder ─────────────────────────
cd /d "%~dp0"

set LOGFILE=%~dp0build_log.txt
echo Build started: %DATE% %TIME% > "%LOGFILE%"
echo WorkDir: %CD% >> "%LOGFILE%"

:: ── Block System32 ────────────────────────────────────────────────────
echo %CD% | findstr /i "System32" >nul
if not errorlevel 1 (
    echo [ERROR] Do not run from System32. Double-click the BAT from your project folder.
    pause & exit /b 1
)

:: ── Block Administrator ───────────────────────────────────────────────
net session >nul 2>&1
if not errorlevel 1 (
    echo [ERROR] Do NOT run as Administrator. Just double-click BUILD_EXE.bat normally.
    pause & exit /b 1
)

:: ── Check Python ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 ( echo [ERROR] Python not found. & pause & exit /b 1 )
for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PYVER=%%V
echo [INFO] Python %PYVER%
echo Python: %PYVER% >> "%LOGFILE%"
echo.

:: ── CLEAN all cached build artifacts to prevent stale spec errors ──────
echo [CLEAN] Removing old build cache...
if exist build       rmdir /s /q build
if exist dist        rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
if exist TelegramAPEX_v10.spec del /q TelegramAPEX_v10.spec
if exist hook_apex.py del /q hook_apex.py
echo [CLEAN] Done.
echo.

python -m pip install --upgrade pip --quiet 2>>"%LOGFILE%"

:: ── Check / install packages ──────────────────────────────────────────
echo [1/4] Checking packages...
python -c "import telethon" >nul 2>&1
if errorlevel 1 ( echo [INFO] Installing telethon... & python -m pip install telethon --quiet 2>>"%LOGFILE%" ) else ( echo [OK] telethon )

python -c "import PIL" >nul 2>&1
if errorlevel 1 ( echo [INFO] Installing pillow... & python -m pip install pillow --quiet 2>>"%LOGFILE%" ) else ( echo [OK] pillow )

python -c "import cryptg" >nul 2>&1
if errorlevel 1 ( echo [INFO] Installing cryptg... & python -m pip install cryptg --quiet 2>>"%LOGFILE%" ) else ( echo [OK] cryptg )

python -c "import pyaes" >nul 2>&1
if errorlevel 1 ( echo [INFO] Installing pyaes... & python -m pip install pyaes --quiet 2>>"%LOGFILE%" ) else ( echo [OK] pyaes )

python -c "import rsa" >nul 2>&1
if errorlevel 1 ( echo [INFO] Installing rsa... & python -m pip install rsa --quiet 2>>"%LOGFILE%" ) else ( echo [OK] rsa )

python -c "import flask" >nul 2>&1
if errorlevel 1 ( echo [INFO] Installing flask... & python -m pip install flask --quiet 2>>"%LOGFILE%" ) else ( echo [OK] flask )

python -c "import webview" >nul 2>&1
if errorlevel 1 ( echo [INFO] Installing pywebview... & python -m pip install pywebview --quiet 2>>"%LOGFILE%" ) else ( echo [OK] pywebview )

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller pre-release...
    python -m pip install pyinstaller --pre --quiet 2>>"%LOGFILE%"
) else ( echo [OK] PyInstaller )
echo.

echo [2/4] Verifying...
python -c "import telethon,PIL,cryptg,pyaes,rsa,flask,PyInstaller; print('  All packages OK')"
if errorlevel 1 ( echo [ERROR] Verification failed. Check build_log.txt & pause & exit /b 1 )
echo.

:: ── Locate Python DLL ─────────────────────────────────────────────────
for /f "usebackq delims=" %%D in (`python -c "import sys,os,glob; dlls=glob.glob(os.path.join(os.path.dirname(sys.executable),'python3*.dll')); print(dlls[0] if dlls else '')" 2^>nul`) do set PYDLL=%%D
if not "%PYDLL%"=="" ( set DLL_FLAG=--add-binary "%PYDLL%;." ) else ( set DLL_FLAG= )

:: ── Write runtime hook ────────────────────────────────────────────────
echo import sys > hook_apex.py
echo if getattr(sys,"frozen",False): pass >> hook_apex.py

:: ── Build ─────────────────────────────────────────────────────────────
echo [3/4] Compiling EXE - please wait 3-5 minutes...
echo       Do NOT close this window.
echo.

python -m PyInstaller TelegramAPEX_v9.py ^
  --onefile ^
  --console ^
  --name TelegramAPEX_v10 ^
  --noconfirm ^
  --runtime-hook hook_apex.py ^
  --collect-all telethon ^
  --collect-all flask ^
  --collect-all werkzeug ^
  --collect-all jinja2 ^
  --collect-all click ^
  --hidden-import telethon ^
  --hidden-import telethon.sessions ^
  --hidden-import telethon.sessions.sqlite ^
  --hidden-import telethon.network ^
  --hidden-import telethon.network.mtprotosender ^
  --hidden-import telethon.network.connection ^
  --hidden-import telethon.network.connection.tcpfull ^
  --hidden-import telethon.network.connection.tcpabridged ^
  --hidden-import telethon.network.connection.tcpintermediate ^
  --hidden-import telethon.crypto ^
  --hidden-import telethon.crypto.aes ^
  --hidden-import telethon.tl ^
  --hidden-import telethon.tl.types ^
  --hidden-import telethon.tl.functions ^
  --hidden-import telethon.errors ^
  --hidden-import telethon.errors.rpcerrorlist ^
  --hidden-import telethon.extensions ^
  --hidden-import PIL ^
  --hidden-import PIL.Image ^
  --hidden-import PIL.ImageDraw ^
  --hidden-import cryptg ^
  --hidden-import pyaes ^
  --hidden-import rsa ^
  --hidden-import flask ^
  --hidden-import flask.json ^
  --hidden-import werkzeug ^
  --hidden-import werkzeug.serving ^
  --hidden-import werkzeug.routing ^
  --hidden-import werkzeug.exceptions ^
  --hidden-import jinja2 ^
  --hidden-import click ^
  --hidden-import sqlite3 ^
  --hidden-import _sqlite3 ^
  --hidden-import asyncio ^
  --hidden-import asyncio.selector_events ^
  --hidden-import asyncio.proactor_events ^
  --hidden-import asyncio.windows_events ^
  --hidden-import asyncio.windows_utils ^
  --hidden-import concurrent.futures ^
  --hidden-import concurrent.futures.thread ^
  --hidden-import webbrowser ^
  --hidden-import hashlib ^
  --hidden-import json ^
  --hidden-import logging ^
  --hidden-import ssl ^
  --hidden-import _ssl ^
  --hidden-import certifi ^
  --hidden-import urllib3 ^
  --hidden-import importlib ^
  --hidden-import importlib.util ^
  --hidden-import collections ^
  --hidden-import collections.abc ^
  --hidden-import tempfile ^
  --hidden-import threading ^
  --hidden-import mimetypes ^
  --hidden-import socket ^
  --exclude-module matplotlib ^
  --exclude-module numpy ^
  --exclude-module scipy ^
  --exclude-module pandas ^
  --exclude-module PyQt5 ^
  --exclude-module PySide2 ^
  --exclude-module wx ^
  --exclude-module tkinter ^
  --exclude-module test ^
  --exclude-module unittest ^
  %DLL_FLAG% >> "%LOGFILE%" 2>&1

if exist hook_apex.py del hook_apex.py

:: ── Result ────────────────────────────────────────────────────────────
echo [4/4] Checking result...
if exist dist\TelegramAPEX_v10.exe (
    copy dist\TelegramAPEX_v10.exe .\TelegramAPEX_v10.exe >nul
    echo Build SUCCESS >> "%LOGFILE%"
    echo.
    echo  ================================================================
    echo    SUCCESS! TelegramAPEX_v10.exe is ready in this folder.
    echo    - No Python needed on other machines
    echo    - Session saved next to EXE, no re-login needed
    echo  ================================================================
) else (
    echo Build FAILED >> "%LOGFILE%"
    echo.
    echo  ================================================================
    echo    BUILD FAILED - open build_log.txt for the exact error
    echo  ================================================================
)
echo.
echo Full log: %LOGFILE%
echo.
pause

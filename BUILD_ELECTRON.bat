@echo off
title APEX v10 ULTRA - Electron Installer Builder
color 0B & cls
echo.
echo  ================================================================
echo    TELEGRAM APEX v10 ULTRA - Building Electron Desktop Installer
echo  ================================================================
echo.

cd /d "%~dp0"

:: ── Block Administrator ───────────────────────────────────────────────
net session >nul 2>&1
if not errorlevel 1 (
    echo [ERROR] Do NOT run as Administrator. Just double-click this file normally.
    pause & exit /b 1
)

:: ── Check Python ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 ( echo [ERROR] Python not found. Install from https://python.org & pause & exit /b 1 )

:: ── Check Node.js ─────────────────────────────────────────────────────
node --version >nul 2>&1
if errorlevel 1 ( echo [ERROR] Node.js not found. Install from https://nodejs.org & pause & exit /b 1 )

echo [1/5] Installing Python dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install telethon pillow cryptg pyaes rsa flask pyinstaller --quiet
echo.

echo [2/5] Cleaning old build artifacts...
if exist build              rmdir /s /q build
if exist dist               rmdir /s /q dist
if exist TelegramAPEX_v10.spec del /q TelegramAPEX_v10.spec
if exist electron\backend   rmdir /s /q electron\backend
if exist electron\release   rmdir /s /q electron\release
echo.

echo [3/5] Building backend EXE with PyInstaller (this takes a few minutes)...
python -m PyInstaller TelegramAPEX_v9.py ^
  --onefile --console --name TelegramAPEX_v10 --noconfirm ^
  --collect-all telethon --collect-all flask ^
  --collect-all werkzeug --collect-all jinja2 --collect-all click ^
  --hidden-import telethon --hidden-import telethon.sessions ^
  --hidden-import telethon.sessions.sqlite --hidden-import telethon.network ^
  --hidden-import telethon.network.mtprotosender --hidden-import telethon.crypto ^
  --hidden-import telethon.crypto.aes --hidden-import telethon.tl ^
  --hidden-import telethon.tl.types --hidden-import telethon.tl.functions ^
  --hidden-import telethon.errors --hidden-import telethon.errors.rpcerrorlist ^
  --hidden-import telethon.extensions --hidden-import PIL --hidden-import PIL.Image ^
  --hidden-import cryptg --hidden-import pyaes --hidden-import rsa ^
  --hidden-import flask --hidden-import werkzeug --hidden-import jinja2 ^
  --hidden-import click --hidden-import sqlite3 --hidden-import _sqlite3 ^
  --hidden-import asyncio --hidden-import ssl --hidden-import certifi ^
  --hidden-import urllib3 --hidden-import threading --hidden-import socket ^
  --exclude-module matplotlib --exclude-module numpy --exclude-module pandas ^
  --exclude-module PyQt5 --exclude-module tkinter --exclude-module test

if not exist dist\TelegramAPEX_v10.exe (
    echo.
    echo [ERROR] Backend build failed - see the PyInstaller output above.
    pause & exit /b 1
)
echo.

echo [4/5] Staging backend into electron\backend...
mkdir electron\backend
copy dist\TelegramAPEX_v10.exe electron\backend\TelegramAPEX_v10.exe >nul
echo.

echo [5/5] Building Windows installer with Electron (first run downloads Electron, ~5 min)...
cd electron
call npm install
call npm run dist
cd ..
echo.

if exist electron\release (
    echo  ================================================================
    echo    SUCCESS! Your installer is in electron\release\
    echo    Look for "Telegram APEX Setup *.exe" - that's what you run
    echo    to install the app (no Python required on the target machine,
    echo    and no console window will show).
    echo  ================================================================
) else (
    echo  ================================================================
    echo    BUILD FAILED - check the output above for the exact error
    echo  ================================================================
)
echo.
pause

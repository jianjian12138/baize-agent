@echo off
title Baize Agent Studio - 白泽智能桌面工作台
cd /d "%~dp0\.."
echo ===================================================
echo   Baize Agent Studio - 白泽智能桌面工作台 (V33.0.0)
echo   正在唤起沉浸式桌面客户端...
echo ===================================================
python -m baize desktop
pause

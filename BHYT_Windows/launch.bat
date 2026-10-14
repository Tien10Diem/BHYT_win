@echo off
chcp 65001 > nul
title Tra Cuu BHYT - Windows
echo Dang khoi dong ung dung Tra cuu BHYT...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python! Vui long cai dat Python 3.10 tro len va them vao PATH.
    pause
    exit /b 1
)

cd /d "%~dp0"
python launcher.py
if %errorlevel% neq 0 (
    echo.
    echo [THONG BAO] Ung dung da dung hoac gap loi.
    pause
)

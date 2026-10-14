@echo off
chcp 65001 > nul
title Cai dat thu vien BHYT
echo Dang cai dat cac thu vien can thiet (streamlit, selenium, openpyxl)...
python -m pip install --upgrade pip
python -m pip install -r "%~dp0app\requirements.txt"
if %errorlevel% equ 0 (
    echo.
    echo [THANH CONG] Da cai dat xong cac thu vien!
) else (
    echo.
    echo [LOI] Cai dat that bai. Vui long kiem tra ket noi Internet hoac Python.
)
pause

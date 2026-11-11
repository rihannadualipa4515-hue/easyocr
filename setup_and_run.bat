@echo off
setlocal
cd /d "%~dp0"
title OCR Text Finder - setup

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv || python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python 3.11+ was not found. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^)
        pause & exit /b 1
    )
)
call ".venv\Scripts\activate.bat"

if not exist ".venv\.deps_installed" (
    echo Installing dependencies ^(first run only, needs internet, several minutes^)...
    python -m pip install --upgrade pip
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu || goto :fail
    pip install -r requirements.txt || goto :fail
    echo ok> ".venv\.deps_installed"
)
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:fail
echo.
echo Installation failed. Check your internet connection and run this file again.
pause
exit /b 1

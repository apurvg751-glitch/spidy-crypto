@echo off
title SPIDY CRYPTO - First Time Setup
echo ============================================================
echo   SPIDY CRYPTO - NEW PC FIRST TIME SETUP
echo ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% equ 0 (
    set PY_CMD=python
) else (
    if exist "C:\Users\admin\python311\python.exe" (
        set PY_CMD="C:\Users\admin\python311\python.exe"
    ) else (
        echo [ERROR] Python not detected!
        echo 1. Download Python 3.11 from https://www.python.org/downloads/
        echo 2. Check "Add Python to PATH" during installation.
        pause
        exit /b 1
    )
)

echo.
echo Step 1: Installing required Python packages...
%PY_CMD% -m pip install --upgrade pip
%PY_CMD% -m pip install -r requirements.txt

echo.
echo Step 2: Testing Telegram alerts...
%PY_CMD% test_telegram.py

echo.
echo ============================================================
echo   SETUP COMPLETE!
echo   You can now launch SPIDY CRYPTO anytime by double-clicking:
echo   run_spidy.bat
echo ============================================================
pause

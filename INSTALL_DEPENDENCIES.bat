@echo off
title INSTALL SPIDY CRYPTO DEPENDENCIES
cd /d "%~dp0"

echo ================================================================
echo    INSTALLING SPIDY CRYPTO REQUIRED LIBRARIES
echo ================================================================
echo.

python -m pip install --upgrade pip
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    py -m pip install --upgrade pip
    py -m pip install -r requirements.txt
)

echo.
echo ================================================================
echo    INSTALLATION COMPLETE! YOU CAN NOW RUN 'START_SPIDY.bat'
echo ================================================================
pause

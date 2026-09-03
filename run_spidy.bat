@echo off
title SPIDY CRYPTO - AUTONOMOUS TRADING ENGINE
cd /d "C:\Users\admin\.gemini\antigravity\scratch\spidy_crypto"

echo ================================================================
echo    SPIDY CRYPTO 2.0 - AUTONOMOUS TRADING ENGINE (PORT 8800)
echo ================================================================
echo Directory: C:\Users\admin\.gemini\antigravity\scratch\spidy_crypto
echo Python:    C:\Users\admin\python311\python.exe
echo.

:: Clear any zombie process on port 8800
for /f "tokens=5" %%p in ('netstat -aon ^| findstr :8800 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%p >nul 2>nul
)

:: Open browser
echo [DASHBOARD] Opening http://localhost:8800 in your browser...
start http://localhost:8800

:: Launch Core Engine
echo [ENGINE] Starting SPIDY Crypto Engine...
echo.
"C:\Users\admin\python311\python.exe" main.py

echo.
echo ================================================================
echo SPIDY CRYPTO has stopped.
echo ================================================================
pause

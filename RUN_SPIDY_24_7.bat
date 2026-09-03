@echo off
title SPIDY CRYPTO - 24/7 AUTONOMOUS GUARDIAN
cd /d "C:\Users\admin\.gemini\antigravity\scratch\spidy_crypto"

echo ================================================================
echo    SPIDY CRYPTO - 24/7 PERMANENT RUNTIME ENGINE (PORT 8800)
echo ================================================================
echo Directory: C:\Users\admin\.gemini\antigravity\scratch\spidy_crypto
echo Python:    C:\Users\admin\python311\python.exe
echo Mode:      Continuous 24/7 Watchdog (Auto-Restarts on Exit)
echo ================================================================
echo.

:: 1. Disable Windows Sleep while plugged in
powercfg /change standby-timeout-ac 0 >nul 2>nul
powercfg /change hibernate-timeout-ac 0 >nul 2>nul

:: 2. Open dashboard in Chrome browser
echo [DASHBOARD] Opening http://localhost:8800 in your browser...
start http://localhost:8800

:WATCHDOG_LOOP
:: 3. Clean port 8800
for /f "tokens=5" %%p in ('netstat -aon ^| findstr :8800 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%p >nul 2>nul
)

echo [%date% %time%] [WATCHDOG] Launching SPIDY CRYPTO Engine...
"C:\Users\admin\python311\python.exe" main.py

echo.
echo [%date% %time%] [ALERT] SPIDY stopped or disconnected!
echo [WATCHDOG] Auto-Reviving SPIDY CRYPTO in 3 seconds...
timeout /t 3 /nobreak >nul
goto WATCHDOG_LOOP

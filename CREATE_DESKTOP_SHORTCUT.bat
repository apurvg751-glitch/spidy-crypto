@echo off
title CREATE SPIDY CRYPTO DESKTOP SHORTCUT
cd /d "%~dp0"

echo ================================================================
echo    CREATING SPIDY CRYPTO SHORTCUT ON YOUR DESKTOP
echo ================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "^
$ws = New-Object -ComObject WScript.Shell; ^
$desktop = [System.Environment]::GetFolderPath('Desktop'); ^
$s = $ws.CreateShortcut("$desktop\SPIDY CRYPTO.lnk"); ^
$s.TargetPath = '%~dp0run_spidy.bat'; ^
$s.WorkingDirectory = '%~dp0'; ^
$s.Description = 'SPIDY CRYPTO 2.0 Autonomous Trading Assistant'; ^
$s.Save(); ^
Write-Host '[OK] Shortcut created successfully on your Desktop!' -ForegroundColor Green"

echo.
echo ================================================================
echo    SPIDY CRYPTO SHORTCUT IS NOW ON YOUR DESKTOP!
echo ================================================================
pause

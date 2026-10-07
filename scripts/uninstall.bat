@echo off
setlocal
echo === Codex Auto Confirm - Uninstall ===
echo.

echo [1/3] Disabling autostart registry entry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v CodexAutoConfirm /f >nul 2>&1
if errorlevel 1 (
    echo     (not set, nothing to remove)
) else (
    echo     OK - removed
)

echo.
echo [2/3] Stopping running instances...
taskkill /IM codex-auto-confirm.exe /F >nul 2>&1
if errorlevel 1 (
    echo     (not running)
) else (
    echo     OK - terminated
)

echo.
echo [3/3] Cleanup checklist:
echo     - Delete the EXE / folder you downloaded (this script does NOT delete it)
echo     - Logs are at: %%APPDATA%%\codex-auto-confirm\watchdog.log
echo       Delete that folder if you want a full clean uninstall.
echo.
echo Done. You can close this window.
pause

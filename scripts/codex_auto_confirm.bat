@echo off
setlocal
rem Portable launcher for codex_auto_confirm.py.
rem Override CODEX_AUTO_CONFIRM_PYTHON_EXE to pin a specific interpreter;
rem otherwise it falls back to the "python" on PATH.
rem On non-zero exit it restarts the monitor after a short delay, so a crash
rem never leaves Codex unattended.

set "SCRIPT_DIR=%~dp0"
if not defined CODEX_AUTO_CONFIRM_PYTHON_EXE set "CODEX_AUTO_CONFIRM_PYTHON_EXE=python"
if not defined CODEX_AUTO_CONFIRM_SCRIPT set "CODEX_AUTO_CONFIRM_SCRIPT=%SCRIPT_DIR%codex_auto_confirm.py"
if not defined CODEX_AUTO_CONFIRM_RESTART_DELAY set "CODEX_AUTO_CONFIRM_RESTART_DELAY=2"

:restart
"%CODEX_AUTO_CONFIRM_PYTHON_EXE%" "%CODEX_AUTO_CONFIRM_SCRIPT%"
set "exit_code=%errorlevel%"
if "%exit_code%"=="0" exit /b 0
echo [codex-auto-confirm] exited with code %exit_code%. Restarting in %CODEX_AUTO_CONFIRM_RESTART_DELAY%s...
powershell.exe -NoLogo -NoProfile -NonInteractive -Command "$delay = 2; $configuredDelay = 0; if ([int]::TryParse($env:CODEX_AUTO_CONFIRM_RESTART_DELAY, [ref]$configuredDelay) -and $configuredDelay -ge 0) { $delay = $configuredDelay }; Start-Sleep -Seconds $delay"
goto restart

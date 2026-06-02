@echo off
REM UltraCode-Shim launcher for Windows (parity with bin/ultracode on POSIX).
REM Resolves the repo from this file's location and runs the PowerShell launcher,
REM so `ultracode` works the same from a clone or a shim on your PATH.
setlocal
set "REPO=%~dp0.."
set "PS=powershell"
where pwsh >nul 2>nul && set "PS=pwsh"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%REPO%\windows\Start-UltraCode.ps1" %*
exit /b %ERRORLEVEL%

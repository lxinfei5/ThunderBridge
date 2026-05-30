@echo off
setlocal
title Claude MiMo UltraCode
wsl.exe -d Ubuntu --cd %USERPROFILE%\repos --exec bash -lc "claude-mimo-ultracode; ec=$?; echo; echo Claude MiMo UltraCode exited with code $ec.; echo Press Enter to close.; read -r _; exit $ec"
if errorlevel 1 pause

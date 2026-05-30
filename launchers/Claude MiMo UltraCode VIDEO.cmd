@echo off
setlocal
title MiMo v2.5 Pro UltraCode
wsl.exe -d Ubuntu --cd %USERPROFILE%\repos --exec bash -lc "exec claude-mimo-ultracode-video"
if errorlevel 1 pause

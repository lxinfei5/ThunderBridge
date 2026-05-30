@echo off
setlocal
title Composer 2.5 Fast UltraCode
wsl.exe -d Ubuntu --cd %USERPROFILE%\repos --exec bash -lc "exec claude-composer-ultracode-video"
if errorlevel 1 pause

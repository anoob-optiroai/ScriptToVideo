@echo off
title ScriptToVideo - Stop
echo Stopping ScriptToVideo...
taskkill /fi "WindowTitle eq ScriptToVideo Backend*" /f >nul 2>&1
taskkill /fi "WindowTitle eq ScriptToVideo Frontend*" /f >nul 2>&1
echo Done. All ScriptToVideo processes stopped.
pause

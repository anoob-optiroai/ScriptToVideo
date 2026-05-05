@echo off
setlocal EnableDelayedExpansion
title ScriptToVideo — Update UI (Frontend Only)

echo ============================================================
echo   ScriptToVideo — Fast UI Update  (React frontend only)
echo   Use this after changing anything in frontend\src\
echo ============================================================
echo.

:: ── Install location ──────────────────────────────────────────────────────────
set INSTALL_DIR=%LOCALAPPDATA%\Programs\ScriptToVideo
set FRONTEND_DST=%INSTALL_DIR%\resources\backend\_internal\frontend_dist

if not exist "%INSTALL_DIR%\ScriptToVideo.exe" (
    echo [ERROR] ScriptToVideo is not installed at:
    echo         %INSTALL_DIR%
    echo         Please run the installer first.
    pause & exit /b 1
)

:: ── 1. Rebuild React frontend ─────────────────────────────────────────────────
echo [1/2] Building React frontend...
cd /d "%~dp0frontend"
call npm run build >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm run build failed. Run manually to see errors:
    echo         cd frontend ^& npm run build
    pause & exit /b 1
)
echo [OK] Frontend built.
echo.

:: ── 2. Close the running app (if open) ───────────────────────────────────────
echo [2/2] Updating installed app...
taskkill /f /im ScriptToVideo.exe >nul 2>&1
ping 127.0.0.1 -n 2 >nul

:: Copy new frontend dist over the installed one
xcopy /e /y /q "%~dp0frontend\dist\*" "%FRONTEND_DST%\" >nul
if errorlevel 1 (
    echo [ERROR] Could not copy files to install directory.
    echo         Try running as Administrator.
    pause & exit /b 1
)
echo [OK] Installed frontend updated.
echo.

:: ── 3. Relaunch the app ───────────────────────────────────────────────────────
echo Launching ScriptToVideo...
start "" "%INSTALL_DIR%\ScriptToVideo.exe"

echo.
echo ============================================================
echo   UI Update complete! App is restarting.
echo ============================================================
echo.
timeout /t 3 /nobreak >nul

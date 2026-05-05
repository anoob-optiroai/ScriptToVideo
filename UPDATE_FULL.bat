@echo off
setlocal EnableDelayedExpansion
title ScriptToVideo — Full Update (Frontend + Backend)

echo ============================================================
echo   ScriptToVideo — Full Update
echo   Use this after changing backend Python files (routers\*.py)
echo   or after changing frontend\src\ files.
echo ============================================================
echo.

:: ── Install location ──────────────────────────────────────────────────────────
set INSTALL_DIR=%LOCALAPPDATA%\Programs\ScriptToVideo
set BACKEND_DST=%INSTALL_DIR%\resources\backend
set FRONTEND_DST=%BACKEND_DST%\_internal\frontend_dist

if not exist "%INSTALL_DIR%\ScriptToVideo.exe" (
    echo [ERROR] ScriptToVideo is not installed at:
    echo         %INSTALL_DIR%
    echo         Please run the installer first.
    pause & exit /b 1
)

:: ── Find Python 3.10–3.12 ────────────────────────────────────────────────────
set PYTHON_EXE=
for %%V in (3.12 3.11 3.10) do (
    if "!PYTHON_EXE!"=="" (
        py -%%V --version >nul 2>&1
        if not errorlevel 1 set PYTHON_EXE=py -%%V
    )
)
if "!PYTHON_EXE!"=="" (
    echo [ERROR] Python 3.10/3.11/3.12 not found.
    pause & exit /b 1
)

:: ── 1. Build React frontend ───────────────────────────────────────────────────
echo [1/3] Building React frontend...
cd /d "%~dp0frontend"
call npm run build >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm run build failed. Run: cd frontend ^& npm run build
    pause & exit /b 1
)
echo [OK] Frontend built.
echo.

:: ── 2. Build Python backend (PyInstaller) ────────────────────────────────────
echo [2/3] Building Python backend (this takes 2-5 minutes)...
cd /d "%~dp0backend"
!PYTHON_EXE! -m pip install -r requirements.txt -q >nul 2>&1
!PYTHON_EXE! -m pip install pyinstaller -q >nul 2>&1
!PYTHON_EXE! -m PyInstaller scriptovideo.spec --noconfirm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    pause & exit /b 1
)
echo [OK] Backend built.
echo.

:: ── 3. Close app and copy new files ─────────────────────────────────────────
echo [3/3] Installing update...
taskkill /f /im ScriptToVideo.exe >nul 2>&1
ping 127.0.0.1 -n 3 >nul

:: Copy backend (exe + _internal folder)
xcopy /e /y /q "%~dp0backend\dist\scriptovideo-backend\*" "%BACKEND_DST%\" >nul
if errorlevel 1 (
    echo [ERROR] Could not copy backend files. Try running as Administrator.
    pause & exit /b 1
)
echo [OK] Backend updated.
echo [OK] Frontend updated (bundled inside backend).
echo.

:: ── 4. Relaunch ──────────────────────────────────────────────────────────────
echo Launching ScriptToVideo...
start "" "%INSTALL_DIR%\ScriptToVideo.exe"

echo.
echo ============================================================
echo   Full Update complete! App is restarting.
echo ============================================================
echo.
timeout /t 3 /nobreak >nul

@echo off
setlocal EnableDelayedExpansion
title ScriptToVideo — Windows Build

echo ============================================================
echo   ScriptToVideo — Windows Installer Build
echo ============================================================
echo.

:: ── GitHub Token (required to publish releases with auto-update) ──────────────
::
::  To PUBLISH a release to GitHub (so users can auto-update), set GH_TOKEN:
::    set GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
::  and then run:
::    build_windows.bat --publish
::
::  To build WITHOUT publishing (local installer only), just run:
::    build_windows.bat
::
::  Create your token at: https://github.com/settings/tokens
::  Required scope: "repo" (for private repos) or "public_repo" (for public repos)
::
set PUBLISH_FLAG=never
if "%1"=="--publish" (
    if "%GH_TOKEN%"=="" (
        echo [ERROR] GH_TOKEN environment variable is not set.
        echo         Set it with: set GH_TOKEN=ghp_your_token_here
        exit /b 1
    )
    set PUBLISH_FLAG=always
    echo [OK] GH_TOKEN found. Will publish release to GitHub.
) else (
    echo [INFO] Building local installer only. Use --publish to upload to GitHub.
)
echo.

:: ── 0. Check prerequisites ────────────────────────────────────────────────────
where node  >nul 2>&1 || (echo [ERROR] Node.js not found. Install from https://nodejs.org && exit /b 1)
where npm   >nul 2>&1 || (echo [ERROR] npm not found. & exit /b 1)

:: ── Find a compatible Python (3.10, 3.11, or 3.12 — NOT 3.13/3.14) ───────────
set PYTHON_EXE=
set PIP_EXE=

for %%V in (3.12 3.11 3.10) do (
    if "!PYTHON_EXE!"=="" (
        py -%%V --version >nul 2>&1
        if not errorlevel 1 (
            set PYTHON_EXE=py -%%V
            set PIP_EXE=py -%%V -m pip
            echo [OK] Found Python %%V
        )
    )
)

if "!PYTHON_EXE!"=="" (
    echo.
    echo [ERROR] Python 3.10, 3.11, or 3.12 not found.
    echo.
    echo  Your Python version is too new ^(3.13+ is not yet supported by
    echo  some dependencies like Pillow^).
    echo.
    echo  Please install Python 3.12 from:
    echo    https://www.python.org/downloads/release/python-3128/
    echo  ^(Pick "Windows installer 64-bit"^)
    echo.
    exit /b 1
)

echo [OK] Prerequisites found.
echo.

:: ── 1. Build React frontend ───────────────────────────────────────────────────
echo [1/4] Building React frontend...
cd /d "%~dp0frontend"
call npm install        || (echo [ERROR] npm install failed && exit /b 1)
call npm run build      || (echo [ERROR] npm run build failed && exit /b 1)
echo [OK] Frontend built → frontend/dist
echo.

:: ── 2. Install Python dependencies and build PyInstaller backend ──────────────
echo [2/4] Building Python backend (PyInstaller)...
cd /d "%~dp0backend"
%PIP_EXE% install -r requirements.txt --quiet  || (echo [ERROR] pip install failed && exit /b 1)
%PIP_EXE% install pyinstaller --quiet          || (echo [ERROR] PyInstaller install failed && exit /b 1)
%PYTHON_EXE% -m PyInstaller scriptovideo.spec --noconfirm || (echo [ERROR] PyInstaller build failed && exit /b 1)
echo [OK] Backend built → backend/dist/scriptovideo-backend/
echo.

:: ── 3. Download FFmpeg (if not already present) ───────────────────────────────
echo [3/4] Checking FFmpeg...
set FFMPEG_DIR=%~dp0ffmpeg_bin
if exist "%FFMPEG_DIR%\ffmpeg.exe" (
    echo [OK] FFmpeg already present at ffmpeg_bin\ffmpeg.exe
) else (
    echo Downloading FFmpeg for Windows x64...
    mkdir "%FFMPEG_DIR%" 2>nul

    :: Use PowerShell to download and extract FFmpeg
    powershell -Command ^
        "$url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip';" ^
        "$out = '%TEMP%\ffmpeg_win.zip';" ^
        "Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing;" ^
        "Expand-Archive -Path $out -DestinationPath '%TEMP%\ffmpeg_extract' -Force;" ^
        "$src = (Get-ChildItem '%TEMP%\ffmpeg_extract' -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1).FullName;" ^
        "Copy-Item $src -Destination '%FFMPEG_DIR%\ffmpeg.exe';" ^
        "Remove-Item $out -Force;" ^
        "Remove-Item '%TEMP%\ffmpeg_extract' -Recurse -Force"
    if exist "%FFMPEG_DIR%\ffmpeg.exe" (
        echo [OK] FFmpeg downloaded.
    ) else (
        echo [WARN] FFmpeg download failed. The app will try to use a system-installed ffmpeg.
        echo        Manually place ffmpeg.exe in: %FFMPEG_DIR%
    )
)
echo.

:: ── 4. Build Electron installer ───────────────────────────────────────────────
echo [4/4] Building Electron Windows installer...
cd /d "%~dp0electron"
call npm install        || (echo [ERROR] npm install failed && exit /b 1)
if "%PUBLISH_FLAG%"=="always" (
    call npx electron-builder --win --publish always || (echo [ERROR] electron-builder failed && exit /b 1)
) else (
    call npm run build:win  || (echo [ERROR] electron-builder failed && exit /b 1)
)
echo.
echo ============================================================
echo   BUILD COMPLETE
echo ============================================================
echo   Installer: dist_electron\ScriptToVideo Setup *.exe
echo ============================================================
echo.
pause

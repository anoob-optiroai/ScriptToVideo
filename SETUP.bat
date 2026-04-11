@echo off
title ScriptToVideo - First Time Setup
color 0A
echo ============================================================
echo   ScriptToVideo - First Time Setup
echo ============================================================
echo.

REM ── Check Python ─────────────────────────────────────────────
echo [1/6] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found. Download from https://python.org
    pause
    exit /b 1
)
python --version
echo  OK
echo.

REM ── Check Node ───────────────────────────────────────────────
echo [2/6] Checking Node.js...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Node.js not found. Download from https://nodejs.org
    pause
    exit /b 1
)
node --version
echo  OK
echo.

REM ── Backend venv ─────────────────────────────────────────────
echo [3/6] Creating Python virtual environment...
cd /d "%~dp0backend"
if not exist venv (
    python -m venv venv
    echo  Virtual environment created.
) else (
    echo  Virtual environment already exists, skipping.
)
echo.

REM ── Install Python dependencies ───────────────────────────────
echo [4/6] Installing Python packages (this may take a few minutes)...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo  ERROR: pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo  Python packages installed.
echo.

REM ── Copy .env ────────────────────────────────────────────────
echo [5/6] Setting up environment config...
if not exist .env (
    copy .env.example .env >nul
    echo  Created .env from template.
    echo  *** IMPORTANT: Open backend\.env and add your API key! ***
) else (
    echo  .env already exists, skipping.
)
echo.

REM ── Frontend packages ─────────────────────────────────────────
echo [6/6] Installing frontend packages...
cd /d "%~dp0frontend"
npm install --silent
if %errorlevel% neq 0 (
    echo  ERROR: npm install failed.
    pause
    exit /b 1
)
echo  Frontend packages installed.
echo.

echo ============================================================
echo   Setup complete!
echo ============================================================
echo.
echo   NEXT STEP: Open backend\.env and add your API key.
echo   Then run START.bat to launch the application.
echo.
echo   Get a free ElevenLabs API key at: https://elevenlabs.io
echo   Or use OpenAI at: https://platform.openai.com
echo.
pause

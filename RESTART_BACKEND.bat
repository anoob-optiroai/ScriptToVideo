@echo off
title ScriptToVideo - Backend
echo ==========================================
echo   ScriptToVideo Backend Restart
echo ==========================================
echo.

:: Kill any existing uvicorn/python process on port 8000
echo Stopping any running backend on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   Killing PID %%a
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: Navigate to backend folder
cd /d "%~dp0backend"

:: Activate virtual environment
if exist "..\venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call "..\venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call "venv\Scripts\activate.bat"
) else (
    echo WARNING: Virtual environment not found, using system Python.
)

echo.
:: Ensure required packages are installed
python -m pip install python-pptx Pillow numpy --quiet

echo Starting backend server...
echo Backend will be available at: http://localhost:8000
echo Press Ctrl+C to stop.
echo.

python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

pause

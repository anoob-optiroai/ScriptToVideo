@echo off
title ScriptToVideo - Launcher
color 0B
echo ============================================================
echo   ScriptToVideo - Starting Application
echo ============================================================
echo.

REM Check .env exists
if not exist "%~dp0backend\.env" (
    echo  ERROR: backend\.env not found.
    echo  Please copy backend\.env.example to backend\.env and add your API key.
    pause
    exit /b 1
)

REM ── Start Backend ─────────────────────────────────────────────
echo  Starting backend API on http://localhost:8000 ...
start "ScriptToVideo Backend" cmd /k "cd /d %~dp0backend && call venv\Scripts\activate.bat && python -m uvicorn main:app --reload --port 8000"

timeout /t 3 /nobreak >/dev/null

REM ── Start Frontend ────────────────────────────────────────────
echo  Starting frontend on http://localhost:5173 ...
start "ScriptToVideo Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 4 /nobreak >/dev/null

REM ── Open browser ─────────────────────────────────────────────
start http://localhost:5173

echo.
echo ============================================================
echo   ScriptToVideo is running!
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo   API Docs: http://localhost:8000/docs
echo ============================================================
echo.
echo   Close the Backend and Frontend windows to stop the app.
pause

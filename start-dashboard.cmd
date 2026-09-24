@echo off
setlocal
title AI Agents 5-Hour Quota Dashboard

cd /d "%~dp0"

echo ================================================================
echo   ⚡ AI AGENTS 5-HOUR QUOTA DASHBOARD LAUNCHER
echo ================================================================
echo.
echo Starting dashboard server at http://localhost:5050...
echo.

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run agents --dashboard
    goto :done
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python agents.py --dashboard
    goto :done
)

echo [ERROR] Neither 'uv' nor 'python' was found in your PATH.
echo Please install uv (https://astral.sh/uv) or Python 3.11+.
pause
exit /b 1

:done
pause

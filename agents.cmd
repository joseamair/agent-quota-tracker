@echo off
setlocal

cd /d "%~dp0"

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run --project "%~dp0." agents %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python "%~dp0agents.py" %*
    exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agents_native.ps1" %*
exit /b %ERRORLEVEL%

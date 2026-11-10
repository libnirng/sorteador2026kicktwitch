@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Execute instalar.bat uma vez antes de iniciar.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m servidor.app
if errorlevel 1 pause

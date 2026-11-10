@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo O Sorteador Geral ainda nao foi instalado neste computador.
    echo Execute instalar.bat uma vez e tente novamente.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "launcher.py" --autostart

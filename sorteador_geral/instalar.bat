@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto install
:use_python
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Instalacao concluida. Abra Iniciar Sorteador.bat para iniciar pela janela grafica.
pause
exit /b 0
:failed
echo.
echo Nao foi possivel instalar. Copie a mensagem de erro acima.
pause
exit /b 1

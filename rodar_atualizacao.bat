@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo Atualizando catalogo, aguarde...
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py atualizar_catalogo.py
) else (
  python atualizar_catalogo.py
)
echo.
pause

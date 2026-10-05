@echo off
setlocal
rem Central BP-MS (HTML5): sobe o servico local e abre a pagina no navegador.
cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\SANKHERR\AppData\Local\Python\bin\pythonw.exe"
if exist "%PYTHON_EXE%" goto :rodar
set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE if exist "%%~dpPpythonw.exe" set "PYTHON_EXE=%%~dpPpythonw.exe"
if defined PYTHON_EXE goto :rodar
where pythonw >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_EXE=pythonw"
    goto :rodar
)
set "PYTHON_EXE=python"

:rodar
start "" "%PYTHON_EXE%" servico\servidor.py

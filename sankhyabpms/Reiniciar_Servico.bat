@echo off
rem Encerra TODAS as copias do servico da Central BP-MS (pythonw ... servidor.py) e sobe uma so.
cd /d "%~dp0"
echo Encerrando o servico da Central...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*servico\servidor.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 /nobreak >nul
echo Iniciando o servico...
wscript "%~dp0Iniciar_Servico.vbs"
timeout /t 3 /nobreak >nul
echo Pronto. Pode recarregar a Central no navegador (Ctrl+F5).
timeout /t 4 >nul

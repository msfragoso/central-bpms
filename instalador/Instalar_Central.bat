@echo off
rem Central BP-MS: registra o endereco bpms:// para o seu usuario (sem administrador).
set DEST=C:\sankhya_integracao\central
if not exist "%DEST%" mkdir "%DEST%"
if not exist "%~dp0central_handler.ps1" (
  echo Coloque central_handler.ps1 na mesma pasta deste arquivo e rode de novo.
  pause
  exit /b 1
)
copy /Y "%~dp0central_handler.ps1" "%DEST%\central_handler.ps1" >nul
set CMD=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%DEST%\central_handler.ps1\" \"%%1\"
reg add "HKCU\Software\Classes\bpms" /ve /d "URL:Central BP-MS" /f >nul
reg add "HKCU\Software\Classes\bpms" /v "URL Protocol" /d "" /f >nul
reg add "HKCU\Software\Classes\bpms\shell\open\command" /ve /d "%CMD%" /f >nul
echo.
echo Pronto. Os botoes verdes da Central BP-MS ja funcionam neste PC.
pause

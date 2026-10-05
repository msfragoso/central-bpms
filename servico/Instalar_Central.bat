@echo off
rem Central BP-MS: instala o servico local e liga junto com o Windows.
set DEST=C:\sankhya_integracao\central
if not exist "%DEST%" mkdir "%DEST%"
if not exist "%~dp0servidor_local.py" (
  echo Coloque servidor_local.py na mesma pasta deste arquivo e rode de novo.
  pause
  exit /b 1
)
copy /Y "%~dp0servidor_local.py" "%DEST%\servidor_local.py" >nul
set PYW=
if exist "%LOCALAPPDATA%\Python\bin\pythonw.exe" set PYW=%LOCALAPPDATA%\Python\bin\pythonw.exe
if not defined PYW for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PYW set PYW=%%P
if not defined PYW (
  echo Nao encontrei o pythonw. Instale o Python e rode de novo.
  pause
  exit /b 1
)
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Central BP-MS.lnk');" ^
  "$s.TargetPath='%PYW%';$s.Arguments='\"%DEST%\servidor_local.py\"';$s.WorkingDirectory='%DEST%';$s.WindowStyle=7;$s.Save()"
start "" "%PYW%" "%DEST%\servidor_local.py"
echo.
echo Pronto. O servico local da Central BP-MS esta ligado e vai iniciar junto com o Windows.
echo Recarregue a pagina da Central.
pause

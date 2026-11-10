@echo off
rem Instala o corretor de texto da Central (Java + LanguageTool) em ferramentas\. Nao altera o Windows.
cd /d "%~dp0"
echo Instalando o corretor de texto. Sao cerca de 290 MB de download.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Instalar_LanguageTool.ps1" > "%~dp0Instalar_LanguageTool.log" 2>&1
type "%~dp0Instalar_LanguageTool.log"
echo.
echo Pronto. Pode fechar esta janela e avisar o Claude.
pause

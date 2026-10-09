@echo off
rem Instala a biblioteca Playwright (usada pela Central para o login assistido no
rem Sankhya-OM e para gerar o PDF da conferência). Usa o Chrome que já está no PC;
rem não baixa outro navegador. Rode uma vez (duplo clique).
echo Instalando o Playwright para o Python...
set "PY=C:\Users\SANKHERR\AppData\Local\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m pip install --user --disable-pip-version-check playwright
if errorlevel 1 (
  echo.
  echo Algo deu errado na instalacao. Copie a mensagem acima e mande para o Claude.
) else (
  echo.
  echo Pronto! Playwright instalado.
)
pause

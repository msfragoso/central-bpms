# -*- coding: utf-8 -*-
"""
Monta o pacote "Lançar tarefa no ClickUp" para outra pessoa usar no próprio
computador, com o PRÓPRIO token do ClickUp (20/10/2026). Não leva nenhuma
credencial, cache pessoal ou dado desta máquina.

Uso:  python criar_pacote_lancar.py
Saída: dist\\Lancar_ClickUp_BP-MS.zip
"""
import ast
import hashlib
import json
import os
import re
import shutil
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
MOTORES = r"C:\sankhya_integracao"
DIST = os.path.join(AQUI, "dist")
PACOTE = os.path.join(DIST, "Lancar_ClickUp_BP-MS")

# 04/11/2026 (caso Adriano): o Lançar abre com caminho relativo ("servico\\servidor.py"), então procurar
# pelo nome da pasta não achava o serviço, que seguia rodando a versão antiga depois de instalar.
# Agora também encerra quem está na porta do Lançar, menos a Central BP-MS (ela tem conferencia.html).
PARAR_SERVICO = r'''# inicio-parar-servico
$porta = 8766
$servicos = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*servidor.py*" })
$parar = @($servicos | Where-Object { $_.CommandLine -like "*Lancar_ClickUp_BP-MS*" } | ForEach-Object { $_.ProcessId })
$donos = @(Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess })
if ($donos.Count -gt 0) {
    $ehCentral = $false
    try { $ehCentral = (Invoke-WebRequest "http://127.0.0.1:$porta/conferencia.html" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch {}
    if (-not $ehCentral) {
        $parar += @($servicos | Where-Object { $donos -contains $_.ProcessId } | ForEach-Object { $_.ProcessId })
    }
}
if ($parar.Count -gt 0) {
    $parar | Select-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}
# fim-parar-servico'''

INSTALAR_PS1 = r'''# Instalador do "Lançar ClickUp BP-MS" (23/10/2026).
# Faz tudo sozinho: Python (se faltar), bibliotecas, cópia para pasta fixa, atalhos e token.
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Instalando o Lançar ClickUp BP-MS"
$origem  = Split-Path -Parent $MyInvocation.MyCommand.Path
$destino = Join-Path $env:LOCALAPPDATA "Lancar_ClickUp_BP-MS"
function Passo($n, $t) { Write-Host ""; Write-Host "[$n/6] $t" -ForegroundColor Cyan }
function Falha($t) {
    Write-Host ""; Write-Host "NÃO DEU CERTO: $t" -ForegroundColor Red
    Write-Host "Tire um print desta janela e envie para quem te mandou o instalador."
    Read-Host "Aperte Enter para fechar"; exit 1
}

function Achar-Python {
    $cands = @()
    foreach ($c in @("py", "python")) {
        try {
            $exe = & $c -3 -c "import sys; print(sys.executable)" 2>$null
            if (-not $exe) { $exe = & $c -c "import sys; print(sys.executable)" 2>$null }
            if ($exe -and (Test-Path $exe)) { $cands += $exe }
        } catch {}
    }
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName
    $cands += Get-ChildItem "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName
    foreach ($p in $cands) {
        try {
            $ok = & $p -c "import sys, tkinter; print(sys.version_info >= (3, 9))" 2>$null
            if ($ok -eq "True") { return $p }
        } catch {}
    }
    return $null
}

Write-Host "=== Lançar ClickUp BP-MS — instalação ===" -ForegroundColor Green
Write-Host "Pasta do programa: $destino"

Passo 1 "Procurando o Python..."
$py = Achar-Python
if (-not $py) {
    Write-Host "Python não encontrado. Instalando (só para o seu usuário, sem pedir administrador)..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        try { & winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host } catch {}
        $py = Achar-Python
    }
    if (-not $py) {
        $url = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
        $tmp = Join-Path $env:TEMP "python-3.12.7-amd64.exe"
        Write-Host "Baixando o Python do site oficial (python.org)..."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
        } catch { Falha "não consegui baixar o Python ($url). Verifique a internet." }
        Write-Host "Instalando o Python (leva 1-2 minutos)..."
        Start-Process -FilePath $tmp -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_pip=1" -Wait
        $py = Achar-Python
    }
    if (-not $py) { Falha "o Python não ficou instalado. Instale pelo site python.org e rode o instalador de novo." }
}
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }
Write-Host "Python: $py"

Passo 2 "Instalando as bibliotecas (requests, keyring)..."
& $py -m pip install --user --upgrade --disable-pip-version-check -q requests keyring | Out-Host
if ($LASTEXITCODE -ne 0) { Falha "o pip não instalou as bibliotecas. Verifique a internet ou o proxy da empresa." }

Passo 3 "Copiando o programa..."
@@PARAR_SERVICO@@
New-Item -ItemType Directory -Force -Path $destino | Out-Null
foreach ($item in @("central", "motores", "configurar_token.py", "configurar_token.vbs", "Abrir_Lancar_ClickUp.vbs", "Configurar_Token_ClickUp.bat", "Desinstalar.bat", "desinstalar.ps1", "LEIA-ME.txt")) {
    Copy-Item -Path (Join-Path $origem $item) -Destination $destino -Recurse -Force
}
# 23/10/2026: UTF-16, para usuario com acento no nome (ex.: C:\Users\USUÁRIO)
Set-Content -Path (Join-Path $destino "python.txt") -Value $pyw -Encoding Unicode

Passo 4 "Criando os atalhos (Área de Trabalho e Menu Iniciar)..."
$sh = New-Object -ComObject WScript.Shell
$icone = Join-Path $destino "central\web\assets\icones\central.ico"
$menu = Join-Path ([Environment]::GetFolderPath("Programs")) "Lançar ClickUp BP-MS"
New-Item -ItemType Directory -Force -Path $menu | Out-Null
$atalhos = @(
    @{ Caminho = Join-Path ([Environment]::GetFolderPath("Desktop")) "Lançar ClickUp BP-MS.lnk"; Alvo = "Abrir_Lancar_ClickUp.vbs" },
    @{ Caminho = Join-Path $menu "Lançar ClickUp BP-MS.lnk"; Alvo = "Abrir_Lancar_ClickUp.vbs" },
    @{ Caminho = Join-Path $menu "Configurar token do ClickUp.lnk"; Alvo = "configurar_token.vbs" },
    @{ Caminho = Join-Path $menu "Desinstalar.lnk"; Alvo = "Desinstalar.bat" }
)
foreach ($a in $atalhos) {
    $lnk = $sh.CreateShortcut($a.Caminho)
    if ($a.Alvo -like "*.vbs") { $lnk.TargetPath = "$env:WINDIR\System32\wscript.exe"; $lnk.Arguments = "`"$(Join-Path $destino $a.Alvo)`"" }
    else { $lnk.TargetPath = Join-Path $destino $a.Alvo }
    $lnk.WorkingDirectory = $destino
    $lnk.IconLocation = $icone
    $lnk.Save()
}

Passo 5 "Conferindo o token do ClickUp..."
$tem = & $py -c "import keyring; print(bool(keyring.get_password('sankhya_experience_sync', 'CLICKUP_TOKEN')))" 2>$null
if ($tem -ne "True") {
    Write-Host "Falta o seu token pessoal do ClickUp. Vai abrir uma janela para colar."
    Write-Host "Onde pegar: ClickUp > seu avatar > Settings > Apps (ClickUp API) > API Token > Generate > Copy (começa com pk_)."
    Start-Process -FilePath $pyw -ArgumentList "`"$(Join-Path $destino 'configurar_token.py')`"" -WorkingDirectory $destino -Wait
    $tem = & $py -c "import keyring; print(bool(keyring.get_password('sankhya_experience_sync', 'CLICKUP_TOKEN')))" 2>$null
    if ($tem -ne "True") { Write-Host "Token não gravado. Depois use 'Configurar token do ClickUp' no Menu Iniciar." -ForegroundColor Yellow }
} else { Write-Host "Token já configurado neste computador." }

Passo 6 "Pronto!"
Write-Host "Use o atalho 'Lançar ClickUp BP-MS' na Área de Trabalho." -ForegroundColor Green
Start-Process -FilePath "$env:WINDIR\System32\wscript.exe" -ArgumentList "`"$(Join-Path $destino 'Abrir_Lancar_ClickUp.vbs')`""
Start-Sleep -Seconds 4
'''

INSTALAR_BAT = r'''@echo off
rem Dê dois cliques aqui para instalar (ou atualizar) o Lançar ClickUp BP-MS.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
'''

ABRIR_VBS = r'''' Abre o Lançar ClickUp BP-MS: se o serviço já estiver no ar, só abre o navegador;
' senão sobe o serviço local (escondido), que abre o navegador sozinho.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
url = "http://127.0.0.1:8766/lancar.html"
noAr = False
On Error Resume Next
Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
http.setTimeouts 1000, 1000, 1000, 1000
http.Open "GET", "http://127.0.0.1:8766/api/status", False
http.Send
If Err.Number = 0 Then noAr = (http.Status = 200)
If Err.Number <> 0 Then noAr = False
Err.Clear
On Error GoTo 0
If noAr Then
  sh.Run url, 1, False
Else
  sh.CurrentDirectory = fso.BuildPath(base, "central")
  sh.Run AcharPython(base) & " servico\servidor.py", 0, False
End If

' python.txt (gravado pelo instalador em UTF-16, aceita acento no caminho); se faltar, pyw
Function AcharPython(base)
  Dim f, arq, cam
  Set f = CreateObject("Scripting.FileSystemObject")
  arq = f.BuildPath(base, "python.txt")
  cam = ""
  If f.FileExists(arq) Then
    On Error Resume Next
    cam = Trim(f.OpenTextFile(arq, 1, False, -1).ReadLine)
    On Error GoTo 0
  End If
  If cam <> "" And f.FileExists(cam) Then
    AcharPython = """" & cam & """"
  Else
    AcharPython = "pyw"
  End If
End Function
'''

CONFIGURAR_TOKEN_VBS = r'''' Abre a janela do token do ClickUp com o Python gravado pelo instalador.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = base
cam = ""
arq = fso.BuildPath(base, "python.txt")
If fso.FileExists(arq) Then
  On Error Resume Next
  cam = Trim(fso.OpenTextFile(arq, 1, False, -1).ReadLine)
  On Error GoTo 0
End If
If cam <> "" And fso.FileExists(cam) Then py = """" & cam & """" Else py = "pyw"
sh.Run py & " configurar_token.py", 1, False
'''

CONFIG_TOKEN_BAT = r'''@echo off
cd /d "%~dp0"
start "" wscript.exe "%~dp0configurar_token.vbs"
'''

DESINSTALAR_BAT = r'''@echo off
rem Remove o Lancar ClickUp BP-MS deste computador (o token fica no cofre do Windows).
copy /y "%~dp0desinstalar.ps1" "%TEMP%\desinstalar_lancar.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\desinstalar_lancar.ps1"
'''

DESINSTALAR_PS1 = r'''# Remove o Lançar ClickUp BP-MS (programa e atalhos). O token continua no cofre do Windows.
$destino = Join-Path $env:LOCALAPPDATA "Lancar_ClickUp_BP-MS"
$r = Read-Host "Remover o Lançar ClickUp BP-MS deste computador? (S/N)"
if ($r -notmatch '^[sS]') { exit }
@@PARAR_SERVICO@@
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Lançar ClickUp BP-MS.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "Lançar ClickUp BP-MS") -Recurse -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Remove-Item $destino -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Removido." -ForegroundColor Green
Start-Sleep -Seconds 2
'''

LEIA_ME = '''LANÇAR TAREFA NO CLICKUP — BP-MS

ATUALIZAR
Depois de instalado, ao abrir a tela aparece "Atualizar agora" quando houver versão nova.

INSTALAR (primeira vez)
1. Extraia este .zip (botão direito > Extrair tudo).
2. Dê dois cliques em  Instalar_Lancar_ClickUp.bat
   O instalador faz tudo sozinho:
   - instala o Python, se o computador não tiver (só para o seu usuário, sem administrador);
   - instala as bibliotecas;
   - copia o programa para %LOCALAPPDATA%\\Lancar_ClickUp_BP-MS;
   - cria o atalho "Lançar ClickUp BP-MS" na Área de Trabalho e no Menu Iniciar;
   - pede o seu token do ClickUp (só na primeira vez) e abre a tela.
3. Depois de instalado, a pasta extraída pode ser apagada.

TOKEN DO CLICKUP (pessoal — cada um usa o seu)
ClickUp > seu avatar (canto inferior esquerdo) > Settings > Apps (ClickUp API) > API Token >
Generate > Copy. Começa com "pk_". Não envie o token por e-mail nem WhatsApp.
As tarefas aparecem criadas por você e você só alcança o que o seu usuário enxerga no ClickUp.

USO
Atalho "Lançar ClickUp BP-MS". O navegador abre em http://127.0.0.1:8766/lancar.html
Na 1ª vez, clique no botão de atualizar a lista de membros (ao lado do Responsável).

PROBLEMAS
- "Token do ClickUp não configurado": Menu Iniciar > Lançar ClickUp BP-MS > Configurar token do ClickUp.
- Token vazou ou trocou: no ClickUp, API Token > Regenerate, e grave o novo pelo mesmo atalho.
- Desinstalar: Menu Iniciar > Lançar ClickUp BP-MS > Desinstalar.
'''


# 04/11/2026: o pacote fica no GitHub público para a atualização online, então o config.py
# dele leva só o que o Lançar usa, sem nomes, e-mails e parceiros.
CONFIG_DO_PACOTE = ("CLICKUP_API", "CLICKUP_HEADERS", "SPACE_ID_PMO_BP_MS", "PASTAS_IGNORADAS", "FIELD_EXPERIENCE",
                    "EXPERIENCE_OPTIONS", "STATUS_NAO_EXECUTADO", "FIELD_ETAPA", "FIELD_USUARIO_CLIENTE",
                    "FIELD_PARCEIRO", "FIELD_MODULO", "ETAPA_ATENDIMENTO_AVULSO", "MODULO_ATENDIMENTO_AVULSO")
CONFIG_PESSOAIS = ("PARCEIRO_FAP", "CONSULTOR_DE_PARA", "CONSULTOR_DE_PARA_POR_FAP", "PESSOAS_NAO_CONSULTORAS_EMAILS")


def _atribuicoes_do_config():
    with open(os.path.join(MOTORES, "clickup_sync", "config.py"), encoding="utf-8") as f:
        fonte = f.read()
    achadas = {}
    for no in ast.parse(fonte).body:
        if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
            achadas[no.targets[0].id] = (no, ast.get_source_segment(fonte, no))
    return achadas


def config_enxuto():
    achadas = _atribuicoes_do_config()
    linhas = ["# Configuração do pacote Lançar ClickUp: só IDs do ClickUp. O token fica no cofre do Windows.",
              "from credenciais import CLICKUP_TOKEN", ""]
    linhas += [achadas[nome][1] for nome in CONFIG_DO_PACOTE]
    return "\n".join(linhas) + "\n"


def textos_pessoais():
    """Nomes e e-mails do config.py completo, para garantir que nenhum foi parar no pacote."""
    achadas = _atribuicoes_do_config()
    textos = set()
    for nome in CONFIG_PESSOAIS:
        if nome in achadas:
            for no in ast.walk(achadas[nome][0].value):
                if isinstance(no, ast.Constant) and isinstance(no.value, str) and len(no.value) >= 4:
                    textos.add(no.value)
    # "BPMS" é o responsável genérico e "Origem" é palavra comum: aparecem nos textos da tela.
    return textos - {"BPMS", "Origem"}


def conferir_sem_dados_pessoais():
    proibidos = textos_pessoais()
    achados = []
    for raiz, _, arquivos in os.walk(PACOTE):
        for a in arquivos:
            if a.lower().endswith((".png", ".ico", ".zip")):
                continue
            cam = os.path.join(raiz, a)
            with open(cam, encoding="utf-8", errors="ignore") as f:
                texto = f.read()
            if "@sankhya" in texto.lower():
                achados.append((os.path.relpath(cam, PACOTE), "@sankhya"))
            for p in proibidos:
                if re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", texto):
                    achados.append((os.path.relpath(cam, PACOTE), p))
    if achados:
        raise SystemExit(f"Pacote recusado, tem dados pessoais: {achados[:10]}")


def limpar_py(caminho, esvaziar=()):
    """Regrava o .py sem comentários e docstrings, que citam clientes, e esvazia as listas pedidas."""
    with open(caminho, encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            corpo = no.body
            if corpo and isinstance(corpo[0], ast.Expr) and isinstance(corpo[0].value, ast.Constant) \
                    and isinstance(corpo[0].value.value, str):
                del corpo[0]
                if not corpo and not isinstance(no, ast.Module):
                    corpo.append(ast.Pass())
        if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name) \
                and no.targets[0].id in esvaziar:
            no.value = ast.Dict(keys=[], values=[])
    escrever(caminho, ast.unparse(arvore) + "\n")


def novidades_da_versao():
    with open(os.path.join(AQUI, "CHANGELOG.md"), encoding="utf-8") as f:
        texto = f.read()
    achou = re.search(r"(?ms)^## " + re.escape(versao_do_pacote()) + r"\b.*?(?=^## |\Z)", texto)
    return achou.group(0).strip() if achou else ""


def versao_do_pacote():
    with open(os.path.join(AQUI, "web", "assets", "comum.js"), encoding="utf-8") as f:
        return re.search(r'const VERSAO = "(\d+\.\d+\.\d+)"', f.read()).group(1)


def copiar(origem, destino):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copy2(origem, destino)


def escrever(destino, texto, bom=False):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8-sig" if bom else "utf-8", newline="\r\n") as f:
        f.write(texto)


AZUL_LANCAR = (29, 78, 216)


def icones_azuis(pasta):
    """
    06/11/2026 (Fragoso): o Lançar ClickUp usa o "BP" em azul, para não confundir com a Central (verde).
    O atalho da Área de Trabalho aponta para central.ico do pacote, então ele recebe o lancar.ico; as imagens
    PNG (aba do navegador, app) são recoloridas do verde para o azul. Sem a biblioteca Pillow, ficam verdes.
    """
    ico = os.path.join(pasta, "lancar.ico")
    if os.path.isfile(ico):
        shutil.copy2(ico, os.path.join(pasta, "central.ico"))
    try:
        from PIL import Image
    except ImportError:
        print("Aviso: sem Pillow, as imagens PNG do Lançar ficam verdes.")
        return
    for nome in os.listdir(pasta):
        if not nome.lower().endswith(".png"):
            continue
        caminho = os.path.join(pasta, nome)
        im = Image.open(caminho).convert("RGBA")
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                t = max(0.0, min(1.0, (255 - r) / 245))
                px[x, y] = tuple(int(round(255 * (1 - t) + cor * t)) for cor in AZUL_LANCAR) + (a,)
        im.save(caminho)


def main():
    if os.path.exists(PACOTE):
        shutil.rmtree(PACOTE)
    c = os.path.join(PACOTE, "central")
    mot = os.path.join(PACOTE, "motores")

    # --- serviço: só o núcleo e a tela Lançar
    for n in ("nucleo.py", "servidor.py", "rotas_tarefas.py", "rotas_textos.py", "rotas_atualizacao.py", "atualizador.py", "app_lancar.py"):
        copiar(os.path.join(AQUI, "servico", n), os.path.join(c, "servico", n))
    escrever(os.path.join(c, "config.json"),
             '{\n  "pasta_motores": "..\\\\motores",\n  "porta": 8766,\n  "abrir_navegador": true,\n'
             '  "modulos": ["lancar"],\n  "atualizacao": "lancar"\n}\n')

    # --- telas: lancar.html + assets; menu só com a tela Lançar
    web = os.path.join(AQUI, "web")
    copiar(os.path.join(web, "lancar.html"), os.path.join(c, "web", "lancar.html"))
    copiar(os.path.join(web, "manifest.json"), os.path.join(c, "web", "manifest.json"))
    for n in ("padrao.css", "login.js", "firebase-config.js"):
        copiar(os.path.join(web, "assets", n), os.path.join(c, "web", "assets", n))
    shutil.copytree(os.path.join(web, "assets", "icones"), os.path.join(c, "web", "assets", "icones"))
    icones_azuis(os.path.join(c, "web", "assets", "icones"))
    with open(os.path.join(web, "assets", "comum.js"), encoding="utf-8") as f:
        comum = f.read()
    comum = re.sub(r"const TELAS = \[.*?\];",
                   'const TELAS = [\n    { id: "lancar", href: "lancar.html", rotulo: "Lançar ClickUp" },\n  ];',
                   comum, count=1, flags=re.S)
    escrever(os.path.join(c, "web", "assets", "comum.js"), comum)
    escrever(os.path.join(c, "web", "index.html"),
             '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=lancar.html">'
             '<title>Lançar ClickUp</title><a href="lancar.html">Abrir Lançar ClickUp</a>\n')
    with open(os.path.join(c, "web", "manifest.json"), encoding="utf-8") as f:
        man = f.read().replace('"start_url": "index.html"', '"start_url": "lancar.html"') \
                      .replace('"name": "Central BP-MS"', '"name": "Lançar ClickUp BP-MS"')
    escrever(os.path.join(c, "web", "manifest.json"), man)

    # --- motores: só o necessário para lançar tarefa no ClickUp
    for n in ("__init__.py", "list_discovery.py", "clickup_client.py", "text_matching.py"):
        copiar(os.path.join(MOTORES, "clickup_sync", n), os.path.join(mot, "clickup_sync", n))
    escrever(os.path.join(mot, "clickup_sync", "config.py"), config_enxuto())
    copiar(os.path.join(MOTORES, "clickup_tasks", "lancar_tarefas_clickup.py"),
           os.path.join(mot, "clickup_tasks", "lancar_tarefas_clickup.py"))
    escrever(os.path.join(mot, "credenciais.py"), '''"""
Credenciais do pacote "Lançar ClickUp": só o token PESSOAL do ClickUp de quem usa,
guardado no Gerenciador de Credenciais do Windows (rode Configurar_Token_ClickUp.bat).
"""
import keyring

SERVICO = "sankhya_experience_sync"
CLICKUP_TOKEN = keyring.get_password(SERVICO, "CLICKUP_TOKEN")
EXPERIENCE_USER = keyring.get_password(SERVICO, "EXPERIENCE_USER")  # não usado no Lançar
EXPERIENCE_PASS = keyring.get_password(SERVICO, "EXPERIENCE_PASS")  # não usado no Lançar

if not CLICKUP_TOKEN:
    raise RuntimeError("Token do ClickUp não configurado. Rode Configurar_Token_ClickUp.bat.")
''')

    # --- configurador do token (janela para colar, sem mostrar o token)
    escrever(os.path.join(PACOTE, "configurar_token.py"), '''"""Grava o token PESSOAL do ClickUp no Gerenciador de Credenciais do Windows."""
import tkinter as tk
from tkinter import messagebox

import keyring
import requests

raiz = tk.Tk()
raiz.title("Token do ClickUp")
raiz.resizable(False, False)
tk.Label(raiz, text="Cole o seu token pessoal do ClickUp (começa com pk_):", padx=12, pady=8).pack(anchor="w")
campo = tk.Entry(raiz, width=60, show="•")
campo.pack(padx=12)
campo.focus_set()


def gravar():
    token = campo.get().strip()
    if not token.startswith("pk_"):
        messagebox.showerror("Token do ClickUp", "O token precisa começar com pk_.")
        return
    try:
        r = requests.get("https://api.clickup.com/api/v2/user", headers={"Authorization": token}, timeout=20)
        nome = r.json().get("user", {}).get("username") if r.status_code == 200 else None
    except requests.RequestException:
        nome = None
    if not nome:
        messagebox.showerror("Token do ClickUp", "O ClickUp não aceitou esse token. Confira e tente de novo.")
        return
    keyring.set_password("sankhya_experience_sync", "CLICKUP_TOKEN", token)
    messagebox.showinfo("Token do ClickUp", f"Token gravado no cofre do Windows.\\nConectado como: {nome}")
    raiz.destroy()


tk.Button(raiz, text="Gravar", command=gravar, padx=16).pack(pady=10)
raiz.bind("<Return>", lambda e: gravar())
raiz.mainloop()
''')
    # --- instalador completo (23/10/2026): um duplo clique instala Python (se faltar),
    # bibliotecas, programa em %LOCALAPPDATA%, atalhos e token.
    escrever(os.path.join(PACOTE, "instalar.ps1"), INSTALAR_PS1.replace("@@PARAR_SERVICO@@", PARAR_SERVICO), bom=True)
    escrever(os.path.join(PACOTE, "Instalar_Lancar_ClickUp.bat"), INSTALAR_BAT)
    escrever(os.path.join(PACOTE, "Configurar_Token_ClickUp.bat"), CONFIG_TOKEN_BAT)
    escrever(os.path.join(PACOTE, "configurar_token.vbs"), CONFIGURAR_TOKEN_VBS)
    escrever(os.path.join(PACOTE, "Abrir_Lancar_ClickUp.vbs"), ABRIR_VBS)
    escrever(os.path.join(PACOTE, "Desinstalar.bat"), DESINSTALAR_BAT)
    escrever(os.path.join(PACOTE, "desinstalar.ps1"), DESINSTALAR_PS1.replace("@@PARAR_SERVICO@@", PARAR_SERVICO), bom=True)
    escrever(os.path.join(PACOTE, "LEIA-ME.txt"), LEIA_ME, bom=True)

    # 04/11/2026: a lista de parceiros vem do ClickUp, com o token de quem usa (atualizar_opcoes_parceiro).
    for pasta in (os.path.join(c, "servico"), mot):
        for raiz, _, arquivos in os.walk(pasta):
            for a in arquivos:
                if a.endswith(".py"):
                    limpar_py(os.path.join(raiz, a), esvaziar=("OPCOES_PARCEIRO",))
    conferir_sem_dados_pessoais()
    os.makedirs(DIST, exist_ok=True)
    zip_path = os.path.join(DIST, "Lancar_ClickUp_BP-MS.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for raiz, _, arquivos in os.walk(PACOTE):
            for a in arquivos:
                cam = os.path.join(raiz, a)
                z.write(cam, os.path.relpath(cam, DIST))
    # 23/10/2026: o passo a passo também fica ao lado do .zip, para mandar junto
    shutil.copy2(os.path.join(PACOTE, "LEIA-ME.txt"), os.path.join(DIST, "Como instalar - Lancar ClickUp BP-MS.txt"))
    # 04/11/2026: versao.json e o .zip vão para pacote-lancar/; o GitHub os anexa à versão (Release).
    with open(zip_path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(DIST, "versao.json"), "w", encoding="utf-8") as f:
        json.dump({"versao": versao_do_pacote(), "sha256": sha, "novidades": novidades_da_versao()},
                  f, ensure_ascii=False, indent=1)
    print("Pacote:", zip_path, versao_do_pacote(), sha)


if __name__ == "__main__":
    main()

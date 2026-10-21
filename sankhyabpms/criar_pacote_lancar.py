# -*- coding: utf-8 -*-
"""
Monta o pacote "Lançar tarefa no ClickUp" para outra pessoa usar no próprio
computador, com o PRÓPRIO token do ClickUp (20/10/2026). Não leva nenhuma
credencial, cache pessoal ou dado desta máquina.

Uso:  python criar_pacote_lancar.py
Saída: dist\\Lancar_ClickUp_BP-MS.zip
"""
import os
import re
import shutil
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
MOTORES = r"C:\sankhya_integracao"
DIST = os.path.join(AQUI, "dist")
PACOTE = os.path.join(DIST, "Lancar_ClickUp_BP-MS")


def copiar(origem, destino):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copy2(origem, destino)


def escrever(destino, texto, bom=False):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8-sig" if bom else "utf-8", newline="\r\n") as f:
        f.write(texto)


def main():
    if os.path.exists(PACOTE):
        shutil.rmtree(PACOTE)
    c = os.path.join(PACOTE, "central")
    mot = os.path.join(PACOTE, "motores")

    # --- serviço: só o núcleo e a tela Lançar
    for n in ("nucleo.py", "servidor.py", "rotas_tarefas.py", "rotas_textos.py", "app_lancar.py"):
        copiar(os.path.join(AQUI, "servico", n), os.path.join(c, "servico", n))
    escrever(os.path.join(c, "config.json"),
             '{\n  "pasta_motores": "..\\\\motores",\n  "porta": 8766,\n  "abrir_navegador": true,\n'
             '  "modulos": ["lancar"]\n}\n')

    # --- telas: lancar.html + assets; menu só com a tela Lançar
    web = os.path.join(AQUI, "web")
    copiar(os.path.join(web, "lancar.html"), os.path.join(c, "web", "lancar.html"))
    copiar(os.path.join(web, "manifest.json"), os.path.join(c, "web", "manifest.json"))
    for n in ("padrao.css", "login.js", "firebase-config.js"):
        copiar(os.path.join(web, "assets", n), os.path.join(c, "web", "assets", n))
    shutil.copytree(os.path.join(web, "assets", "icones"), os.path.join(c, "web", "assets", "icones"))
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
    for n in ("__init__.py", "config.py", "list_discovery.py", "clickup_client.py", "text_matching.py"):
        copiar(os.path.join(MOTORES, "clickup_sync", n), os.path.join(mot, "clickup_sync", n))
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
    escrever(os.path.join(PACOTE, "Instalar.bat"), r'''@echo off
rem Instala as bibliotecas do Python usadas pelo Lançar ClickUp.
where py >nul 2>nul && (set "PY=py") || (set "PY=python")
%PY% --version >nul 2>nul || (echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH". & pause & exit /b 1)
%PY% -m pip install --user requests keyring
echo.
echo Pronto. Agora rode Configurar_Token_ClickUp.bat.
pause
''')
    escrever(os.path.join(PACOTE, "Configurar_Token_ClickUp.bat"), r'''@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw configurar_token.py) || (start "" pythonw configurar_token.py)
''')
    escrever(os.path.join(PACOTE, "Abrir_Lancar_ClickUp.vbs"), r'''' Abre o Lançar ClickUp: sobe o serviço local (escondido) e abre o navegador.
Set fso = CreateObject("Scripting.FileSystemObject")
pasta = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "central")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = pasta
py = "pyw"
On Error Resume Next
sh.Run "where pyw", 0, True
If Err.Number <> 0 Then py = "pythonw"
On Error GoTo 0
sh.Run py & " servico\servidor.py", 0, False
''', bom=False)
    escrever(os.path.join(PACOTE, "LEIA-ME.txt"), '''LANÇAR TAREFA NO CLICKUP — BP-MS (só esta tela da Central)

Cada pessoa usa o PRÓPRIO token do ClickUp: as tarefas aparecem criadas por ela,
e ela só alcança o que o usuário dela enxerga no ClickUp. Nenhuma senha vem no pacote.

INSTALAÇÃO (uma vez)
1. Instale o Python (https://www.python.org/downloads/) marcando "Add python.exe to PATH".
2. Copie esta pasta para C:\\Lancar_ClickUp_BP-MS (ou outro lugar fixo).
3. Dê dois cliques em Instalar.bat.
4. Gere o token pessoal no ClickUp:
   avatar (canto inferior esquerdo) > Settings > Apps (ou "ClickUp API") > API Token >
   Generate > Copy. Começa com "pk_". Não envie o token por e-mail/WhatsApp.
5. Dê dois cliques em Configurar_Token_ClickUp.bat, cole o token e clique em Gravar.
   A janela confirma com o seu nome de usuário do ClickUp.

USO
- Dê dois cliques em Abrir_Lancar_ClickUp.vbs. O navegador abre em http://127.0.0.1:8766/lancar.html
- Na 1ª vez, clique no botão de atualizar a lista de membros (ao lado do Responsável).
- Dica: crie um atalho do .vbs na Área de Trabalho (ícone: central\\web\\assets\\icones\\central.ico).

PROBLEMAS
- "Token do ClickUp não configurado": rode de novo Configurar_Token_ClickUp.bat.
- Token vazou ou trocou: no ClickUp, API Token > Regenerate, e grave o novo pelo .bat.
''')

    os.makedirs(DIST, exist_ok=True)
    zip_path = os.path.join(DIST, "Lancar_ClickUp_BP-MS.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for raiz, _, arquivos in os.walk(PACOTE):
            for a in arquivos:
                cam = os.path.join(raiz, a)
                z.write(cam, os.path.relpath(cam, DIST))
    print("Pacote:", zip_path)


if __name__ == "__main__":
    main()

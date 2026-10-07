# -*- coding: utf-8 -*-
"""
Converte o relatório HTML da conferência em PDF com o Chrome do PC (Playwright,
sem janela). Roda num processo separado para não misturar com o Playwright da
janela do Sankhya-OM (om_sessao.py), que vive em outra thread do serviço.
"""
import os
import subprocess
import sys

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

_SCRIPT = r"""
import sys, pathlib
from playwright.sync_api import sync_playwright
html, pdf, chrome = sys.argv[1], sys.argv[2], sys.argv[3]
with sync_playwright() as p:
    opcoes = {"headless": True}
    if pathlib.Path(chrome).is_file():
        opcoes["executable_path"] = chrome
    else:
        opcoes["channel"] = "chrome"
    nav = p.chromium.launch(**opcoes)
    pagina = nav.new_page()
    pagina.goto(pathlib.Path(html).resolve().as_uri(), wait_until="load", timeout=60000)
    pagina.emulate_media(media="print")
    pagina.pdf(path=pdf, format="A4", landscape=True, print_background=True,
               margin={"top": "10mm", "bottom": "12mm", "left": "8mm", "right": "8mm"},
               display_header_footer=True, header_template="<span></span>",
               footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#666">'
                               'Página <span class="pageNumber"></span> de <span class="totalPages"></span></div>')
    nav.close()
"""


def html_para_pdf(caminho_html):
    """Gera o PDF ao lado do HTML (mesmo nome, .pdf) e devolve o caminho."""
    caminho_pdf = os.path.splitext(caminho_html)[0] + ".pdf"
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    r = subprocess.run([exe, "-c", _SCRIPT, caminho_html, caminho_pdf, CHROME],
                       capture_output=True, text=True, timeout=180,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not os.path.isfile(caminho_pdf):
        raise RuntimeError("Não consegui gerar o PDF: " + (r.stderr or r.stdout or "erro desconhecido").strip()[-400:])
    return caminho_pdf

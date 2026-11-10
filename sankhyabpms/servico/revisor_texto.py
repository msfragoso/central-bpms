# -*- coding: utf-8 -*-
"""
Revisor do texto da Solução das OS (10/11/2026, pedido do Fragoso). Usa o LanguageTool instalado em ferramentas/
(Instalar_LanguageTool.bat): o servidor escuta só em localhost e o texto não sai do computador.

Só aplica sozinho o que é seguro: caixa alta, acentos, espaços e erros conhecidos. Palavra desconhecida e dúvida de
concordância viram "a conferir", porque a sugestão do corretor costuma errar em termo técnico (DEPOLY -> DEPOIS).
Quem aprova o texto final é sempre a pessoa, na tela do Aceite.

Termos da equipe ficam em dados/glossario_texto.json (ignorar, trocar, siglas), que soma com os padrões abaixo.
"""
import glob
import os
import re
import socket
import subprocess
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests

from nucleo import PASTAS, ErroUsuario, ler_json_dados

PORTA = 8095
URL = f"http://localhost:{PORTA}/v2/check"
ARQ_GLOSSARIO = "glossario_texto.json"
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_FERRAMENTAS = os.path.join(_RAIZ, "ferramentas")
LIMITE_CAIXA_ALTA = 0.7
_processo = {"p": None}

SIGLAS = {"OS", "NF", "NFE", "NF-E", "NFSE", "NFS-E", "CTE", "CT-E", "MDFE", "MDF-E", "SKU", "TI", "ERP", "CNPJ", "CPF", "WMS", "MMS", "API", "DANFE", "ICMS", "IPI",
          "PIS", "COFINS", "CFOP", "NCM", "ST", "BI", "RH", "DP", "PDV", "GP", "FAP", "CRM", "XML", "PDF", "SQL", "MRP", "DRE", "CST", "ISS", "CFO", "PMO", "TGF", "TSI", "OM"}
IGNORAR = {"sankhya", "picking", "ireport", "setlist", "deploy", "status", "dashboard", "dashboards", "setup", "go-live", "backlog", "workflow", "layout", "layouts", "login",
           "email", "e-mail", "showtime", "check-in", "script", "scripts", "query", "queries", "gadget", "gadgets", "snk", "experience", "clickup", "whatsapp", "excel", "java", "card", "cards", "trigger", "triggers", "procedure", "procedures", "recontabilização"}
TROCAR = {"depoly": "deploy"}
# Regras em que a primeira sugestão do corretor costuma estar certa
REGRAS_SEGURAS = ("PARONYM_", "LP_PARONYMS", "DIACRITICS", "PT_SIMPLE_REPLACE_ORTHOGRAPHY", "SPACE_BEFORE_PUNCTUATION", "WHITESPACE_RULE", "COMMA_PARENTHESIS_WHITESPACE",
                  "DOUBLE_PUNCTUATION", "UPPERCASE_SENTENCE_START", "CP_AI_")
REGRAS_CONFERIR = ("GENERAL_NUMBER_AGREEMENT", "GENERAL_GENDER_AGREEMENT", "CONCORDANCIA", "QUE_VERBO", "SER_PARA_SER")


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def glossario():
    g = ler_json_dados(ARQ_GLOSSARIO, {}) or {}
    return {"siglas": SIGLAS | {str(x).upper() for x in g.get("siglas") or []},
            "ignorar": IGNORAR | {str(x).lower() for x in g.get("ignorar") or []},
            "trocar": {**TROCAR, **{str(k).lower(): str(v) for k, v in (g.get("trocar") or {}).items()}}}


def em_caixa_alta(texto):
    letras = [c for c in texto if c.isalpha()]
    return len(letras) >= 12 and sum(c.isupper() for c in letras) / len(letras) >= LIMITE_CAIXA_ALTA


def normalizar_caixa(texto, siglas):
    """Tudo em minúsculas, menos siglas e códigos, com maiúscula no início de cada frase ou linha."""
    def palavra(m):
        p = m.group(0)
        return p if p.upper() in siglas or re.search(r"[\d_]", p) else p.lower()

    t = re.sub(r"[^\W_]+(?:[-_][^\W_]+)*", palavra, texto)
    return re.sub(r"(^|[.!?]\s+|\n\s*)([^\W\d_])", lambda m: m.group(1) + m.group(2).upper(), t, flags=re.M) if t else t


def _casar_caixa(origem, novo):
    if origem.isupper():
        return novo.upper()
    if origem[:1].isupper():
        return novo[:1].upper() + novo[1:]
    return novo


def _servidor_ativo():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def disponivel():
    return bool(glob.glob(os.path.join(PASTA_FERRAMENTAS, "jdk-*", "bin", "java.exe")) and glob.glob(os.path.join(PASTA_FERRAMENTAS, "LanguageTool-*")))


def garantir_servidor(log=print):
    if not disponivel():
        raise ErroUsuario("O corretor não está instalado. Rode o Instalar_LanguageTool.bat na pasta da Central.")
    if _servidor_ativo():
        return
    java = glob.glob(os.path.join(PASTA_FERRAMENTAS, "jdk-*", "bin", "java.exe"))[0]
    pasta = glob.glob(os.path.join(PASTA_FERRAMENTAS, "LanguageTool-*"))[0]
    log("Iniciando o corretor neste computador...")
    _processo["p"] = subprocess.Popen([java, "-Xmx1g", "-cp", "languagetool-server.jar", "org.languagetool.server.HTTPServer", "--port", str(PORTA)],
                                      cwd=pasta, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    limite = time.time() + 90
    while time.time() < limite:
        try:
            requests.post(URL, data={"language": "pt-BR", "text": "teste"}, timeout=30).raise_for_status()
            return
        except requests.RequestException:
            time.sleep(1)
    raise ErroUsuario("O corretor não respondeu em 90 segundos. Tente de novo.")


def revisar(texto, g=None):
    """Devolve {sugerido, ajustes: [{de, para, motivo}], conferir: [{trecho, opcoes, motivo}], caixa_alta}."""
    g = g or glossario()
    original = texto or ""
    caixa = em_caixa_alta(original)
    ajustes, conferir = [], []
    base = normalizar_caixa(original, g["siglas"]) if caixa else original

    def trocar_conhecido(m):
        p = m.group(0)
        novo = g["trocar"].get(p.lower())
        if not novo:
            return p
        final = _casar_caixa(p, novo)
        ajustes.append({"de": p, "para": final, "motivo": "Erro conhecido"})
        return final

    base = re.sub(r"[^\W\d_]+", trocar_conhecido, base)
    if not base.strip():
        return {"sugerido": original, "ajustes": [], "conferir": [], "caixa_alta": False}
    r = requests.post(URL, data={"language": "pt-BR", "text": base}, timeout=120)
    r.raise_for_status()
    trocas = []
    for m in r.json().get("matches") or []:
        regra = m["rule"]["id"]
        ini, fim = m["offset"], m["offset"] + m["length"]
        trecho = base[ini:fim]
        opcoes = [x["value"] for x in m.get("replacements") or []][:3]
        motivo = m.get("shortMessage") or m.get("message") or ""
        if regra.startswith("MORFOLOGIK"):
            if trecho.lower() in g["ignorar"] or trecho.upper() in g["siglas"] or re.search(r"[\d_]", trecho):
                continue
            if not caixa and (trecho.isupper() or (trecho[:1].isupper() and " " not in trecho and not (ini == 0 or base[max(0, ini - 2):ini].strip() in (".", "!", "?")))):
                continue  # em texto normal, maiúscula indica sigla, sistema ou nome próprio
            acento = next((o for o in opcoes if " " not in o and _sem_acento(o) == _sem_acento(trecho)), None)
            if acento:
                trocas.append((ini, fim, _casar_caixa(trecho, acento), "Acento ou grafia"))
            else:
                if caixa and " " not in trecho and trecho.isalpha():
                    # palavra desconhecida em texto que estava todo em maiúsculas: sigla curta ou nome próprio
                    trocas.append((ini, fim, trecho.upper() if len(trecho) <= 3 else trecho.capitalize(), "Nome ou sigla"))
                conferir.append({"trecho": trecho, "opcoes": opcoes, "motivo": "Palavra desconhecida"})
        elif regra.startswith(REGRAS_SEGURAS) and opcoes:
            if trecho.split()[0].lower() in ("da", "de", "ai", "a", "e", "o", "se", "nos") and opcoes[0].split()[0].lower() != trecho.split()[0].lower():
                conferir.append({"trecho": trecho, "opcoes": opcoes, "motivo": "Possível acento"})  # da/dá, ai/aí: depende do sentido
            else:
                trocas.append((ini, fim, opcoes[0], motivo or "Correção"))
        elif regra.startswith(REGRAS_CONFERIR):
            conferir.append({"trecho": trecho, "opcoes": opcoes, "motivo": "Concordância"})
    sugerido = base
    ultimo = len(base) + 1
    for ini, fim, novo, motivo in sorted(trocas, key=lambda x: -x[0]):
        if fim > ultimo:  # sobreposição: fica a troca que vem depois no texto
            continue
        if base[ini:fim] != novo:
            ajustes.append({"de": base[ini:fim], "para": novo, "motivo": motivo})
        sugerido, ultimo = sugerido[:ini] + novo + sugerido[fim:], ini
    return {"sugerido": sugerido, "ajustes": ajustes, "conferir": conferir, "caixa_alta": caixa}


def revisar_varios(textos, log=print):
    """{chave: texto} -> {chave: revisão} só com os textos que têm ajuste ou ponto a conferir."""
    garantir_servidor(log)
    g = glossario()
    saida, feitos = {}, 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros = {k: ex.submit(revisar, t, g) for k, t in textos.items() if (t or "").strip()}
        for k, f in futuros.items():
            r = f.result()
            feitos += 1
            if feitos % 10 == 0:
                log(f"  textos revisados: {feitos}/{len(futuros)}")
            if r["sugerido"] != textos[k] or r["conferir"]:
                saida[k] = r
    return saida

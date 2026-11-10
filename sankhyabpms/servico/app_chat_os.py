# -*- coding: utf-8 -*-
"""
Chat x OS (09/11/2026, pedido do Fragoso): indicadores mensais do tempo gasto nos atendimentos do Total Chat e de
quanto desse tempo tem OS no Sankhya OM. Só lê: o CSV do mês vem de atendimentos_whatsapp/dados/ e as OS, do OM.

Os nomes de parceiros e contatos ficam no motor local e em dados/ (não vão para o GitHub).
"""
import glob
import importlib.util
import os
from datetime import timedelta

import pandas as pd

from nucleo import GERENTE, PASTAS, ErroUsuario, gravar_json_dados, ler_json_dados, marcar_uso, rota

PASTA = os.path.join(PASTAS["raiz"], "atendimentos_whatsapp")
PASTA_DADOS = os.path.join(PASTA, "dados")
PASTA_SAIDA = os.path.join(PASTA, "saida")
ARQ_HISTORICO = "chat_os_indicadores.json"
_mod = {}


def _motor():
    if "m" not in _mod:
        caminho = os.path.join(PASTA, "cruzamento_chat_os.py")
        if not os.path.exists(caminho):
            raise ErroUsuario(f"Não achei {caminho}.")
        spec = importlib.util.spec_from_file_location("cruzamento_chat_os", caminho)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _mod["m"] = m
    return _mod["m"]


def _csvs():
    """{"AAAA-MM": caminho}: mês pela moda de HrInicio; com dois arquivos do mesmo mês, vale o maior."""
    por_mes = {}
    for c in sorted(glob.glob(os.path.join(PASTA_DADOS, "*.csv"))):
        try:
            df = pd.read_csv(c, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False, usecols=["HrInicio"])
        except (ValueError, UnicodeDecodeError):
            continue
        datas = pd.to_datetime(df["HrInicio"], format="%m/%d/%Y %H:%M:%S", errors="coerce").dropna()
        if datas.empty:
            continue
        p = str(datas.dt.to_period("M").value_counts().idxmax())
        if p not in por_mes or len(datas) > por_mes[p][1]:
            por_mes[p] = (c, len(datas))
    return por_mes


def _historico():
    return ler_json_dados(ARQ_HISTORICO, {}) or {}


@rota("GET", "/api/chat-os/opcoes")
def opcoes(req):
    meses = [{"mes": m, "arquivo": os.path.basename(c), "linhas": n} for m, (c, n) in sorted(_csvs().items())]
    return 200, {"meses": meses, "historico": _historico(), "mensagens": _mensagens()}


PASTA_MENSAGENS = os.path.join(PASTA_DADOS, "mensagens")


def _mensagens():
    """Backups de mensagens do Total Chat guardados (só a coluna de horário, para mostrar o período)."""
    saida = []
    for c in sorted(glob.glob(os.path.join(PASTA_MENSAGENS, "*.csv"))):
        try:
            d = pd.read_csv(c, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False, usecols=["Horario"])
            t = pd.to_datetime(d["Horario"], format="%d/%m/%Y %H:%M:%S", errors="coerce").dropna()
            saida.append({"arquivo": os.path.basename(c), "mensagens": int(len(t)), "de": f"{t.min():%d/%m/%Y}" if len(t) else "", "ate": f"{t.max():%d/%m/%Y}" if len(t) else ""})
        except (ValueError, UnicodeDecodeError):
            continue
    return saida


@rota("POST", "/api/chat-os/enviar-mensagens")
def enviar_mensagens(req):
    """10/11/2026: backup de mensagens do Total Chat (Nome;Telefone;...;Texto;...;Horario;...). Fica só neste computador."""
    import base64
    import re
    nome = re.sub(r"[^\w.\- ()]", "_", os.path.basename(req.corpo.get("nome") or "mensagens.csv"))[:120]
    if not nome.lower().endswith(".csv"):
        raise ErroUsuario("Envie o .csv do backup de mensagens do Total Chat.")
    try:
        conteudo = base64.b64decode(req.corpo.get("conteudo_b64") or "", validate=True)
    except ValueError:
        raise ErroUsuario("Arquivo inválido.")
    cabecalho = conteudo[:400].decode("utf-8-sig", errors="ignore").splitlines()[0] if conteudo else ""
    if not all(c in cabecalho.split(";") for c in ("Telefone", "Texto", "Horario")):
        raise ErroUsuario("Este não parece o backup de mensagens: faltam as colunas Telefone, Texto e Horario.")
    os.makedirs(PASTA_MENSAGENS, exist_ok=True)
    destino, n = os.path.join(PASTA_MENSAGENS, nome), 1
    while os.path.exists(destino):
        base, ext = os.path.splitext(nome)
        destino, n = os.path.join(PASTA_MENSAGENS, f"{base} ({n}){ext}"), n + 1
    with open(destino, "wb") as f:
        f.write(conteudo)
    return 200, {"arquivo": os.path.basename(destino)}


@rota("POST", "/api/chat-os/gerar")
def gerar(req):
    mes_txt = str(req.corpo.get("mes") or "")
    csvs = _csvs()
    if mes_txt not in csvs:
        raise ErroUsuario("Escolha um mês da lista (envie o CSV do Total Chat se faltar).")
    from om_sessao import OM
    if OM.estado != "conectado":
        raise ErroUsuario("Conecte ao Sankhya-OM antes e faça o login na janela que abrir.")
    mes = pd.Period(mes_txt, "M")

    def trabalho(t):
        import app_om
        m = _motor()
        folga = timedelta(days=m.FOLGA_OM_DIAS)
        ini, fim = mes.start_time.date() - folga, mes.end_time.date() + folga
        om_df, _ = app_om.buscar_os(ini, fim, t.log)
        t.log("Cruzando os atendimentos com as OS...")
        hist = _historico()
        ind, pdf, xlsx = m.gerar(csvs[mes_txt][0], om_df, mes, PASTA_SAIDA, historico=hist, log=t.log, pasta_mensagens=PASTA_MENSAGENS)
        hist[mes_txt] = ind
        gravar_json_dados(ARQ_HISTORICO, hist)
        t.adicionar_arquivo("Relatório (PDF)", pdf)
        t.adicionar_arquivo("Planilha de conferência (Excel)", xlsx)
        marcar_uso("chat_os")
        msg = f"{ind['rotulo'].capitalize()}: {round(ind['pct_com_os'] * 100)}% do tempo com parceiros tem OS vinculada."
        if ind["sem_correspondencia"]:
            msg += " Sem correspondência no OM: " + ", ".join(ind["sem_correspondencia"]) + "."
        return {"mensagem": msg}

    t = GERENTE.iniciar("chat_os", "Chat x OS", trabalho, pasta=PASTA_SAIDA)
    return 200, {"tarefa": t.id}

# -*- coding: utf-8 -*-
"""
Sankhya-OM: conexão por login assistido (ver om_sessao.py) e consulta das OS
da tela "Consulta de OS" (entidade ItemOrdemServico), igual à que a tela faz
ao clicar em Aplicar: período de execução + executantes + tempo gasto > 0.

A consulta devolve a mesma tabela que a conferência já recebia do Experience
ou da planilha exportada do OM (colunas "Dt execução", "Núm. OS", ...), então
o motor de conferencia_os não muda. Diferença: entram as OS de todas as FAPs,
inclusive de outras BPs (horas cruzadas), porque o filtro é por executante.
Só leitura.
"""
import re

from nucleo import CONFIG, ErroUsuario, rota
from om_sessao import OM

# Executantes marcados na Consulta de OS do Fragoso (HAR de 06/10/2026).
# Dá para trocar em config.json, chave "om_executantes" (lista de CODUSU).
EXECUTANTES_PADRAO = [5147, 5224, 11886, 6514, 9863, 5163, 12870, 8695, 12464, 10435, 8591, 4818, 9800, 5447, 3960]

CAMPOS = ["NUMOS", "NUMITEM", "INICEXEC", "HRINICIAL", "HRFINAL", "INTERVALO", "TEMPGASTO", "CODUSU",
          "Executante.NOMEUSU", "SOLUCAO", "OrdemServico.NUFAP", "OrdemServico.CODPARC",
          "OrdemServico.Parceiro.NOMEPARC"]


def executantes():
    lista = CONFIG.get("om_executantes") or EXECUTANTES_PADRAO
    return [int(x) for x in lista]


def _hhmm(valor):
    """800 -> '08:00', 1830 -> '18:30' (formato HHMM do OM)."""
    s = re.sub(r"\D", "", str(valor or ""))
    if not s:
        return ""
    s = s.zfill(4)
    return f"{s[:-2].zfill(2)}:{s[-2:]}"


def _minutos(valor):
    """TEMPGASTO vem em minutos: 480 -> '08:00'."""
    try:
        m = int(float(valor))
    except (TypeError, ValueError):
        return ""
    return f"{m // 60:02d}:{m % 60:02d}"


def buscar_os(data_ini, data_fim, log=print):
    """Devolve (DataFrame no formato da conferência, total de OS lidas)."""
    codusus = executantes()
    log(f"Consultando OS no Sankhya-OM de {data_ini:%d/%m/%Y} a {data_fim:%d/%m/%Y} "
        f"({len(codusus)} executante(s))...")
    # 26/10/2026 (caso Jean, OS 7184247 de 15/10 sumida da conferência de 01 a 20/10): o OM
    # devolve no máximo 150 linhas por consulta e informa total=150, sem avisar que cortou.
    # Consulta em blocos de até 7 dias; bloco que bater no teto é dividido de novo (até 1 dia).
    linhas, i = _buscar_em_blocos(codusus, data_ini, data_fim, log), {c: n for n, c in enumerate(CAMPOS)}
    total = len(linhas)
    return _montar_df(linhas, i, total, log)


TETO_OM = 150


def _consultar_bloco(codusus, data_ini, data_fim):
    corpo = {
        "dataSetID": "001", "entityName": "ItemOrdemServico", "standAlone": True, "fields": CAMPOS,
        "tryJoinedFields": True, "parallelLoader": True,
        "crudListener": "br.com.sankhya.mgeserv.model.helpper.OSCRUDListener",
        "criteria": {
            "expression": (f"(this.INICEXEC >= ? AND this.INICEXEC <= ? AND this.CODUSU IN "
                           f"({','.join(map(str, codusus))})) AND (ItemOrdemServico.TEMPGASTO > 0)"),
            "parameters": [{"type": "D", "value": f"{data_ini:%d/%m/%Y}"},
                           {"type": "D", "value": f"{data_fim:%d/%m/%Y}"}],
        },
        "txProperties": {"nome.tela": "ConsultaOs"},
        "ignoreListenerMethods": "interceptMetadata", "useDefaultRowsLimit": False,
    }
    resp = OM.chamar("DatasetSP.loadRecords", corpo,
                     {"application": "ConsultaOS", "resourceID": "br.com.sankhya.os.con.consultaOs",
                      "allowConcurrentCalls": "true"})
    corpo_resp = resp.get("responseBody") or {}
    return corpo_resp.get("result") or []


def _buscar_em_blocos(codusus, data_ini, data_fim, log):
    from datetime import timedelta
    linhas, vistos = [], set()
    pendentes = []
    d = data_ini
    while d <= data_fim:
        pendentes.append((d, min(d + timedelta(days=6), data_fim)))
        d += timedelta(days=7)
    while pendentes:
        a, b = pendentes.pop(0)
        lote = _consultar_bloco(codusus, a, b)
        if len(lote) >= TETO_OM and a < b:
            meio = a + timedelta(days=(b - a).days // 2)
            pendentes[:0] = [(a, meio), (meio + timedelta(days=1), b)]
            continue
        if len(lote) >= TETO_OM:
            log(f"⚠ Em {a:%d/%m/%Y} o OM devolveu {len(lote)} OS (o teto da consulta): pode faltar OS nesse dia.")
        for l in lote:
            chave = (l[0], l[1])  # NUMOS, NUMITEM
            if chave not in vistos:
                vistos.add(chave)
                linhas.append(l)
    return linhas


def _montar_df(linhas, i, total, log):
    import pandas as pd
    from dados_conferencia import _garantir_coluna_tag_clickup, eh_pessoa_excluida_sankhya
    registros, excluidas = [], 0
    for l in linhas:
        nome = l[i["Executante.NOMEUSU"]]
        if eh_pessoa_excluida_sankhya(nome):
            excluidas += 1
            continue
        registros.append({
            "Dt execução": l[i["INICEXEC"]],
            "Núm. OS": l[i["NUMOS"]],
            "Sub-OS": l[i["NUMITEM"]],
            "Nome (Executante)": nome,
            "Número Unico FAP": l[i["OrdemServico.NUFAP"]],
            "Nome Parceiro (Parceiro)": l[i["OrdemServico.Parceiro.NOMEPARC"]],
            "Cód. Parceiro": l[i["OrdemServico.CODPARC"]],
            "Tempo gasto": _minutos(l[i["TEMPGASTO"]]),
            "Hora Inicial": _hhmm(l[i["HRINICIAL"]]),
            "Hora Final": _hhmm(l[i["HRFINAL"]]),
            "Intervalo": _hhmm(l[i["INTERVALO"]]),
            "Nro.único do pedido": "",
            "Solução": l[i["SOLUCAO"]],
        })
    if excluidas:
        log(f"  {excluidas} OS de pessoas excluídas (Elson/Capulo) ignoradas.")
    colunas = ["Dt execução", "Núm. OS", "Sub-OS", "Nome (Executante)", "Número Unico FAP",
               "Nome Parceiro (Parceiro)", "Cód. Parceiro", "Tempo gasto", "Hora Inicial", "Hora Final", "Intervalo",
               "Nro.único do pedido", "Solução"]
    df = _garantir_coluna_tag_clickup(pd.DataFrame(registros, columns=colunas))
    log(f"{len(df)} OS lidas do Sankhya-OM (de {len(set(df['Número Unico FAP']))} FAP(s)). Nada foi alterado no OM.")
    return df, total


@rota("POST", "/api/om/conectar")
def conectar(req):
    OM.conectar()
    return 200, OM.status()


@rota("GET", "/api/om/status")
def status(req):
    return 200, OM.status()


@rota("POST", "/api/om/teste")
def teste(req):
    """Consulta de leitura para conferir a conexão: devolve quantas OS há no período."""
    from nucleo import periodo_br
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    msgs = []
    df, total = buscar_os(ini, fim, msgs.append)
    if df is None:
        raise ErroUsuario("Sem resposta do OM.")
    amostra = df.head(5)[["Dt execução", "Núm. OS", "Nome (Executante)", "Número Unico FAP",
                          "Nome Parceiro (Parceiro)", "Hora Inicial", "Hora Final", "Tempo gasto"]]
    return 200, {"total": total, "lidas": len(df), "faps": sorted(set(map(str, df["Número Unico FAP"]))),
                 "os": [f"{o}/{s}" for o, s in zip(df["Núm. OS"], df["Sub-OS"])],
                 "amostra": amostra.to_dict("records"), "log": msgs}


@rota("GET", "/api/om/diagnostico")
def diagnostico(req):
    from om_sessao import diagnostico as d
    return 200, d()


# ----------------------------------------------------------------------------
# Relatório das OS de um parceiro (16/10/2026, pedido do Fragoso): as mesmas
# informações da tela Consulta de OS do OM, filtradas por parceiro. Só leitura.
# ----------------------------------------------------------------------------
def _html_relatorio_parceiro(parceiro, ini, fim, df, gerado_em):
    from html import escape as e

    def minutos(h):
        try:
            hh, mm = str(h).split(":")[:2]
            return int(hh) * 60 + int(mm)
        except ValueError:
            return 0
    total = sum(minutos(h) for h in df["Tempo gasto"])
    por_exec = df.groupby("Nome (Executante)")["Tempo gasto"].agg(lambda s: sum(minutos(h) for h in s))
    por_fap = df.groupby("Número Unico FAP")["Tempo gasto"].agg(lambda s: sum(minutos(h) for h in s))
    hm = lambda m: f"{m // 60:02d}:{m % 60:02d}"
    resumo = "".join(f"<tr><td>{e(str(k))}</td><td class='c'>{int((df['Nome (Executante)'] == k).sum())}</td>"
                     f"<td class='c'>{hm(v)}</td></tr>" for k, v in por_exec.sort_values(ascending=False).items())
    faps = " · ".join(f"FAP {e(str(k))}: {hm(v)}" for k, v in por_fap.items())
    linhas = "".join(
        f"<tr><td>{e(str(r['Dt execução']))}</td><td>{e(str(r['Núm. OS']))}</td><td>{e(str(r['Nome (Executante)']))}</td>"
        f"<td>{e(str(r['Número Unico FAP']))}</td><td class='c'>{e(str(r['Hora Inicial']))}–{e(str(r['Hora Final']))}</td>"
        f"<td class='c'>{e(str(r['Intervalo']))}</td><td class='c'><b>{e(str(r['Tempo gasto']))}</b></td>"
        f"<td class='sol'>{e(str(r['Solução'] or '')).replace(chr(10), '<br>')}</td></tr>"
        for _, r in df.iterrows())
    nome_parc = e(str(df["Nome Parceiro (Parceiro)"].iloc[0])) if len(df) else e(parceiro)
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>OS {nome_parc}</title>
<style>@page{{size:A4 landscape;margin:12mm}} body{{font-family:Segoe UI,Arial,sans-serif;color:#14211b;font-size:11px}}
h1{{color:#0a7a52;font-size:20px;margin:0}} .sub{{color:#5b6b63;margin:4px 0 14px}}
.box{{border:2px solid #0a7a52;background:#e5f3ec;border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:12px}}
table{{border-collapse:collapse;width:100%}} th{{background:#0a7a52;color:#fff;text-align:left;padding:6px}}
td{{border-bottom:1px solid #d7e0db;padding:5px 6px;vertical-align:top}} tr:nth-child(even) td{{background:#f3f6f4}}
.c{{text-align:center;white-space:nowrap}} .sol{{font-size:10px;color:#33443c}} tr{{break-inside:avoid}}
th,td{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}</style></head><body>
<h1>Ordens de Serviço — {nome_parc}</h1>
<div class="sub">Execução de {ini:%d/%m/%Y} a {fim:%d/%m/%Y} · fonte: Sankhya-OM (Consulta de OS) · gerado em {gerado_em}</div>
<div class="box"><b>{len(df)} OS</b> · <b>{hm(total)}</b> horas realizadas · {faps}
<table style="margin-top:8px;width:auto;min-width:50%"><tr><th>Executante</th><th class="c">OS</th><th class="c">Horas</th></tr>{resumo}</table></div>
<table><tr><th>Execução</th><th>Nº OS</th><th>Executante</th><th>FAP</th><th class="c">Horário</th><th class="c">Intervalo</th>
<th class="c">Tempo gasto</th><th>Solução</th></tr>{linhas}</table></body></html>"""


@rota("POST", "/api/om/relatorio-parceiro")
def relatorio_parceiro(req):
    import os
    from datetime import datetime
    from nucleo import GERENTE, ErroUsuario, dados_arquivo, periodo_br
    from clickup_sync.text_matching import normalizar_texto
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    parceiro = (req.corpo.get("parceiro") or "").strip()
    if not parceiro:
        raise ErroUsuario("Informe o parceiro.")
    if OM.status().get("estado") != "conectado":
        raise ErroUsuario("O Sankhya-OM não está conectado. Conecte pela tela da Conferência de OS.")

    def trabalho(t):
        df, _ = buscar_os(ini, fim, t.log)
        alvo = normalizar_texto(parceiro)
        df = df[df["Nome Parceiro (Parceiro)"].map(lambda n: alvo in normalizar_texto(n or ""))].copy()
        df["_ord"] = df["Dt execução"].map(lambda d: datetime.strptime(str(d)[:10], "%d/%m/%Y") if d else datetime.min)
        df = df.sort_values(["_ord", "Hora Inicial"]).drop(columns="_ord")
        t.log(f"{len(df)} OS do parceiro '{parceiro}' no período.")
        if df.empty:
            return {"mensagem": f"Nenhuma OS do parceiro '{parceiro}' entre {ini:%d/%m/%Y} e {fim:%d/%m/%Y}."}
        os.makedirs(dados_arquivo("relatorios"), exist_ok=True)
        base = os.path.join(dados_arquivo("relatorios"), f"OS {parceiro} {ini:%d-%m-%Y} a {fim:%d-%m-%Y}")
        df.drop(columns=[c for c in ("Tag ClickUp", "Nro.único do pedido") if c in df.columns]).to_excel(base + ".xlsx", index=False)
        t.adicionar_arquivo("OS do parceiro (.xlsx)", base + ".xlsx")
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(_html_relatorio_parceiro(parceiro, ini, fim, df, datetime.now().strftime("%d/%m/%Y às %Hh%M")))
        t.adicionar_arquivo("Relatório (HTML)", base + ".html")
        try:
            from pdf_relatorio import html_para_pdf
            t.adicionar_arquivo("Relatório (PDF)", html_para_pdf(base + ".html"))
        except Exception as e:
            t.log(f"⚠ PDF não gerado ({e}); o HTML e o Excel estão prontos.")
        return {"mensagem": f"Relatório gerado: {len(df)} OS de {parceiro}. Nada foi alterado no OM.",
                "resultado": {"pasta": dados_arquivo("relatorios"), "arquivo": base}}

    t = GERENTE.iniciar("om_relatorio", f"OS do parceiro {parceiro} (OM, só leitura)", trabalho)
    return 200, {"tarefa": t.id}

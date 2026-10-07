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
    """Devolve (DataFrame no formato da conferência, total informado pelo OM)."""
    import pandas as pd
    from dados_conferencia import _garantir_coluna_tag_clickup, eh_pessoa_excluida_sankhya

    codusus = executantes()
    log(f"Consultando OS no Sankhya-OM de {data_ini:%d/%m/%Y} a {data_fim:%d/%m/%Y} "
        f"({len(codusus)} executante(s))...")
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
    linhas = corpo_resp.get("result") or []
    total = int(corpo_resp.get("total") or len(linhas))
    if total != len(linhas):
        log(f"⚠ O OM informou {total} OS mas devolveu {len(linhas)}. Confira o período.")
    i = {c: n for n, c in enumerate(CAMPOS)}
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

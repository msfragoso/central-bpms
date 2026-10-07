# -*- coding: utf-8 -*-
"""
Gera, pela API do ClickUp, o mesmo CSV que a exportação manual da visualização
"Visão para IA" (https://app.clickup.com/9013912851/v/gr/8cmat8k-12653).

O endpoint da própria visualização (GET /view/{id}/task) não devolve subtarefas,
e as tarefas da conferência são subtarefas ("2026-09 Setembro" etc.). Por isso
os filtros da visualização são reproduzidos na busca de tarefas do workspace
(GET /team/{id}/task, com subtasks=true), lidos da própria visualização a cada
execução, só trocando o período fixo dela pelo período da conferência.

Só leitura. O CSV gerado tem as colunas e formatos da exportação do ClickUp
que os motores de conferencia_os usam, então nada nos motores muda.
"""
import csv
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

VIEW_ID = "8cmat8k-12653"
FUSO = ZoneInfo("America/Campo_Grande")
POR_PAGINA = 100

# Rótulos que a exportação do ClickUp usa entre parênteses: "Parceiro (drop down)"
ROTULO_TIPO = {
    "drop_down": "drop down", "formula": "formula", "short_text": "short text", "text": "text",
    "number": "number", "date": "date", "labels": "labels", "users": "users", "currency": "currency",
    "checkbox": "checkbox", "url": "url", "email": "email", "phone": "phone", "emoji": "rating",
}


def _get(url, headers, params=None, tentativas=6):
    for i in range(tentativas):
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code == 429:  # limite de requisições: espera e tenta de novo
            time.sleep(min(60, 5 * (i + 1)))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("ClickUp recusou por limite de requisições várias vezes seguidas.")


def _ms(d, fim=False):
    """date -> ms no fuso local (início do dia, ou início do dia seguinte se fim=True)."""
    dia = d + timedelta(days=1) if fim else d
    return int(datetime(dia.year, dia.month, dia.day, tzinfo=FUSO).timestamp() * 1000)


def _filtros_da_visao(api, headers):
    vw = _get(f"{api}/view/{VIEW_ID}", headers)["view"]
    space_id = (vw.get("parent") or {}).get("id")
    incluir_qualquer, excluir = {}, {}
    for f in (vw.get("filters") or {}).get("fields", []):
        campo = f.get("field", "")
        if not campo.startswith("cf_"):
            continue  # responsável e data: o período vem da conferência; responsável vazio o motor já tira
        cf = campo[3:]
        if f.get("op") == "EQ":
            incluir_qualquer[cf] = set(map(str, f.get("values") or []))
        elif f.get("op") == "NOT":
            excluir[cf] = set(map(str, f.get("values") or []))
    return space_id, incluir_qualquer, excluir, bool((vw.get("filters") or {}).get("show_closed", True))


def _valor_dropdown(cf):
    v = cf.get("value")
    if v is None or v == "":
        return None
    for i, o in enumerate((cf.get("type_config") or {}).get("options", [])):
        if str(o.get("id")) == str(v) or (isinstance(v, int) and o.get("orderindex") == v) or i == v:
            return o.get("name")
    return None


def _id_dropdown(cf):
    v = cf.get("value")
    if v is None or v == "":
        return None
    for o in (cf.get("type_config") or {}).get("options", []):
        if str(o.get("id")) == str(v) or o.get("orderindex") == v:
            return str(o.get("id"))
    return str(v)


def _texto_cf(cf):
    t = cf.get("type")
    v = cf.get("value")
    if t == "drop_down":
        return _valor_dropdown(cf)
    if t == "labels":
        ops = {str(o.get("id")): o.get("label") for o in (cf.get("type_config") or {}).get("options", [])}
        return ", ".join(ops.get(str(x), str(x)) for x in (v or [])) or None
    if t == "users":
        return ", ".join(u.get("username") or "" for u in (v or [])) or None
    if v is None or v == "":
        return None
    return str(v)


def _tempo_logado(ms):
    if not ms:
        return None
    minutos = int(round(int(ms) / 60000))
    h, m = divmod(minutos, 60)
    return " ".join(p for p in (f"{h}h" if h else "", f"{m}m" if m else "") if p) or None


def buscar_tarefas(api, headers, data_ini, data_fim, log=print):
    """Tarefas da visualização com vencimento entre data_ini e data_fim (inclusive)."""
    space_id, incluir, excluir, fechadas = _filtros_da_visao(api, headers)
    team_id = _get(f"{api}/team", headers)["teams"][0]["id"]
    params = {
        "space_ids[]": space_id, "subtasks": "true", "include_closed": str(fechadas).lower(),
        "due_date_gt": _ms(data_ini) - 1, "due_date_lt": _ms(data_fim, fim=True),
        "order_by": "due_date",
    }
    tarefas, pagina = [], 0
    while True:
        params["page"] = pagina
        lote = _get(f"{api}/team/{team_id}/task", headers, params).get("tasks", [])
        tarefas.extend(lote)
        log(f"  ClickUp: página {pagina + 1}, {len(tarefas)} tarefa(s) lida(s)...")
        if len(lote) < POR_PAGINA:
            break
        pagina += 1

    def passa(t):
        if not t.get("assignees"):  # filtro "Responsável: definido" da visualização
            return False
        cfs = {c.get("id"): c for c in t.get("custom_fields", [])}
        for cf_id, permitidos in incluir.items():
            if _id_dropdown(cfs.get(cf_id, {})) not in permitidos:
                return False
        for cf_id, proibidos in excluir.items():
            if _id_dropdown(cfs.get(cf_id, {})) in proibidos:
                return False
        return True

    filtradas = [t for t in tarefas if passa(t)]
    log(f"  {len(filtradas)} tarefa(s) batem com os filtros da visualização.")
    return filtradas


def _data_ms(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, FUSO)


def _linha(t, nomes_pais):
    d = {
        "Task Type": "Task",
        "Task ID": t.get("id"),
        "Task Name": t.get("name"),
        "Parent ID": t.get("parent"),
        "Parent Name": nomes_pais.get(t.get("parent")),
        "Status": (t.get("status") or {}).get("status"),
        "Assignee": "[" + ", ".join(a.get("username") or "" for a in t.get("assignees", [])) + "]",
        "Space": (t.get("space") or {}).get("name"),
        "Folder": (t.get("folder") or {}).get("name"),
        "List": (t.get("list") or {}).get("name"),
        "Time Logged": _tempo_logado(t.get("time_spent")),
        "Due Date": (_data_ms(t.get("due_date")) or None) and _data_ms(t.get("due_date")).strftime("%d/%m/%Y"),
    }
    for cf in t.get("custom_fields", []):
        tipo = cf.get("type")
        if tipo == "multi_key":
            continue
        d[f"{cf.get('name')} ({ROTULO_TIPO.get(tipo, tipo)})"] = _texto_cf(cf)
    # "Data" é a fórmula DAY/MONTH/YEAR(TASK_DUE_DATE). A API às vezes devolve o
    # valor antigo da fórmula depois que o vencimento muda (visto em 06/10/2026,
    # tarefa 86akp2xen: API "3/10/2026", vencimento e CSV "6/10/2026"), então o
    # valor é recalculado do próprio vencimento, no mesmo formato D/M/AAAA.
    if "Data (formula)" in d:
        venc = _data_ms(t.get("due_date"))
        d["Data (formula)"] = f"{venc.day}/{venc.month}/{venc.year}" if venc else None
    return d


def gerar_csv(caminho, data_ini, data_fim, log=print):
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS
    log(f"Lendo a visualização 'Visão para IA' do ClickUp ({data_ini:%d/%m/%Y} a {data_fim:%d/%m/%Y})...")
    tarefas = buscar_tarefas(CLICKUP_API, CLICKUP_HEADERS, data_ini, data_fim, log)
    ids = {t.get("id") for t in tarefas}
    nomes_pais = {t.get("id"): t.get("name") for t in tarefas}
    for pai in {t.get("parent") for t in tarefas if t.get("parent") and t.get("parent") not in ids}:
        try:
            nomes_pais[pai] = _get(f"{CLICKUP_API}/task/{pai}", CLICKUP_HEADERS).get("name")
        except Exception:
            nomes_pais[pai] = None
    linhas = [_linha(t, nomes_pais) for t in tarefas]
    colunas = []
    for l in linhas:
        for k in l:
            if k not in colunas:
                colunas.append(k)
    if not colunas:
        colunas = ["Task ID", "Task Name", "Status", "Assignee", "List", "Data (formula)"]
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=colunas)
        w.writeheader()
        for l in linhas:
            w.writerow({k: ("" if v is None else v) for k, v in l.items()})
    log(f"CSV do ClickUp gerado: {len(linhas)} tarefa(s).")
    return caminho, len(linhas)

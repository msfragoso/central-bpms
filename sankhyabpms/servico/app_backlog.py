# -*- coding: utf-8 -*-
"""
Painel Backlog Base (22/10/2026): todas as tarefas (e subtarefas) do espaço
PMO BP-MS com Status = "backlog base", lidas pela API oficial do ClickUp.
Só leitura -- nada é alterado no ClickUp.
"""
import time
from datetime import datetime

from nucleo import ErroUsuario, marcar_uso, rota

STATUS = "backlog base"
TEAM_ID = "9013912851"
CAMPOS = ("Agendamento", "Parceiro", "Usuário cliente", "Origem", "Data", "Período", "Etapa", "Módulo", "Apontamento")
PRIORIDADE = {"urgent": "Urgente", "high": "Alta", "normal": "Normal", "low": "Baixa"}


def _get(url, headers, params):
    import requests
    for i in range(6):
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code == 429:  # limite de requisições
            time.sleep(min(60, 5 * (i + 1)))
            continue
        if r.status_code == 401:
            raise ErroUsuario("O ClickUp recusou o token (401). Confira o token do ClickUp no cofre.")
        r.raise_for_status()
        return r.json()
    raise ErroUsuario("ClickUp recusou por limite de requisições várias vezes seguidas.")


def _valor(cf):
    v = cf.get("value")
    if v is None or v == "":
        return None, None
    if cf.get("type") == "drop_down":
        for i, o in enumerate((cf.get("type_config") or {}).get("options", [])):
            if str(o.get("id")) == str(v) or o.get("orderindex") == v or i == v:
                return o.get("name"), o.get("color")
        return None, None
    if cf.get("type") == "date":
        try:
            return datetime.fromtimestamp(int(v) / 1000).strftime("%d/%m/%Y"), None
        except (TypeError, ValueError):
            return None, None
    return str(v), None


def _data(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000) if ms else None
    except (TypeError, ValueError):
        return None


@rota("GET", "/api/backlog/status")
def lista_status(req):
    """Status do espaço PMO BP-MS, na ordem do ClickUp (para o filtro da tela)."""
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS, SPACE_ID_PMO_BP_MS
    sp = _get(f"{CLICKUP_API}/space/{SPACE_ID_PMO_BP_MS}", CLICKUP_HEADERS, None)
    return 200, {"status": [{"nome": s.get("status"), "cor": s.get("color")} for s in sp.get("statuses") or []],
                 "padrao": STATUS}


@rota("GET", "/api/backlog/tarefas")
def tarefas(req):
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS, SPACE_ID_PMO_BP_MS
    # 22/10/2026: filtro por status na tela (?status=a,b); sem nada, só "backlog base"
    escolhidos = [x.strip() for x in (req.query.get("status") or "").split(",") if x.strip()] or [STATUS]
    saida, pagina = [], 0
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    while True:
        r = _get(f"{CLICKUP_API}/team/{TEAM_ID}/task", CLICKUP_HEADERS, {
            "space_ids[]": SPACE_ID_PMO_BP_MS, "statuses[]": escolhidos, "subtasks": "true",
            "include_closed": "true", "page": pagina,
        })
        lote = r.get("tasks") or []
        for t in lote:
            campos, cores = {}, {}
            for cf in t.get("custom_fields") or []:
                if cf.get("name") in CAMPOS:
                    campos[cf["name"]], cores[cf["name"]] = _valor(cf)
            criada, venc = _data(t.get("date_created")), _data(t.get("due_date"))
            pr = (t.get("priority") or {})
            saida.append({
                "id": t.get("id"),
                "nome": t.get("name"),
                "status": (t.get("status") or {}).get("status") or "",
                "status_cor": (t.get("status") or {}).get("color") or "",
                "url": t.get("url") or f"https://app.clickup.com/t/{t.get('id')}",
                "pasta": (t.get("folder") or {}).get("name") or "",
                "lista": (t.get("list") or {}).get("name") or "",
                "responsaveis": [a.get("username") or a.get("email") or "" for a in t.get("assignees") or []],
                "criada": criada.strftime("%d/%m/%Y") if criada else "",
                "criada_ms": int(t.get("date_created") or 0),
                "vencimento_ms": int(t.get("due_date") or 0),
                "prioridade_ordem": int(pr.get("orderindex") or 9),
                "dias_fila": (hoje - criada.replace(hour=0, minute=0, second=0, microsecond=0)).days if criada else None,
                "vencimento": venc.strftime("%d/%m/%Y") if venc else "",
                "vencida": bool(venc and venc < hoje),
                "prioridade": PRIORIDADE.get(pr.get("priority"), ""),
                "prioridade_cor": pr.get("color") or "",
                "campos": campos,
                "cores": {k: v for k, v in cores.items() if v},
            })
        if r.get("last_page", True) or not lote:
            break
        pagina += 1
    marcar_uso("backlog")
    return 200, {"tarefas": saida, "atualizado": datetime.now().strftime("%d/%m/%Y %H:%M")}

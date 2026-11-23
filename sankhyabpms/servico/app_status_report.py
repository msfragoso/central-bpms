# -*- coding: utf-8 -*-
"""
Relatório de Status Report (23/11/2026, pedido do Fragoso): horas de um parceiro num período,
por frente de trabalho (ou etapa) e por consultor.

Fontes (só leitura):
  - Sankhya-OM: Consulta de OS do período (app_om.buscar_os, em blocos por causa do teto de 150).
  - ClickUp: tarefas da pasta do parceiro no espaço PMO BP-MS (campo "OS Sankhya", Etapa,
    Apontamento, demanda de origem).

Fluxo da tela: 1) Buscar -> prévia editável (frente, consultor, atividade, incluir/excluir);
2) Gerar -> HTML + PDF + Excel em dados/relatorios. Nada é alterado no OM nem no ClickUp.

Regras:
  - Horas = tempo gasto da OS no OM (já sem intervalo).
  - Apontamento "Bonificado (Apontamento OS)" -> "Bonificado em OS".
  - Tarefas "Bonificado (Planilha)" e "Planilha - Serviços" sem OS -> "Bonificado em planilha" (rótulo só "Planilha"),
    sem duplicar: mesmo consultor, dia e horário de outro lançamento fica fora (23/11/2026, Fragoso).
  - Tarefas sem OS no OM e OS de outro parceiro vêm desmarcadas, com o motivo.
  - Os dados de clientes ficam só neste computador (dados/), nunca no GitHub.
"""
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import escape as e

from nucleo import (GERENTE, ErroUsuario, dados_arquivo, gravar_json_dados, ler_json_dados, marcar_uso,
                    periodo_br, rota)

SPACE_PMO = "90133723590"
ARQ_RASCUNHO = "status_report_rascunho.json"
ARQ_NOMES = "status_report_nomes.json"
TIPOS = {"OS": "Horas em OS", "BONIF_OS": "Bonificado em OS", "PLANILHA": "Bonificado em planilha"}
CORES = {"OS": "#3A6FB0", "BONIF_OS": "#3AA552", "PLANILHA": "#C2410C"}
# Nomes dos consultores no relatório (login do OM -> nome). Vêm do ClickUp e podem ser corrigidos
# na tela; ficam lembrados em dados/status_report_nomes.json (só neste computador, fora do GitHub).
NOMES_PADRAO = {}


# ============================================================================ ClickUp (leitura)
def _api():
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS
    return CLICKUP_API, CLICKUP_HEADERS


def _get(caminho, params=None):
    import clickup_visao as V
    api, cab = _api()
    return V._get(f"{api}{caminho}", cab, params)


_cache_pastas = {}


@rota("GET", "/api/status-report/pastas")
def pastas(req):
    """Pastas (parceiros) do espaço PMO BP-MS, para escolher na tela."""
    if not _cache_pastas or time.time() - _cache_pastas.get("em", 0) > 3600 or req.query.get("recarregar"):
        r = _get(f"/space/{SPACE_PMO}/folder", {"archived": "false"})
        _cache_pastas["lista"] = sorted(({"id": f["id"], "nome": f["name"]} for f in r.get("folders", [])),
                                        key=lambda x: x["nome"].lower())
        _cache_pastas["em"] = time.time()
    return 200, {"pastas": _cache_pastas["lista"]}


@rota("GET", "/api/status-report/rascunho")
def rascunho(req):
    return 200, ler_json_dados(ARQ_RASCUNHO, {}) or {}


def _cf(t):
    import clickup_visao as V
    return {c.get("name"): (V._texto_cf(c) or "") for c in t.get("custom_fields", [])}


def _data_tarefa(t, cf):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", cf.get("Data") or "")
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    if t.get("due_date"):  # vencimento só com data: o ClickUp grava meia-noite UTC
        return datetime.fromtimestamp(int(t["due_date"]) / 1000, timezone.utc).date()
    return None


def _tarefas_da_pasta(pasta_id, ini, fim, log):
    listas = _get(f"/folder/{pasta_id}/list", {"archived": "false"}).get("lists", [])
    ms = lambda d: int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
    tarefas = []
    for li in listas:
        pagina = 0
        while True:
            lote = _get(f"/list/{li['id']}/task", {
                "subtasks": "true", "include_closed": "true", "page": pagina,
                "due_date_gt": ms(ini - timedelta(days=1)), "due_date_lt": ms(fim + timedelta(days=2)),
            }).get("tasks", [])
            tarefas.extend(lote)
            if len(lote) < 100:
                break
            pagina += 1
    log(f"ClickUp: {len(tarefas)} tarefa(s) em {len(listas)} lista(s) da pasta.")
    return tarefas


def _cadeia_pais(tarefas, log):
    """{id: (nome, pai)} das tarefas e de todos os pais acima delas."""
    info = {t["id"]: (t.get("name"), t.get("parent")) for t in tarefas}
    faltam = {p for _, p in info.values() if p and p not in info}
    while faltam:
        for pid in list(faltam):
            try:
                t = _get(f"/task/{pid}")
                info[pid] = (t.get("name"), t.get("parent"))
            except Exception:
                info[pid] = ("", None)
        faltam = {p for _, p in info.values() if p and p not in info}
    return info


def _demanda(tid, info):
    """Nome da demanda de origem: a tarefa mais alta da cadeia. Atendimento Base/mês -> atendimentos avulsos."""
    cadeia, atual = [], info.get(tid, ("", None))[1]
    while atual:
        cadeia.append(info.get(atual, ("", None))[0] or "")
        atual = info.get(atual, ("", None))[1]
    if not cadeia:
        return ""
    topo = cadeia[-1]
    if re.search(r"atendimento base", topo, re.I) or all(re.match(r"\d{4}-\d{2}\b", c) or re.search(r"atendimento base", c, re.I) for c in cadeia):
        return "Atendimentos avulsos"
    return topo


def _etapa_metodologia(etapa):
    """'58 - Configuração em linha - 5.0 - Projeto Inicial' -> 'Configuração em linha'."""
    m = re.match(r"\s*\d+\s*-\s*(.+?)\s*-\s*(5\.0|RH|Trilha)", etapa or "")
    return m.group(1).replace("Folha | ", "") if m else ""


def _horas_periodo(txt):
    m = re.match(r"(\d{1,2})h-(\d{1,2})h", txt or "")
    return float(int(m[2]) - int(m[1])) if m else 0.0


# ============================================================================ texto da OS
def _atividade(solucao):
    """Limpa o texto da OS para o relatório (o Fragoso ajusta na prévia, se quiser)."""
    s = str(solucao or "")
    if "--- Informações Adicionais ---" in s:
        s = s.split("--- Informações Adicionais ---", 1)[1]
    s = re.sub(r"(?im)^\s*(Etapa|Processos):.*$", "", s)
    s = re.sub(r"\[[A-Z ]+\]|\*\*|#", "", s)
    s = re.sub(r"(?i)^\s*(atendimento (interno|presencial|remoto)|remoto|interno)\s*-*\s*", "", s.strip())
    s = re.sub(r"\s+", " ", s).strip(" -;")
    letras = [c for c in s if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) > 0.6:  # texto todo em maiúsculas
        s = s.lower()
    s = s[:1].upper() + s[1:]
    if len(s) > 260:
        corte = s[:260]
        p = max(corte.rfind(". "), corte.rfind("; "))
        s = corte[:p + 1] if p > 80 else corte.rsplit(" ", 1)[0] + "…"
    return s


def _min(h):
    try:
        a, b = str(h).split(":")[:2]
        return int(a) * 60 + int(b)
    except ValueError:
        return 0


# ============================================================================ 1) buscar
@rota("POST", "/api/status-report/buscar")
def buscar(req):
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    pasta_id = str(req.corpo.get("pasta_id") or "").strip()
    pasta_nome = str(req.corpo.get("pasta_nome") or "").strip()
    nome_om = str(req.corpo.get("nome_om") or "").strip()
    if not pasta_id:
        raise ErroUsuario("Escolha a pasta do parceiro no ClickUp.")
    from om_sessao import OM
    if OM.status().get("estado") != "conectado":
        raise ErroUsuario("O Sankhya-OM não está conectado. Conecte e tente de novo.")

    def trabalho(t):
        import app_om
        from clickup_sync.text_matching import normalizar_texto
        tarefas = _tarefas_da_pasta(pasta_id, ini, fim, t.log)
        info = _cadeia_pais(tarefas, t.log)
        t.log("Lendo as OS do período no Sankhya-OM (só leitura)...")
        df, _ = app_om.buscar_os(ini, fim, t.log)
        por_os = {}
        for _, r in df.iterrows():
            por_os.setdefault(str(r["Núm. OS"]), []).append(r)

        maes = {x[1] for x in info.values() if x[1]}
        ck_todas = []  # tarefas com os campos que importam (a OS casa mesmo se a data do ClickUp estiver fora)
        for tk in tarefas:
            cf = _cf(tk)
            d = _data_tarefa(tk, cf)
            if not d:
                continue
            if tk.get("id") in maes and not cf.get("OS Sankhya"):
                continue  # tarefa-mãe (planejamento), as horas estão nas subtarefas
            ck_todas.append({"id": tk["id"], "nome": tk.get("name"), "data": d, "cf": cf,
                       "status": ((tk.get("status") or {}).get("status") or "").lower(),
                       "fechada": (tk.get("status") or {}).get("type") == "closed" or bool(tk.get("date_closed")),
                       "resp": ", ".join(a.get("username") or "" for a in tk.get("assignees", [])),
                       "est": (tk.get("time_estimate") or 0) / 3600000,
                       "demanda": _demanda(tk["id"], info), "etapa": _etapa_metodologia(cf.get("Etapa"))})
        ck = [c for c in ck_todas if ini <= c["data"] <= fim]
        os_ck = {}
        for c in ck_todas:
            for n in re.findall(r"\d{6,8}", c["cf"].get("OS Sankhya") or ""):
                os_ck.setdefault(n, []).append(c)

        # parceiro no OM: o código que mais aparece nas OS ligadas às tarefas (ou o nome informado)
        codigos = Counter(str(r["Cód. Parceiro"]) for n in os_ck for r in por_os.get(n, []))
        if codigos:
            cod = codigos.most_common(1)[0][0]
            do_parc = df[df["Cód. Parceiro"].astype(str) == cod]
        elif nome_om:
            alvo = normalizar_texto(nome_om)
            do_parc = df[df["Nome Parceiro (Parceiro)"].map(lambda n: alvo in normalizar_texto(n or ""))]
            cod = str(do_parc["Cód. Parceiro"].iloc[0]) if len(do_parc) else ""
        else:
            raise ErroUsuario("Nenhuma OS das tarefas desta pasta foi achada no OM no período. "
                              "Informe o nome do parceiro como está no OM.")
        nome_parc = str(do_parc["Nome Parceiro (Parceiro)"].iloc[0]) if len(do_parc) else nome_om
        faps = sorted({str(x) for x in do_parc["Número Unico FAP"]})
        t.log(f"Parceiro no OM: {cod} - {nome_parc} · {len(do_parc)} OS · FAP(s) {', '.join(faps)}")

        nomes = {**NOMES_PADRAO, **(ler_json_dados(ARQ_NOMES, {}) or {})}
        implantacao = sum(1 for c in ck if c["etapa"]) > len(ck) / 2
        linhas, usadas = [], set()
        for _, r in do_parc.iterrows():
            n = str(r["Núm. OS"])
            tks = os_ck.get(n, [])
            c = tks[0] if tks else None
            login = str(r["Nome (Executante)"])
            if login not in nomes and c and c["resp"]:
                nomes[login] = c["resp"].split(",")[0].strip().title()
            tipo = "BONIF_OS" if c and "Bonificado (Apontamento OS)" in c["cf"].get("Apontamento", "") else "OS"
            frente = (c["etapa"] if implantacao and c and c["etapa"] else (c["demanda"] if c else "")) or "Outros atendimentos"
            linhas.append({"incluir": True, "data": str(r["Dt execução"])[:10], "os": n, "login": login,
                           "consultor": nomes.get(login, login.replace(".", " ").title()), "frente": frente, "tipo": tipo,
                           "horas": round(_min(r["Tempo gasto"]) / 60, 2),
                           "horario": f"{r['Hora Inicial']}-{r['Hora Final']}", "atividade": _atividade(r["Solução"]),
                           "tarefa": c["nome"] if c else "", "tarefa_id": c["id"] if c else "",
                           "motivo": "" if c else "OS sem tarefa no ClickUp"})
            usadas.update(x["id"] for x in tks)
        for c in ck:
            if c["id"] in usadas:
                continue
            ap = c["cf"].get("Apontamento", "")
            nums = re.findall(r"\d{6,8}", c["cf"].get("OS Sankhya") or "")
            horas = round(c["est"] or _horas_periodo(c["cf"].get("Período")), 2)
            base = {"data": c["data"].strftime("%d/%m/%Y"), "os": "", "login": "", "consultor": c["resp"].split(",")[0].strip().title(),
                    "frente": (c["etapa"] if implantacao and c["etapa"] else c["demanda"]) or "Outros atendimentos",
                    "horas": horas, "horario": (c["cf"].get("Período") or "").replace("h", ":00"),
                    "atividade": _atividade(c["cf"].get("Detalhamento") or c["nome"]), "tarefa": c["nome"], "tarefa_id": c["id"]}
            if nums:
                outro = [str(rr["Nome Parceiro (Parceiro)"]) for n in nums for rr in por_os.get(n, [])]
                motivo = f"OS {', '.join(nums)} é de outro parceiro no OM ({outro[0]})" if outro else f"OS {', '.join(nums)} não achada no OM no período"
                linhas.append({**base, "incluir": False, "tipo": "OS", "motivo": motivo})
            elif ap in ("Bonificado (Planilha)", "Planilha - Serviços"):
                # 23/11/2026 (Fragoso): todas as tarefas bonificadas do ClickUp entram, sem duplicar lançamento
                linhas.append({**base, "incluir": True, "tipo": "PLANILHA",
                               "motivo": "" if c["fechada"] else f"Tarefa ainda {c['status'] or 'sem status'} no ClickUp (confira)"})
            else:
                linhas.append({**base, "incluir": False, "tipo": "PLANILHA" if "Planilha" in ap else "OS",
                               "motivo": f"Sem OS no OM ({ap or 'sem apontamento'}, {c['status'] or 'sem status'})"})
        linhas.sort(key=lambda x: (datetime.strptime(x["data"], "%d/%m/%Y"), x["horario"]))
        _sem_duplicidade(linhas)
        res = {"pasta": pasta_nome, "pasta_id": pasta_id, "de": f"{ini:%d/%m/%Y}", "ate": f"{fim:%d/%m/%Y}",
               "parceiro": {"codigo": cod, "nome": nome_parc}, "faps": faps, "agrupar": "Etapa" if implantacao else "Frente",
               "linhas": linhas, "buscado_em": datetime.now().strftime("%d/%m/%Y %H:%M")}
        gravar_json_dados(ARQ_RASCUNHO, res)
        dentro = [x for x in linhas if x["incluir"]]
        return {"mensagem": f"{len(dentro)} lançamento(s) prontos para conferir ({sum(x['horas'] for x in dentro):.1f} h); "
                            f"{len(linhas) - len(dentro)} fora, com o motivo. Nada foi alterado no OM nem no ClickUp.",
                "resultado": res}

    tk = GERENTE.iniciar("status_report", "Status Report: buscar OS e tarefas (só leitura)", trabalho)
    return 200, {"tarefa": tk.id}


def _faixa(h):
    m = re.match(r"(\d{1,2}):?(\d{2})?\s*-\s*(\d{1,2}):?(\d{2})?", h or "")
    return (int(m[1]) * 60 + int(m[2] or 0), int(m[3]) * 60 + int(m[4] or 0)) if m else None


def _sem_duplicidade(linhas):
    """Lançamento bonificado que cai no mesmo consultor, dia e horário de outro já marcado sai (fica o primeiro: OS antes de planilha)."""
    marcadas = [x for x in linhas if x["incluir"] and x["tipo"] != "PLANILHA"]
    for x in [x for x in linhas if x["incluir"] and x["tipo"] == "PLANILHA"]:
        fx = _faixa(x["horario"])
        for o in marcadas:
            fo = _faixa(o["horario"])
            mesmo = o["data"] == x["data"] and o["consultor"].split()[0].lower() == x["consultor"].split()[0].lower()
            if mesmo and (fx is None or fo is None or (fx[0] < fo[1] and fo[0] < fx[1])):
                x["incluir"] = False
                x["motivo"] = f"Duplicado com {('OS ' + o['os']) if o['os'] else o['tarefa'] or 'outro lançamento'} ({o['horario']})"
                break
        else:
            marcadas.append(x)


# ============================================================================ 2) gerar
def _fh(x):
    return (f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " h") if x else "–"


def _fn(x):
    return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") if x else "–"


def _pct(x):
    return f"{x:.1f}%".replace(".", ",") if x else "–"


CSS = """@page{size:A4;margin:12mm 12mm}*{box-sizing:border-box}
body{font-family:Arial,Helvetica,sans-serif;color:#1C2430;font-size:9.8pt;line-height:1.38;margin:0;background:#fff}
.topo{background:#1C2430;color:#fff;border-radius:8px;padding:16px 18px;margin-bottom:12px;border-left:8px solid #66CB66}
.topo h1{margin:0;font-size:18pt}.topo div{color:#cfd8e3;font-size:9.4pt;margin-top:4px}
h2{font-size:12.5pt;margin:16px 0 6px;color:#1C2430;border-bottom:2px solid #66CB66;padding-bottom:3px;break-after:avoid}
h3{font-size:10.2pt;margin:12px 0 4px;break-after:avoid}p{margin:6px 0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0}.kpi{background:#E9F9EA;border-radius:8px;padding:9px 11px;border-left:4px solid #66CB66}
.kpi b{display:block;font-size:16pt;line-height:1.1}.kpi span{font-size:8.5pt;color:#475569}
ul.ficha{margin:6px 0;padding-left:17px}ul.ficha li{margin:2px 0}
.leg{display:flex;gap:14px;font-size:8.5pt;color:#475569;margin:2px 0 4px}.leg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.lin{display:grid;grid-template-columns:240px 1fr 70px;gap:8px;align-items:center;margin:5px 0}.rot{font-size:9.2pt}
.pista{display:flex;gap:2px;height:13px}.pista i{display:block;height:13px}.pista i:last-child{border-radius:0 4px 4px 0}.val{text-align:right;font-size:9pt}
.colunas{display:flex;gap:8px;align-items:flex-end;height:140px;padding-top:6px}.col{flex:1;display:flex;flex-direction:column;align-items:center;height:100%}
.col .pilha{flex:1;width:62%;display:flex;flex-direction:column;justify-content:flex-end;gap:2px}.col .pilha i{display:block;width:100%}.col .pilha i:first-child{border-radius:4px 4px 0 0}
.col .v{font-size:8.3pt;font-weight:700}.col .m{font-size:8pt;color:#475569;margin-top:3px}
table{border-collapse:collapse;width:100%;font-size:8.3pt}th{background:#1C2430;color:#fff;text-align:left;padding:4px 5px;font-size:7.9pt}
td{padding:3px 5px;border-bottom:1px solid #e2e8f0;vertical-align:top}td.num,th.num{text-align:right;white-space:nowrap}tr{break-inside:avoid}
tr.tot td{font-weight:700;background:#E9F9EA}tr.pl td{background:#fff4ec}.nota{font-size:8.3pt;color:#475569;margin-top:5px}.quebra{break-before:page}
th,td,.kpi,.topo,.pista i,.pilha i,tr.tot td{-webkit-print-color-adjust:exact;print-color-adjust:exact}"""


def _montar(cab, linhas):
    """cab: titulo, destinatario, parceiro, negociacao, gp, de, ate, agrupar, introducao. linhas: as marcadas."""
    for x in linhas:
        x["_d"] = datetime.strptime(x["data"], "%d/%m/%Y")
        x["horas"] = float(x["horas"] or 0)
    linhas.sort(key=lambda x: (x["_d"], x.get("horario") or ""))
    tipos = [k for k in TIPOS if any(x["tipo"] == k for x in linhas)]
    soma = lambda f: sum(x["horas"] for x in linhas if f(x))
    tot = soma(lambda x: True)
    h = {k: soma(lambda x, k=k: x["tipo"] == k) for k in TIPOS}
    n = {k: sum(1 for x in linhas if x["tipo"] == k) for k in TIPOS}
    grp = cab.get("agrupar") or "Frente"
    g_min = grp.lower()
    frentes = sorted({x["frente"] for x in linhas}, key=lambda f: -soma(lambda x: x["frente"] == f))
    consult = sorted({x["consultor"] for x in linhas}, key=lambda c: -soma(lambda x: x["consultor"] == c))
    leg = '<div class="leg">' + "".join(f'<span><i style="background:{CORES[k]}"></i>{TIPOS[k]}</span>' for k in tipos) + "</div>"

    def barras(campo, ordem):
        mx = max(soma(lambda x, k=k: x[campo] == k) for k in ordem) or 1
        s = ""
        for k in ordem:
            seg = "".join(f'<i style="width:{soma(lambda x: x[campo] == k and x["tipo"] == tp) / mx * 100:.2f}%;background:{CORES[tp]}" '
                          f'title="{TIPOS[tp]}: {_fh(soma(lambda x: x[campo] == k and x["tipo"] == tp))}"></i>'
                          for tp in tipos if soma(lambda x: x[campo] == k and x["tipo"] == tp))
            s += f'<div class="lin"><div class="rot">{e(k)}</div><div class="pista">{seg}</div><div class="val"><b>{_fh(soma(lambda x: x[campo] == k))}</b></div></div>'
        return s

    # por semana (até ~10 semanas) ou por mês
    d0, d1 = datetime.strptime(cab["de"], "%d/%m/%Y"), datetime.strptime(cab["ate"], "%d/%m/%Y")
    semanal = (d1 - d0).days <= 75
    chave = (lambda d: max(d - timedelta(days=d.weekday()), d0)) if semanal else (lambda d: d.replace(day=1))
    rot = (lambda d: f"{d:%d/%m}") if semanal else (lambda d: ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"][d.month - 1] + f"/{d:%y}")
    per = sorted({chave(x["_d"]) for x in linhas})
    mxp = max((soma(lambda x, p=p: chave(x["_d"]) == p) for p in per), default=1) or 1
    cols = ""
    for p in per:
        pil = "".join(f'<i style="height:{soma(lambda x: chave(x["_d"]) == p and x["tipo"] == tp) / mxp * 100:.2f}%;background:{CORES[tp]}"></i>'
                      for tp in reversed(tipos) if soma(lambda x: chave(x["_d"]) == p and x["tipo"] == tp))
        cols += f'<div class="col"><div class="v">{_fn(soma(lambda x: chave(x["_d"]) == p))}</div><div class="pilha">{pil}</div><div class="m">{rot(p)}</div></div>'

    def resumo(campo, ordem, titulo):
        s = f'<table><tr><th>{titulo}</th>' + "".join(f'<th class="num">{TIPOS[k]}</th>' for k in tipos)
        s += '<th class="num">% das horas em OS</th><th class="num">OS</th><th class="num">Total</th></tr>'
        for k in ordem:
            ho = soma(lambda x: x[campo] == k and x["tipo"] == "OS")
            s += f"<tr><td>{e(k)}</td>" + "".join(f'<td class="num">{_fh(soma(lambda x: x[campo] == k and x["tipo"] == tp))}</td>' for tp in tipos)
            s += (f'<td class="num">{_pct(ho / h["OS"] * 100 if h["OS"] else 0)}</td>'
                  f'<td class="num">{sum(1 for x in linhas if x[campo] == k and x["os"]) or "–"}</td>'
                  f'<td class="num"><b>{_fh(soma(lambda x: x[campo] == k))}</b></td></tr>')
        s += '<tr class="tot"><td>Total</td>' + "".join(f'<td class="num">{_fh(h[tp])}</td>' for tp in tipos)
        s += f'<td class="num">{"100%" if h["OS"] else "–"}</td><td class="num">{sum(1 for x in linhas if x["os"])}</td><td class="num">{_fh(tot)}</td></tr></table>'
        return s

    curto = {c: c.split()[0] for c in consult}
    if len(set(curto.values())) < len(curto):
        curto = {c: " ".join(c.split()[:2]) for c in consult}
    mat = f"<table><tr><th>{grp}</th>" + "".join(f'<th class="num">{e(curto[c])}</th>' for c in consult) + '<th class="num">Total</th></tr>'
    for f in frentes:
        mat += f"<tr><td>{e(f)}</td>" + "".join(f'<td class="num">{_fn(soma(lambda x: x["frente"] == f and x["consultor"] == c))}</td>' for c in consult)
        mat += f'<td class="num"><b>{_fn(soma(lambda x: x["frente"] == f))}</b></td></tr>'
    mat += '<tr class="tot"><td>Total</td>' + "".join(f'<td class="num">{_fn(soma(lambda x: x["consultor"] == c))}</td>' for c in consult) + f'<td class="num">{_fn(tot)}</td></tr></table>'

    det = ""
    for f in frentes:
        sub = [x for x in linhas if x["frente"] == f]
        partes = [f"{_fh(sum(x['horas'] for x in sub if x['tipo'] == k))} {TIPOS[k].lower().replace('horas em os', 'em OS')}"
                  for k in tipos if any(x["tipo"] == k for x in sub)]
        det += f"<h3>{e(f)} · {' + '.join(partes)} · {sum(1 for x in sub if x['os'])} OS</h3>"
        det += '<table><tr><th>Data</th><th>OS</th><th>Consultor</th><th>Horário</th><th class="num">Horas</th><th>Atividade</th></tr>'
        for x in sub:
            det += (f'<tr{" class=pl" if x["tipo"] == "PLANILHA" else ""}><td>{x["_d"]:%d/%m/%y}</td><td>{e(x["os"] or "Planilha")}</td>'
                    f'<td>{e(x["consultor"])}</td><td>{e(x.get("horario") or "")}</td><td class="num">{_fh(x["horas"])}</td><td>{e(x["atividade"])}</td></tr>')
        det += "</table>"

    n_os = sum(1 for x in linhas if x["os"])
    kpis = [(_fh(h["OS"]), f"apontadas em {n['OS']} OS")]
    if "BONIF_OS" in tipos:
        kpis.append((_fh(h["BONIF_OS"]), f"bonificadas em {n['BONIF_OS']} OS, sem cobrança"))
    if "PLANILHA" in tipos:
        kpis.append((_fh(h["PLANILHA"]), f"bonificadas em {n['PLANILHA']} atendimento(s) nas planilhas, sem cobrança"))
    kpis.append((_fh(tot), "de dedicação total no período"))
    if len(kpis) < 4:
        kpis.append((str(len(frentes)), f"{'etapas' if grp == 'Etapa' else 'frentes de trabalho'} atendidas"))
    intro = cab.get("introducao") or (
        f"Apresentamos os atendimentos realizados para a {cab['parceiro_nome']} entre {cab['de']} e {cab['ate']}, separados por "
        f"{'etapa' if grp == 'Etapa' else 'frente de trabalho'} e por consultor. Foram {n_os} ordens de serviço, somando {_fh(h['OS'] + h['BONIF_OS'])}"
        + (f", das quais {n['BONIF_OS']} bonificadas ({_fh(h['BONIF_OS'])}), sem cobrança" if n["BONIF_OS"] else "") + "."
        + (f" Além das OS, registramos {n['PLANILHA']} atendimento(s) bonificado(s) nas planilhas de horas, somando {_fh(h['PLANILHA'])}, sem cobrança." if n["PLANILHA"] else "")
        + (f" As principais {'etapas' if grp == 'Etapa' else 'frentes'} do período foram {e(frentes[0])}"
           + (f" e {e(frentes[1])}" if len(frentes) > 1 else "") + f", que concentram {_fh(sum(soma(lambda x, f=f: x['frente'] == f) for f in frentes[:2]))}." if frentes else ""))
    ficha = [f"<li><b>Parceiro:</b> {e(cab['parceiro'])}</li>"]
    if cab.get("negociacao"):
        ficha.append(f"<li><b>Negociação:</b> {e(cab['negociacao'])}</li>")
    if cab.get("gp"):
        ficha.append(f"<li><b>Gerente de projeto:</b> {e(cab['gp'])}</li>")
    ficha += [f"<li><b>Período:</b> {cab['de']} a {cab['ate']}</li>", f"<li><b>Consultores:</b> {len(consult)}</li>"]
    titulo = cab.get("titulo") or "Relatório de status de atendimentos"
    html = f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><title>{e(cab['parceiro_nome'])} · {e(titulo)}</title><style>{CSS}</style></head><body>
<div class="topo"><h1>{e(titulo)}</h1><div>{e(cab['parceiro_nome'])} · {'Etapas' if grp == 'Etapa' else 'Frentes de trabalho'} e consultores · {cab['de']} a {cab['ate']}</div></div>
<p>{e(cab.get('destinatario') or 'Prezados,')}</p><p>{intro}</p><ul class="ficha">{''.join(ficha)}</ul>
<div class="kpis">{''.join(f'<div class="kpi"><b>{a}</b><span>{b}</span></div>' for a, b in kpis[:4])}</div>
<h2>Horas por {g_min}</h2>{leg}{barras('frente', frentes)}
<h2>Horas por {'semana' if semanal else 'mês'}</h2>{leg}<div class="colunas">{cols}</div>
{'<div class="nota">Semana identificada pelo primeiro dia dentro do período.</div>' if semanal else ''}
<h2>Resumo por {g_min}</h2>{resumo('frente', frentes, grp)}
<h2>Horas por consultor</h2>{leg}{barras('consultor', consult)}<div style="height:8px"></div>{resumo('consultor', consult, 'Consultor')}
<h2>{grp} x consultor (horas)</h2>{mat}<div class="nota">Soma de todas as horas do relatório.</div>
<h2 class="quebra">Detalhamento por {g_min}</h2>{det}
<h2>Premissas</h2><ul class="ficha"><li>OS: Consulta de OS do Sankhya-Om, parceiro {e(cab['parceiro'])}, execução entre {cab['de']} e {cab['ate']}.</li>
<li>{grp}: {'a etapa informada na demanda de cada OS' if grp == 'Etapa' else 'definida pela demanda de origem e pela atividade de cada OS'}.</li>
{'<li>Planilha: atendimentos bonificados fora de OS, registrados nas planilhas de horas dos consultores, cruzados com as tarefas bonificadas lançadas no ClickUp (cada atendimento contado uma única vez).</li>' if n['PLANILHA'] else ''}
<li>Horas: tempo gasto apontado na OS, já descontado o intervalo.</li></ul>
<div class="nota">Gerado em {datetime.now():%d/%m/%Y}.</div></body></html>"""
    return html, tot, n_os


_PDF = r"""
import sys, pathlib
from playwright.sync_api import sync_playwright
html, pdf, chrome = sys.argv[1], sys.argv[2], sys.argv[3]
with sync_playwright() as p:
    op = {"headless": True}
    if pathlib.Path(chrome).is_file():
        op["executable_path"] = chrome
    else:
        op["channel"] = "chrome"
    nav = p.chromium.launch(**op)
    pg = nav.new_page()
    pg.goto(pathlib.Path(html).resolve().as_uri(), wait_until="load", timeout=60000)
    pg.pdf(path=pdf, format="A4", print_background=True, prefer_css_page_size=True)
    nav.close()
"""


def _pdf(caminho_html):
    """PDF em pé (o pdf_relatorio.py da conferência é deitado)."""
    from pdf_relatorio import CHROME
    destino = os.path.splitext(caminho_html)[0] + ".pdf"
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    r = subprocess.run([exe, "-c", _PDF, caminho_html, destino, CHROME], capture_output=True, text=True, timeout=180,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not os.path.isfile(destino):
        raise RuntimeError("Não consegui gerar o PDF: " + (r.stderr or r.stdout or "erro desconhecido").strip()[-400:])
    return destino


@rota("POST", "/api/status-report/gerar")
def gerar(req):
    cab = req.corpo.get("cabecalho") or {}
    todas = req.corpo.get("linhas") or []
    linhas = [dict(x) for x in todas if x.get("incluir")]
    if not linhas:
        raise ErroUsuario("Marque pelo menos um lançamento para o relatório.")
    for x in linhas:
        if not (x.get("frente") or "").strip():
            raise ErroUsuario(f"Falta a frente/etapa do lançamento de {x.get('data')} (OS {x.get('os') or 'planilha'}).")
        if not (x.get("consultor") or "").strip():
            raise ErroUsuario(f"Falta o consultor do lançamento de {x.get('data')}.")
        x["data"] = str(x.get("data"))[:10]
        periodo_br(x["data"], x["data"])  # valida a data
    for k in ("parceiro", "parceiro_nome", "de", "ate"):
        if not cab.get(k):
            raise ErroUsuario("Faça a busca antes de gerar (faltam os dados do parceiro e do período).")

    def trabalho(t):
        import pandas as pd
        # lembra os nomes corrigidos na prévia (login do OM -> nome no relatório)
        nomes = ler_json_dados(ARQ_NOMES, {}) or {}
        for x in linhas:
            if x.get("login") and x.get("consultor"):
                nomes[x["login"]] = x["consultor"].strip()
        gravar_json_dados(ARQ_NOMES, nomes)
        rasc = ler_json_dados(ARQ_RASCUNHO, {}) or {}
        rasc.update({"linhas": todas, "cabecalho": cab})
        gravar_json_dados(ARQ_RASCUNHO, rasc)

        html, tot, n_os = _montar(cab, linhas)
        pasta = dados_arquivo("relatorios")
        os.makedirs(pasta, exist_ok=True)
        base = re.sub(r"[^\w\- ]", "", cab["parceiro_nome"]).strip().replace(" ", "_")
        nome = f"{base}_Status_Report_{cab['de'].replace('/', '-')}_a_{cab['ate'].replace('/', '-')}"
        arq = os.path.join(pasta, nome)
        with open(arq + ".html", "w", encoding="utf-8") as f:
            f.write(html)
        t.log("HTML gerado. Gerando o PDF...")
        try:
            t.adicionar_arquivo("Relatório (PDF)", _pdf(arq + ".html"))
        except Exception as erro:
            t.log(f"⚠ PDF não gerado ({erro}); o HTML e o Excel estão prontos.")
        x = pd.DataFrame([{"Data": datetime.strptime(l["data"], "%d/%m/%Y"), "OS": l.get("os") or "Planilha", "Consultor": l["consultor"],
                           cab.get("agrupar") or "Frente": l["frente"], "Tipo": TIPOS.get(l["tipo"], l["tipo"]),
                           "Horas": float(l["horas"] or 0), "Horário": l.get("horario"), "Atividade": l["atividade"]} for l in linhas]).sort_values("Data")
        with pd.ExcelWriter(arq + ".xlsx") as w:
            x.to_excel(w, sheet_name="Atendimentos", index=False)
            pd.pivot_table(x, index=cab.get("agrupar") or "Frente", columns="Consultor", values="Horas", aggfunc="sum",
                           margins=True, margins_name="Total").fillna(0).to_excel(w, sheet_name="Frente x Consultor")
        t.adicionar_arquivo("Planilha (Excel)", arq + ".xlsx")
        t.adicionar_arquivo("Relatório (HTML)", arq + ".html")
        marcar_uso("status_report")
        return {"mensagem": f"Relatório gerado: {n_os} OS, {_fh(tot)} no total. Arquivos em dados\\relatorios.",
                "resultado": {"arquivo": arq + ".pdf"}}

    tk = GERENTE.iniciar("status_report_gerar", "Status Report: gerar relatório", trabalho)
    return 200, {"tarefa": tk.id}

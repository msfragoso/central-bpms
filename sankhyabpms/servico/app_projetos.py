# -*- coding: utf-8 -*-
"""
Acompanhamento de Projetos (11/11/2026, pedido do Fragoso). Só leitura no Experience.

Para cada projeto ativo (Em andamento, Suspenso, Não iniciado, Impedido; Implantação
inicial e Fase 2, ou seja, sem os avulsos) lê as etapas, os módulos de cada etapa
(concluídos, datas), se a etapa foi encerrada, os documentos (relatórios) com os
aprovadores e o termômetro. Mesmas chamadas da tela de projetos do Experience
(HAR de 11/11/2026).

Alertas:
 - etapa com data final vencida e ainda aberta;
 - etapa encerrada (ou com todos os módulos concluídos) que prevê relatório e não tem documento;
 - Cronograma Sintético faltando depois do Kick off / Check-in encerrado.
A documentação monitorada cobra só o documento gerado (não a aprovação), decisão do Fragoso em 11/11/2026.
Tela, HTML5 para compartilhar e e-mail (08h, seg a sex, só alertas novos).
"""
import html
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import requests

from nucleo import GERENTE, ErroUsuario, Ocupado, dados_arquivo, gravar_json_dados, ler_json_dados, marcar_uso, rota

STATUS_ATIVOS = ["EM_ANDAMENTO", "SUSPENSO", "NAO_INICIADO", "IMPEDIDO"]
CLASSIFICACOES = ["INICIAL", "FASE2"]          # sem os avulsos
ETAPAS_GESTAO = {32, 108}                      # "Gerenciamento do Projeto" e "Gestão da Trilha" correm o projeto todo
ETAPAS_TRANSVERSAIS = {3}                      # "Capacitação dos Usuários Chave": corre junto, não define a etapa atual
DIAS_APROVACAO = 3          # dias úteis (11/11/2026, Fragoso)
HORA_EMAIL = 8
ARQ = "projetos.json"
ARQ_AVISADOS = "projetos_avisados.json"
ARQ_AGENDA = "projetos_agenda.json"
TERMOMETRO = {"S": "Satisfeito", "N": "Neutro", "I": "Insatisfeito", "A": "Atenção", "C": "Crítico"}


def _api():
    from experience_api._base import _BASE, auth_headers
    return _BASE, auth_headers


class Cliente:
    def __init__(self, token):
        self.base, cab = _api()
        self.h = cab(token)
        self.s = requests.Session()

    def _ok(self, r, caminho):
        j = r.json() if r.content else {}
        if r.status_code != 200 or (j.get("response") or {}).get("error"):
            raise RuntimeError(f"Experience: {caminho} -> HTTP {r.status_code} {(j.get('response') or {}).get('message', '')}")
        return j.get("data")

    def get(self, caminho, **params):
        for tentativa in range(3):
            r = self.s.get(f"{self.base}/{caminho}", headers=self.h, params=params, timeout=40)
            if r.status_code < 500:
                return self._ok(r, caminho)
            time.sleep(1 + tentativa)
        return self._ok(r, caminho)

    def post(self, caminho, corpo, **params):
        for tentativa in range(3):
            r = self.s.post(f"{self.base}/{caminho}", headers=self.h, params=params, json=corpo, timeout=40)
            if r.status_code < 500:
                return self._ok(r, caminho)
            time.sleep(1 + tentativa)
        return self._ok(r, caminho)


def _pessoa(token):
    import base64
    import json
    try:
        carga = token.split(".")[1]
        d = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))
        for k in ("person_id", "personId", "custom:person_id"):
            if d.get(k):
                return int(d[k])
    except Exception:
        pass
    import enviar_aceite_os as aceite
    return int(aceite.SOLICITANTE_PERSON_ID)


def _data(txt):
    try:
        return datetime.strptime(str(txt)[:10], "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def _br(txt):
    """'2025-11-20 10:26:00' -> '20/11/2025 10:26'."""
    try:
        return datetime.strptime(str(txt)[:16], "%Y-%m-%d %H:%M").strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(txt or "")[:16]


# Documentação monitorada (11/11/2026, lista do Fragoso), pelas três trilhas: Metodologia 5.0, RH (Folha) e Trilha do Sucesso.
# Etapas fora desta lista não geram alerta de documento nem de aprovação. "Cronograma Sintético" é documento, não etapa.
ETAPAS_MONITORADAS = [
    "Sintonia Comercial", "Kick off", "Folha | Validação do escopo", "Folha | Treinam.Validação processos",
    "Folha | Simulação integrada", "Folha | Encerramento",
    "Validação do escopo", "Auditoria", "Treinamento e validação dos processos", "Simulação integrada",
    "Gestão da Trilha", "Check-in", "Showtime", "Aprovação do Setlist", "Checagem Final", "Dia da Estreia",
]


def _norm(txt):
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFKD", str(txt or "")) if not unicodedata.combining(c)).lower()
    return " ".join(t.split())


MONITORADAS = {_norm(x) for x in ETAPAS_MONITORADAS}


def _docs_validos(docs):
    return [d for d in docs if (d.get("situacao") or "").lower() not in ("cancelado", "reprovado")]


def _situacao_docs(validos):
    s = [(d.get("situacao") or "").lower() for d in validos]
    if not s:
        return "sem_documento"
    return "gerado"   # 11/11/2026 (Fragoso): cobra só o documento gerado na aba Documentação, não a aprovação


def _dias_uteis(de, ate):
    import numpy as np
    try:
        from indicador_prazo import configuracao
        feriados = configuracao()[2]
    except Exception:
        feriados = []
    return int(np.busday_count(de, ate, holidays=feriados)) if ate > de else 0


def listar_projetos(c):
    colunas = [{"name": "thermometer", "alias": "thermometer"}, {"name": "impl.id", "alias": "id"},
               {"name": "impl.company_name", "alias": "company_name"}, {"name": "impl.project_name", "alias": "project_name"},
               {"name": "to_char(init.date, 'DD/MM/YYYY')", "alias": "data_inicio"}, {"name": "to_char(go_live.date, 'DD/MM/YYYY')", "alias": "go_live"},
               {"name": "status", "alias": "status"}, {"name": "implantation_classification", "alias": "implantation_classification"},
               {"name": "fap_model", "alias": "fap_model"}, {"name": "impl.fap_number", "alias": "fap"},
               {"name": "fap_coordinators.fap_coordinator", "alias": "fap_coordinator"}]
    todos, pag = [], 1
    while True:
        d = c.post("implantations/filters", {"columns": colunas, "page": pag, "length": 50, "order": {},
                                             "filters": {"status": STATUS_ATIVOS, "classification": CLASSIFICACOES}}) or {}
        r = d.get("result") or []
        todos += r
        if not r or len(todos) >= int(r[0].get("full_count") or 0):
            return todos
        pag += 1


def _documentos(c, impl):
    docs, pag = [], 1
    while True:
        d = c.post("attachments/filtering", {"columns": [], "page": pag, "length": 50, "order": {}, "filters": {}}, implantation_id=impl) or {}
        r = d.get("result") or []
        docs += r
        if not r or len(docs) >= int(r[0].get("full_count") or 0):
            break
        pag += 1
    saida = []
    for x in docs:
        if x.get("cancelled_at"):
            continue
        aprov = []
        if x.get("require_approval"):
            try:
                aprov = [{"pessoa": a.get("approving_person"), "papel": a.get("roles_names"), "situacao": a.get("status"),
                          "data": a.get("created_at_approving_format")}
                         for a in (c.post(f"attachments/attachments-persons/{x['id']}/approvers",
                                          {"columns": [], "page": 1, "length": 50, "order": {}}) or {}).get("result") or []]
            except Exception:
                aprov = []
        saida.append({"id": x["id"], "titulo": x.get("title"), "etapa_id": x.get("stage_id"), "etapa": (x.get("stage") or {}).get("name"),
                      "situacao": x.get("status"), "criado": x.get("created_at"), "por": x.get("name"), "modulo": x.get("process_one"),
                      "aprovacao": x.get("require_approval"), "aprovadores": aprov, "arquivo": x.get("attachment_name")})
    return saida


def ler_projeto(c, pessoa, p, hoje, log):
    impl = int(p["id"])
    menu = c.get(f"stages/implantation/{impl}/adapt-to-menu/true") or []
    etapas_menu = [s for grupo in menu for s in grupo.get("stages") or []]
    try:
        termo = (c.get(f"implantations/{impl}/thermometer") or [{}])
        termo = next((t for t in termo if t.get("is_latest_version")), termo[0] if termo else {})
    except Exception:
        termo = {}
    docs = _documentos(c, impl)

    def etapa(s):
        sid = s["id"]
        info = c.get(f"stages/{sid}", implantation_id=impl) or {}
        mods = c.get(f"processes/implantation/{impl}/stage/{sid}/person/{pessoa}", isBetterPractices="false") or []
        fech = c.get(f"stages/closed/{sid}/implantation/{impl}") or {}
        fins = [d for d in (_data(m.get("stage_final_date")) for m in mods) if d]
        inis = [d for d in (_data(m.get("stage_initial_date")) for m in mods) if d]
        concl = sum(1 for m in mods if m.get("concluded"))
        fechada = bool(fech.get("is_closed"))
        inicio, fim = (min(inis) if inis else None), (max(fins) if fins else None)
        if fechada:
            situacao = "encerrada"
        elif concl or (inicio and inicio <= hoje):
            situacao = "andamento"
        else:
            situacao = "nao_iniciada"
        relatorios = [r.get("name") for r in info.get("released_reports") or []]
        return {"id": sid, "nome": s.get("title") or info.get("name"), "gestao": sid in ETAPAS_GESTAO, "situacao": situacao,
                "modulos": len(mods), "concluidos": concl, "inicio": inicio.strftime("%d/%m/%Y") if inicio else "",
                "fim": fim.strftime("%d/%m/%Y") if fim else "", "vencida": bool(fim and fim < hoje and not fechada),
                "encerrada_por": fech.get("closed_by"), "encerrada_em": _br(fech.get("closing_date")),
                "relatorios_previstos": relatorios, "nao_aplica": bool(info.get("not_applicable") and not mods),
                "documentos": [d for d in docs if d["etapa_id"] == sid]}

    with ThreadPoolExecutor(max_workers=6) as ex:
        etapas = list(ex.map(etapa, etapas_menu))
    # O menu traz todas as etapas do modelo (ex.: trilhas Pontotel no RH). Só ficam as que o projeto usa:
    # com módulo, encerrada ou com documento.
    etapas = [e for e in etapas if e["modulos"] or e["situacao"] == "encerrada" or e["documentos"]]
    alertas, documentacao = [], []
    for e in etapas:
        e["monitorada"] = _norm(e["nome"]) in MONITORADAS
        if e["vencida"] and not e["gestao"]:
            alertas.append({"tipo": "etapa_vencida", "etapa": e["nome"], "texto": f"Etapa \"{e['nome']}\" com data final {e['fim']} vencida e ainda aberta."})
        if not e["monitorada"]:
            continue
        validos = _docs_validos(e["documentos"])
        documentacao.append({"item": e["nome"], "etapa_situacao": e["situacao"], "situacao": _situacao_docs(validos),
                             "documentos": [d["titulo"] for d in validos]})
        terminou = e["situacao"] == "encerrada" or (e["modulos"] and e["concluidos"] == e["modulos"])
        if terminou and not validos:
            alertas.append({"tipo": "sem_documento", "etapa": e["nome"],
                            "texto": f"Etapa \"{e['nome']}\" {'encerrada' if e['situacao'] == 'encerrada' else 'com módulos concluídos'} sem documento"
                                     + (f" ({', '.join(e['relatorios_previstos'])})." if e["relatorios_previstos"] else ".")})
    # Cronograma Sintético: documento do projeto (costuma vir "Sem Etapa"). Esperado depois do Kick off / Check-in encerrado.
    crono = _docs_validos([d for d in docs if "cronograma sintetico" in _norm(d["titulo"])])
    documentacao.append({"item": "Cronograma Sintético", "etapa_situacao": "", "situacao": _situacao_docs(crono), "documentos": [d["titulo"] for d in crono]})
    inicio_feito = any(_norm(e["nome"]) in ("kick off", "check-in") and e["situacao"] == "encerrada" for e in etapas)
    if inicio_feito and not crono:
        alertas.append({"tipo": "sem_cronograma", "etapa": "Cronograma Sintético",
                        "texto": "Kick off / Check-in encerrado e o projeto ainda não tem o Cronograma Sintético."})
    # 11/11/2026 (Fragoso): a aprovação não é cobrada; só se o documento foi gerado. A situação de aprovação
    # continua visível no detalhe, sem alerta.
    validas = [e for e in etapas if not e["gestao"] and not e["nao_aplica"]]
    atual = next((e for e in validas if e["situacao"] != "encerrada" and e["id"] not in ETAPAS_TRANSVERSAIS), None)
    pend_docs = sum(1 for d in docs if d["situacao"] and "aguardando" in d["situacao"].lower())
    log(f"  FAP {p.get('fap')} {p.get('company_name')}: {len(etapas)} etapa(s), {len(docs)} documento(s), {len(alertas)} alerta(s).")
    return {"fap": str(p.get("fap")), "implantacao": impl, "cliente": p.get("company_name"), "projeto": p.get("project_name"),
            "gp": p.get("fap_coordinator"), "status": p.get("status"), "classificacao": p.get("implantation_classification"),
            "modelo": p.get("fap_model"), "go_live": p.get("go_live"),
            "termometro": TERMOMETRO.get(termo.get("status") or p.get("thermometer"), termo.get("status") or p.get("thermometer") or ""),
            "termometro_desc": termo.get("description"), "termometro_data": termo.get("updated_at"),
            "etapa_atual": atual["nome"] if atual else ("Todas encerradas" if validas else "—"),
            "encerradas": sum(1 for e in validas if e["situacao"] == "encerrada"), "total_etapas": len(validas),
            "docs_pendentes": pend_docs, "documentos": len(docs), "etapas": etapas, "alertas": alertas,
            "documentacao": documentacao, "doc_gerados": sum(1 for x in documentacao if x["situacao"] == "gerado"),
            "doc_total": len(documentacao)}


def levantar(log=print):
    import experience_api as exp
    from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
    log("Login no Experience...")
    tk = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
    if not tk:
        raise ErroUsuario("O Experience recusou o login. Confira a senha na tela Credenciais.")
    c, pessoa, hoje = Cliente(tk), _pessoa(tk), date.today()
    projetos = listar_projetos(c)
    log(f"{len(projetos)} projeto(s) ativo(s), sem os avulsos.")
    saida = []
    for p in projetos:
        try:
            saida.append(ler_projeto(c, pessoa, p, hoje, log))
        except Exception as e:  # um projeto com problema não derruba o levantamento
            log(f"  ⚠ FAP {p.get('fap')}: {e}")
            saida.append({"fap": str(p.get("fap")), "cliente": p.get("company_name"), "projeto": p.get("project_name"),
                          "gp": p.get("fap_coordinator"), "status": p.get("status"), "etapas": [], "erro": str(e),
                          "alertas": [{"tipo": "erro", "texto": f"Falha ao ler o projeto: {e}"}], "etapa_atual": "—",
                          "encerradas": 0, "total_etapas": 0, "docs_pendentes": 0, "documentos": 0, "termometro": "",
                          "documentacao": [], "doc_gerados": 0, "doc_total": 0})
    saida.sort(key=lambda r: (-len(r["alertas"]), r["cliente"] or ""))
    return {"quando": datetime.now().strftime("%d/%m/%Y %H:%M"), "dias_aprovacao": DIAS_APROVACAO, "projetos": saida,
            "alertas": sum(len(r["alertas"]) for r in saida)}


# ---------------------------------------------------------------- HTML5
SIT_DOC = {"gerado": "gerado", "sem_documento": "sem documento"}


def gerar_html(res, caminho):
    e = html.escape
    COR = {"encerrada": "#3AA552", "andamento": "#3A6FB0", "nao_iniciada": "#94A3B8"}
    ROT = {"encerrada": "Encerrada", "andamento": "Em andamento", "nao_iniciada": "Não iniciada"}
    linhas = ""
    for i, p in enumerate(res["projetos"]):
        pct = (p["encerradas"] / p["total_etapas"] * 100) if p.get("total_etapas") else 0
        linhas += (f"<tr class='proj' data-i='{i}'><td><b>{e(p['cliente'] or '')}</b><div class='sub'>{e(p.get('projeto') or '')}</div></td>"
                   f"<td>{e(p['fap'])}</td><td>{e(p.get('gp') or '')}</td><td>{e(p.get('termometro') or '')}</td><td>{e(p.get('etapa_atual') or '')}</td>"
                   f"<td><div class='barra'><i style='width:{pct:.0f}%'></i></div><span class='sub'>{p['encerradas']}/{p['total_etapas']} etapas</span></td>"
                   f"<td>{p.get('doc_gerados', 0)}/{p.get('doc_total', 0)} gerados</td><td class='n'>{p['docs_pendentes']}</td><td class='n'>{'<b class=al>' + str(len(p['alertas'])) + '</b>' if p['alertas'] else '0'}</td></tr>")
        det = ""
        if p["alertas"]:
            det += "<ul class='alertas'>" + "".join(f"<li>⚠ {e(a['texto'])}</li>" for a in p["alertas"]) + "</ul>"
        for s in p["etapas"]:
            if s.get("nao_aplica"):
                continue
            docs = "".join(
                f"<div class='doc'>📄 {e(d['titulo'] or '')}{(' · ' + e(d['modulo'])) if d.get('modulo') else ''} · <b>{e(d['situacao'] or '')}</b> · {e(d['criado'] or '')}"
                + ("".join(f"<span class='ap {('ok' if (a['situacao'] or '').lower().startswith('aprov') else 'pe')}'>{e(a['pessoa'] or '')} · {e(a['papel'] or '')}: {e(a['situacao'] or '')}</span>" for a in d["aprovadores"]))
                + "</div>" for d in s["documentos"])
            prev = (f"<div class='sub'>Relatório previsto: {e(', '.join(s['relatorios_previstos']))}</div>" if s["relatorios_previstos"] and not s["documentos"] else "")
            det += (f"<div class='etapa'><span class='pt' style='background:{COR[s['situacao']]}'></span><div><b>{e(s['nome'] or '')}</b> "
                    f"<span class='sit' style='color:{COR[s['situacao']]}'>{ROT[s['situacao']]}</span>"
                    + (" <span class='al'>vencida</span>" if s["vencida"] and not s["gestao"] else "")
                    + f"<div class='sub'>{s['concluidos']}/{s['modulos']} módulo(s) concluído(s)"
                    + (f" · {e(s['inicio'])} a {e(s['fim'])}" if s["inicio"] or s["fim"] else "")
                    + (f" · encerrada por {e(s['encerrada_por'] or '')} em {e(s['encerrada_em'])}" if s["situacao"] == "encerrada" and s.get("encerrada_por") else "")
                    + f"</div>{prev}{docs}</div></div>")
        if p.get("documentacao"):
            det = ("<div class='docmon'><b>Documentação monitorada</b> " + "".join(
                f"<span class='dm {x['situacao']}'>{e(x['item'])}: {SIT_DOC.get(x['situacao'], x['situacao'])}</span>" for x in p["documentacao"]) + "</div>") + det
        linhas += f"<tr class='det oculto' id='d{i}'><td colspan='9'>{det or '<span class=sub>Sem etapas lidas.</span>'}</td></tr>"
    doc = f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Acompanhamento de Projetos</title><style>
*{{box-sizing:border-box}}body{{font-family:Arial,Helvetica,sans-serif;color:#1C2430;font-size:10pt;margin:0 auto;max-width:1150px;padding:16px;background:#fff}}
.topo{{background:#1C2430;color:#fff;border-radius:8px;padding:14px 16px;border-left:8px solid #66CB66;margin-bottom:12px}}.topo h1{{margin:0;font-size:17pt}}.topo div{{color:#cfd8e3;font-size:9.4pt;margin-top:3px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:12px}}.kpi{{background:#E9F9EA;border-left:4px solid #66CB66;border-radius:8px;padding:8px 10px}}.kpi b{{display:block;font-size:16pt}}.kpi span{{font-size:8.5pt;color:#475569}}
.tab{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:9pt}}th{{background:#1C2430;color:#fff;padding:6px;text-align:left}}td{{padding:6px;border-bottom:1px solid #e2e8f0;vertical-align:top}}
tr.proj{{cursor:pointer}}tr.proj:hover td{{background:#f8fafc}}.n{{text-align:right}}.sub{{color:#475569;font-size:8.5pt}}.al{{color:#C2410C;font-weight:700}}
.barra{{height:8px;background:#e2e8f0;border-radius:4px;width:110px}}.barra i{{display:block;height:8px;background:#3AA552;border-radius:4px}}
.oculto{{display:none}}.det td{{background:#f8fafc}}.etapa{{display:flex;gap:8px;padding:6px 0;border-bottom:1px dashed #e2e8f0}}.pt{{width:10px;height:10px;border-radius:50%;margin-top:4px;flex:none}}
.sit{{font-size:8.5pt;font-weight:700}}.doc{{margin-top:4px;font-size:9pt}}.ap{{display:inline-block;margin:2px 4px 0 0;padding:1px 6px;border-radius:5px;font-size:8pt}}.ap.ok{{background:#E9F9EA;color:#1f7a33}}.ap.pe{{background:#fff4ec;color:#C2410C}}
.docmon{{margin:0 0 8px}}.dm{{display:inline-block;margin:3px 4px 0 0;padding:1px 7px;border-radius:5px;font-size:8pt;border:1px solid #e2e8f0}}.dm.gerado{{background:#E9F9EA;color:#1f7a33}}.dm.sem_documento{{background:#fde8e8;color:#b42318}}
ul.alertas{{margin:4px 0 8px;padding-left:18px;color:#C2410C}}.nota{{font-size:8.4pt;color:#475569;margin-top:8px}}
@media print{{.det{{display:table-row!important}}}}
</style></head><body>
<div class="topo"><h1>Acompanhamento de Projetos</h1><div>Etapas, módulos e documentos · projetos ativos (sem avulsos) · fonte: Sankhya Experience · {e(res['quando'])}</div></div>
<div class="kpis"><div class="kpi"><b>{len(res['projetos'])}</b><span>projetos ativos</span></div>
<div class="kpi"><b>{sum(p['docs_pendentes'] for p in res['projetos'])}</b><span>documentos aguardando aprovação</span></div>
<div class="kpi"><b>{res['alertas']}</b><span>alertas</span></div>
<div class="kpi"><b>{sum(p['encerradas'] for p in res['projetos'])}/{sum(p['total_etapas'] for p in res['projetos'])}</b><span>etapas encerradas</span></div></div>
<div class="tab"><table><tr><th>Cliente / projeto</th><th>FAP</th><th>GP</th><th>Termômetro</th><th>Etapa atual</th><th>Evolução</th><th>Documentação</th><th class="n">Docs pendentes</th><th class="n">Alertas</th></tr>{linhas}</table></div>
<div class="nota">Clique no projeto para ver as etapas e os documentos. Alertas: etapa com data final vencida e aberta; etapa encerrada ou com módulos concluídos sem o relatório previsto; Cronograma Sintético faltando depois do Kick off / Check-in. Na documentação monitorada vale o documento gerado; a aprovação aparece só como informação. Etapas de gestão (Gerenciamento do Projeto, Gestão da Trilha) não contam na evolução. Documentação monitorada: {e(', '.join(ETAPAS_MONITORADAS))} e Cronograma Sintético.</div>
<script>document.querySelectorAll("tr.proj").forEach(function(r){{r.addEventListener("click",function(){{document.getElementById("d"+r.dataset.i).classList.toggle("oculto");}});}});</script>
</body></html>"""
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(doc)
    return caminho


# ---------------------------------------------------------------- e-mail (alertas novos)
def _chave(p, a):
    return f"{p['fap']}|{a['tipo']}|{a.get('etapa') or ''}|{a.get('documento') or ''}"


def _enviar_email(novos, res):
    import configparser
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    import keyring
    from clickup_sync.os_data_diferente import SMTP_INI
    cfg = configparser.ConfigParser()
    cfg.read(SMTP_INI, encoding="utf-8")
    email = cfg.get("gmail", "email", fallback="").strip()
    senha = (keyring.get_password("sankhya_experience_sync", "GMAIL_APP_PASSWORD") or "").strip()
    if not email or not senha:
        return "Gmail não configurado (smtp_config.ini / senha de app no cofre)"
    e = html.escape
    linhas = "".join(f"<tr><td>{e(p['cliente'] or '')}<br><small>FAP {e(p['fap'])} · GP {e(p.get('gp') or '')}</small></td><td>{e(a['texto'])}</td></tr>"
                     for p, a in novos)
    corpo = (f"<p>O Acompanhamento de Projetos encontrou <b>{len(novos)} alerta(s) novo(s)</b>:</p>"
             "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:13px'>"
             f"<tr style='background:#e5f3ec'><th>Projeto</th><th>Alerta</th></tr>{linhas}</table>"
             f"<p style='color:#5b6b63;font-size:12px'>Fonte: Sankhya Experience. Aviso automático da Central BP-MS; cada alerta é avisado uma vez ({e(res['quando'])}).</p>")
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Central BP-MS <{email}>"
    msg["To"] = email
    msg["Subject"] = f"[Central BP-MS] {len(novos)} alerta(s) novo(s) nos projetos"
    msg.attach(MIMEText(corpo, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(email, senha)
        s.sendmail(email, [email], msg.as_string())
    return None


def _avisar(res, t):
    antes = set((ler_json_dados(ARQ_AVISADOS, {}) or {}).get("avisados") or [])
    atuais = {_chave(p, a): (p, a) for p in res["projetos"] for a in p["alertas"] if a["tipo"] != "erro"}
    novos = [v for k, v in atuais.items() if k not in antes]
    if not novos:
        gravar_json_dados(ARQ_AVISADOS, {"avisados": sorted(atuais)})
        return "Nenhum alerta novo para enviar por e-mail."
    try:
        erro = _enviar_email(novos, res)
    except Exception as e:
        erro = f"{e.__class__.__name__}: {e}"
    if erro:
        t.log(f"⚠ E-mail não enviado: {erro}")
        return f"E-mail não enviado: {erro}"
    gravar_json_dados(ARQ_AVISADOS, {"avisados": sorted(atuais)})   # alerta resolvido sai da lista; se voltar, avisa de novo
    t.log(f"E-mail enviado com {len(novos)} alerta(s) novo(s).")
    return f"E-mail enviado com {len(novos)} alerta(s) novo(s)."


def iniciar(origem="manual", enviar_email=True):
    def trabalho(t):
        res = levantar(t.log)
        pasta = dados_arquivo("relatorios")
        os.makedirs(pasta, exist_ok=True)
        arq = gerar_html(res, os.path.join(pasta, f"Acompanhamento de Projetos {datetime.now():%d-%m-%Y %Hh%M}.html"))
        t.adicionar_arquivo("Acompanhamento (HTML)", arq)
        res["email"] = _avisar(res, t) if enviar_email else "E-mail não enviado nesta atualização."
        res["origem"] = origem
        gravar_json_dados(ARQ, res)
        marcar_uso("projetos")
        if origem == "08h":
            gravar_json_dados(ARQ_AGENDA, {"ultima_ok": date.today().isoformat()})
        return {"mensagem": f"{len(res['projetos'])} projeto(s) lido(s), {res['alertas']} alerta(s). {res['email']} Nada foi alterado no Experience.",
                "resultado": res}

    return GERENTE.iniciar("projetos", "Acompanhamento de Projetos" + (" (08h)" if origem == "08h" else ""), trabalho)


@rota("POST", "/api/projetos/atualizar")
def atualizar(req):
    return 200, {"tarefa": iniciar("manual", req.corpo.get("email", True) is not False).id}


@rota("GET", "/api/projetos/ultima")
def ultima(req):
    return 200, {"resultado": ler_json_dados(ARQ, None)}


def _laco():
    ultima_tentativa = 0
    while True:
        try:
            agora = datetime.now()
            feita = (ler_json_dados(ARQ_AGENDA, {}) or {}).get("ultima_ok")
            if agora.weekday() < 5 and agora.hour >= HORA_EMAIL and feita != agora.date().isoformat() and time.time() - ultima_tentativa >= 3600:
                ultima_tentativa = time.time()
                iniciar("08h")
        except Ocupado:
            ultima_tentativa = time.time() - 3600 + 300
        except Exception as e:  # nunca derruba o serviço
            print(f"[Projetos] Falha na checagem automática: {e}")
        time.sleep(60)


if os.environ.get("BPMS_SEM_AGENDA") != "1":   # testes fora do serviço não disparam a checagem das 08h
    threading.Thread(target=_laco, daemon=True, name="projetos-08h").start()

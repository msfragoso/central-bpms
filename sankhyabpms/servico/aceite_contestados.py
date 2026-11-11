# -*- coding: utf-8 -*-
"""
Aceites contestados (11/11/2026, pedido do Fragoso). Só leitura no Experience.

Quando o cliente recusa ou contesta o aceite, ele fica "Recusado" (REC) ou "Com Contestação" (CTO).
A Central lê a aba Aceite de OS de cada projeto ativo (só aceites criados no mês atual),
com quem recusou, o motivo e as OS, e avisa por e-mail os novos, uma vez cada (HAR de 11/11/2026).

Agenda: terças e quintas, três vezes no dia (08h, 13h e 17h; decisão do Fragoso), e pelo
botão "Verificar agora" na tela Aceite de OS.
"""
import html
import os
import threading
import time
from datetime import date, datetime, timedelta

import requests

from nucleo import GERENTE, Ocupado, gravar_json_dados, ler_json_dados, rota

# 11/11/2026 (Fragoso): só aceites do mês atual. O cliente tem 3 dias úteis contando o sábado (seg a sáb)
# para contestar/recusar depois do envio; por isso entram também os enviados nos 3 dias úteis antes do dia 1
# (aceite enviado em 29/11 e recusado em 02/12 aparece em dezembro).
PRAZO_CLIENTE = 3


def _inicio_janela(hoje):
    d, n = hoje.replace(day=1), 0
    while n < PRAZO_CLIENTE:
        d -= timedelta(days=1)
        if d.weekday() != 6:   # domingo não conta
            n += 1
    return d
DIAS_SEMANA = {1, 3}          # terça e quinta (segunda = 0)
HORARIOS = [8, 13, 17]        # três verificações no dia
ARQ = "aceites_contestados.json"


def _projetos(base, h):
    corpo = {"columns": [{"name": "impl.id", "alias": "id"}, {"name": "impl.fap_number", "alias": "fap"},
                         {"name": "impl.company_name", "alias": "company_name"}, {"name": "fap_coordinators.fap_coordinator", "alias": "gp"}],
             "page": 1, "length": 200, "order": {}, "filters": {"status": ["EM_ANDAMENTO", "SUSPENSO", "NAO_INICIADO", "IMPEDIDO"]}}
    r = requests.post(f"{base}/implantations/filters", headers=h, json=corpo, timeout=60).json()
    return {int(p["id"]): p for p in ((r.get("data") or {}).get("result") or [])}


# A OS e o aceite não têm link próprio no Experience (Fragoso, 11/11/2026): o e-mail não leva link.
STATUS_BUSCA = ["CTO", "REC"]   # Com Contestação e Recusado


def _post(base, h, caminho, corpo):
    for tentativa in range(3):
        r = requests.post(f"{base}/{caminho}", headers=h, json=corpo, timeout=40)
        if r.status_code < 500:
            break
        time.sleep(1 + tentativa)
    j = r.json() if r.content else {}
    return (j.get("data") or {}).get("result") or []


def _data(txt):
    try:
        return datetime.strptime(str(txt).strip()[:10], "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def verificar(log=print):
    """Aceites contestados ou recusados nos projetos ativos (HAR de 11/11/2026: aba Aceite de OS do projeto)."""
    from concurrent.futures import ThreadPoolExecutor
    import experience_api as exp
    from experience_api._base import _BASE, auth_headers
    from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
    from app_projetos import _pessoa
    tk = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
    if not tk:
        raise RuntimeError("O Experience recusou o login. Confira a senha na tela Credenciais.")
    h, pessoa = auth_headers(tk), _pessoa(tk)
    projs = _projetos(_BASE, h)
    limite = _inicio_janela(date.today())
    log(f"Procurando aceites contestados ou recusados em {len(projs)} projeto(s) ativo(s), criados desde {limite:%d/%m/%Y}...")

    def do_projeto(impl):
        itens, pag = [], 1
        while True:
            r = _post(_BASE, h, f"accepted-os/filtering/implantation/{impl}/{pessoa}",
                      {"columns": [], "page": pag, "length": 50, "order": {}, "filters": {"status": STATUS_BUSCA}})
            itens += r
            if not r or len(itens) >= int(r[0].get("full_count") or 0):
                return impl, itens
            pag += 1

    with ThreadPoolExecutor(max_workers=6) as ex:
        por_projeto = list(ex.map(do_projeto, list(projs)))
    achados = []
    for impl, itens in por_projeto:
        p = projs.get(impl, {})
        for a in itens:
            criado = _data(a.get("created_at_format"))
            if criado and criado < limite:
                continue
            aid = a.get("accept_os_id")
            pessoas = _post(_BASE, h, f"accepted-os/accepted-os-persons/{aid}/table", {"columns": [], "page": 1, "length": 50, "order": {}})
            oss = _post(_BASE, h, f"accepted-os/accepted-os-orders/{aid}/table", {"columns": [], "page": 1, "length": 50, "order": {}})
            quem = [x for x in pessoas if any(t in (x.get("status") or "").lower() for t in ("contest", "recus"))]
            achados.append({
                "chave": str(aid), "aceite": str(aid), "situacao": a.get("status"), "criado": a.get("created_at_format"),
                "cliente": p.get("company_name"), "fap": str(p.get("fap") or ""), "gp": p.get("gp"),
                "recusou": [{"pessoa": x.get("approving_person"), "situacao": x.get("status"),
                             "motivo": (x.get("additional_information") or "").strip()} for x in quem],
                "motivo": next(((x.get("additional_information") or "").strip() for x in quem if x.get("additional_information")),
                               (a.get("additional_information") or "").strip()),
                "os": [{"os": str(o.get("id")), "data": o.get("date_done"), "consultor": o.get("person_name"), "horas": o.get("diff_time"),
                        "etapa": o.get("stage_name"), "processo": o.get("process_name"), "contestada": bool(o.get("was_disputed"))} for o in oss],
                })
    achados.sort(key=lambda x: (x["cliente"] or "", x["aceite"]))
    log(f"{len(achados)} aceite(s) contestado(s) ou recusado(s).")
    return achados


def _enviar_email(novos):
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
    br = lambda t: e(t or "").replace(chr(10), "<br>")
    linhas = "".join(
        f"<tr><td>{e(x['cliente'] or '')}<br><small>GP {e(x['gp'] or '')}</small></td><td>{e(x['fap'])}</td>"
        f"<td>{e(x['aceite'])}<br><small>{e(x['situacao'] or '')} · {e(x['criado'] or '')}</small></td>"
        f"<td>{'<br>'.join(e(o['os']) + ' · ' + e(o['data'] or '') + ' · ' + e(o['consultor'] or '') + ' · ' + e(o['horas'] or '') + ('h' if o.get('horas') else '') + (' <b>(contestada)</b>' if o['contestada'] else '') for o in x['os'])}</td>"
        f"<td>{'<br>'.join(e(r['pessoa'] or '') for r in x['recusou']) or '-'}</td><td>{br(x['motivo']) or '-'}</td>"
        "</tr>"
        for x in novos)
    corpo = (f"<p><b>{len(novos)} aceite(s) de OS recusado(s) ou contestado(s) pelo cliente</b>:</p>"
             "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:13px;vertical-align:top'>"
             "<tr style='background:#fde8e8'><th>Cliente</th><th>FAP</th><th>Aceite</th><th>OS envolvidas</th><th>Quem recusou</th><th>Motivo</th></tr>"
             f"{linhas}</table><p style='color:#5b6b63;font-size:12px'>Fonte: Sankhya Experience. "
             f"Aviso automático da Central BP-MS; cada aceite é avisado uma vez ({datetime.now():%d/%m/%Y %H:%M}).</p>")
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Central BP-MS <{email}>"
    msg["To"] = email
    msg["Subject"] = f"[Central BP-MS] {len(novos)} aceite(s) de OS recusado(s) ou contestado(s) pelo cliente"
    msg.attach(MIMEText(corpo, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(email, senha)
        s.sendmail(email, [email], msg.as_string())
    return None


def iniciar(origem="manual", janela=None):
    def trabalho(t):
        achados = verificar(t.log)
        guardado = ler_json_dados(ARQ, {}) or {}
        avisados = set(guardado.get("avisados") or [])
        novos = [x for x in achados if x["chave"] not in avisados]
        email = "Nenhuma contestação nova."
        if novos:
            try:
                erro = _enviar_email(novos)
            except Exception as e:
                erro = f"{e.__class__.__name__}: {e}"
            if erro:
                email = f"E-mail não enviado: {erro}"
                t.log(f"⚠ {email}")
            else:
                avisados |= {x["chave"] for x in novos}
                email = f"E-mail enviado com {len(novos)} contestação(ões) nova(s)."
                t.log(email)
        res = {"quando": datetime.now().strftime("%d/%m/%Y %H:%M"), "origem": origem, "contestados": achados, "email": email,
               "avisados": sorted(avisados), "ultima_janela": janela or guardado.get("ultima_janela")}
        gravar_json_dados(ARQ, res)
        return {"mensagem": f"{len(achados)} aceite(s) contestado(s). {email} Nada foi alterado no Experience.", "resultado": res}

    return GERENTE.iniciar("aceite_contestados", "Aceites contestados" + (" (agenda)" if origem != "manual" else ""), trabalho)


@rota("POST", "/api/aceite/contestados/verificar")
def rota_verificar(req):
    return 200, {"tarefa": iniciar("manual").id}


@rota("GET", "/api/aceite/contestados")
def rota_ultima(req):
    r = ler_json_dados(ARQ, None) or {}
    return 200, {"resultado": {k: r.get(k) for k in ("quando", "contestados", "email")} if r else None}


def _laco():
    while True:
        try:
            agora = datetime.now()
            # Vale a última janela já alcançada no dia (08h, 13h, 17h). PC ligado mais tarde verifica ao abrir o serviço.
            janelas = [h for h in HORARIOS if agora.hour >= h]
            if agora.weekday() in DIAS_SEMANA and janelas:
                alvo = f"{agora:%Y-%m-%d} {janelas[-1]:02d}"
                if (ler_json_dados(ARQ, {}) or {}).get("ultima_janela") != alvo:
                    iniciar("agenda", alvo)
        except Ocupado:
            pass   # outro processo rodando: tenta no próximo minuto
        except Exception as e:  # nunca derruba o serviço
            print(f"[Aceites contestados] Falha na checagem automática: {e}")
        time.sleep(60)


if os.environ.get("BPMS_SEM_AGENDA") != "1":
    threading.Thread(target=_laco, daemon=True, name="aceites-contestados").start()

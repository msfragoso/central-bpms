# -*- coding: utf-8 -*-
"""
Chamados (06/11/2026, pedido do Fragoso): acompanhar os chamados abertos no portal ajuda.sankhya.com.br
para não esquecer de cobrar o andamento.

- Cadastro: cola um ou vários links/números de uma vez; dá para pôr parceiro, nota e a data do próximo
  acompanhamento. Excluir quando quiser (finalizado ou não).
- Andamento: a Central lê cada chamado no portal (Zendesk) com o login Sankhya ID do navegador dela, o
  mesmo do Sankhya-OM (om_sessao.OM.ler_chamado). Só leitura: nunca responde nada no portal.
- Para não esquecer: "resposta nova" (mudou desde a última vez que você viu), "aguardando você" (o
  portal espera sua resposta), "acompanhamento vencido" e "parado há N dias". Aviso no topo de todas as
  telas e e-mail só para o Gmail da Agenda. Leitura automática de hora em hora nos dias úteis (sem sábado, domingo e feriados; 06/11/2026);
  o e-mail só sai quando aparece algo NOVO (cada sinal de cada chamado é avisado uma vez).

Os chamados ficam só neste computador, em dados/chamados.json.
"""
import html
import re
import threading
import time
from datetime import date, datetime

from nucleo import (GERENTE, ErroUsuario, Ocupado, data_br, exigir_confirmacao, gravar_json_dados, ler_json_dados,
                    marcar_uso, rota)

ARQ = "chamados.json"
ARQ_AGENDA = "chamados_agenda.json"
PORTAL = "https://ajuda.sankhya.com.br/hc/pt-br/requests/"
INTERVALO_AUTOMATICO = 3600   # 06/11/2026 (Fragoso): de hora em hora, nos dias úteis
DIAS_PARADO = 3
LIMITE_TEXTO = 400
STATUS = {"new": "Novo", "open": "Aberto", "pending": "Aguardando você", "hold": "Em espera",
          "solved": "Resolvido", "closed": "Fechado"}
_trava = threading.Lock()
PAPEIS = {"atribuido": "Atendente", "suporte": "Suporte", "solicitante": "Solicitante", "voce": "Você", "outro": "Participante"}


def _ler():
    return (ler_json_dados(ARQ, None) or {}).get("chamados") or []


def _gravar(lista):
    gravar_json_dados(ARQ, {"chamados": lista})


def _achar(lista, numero):
    numero = str(numero or "").strip()
    c = next((c for c in lista if c["numero"] == numero), None)
    if not c:
        raise ErroUsuario(f"Chamado {numero} não está na lista.")
    return c


def _texto(v, limite=120):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limite]


def _quando(iso):
    """'2026-11-06T13:45:10Z' -> datetime local (sem fuso) ou None."""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


AGUARDANDO_VOCE = re.compile(r"aguardando.*(cliente|voc[eê]|sua|seu)", re.I)


def _aguardando_voce(c):
    """Zendesk "pending" ou rótulo do portal pedindo ação do cliente (ex.: "resolvido - aguardando validação do cliente")."""
    return c.get("status") == "pending" or bool(AGUARDANDO_VOCE.search(c.get("status_label") or ""))


def _encerrado(c):
    return c.get("status") in ("solved", "closed") and not _aguardando_voce(c)


def _situacao(c, hoje=None):
    """Sinais para a tela e para o aviso. Ordem de importância: novidade, aguardando você, vencido, parado."""
    hoje = hoje or date.today()
    sinais = []
    encerrado = _encerrado(c)
    if c.get("atualizado_portal") and c.get("atualizado_portal") != c.get("visto"):
        sinais.append("novidade")
    if _aguardando_voce(c):
        sinais.append("aguardando_voce")
    if c.get("proximo") and not encerrado:
        try:
            if datetime.strptime(c["proximo"], "%d/%m/%Y").date() <= hoje:
                sinais.append("vencido")
        except ValueError:
            pass
    ult = _quando(c.get("atualizado_portal"))
    if ult and not encerrado and (hoje - ult.date()).days >= DIAS_PARADO:
        sinais.append("parado")
    return sinais


def _com_sinais(c):
    ult = _quando(c.get("atualizado_portal"))
    return {**c, "sinais": _situacao(c), "encerrado": _encerrado(c),
            "status_txt": c.get("status_label") or STATUS.get(c.get("status"), c.get("status") or "não lido"),
            "dias_sem_movimento": (date.today() - ult.date()).days if ult else None,
            "atualizado_txt": ult.strftime("%d/%m/%Y %H:%M") if ult else ""}


def _ordem(c):
    s = c["sinais"]
    return (c["encerrado"], "novidade" not in s, "aguardando_voce" not in s, "vencido" not in s, "parado" not in s,
            -(c.get("dias_sem_movimento") or 0))


@rota("GET", "/api/chamados")
def listar(req):
    lista = sorted((_com_sinais(c) for c in _ler()), key=_ordem)
    return 200, {"chamados": lista, "portal": PORTAL,
                 "ultima": (ler_json_dados(ARQ_AGENDA, {}) or {}).get("ultima_leitura")}


@rota("GET", "/api/chamados/aviso")
def aviso(req):
    sinais = [_situacao(c) for c in _ler()]
    return 200, {"novidades": sum("novidade" in s for s in sinais), "aguardando": sum("aguardando_voce" in s for s in sinais),
                 "vencidos": sum("vencido" in s for s in sinais)}


@rota("POST", "/api/chamados/adicionar")
def adicionar(req):
    """Aceita um ou vários links/números (um por linha, ou separados por espaço/vírgula)."""
    numeros = list(dict.fromkeys(re.findall(r"(?<!\d)(\d{5,8})(?!\d)", str(req.corpo.get("texto") or ""))))
    if not numeros:
        raise ErroUsuario("Cole o link ou o número do chamado (ex.: https://ajuda.sankhya.com.br/hc/pt-br/requests/123456).")
    proximo = (req.corpo.get("proximo") or "").strip()
    if proximo:
        proximo = data_br(proximo, "Próximo acompanhamento").strftime("%d/%m/%Y")
    with _trava:
        lista = _ler()
        ja = {c["numero"] for c in lista}
        novos = [n for n in numeros if n not in ja]
        for n in novos:
            lista.append({"numero": n, "link": PORTAL + n, "titulo": "", "parceiro": _texto(req.corpo.get("parceiro")),
                          "nota": _texto(req.corpo.get("nota"), LIMITE_TEXTO), "proximo": proximo,
                          "criado": datetime.now().strftime("%d/%m/%Y %H:%M"), "status": "", "atualizado_portal": "",
                          "visto": "", "ultima_resposta": None, "erro": ""})
        _gravar(lista)
    marcar_uso("chamados")
    return 200, {"novos": novos, "ja_existiam": [n for n in numeros if n in ja]}


@rota("POST", "/api/chamados/editar")
def editar(req):
    with _trava:
        lista = _ler()
        c = _achar(lista, req.corpo.get("numero"))
        for campo, limite in (("parceiro", 120), ("titulo", 160), ("nota", LIMITE_TEXTO)):
            if campo in req.corpo:
                c[campo] = _texto(req.corpo.get(campo), limite)
        if "proximo" in req.corpo:
            p = (req.corpo.get("proximo") or "").strip()
            c["proximo"] = data_br(p, "Próximo acompanhamento").strftime("%d/%m/%Y") if p else ""
        _gravar(lista)
    return 200, _com_sinais(c)


@rota("POST", "/api/chamados/visto")
def visto(req):
    """Marca a novidade como vista (o aviso some até o chamado mudar de novo no portal)."""
    with _trava:
        lista = _ler()
        alvos = lista if req.corpo.get("todos") else [_achar(lista, req.corpo.get("numero"))]
        for c in alvos:
            c["visto"] = c.get("atualizado_portal") or ""
        _gravar(lista)
    return 200, {"ok": True}


@rota("POST", "/api/chamados/excluir")
def excluir(req):
    exigir_confirmacao(req)
    numero = str(req.corpo.get("numero") or "").strip()
    with _trava:
        lista = _ler()
        _achar(lista, numero)
        _gravar([c for c in lista if c["numero"] != numero])
    return 200, {"ok": True}


def _resumo_portal(c, dados):
    r = dados.get("request") or {}
    usuarios = {u.get("id"): u.get("name") or "" for u in dados.get("users") or []}
    c["status"] = r.get("status") or c.get("status") or ""
    c["status_label"] = _texto(r.get("status_label"), 120) or c.get("status_label", "")
    c["titulo"] = c.get("titulo") or _texto(r.get("subject"), 160)
    c["titulo_portal"] = _texto(r.get("subject"), 160)
    c["atualizado_portal"] = r.get("updated_at") or c.get("atualizado_portal") or ""
    c["criado_portal"] = r.get("created_at") or ""
    # 06/11/2026 (Fragoso): distinguir quem se manifestou -- solicitante, atendente atribuído, você ou outro do suporte
    agentes = {u.get("id") for u in dados.get("users") or [] if u.get("agent") or u.get("role") in ("agent", "admin")}
    eu = dados.get("eu")
    c["solicitante"] = usuarios.get(r.get("requester_id")) or c.get("solicitante", "")
    c["atribuido"] = usuarios.get(r.get("assignee_id")) or c.get("atribuido", "")

    def papel(autor_id):
        if eu and autor_id == eu:
            return "voce"
        if autor_id and autor_id == r.get("assignee_id"):
            return "atribuido"
        if autor_id and autor_id == r.get("requester_id"):
            return "solicitante"
        if autor_id in agentes:
            return "suporte"
        return "outro"

    ultimas = []
    for com in (dados.get("comments") or [])[:3]:
        corpo = com.get("plain_body") or re.sub(r"<[^>]+>", " ", com.get("html_body") or com.get("body") or "")
        q = _quando(com.get("created_at"))
        ultimas.append({"autor": usuarios.get(com.get("author_id"), ""), "papel": papel(com.get("author_id")),
                        "quando": q.strftime("%d/%m/%Y %H:%M") if q else "", "texto": _texto(html.unescape(corpo), LIMITE_TEXTO)})
    if ultimas:
        c["ultima_resposta"] = ultimas[0]
        c["ultimas"] = ultimas
    c["erro"] = ""
    c["ultima_leitura"] = datetime.now().strftime("%d/%m/%Y %H:%M")


def iniciar_atualizacao(origem="manual", numeros=None):
    def trabalho(t):
        from om_sessao import OM
        lista = _ler()
        alvos = [c for c in lista if (not numeros or c["numero"] in numeros) and c.get("status") != "closed"]
        if not alvos:
            return {"mensagem": "Nenhum chamado para atualizar."}
        t.log(f"Lendo {len(alvos)} chamado(s) no portal ajuda.sankhya.com.br (só leitura)...")
        lidos, erros = {}, {}
        for i, c in enumerate(alvos, 1):
            try:
                lidos[c["numero"]] = OM.ler_chamado(c["numero"])
                t.log(f"  [{i}/{len(alvos)}] {c['numero']}: {STATUS.get(lidos[c['numero']]['request'].get('status'), '?')}")
            except Exception as e:  # um chamado com problema não derruba os outros
                erros[c["numero"]] = str(e)
                t.log(f"  [{i}/{len(alvos)}] {c['numero']}: {e}")
                if "pediu login" in str(e):
                    t.log("  Parando: o portal pediu login. Entre com o Sankhya ID na janela do navegador e atualize de novo.")
                    break
        with _trava:
            atual = _ler()
            for c in atual:
                if c["numero"] in lidos:
                    primeira = not c.get("atualizado_portal")
                    _resumo_portal(c, lidos[c["numero"]])
                    if primeira:
                        c["visto"] = c["atualizado_portal"]   # 1ª leitura não conta como novidade
                elif c["numero"] in erros:
                    c["erro"] = erros[c["numero"]]
            _gravar(atual)
        gravar_json_dados(ARQ_AGENDA, {**(ler_json_dados(ARQ_AGENDA, {}) or {}),
                                       "ultima_leitura": datetime.now().strftime("%d/%m/%Y %H:%M"),
                                       "ultima_auto": time.time()})
        email = _avisar_por_email(t) if origem == "auto" else ""
        marcar_uso("chamados")
        return {"mensagem": f"{len(lidos)} chamado(s) atualizado(s)" + (f", {len(erros)} com erro" if erros else "") + "."
                            + (f" {email}" if email else "")}
    return GERENTE.iniciar("chamados", "Chamados - leitura do portal" + (" (automática)" if origem == "auto" else ""), trabalho)


@rota("POST", "/api/chamados/atualizar")
def atualizar(req):
    numero = str(req.corpo.get("numero") or "").strip()
    return 200, {"tarefa": iniciar_atualizacao("manual", {numero} if numero else None).id}


# ---------------------------------------------------------------- e-mail e leitura automática de hora em hora
def _avisar_por_email(t):
    import configparser
    import smtplib
    from email.mime.text import MIMEText
    import keyring
    from clickup_sync.os_data_diferente import SMTP_INI
    # De hora em hora: cada sinal de cada chamado só vai por e-mail uma vez (muda a chave quando o portal muda).
    agenda = ler_json_dados(ARQ_AGENDA, {}) or {}
    avisados = set(agenda.get("avisados") or [])
    casos, chaves = [], []
    for c in (_com_sinais(c) for c in _ler()):
        novas = [f"{c['numero']}|{s}|{c.get('atualizado_portal') or ''}|{c.get('proximo') or ''}"
                 for s in c["sinais"] if s in ("novidade", "aguardando_voce", "vencido")]
        novas = [k for k in novas if k not in avisados]
        if novas:
            casos.append(c)
            chaves += novas
    if not casos:
        return "Nada novo para avisar por e-mail."
    cfg = configparser.ConfigParser()
    cfg.read(SMTP_INI, encoding="utf-8")
    email = cfg.get("gmail", "email", fallback="").strip()
    senha = (keyring.get_password("sankhya_experience_sync", "GMAIL_APP_PASSWORD") or "").strip()
    if not email or not senha:
        return "E-mail não enviado: Gmail não configurado."
    rotulos = {"novidade": "Resposta nova", "aguardando_voce": "Aguardando você", "vencido": "Acompanhamento vencido",
               "parado": "Parado"}
    e = html.escape
    linhas = "".join(
        f"<tr><td><a href='{e(c['link'])}'>{e(c['numero'])}</a></td><td>{e(c.get('titulo') or '')}</td><td>{e(c.get('parceiro') or '')}</td>"
        f"<td>{e(c['status_txt'])}</td><td><b>{e(', '.join(rotulos[s] for s in c['sinais'] if s in rotulos))}</b></td>"
        f"<td>{e(PAPEIS.get((c.get('ultima_resposta') or {}).get('papel'), ''))} {e((c.get('ultima_resposta') or {}).get('autor', ''))}: "
        f"{e((c.get('ultima_resposta') or {}).get('texto', '')[:200])}</td></tr>" for c in casos)
    corpo = ("<p>Chamados que pedem sua atenção hoje:</p><table border='1' cellpadding='6' cellspacing='0' "
             "style='border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:13px'>"
             "<tr style='background:#e5f3ec'><th>Chamado</th><th>Assunto</th><th>Parceiro</th><th>Status</th><th>Atenção</th>"
             f"<th>Última resposta</th></tr>{linhas}</table><p style='color:#5b6b63;font-size:12px'>Aviso automático da "
             f"Central BP-MS ({datetime.now():%d/%m/%Y %H:%M}). Fonte: portal ajuda.sankhya.com.br.</p>")
    msg = MIMEText(corpo, "html", "utf-8")
    msg["From"], msg["To"] = f"Central BP-MS <{email}>", email
    msg["Subject"] = f"[Central BP-MS] {len(casos)} chamado(s) para acompanhar"
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(email, senha)
            s.sendmail(email, [email], msg.as_string())
    except Exception as ex:  # falha de e-mail não invalida a leitura
        t.log(f"⚠ E-mail não enviado: {ex}")
        return f"E-mail não enviado: {ex}"
    agenda = ler_json_dados(ARQ_AGENDA, {}) or {}
    gravar_json_dados(ARQ_AGENDA, {**agenda, "avisados": (list(avisados) + chaves)[-500:]})
    return f"E-mail enviado com {len(casos)} chamado(s)."


def dia_util(dia):
    """06/11/2026 (Fragoso): sem leitura automática no sábado, no domingo e nos feriados nacionais
    (biblioteca holidays, a mesma da Fase 3; sem ela, só fins de semana ficam de fora)."""
    if dia.weekday() >= 5:
        return False
    try:
        import holidays
        return dia not in holidays.Brazil(years=dia.year)
    except ImportError:
        return True


def checagem_devida(agora_ts, ultima_auto):
    """De hora em hora nos dias úteis, contando da última leitura (manual ou automática)."""
    return (dia_util(datetime.fromtimestamp(agora_ts).date())
            and agora_ts - float(ultima_auto or 0) >= INTERVALO_AUTOMATICO)


def _laco_checagem():
    ultima_tentativa = 0
    while True:
        try:
            ultima_auto = (ler_json_dados(ARQ_AGENDA, {}) or {}).get("ultima_auto")
            if _ler() and checagem_devida(time.time(), ultima_auto) and time.time() - ultima_tentativa >= 900:
                ultima_tentativa = time.time()
                iniciar_atualizacao("auto")
        except Ocupado:
            ultima_tentativa = time.time() - 900 + 300
        except Exception as e:  # a checagem automática nunca derruba o serviço
            print(f"[Chamados] Falha na checagem automática: {e}")
        time.sleep(60)


threading.Thread(target=_laco_checagem, daemon=True, name="chamados-auto").start()

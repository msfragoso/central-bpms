# -*- coding: utf-8 -*-
"""
Verificação de Pedidos (05/11/2026, pedido do Fragoso): os pedidos de horas (naturezas 110401 e
110501) cobrem as tarefas alocadas na semana? Só leitura: nada muda no ClickUp nem no Experience.

Conta do módulo: saldo do pedido - horas das tarefas do período que ainda não terminaram.
O consumido do Experience só desconta OS fechada, por isso os dias que já passaram também entram.

Entram todos os Apontamentos de OS (OS Experience e os que têm "Apontamento OS" no nome). Hora
Dobrada conta 1x. A checagem roda às 08h de segunda a sexta e também pelo botão da tela. Pedido em
alerta na semana atual gera e-mail para o Gmail da Agenda, uma vez só, a menos que a situação piore.
"""
import html
import json
import threading
import time
from datetime import date, datetime, time as hora, timedelta

from app_backlog import TEAM_ID, _get, _valor
from nucleo import (GERENTE, ErroUsuario, Ocupado, dados_arquivo, exigir_confirmacao, gravar_json_dados, ler_json_dados,
                    marcar_uso, periodo_br, rota)

ARQ = "pedidos_ultima_verificacao.json"
ARQ_AGENDA = "pedidos_agenda.json"
ARQ_AVISADOS = "pedidos_avisados.json"
ARQ_PENDENTES = "pedidos_ajustes_pendentes.json"   # ajustado no OM, falta o Experience (manual)
ARQ_LOG_AJUSTES = "ajustes_pedidos.jsonl"
SUGESTAO_MINIMA_HORAS = 20
MAX_HORAS_POR_AJUSTE = 500
HORA_CHECAGEM = 8
ESPERA_NOVA_TENTATIVA = 1800
LIMITE_BAIXO_HORAS = 8
STATUS_ENCERRADOS = {"concluído", "concluido", "não executado", "nao executado", "cancelado", "suspenso"}
MAX_PAGINAS = 60


def _e_apontamento_de_os(nome):
    return nome == "OS Experience" or "apontamento os" in (nome or "").lower()


def _semana_atual():
    hoje = date.today()
    seg = hoje - timedelta(days=hoje.weekday())
    return seg, seg + timedelta(days=6)


def _campos(tarefa):
    saida = {}
    for cf in tarefa.get("custom_fields", []):
        saida[cf.get("name")] = _valor(cf)[0]
    return saida


def _tarefas_do_periodo(ini, fim, t):
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS, SPACE_ID_PMO_BP_MS
    de = int(datetime.combine(ini, hora.min).timestamp() * 1000)
    ate = int(datetime.combine(fim, hora.max).timestamp() * 1000)
    tarefas = []
    for pagina in range(MAX_PAGINAS):
        lote = _get(f"{CLICKUP_API}/team/{TEAM_ID}/task", CLICKUP_HEADERS, {
            "space_ids[]": SPACE_ID_PMO_BP_MS, "subtasks": "true", "include_closed": "true", "page": pagina,
            "due_date_gt": de - 1, "due_date_lt": ate + 1}).get("tasks", [])
        tarefas += lote
        if len(lote) < 100:
            return tarefas
    t.log(f"⚠ Parei em {MAX_PAGINAS} páginas de tarefas: o resultado pode estar incompleto.")
    return tarefas


def _classificar(tarefas):
    """Separa o que consome pedido, agrupado por FAP. Devolve (por_fap, avisos, ignoradas)."""
    from clickup_sync.config import PASTAS_IGNORADAS
    from clickup_sync.list_discovery import extrair_fap_do_nome_lista
    from clickup_sync.saldo_pedidos import _minutos_do_periodo
    por_fap, avisos = {}, []
    ignoradas = {"encerradas": 0, "outro_apontamento": 0, "planejamento": 0, "lixeira": 0}
    for x in tarefas:
        if (x.get("folder") or {}).get("name", "").strip() in PASTAS_IGNORADAS:
            continue
        status = (x.get("status") or {})
        if status.get("type") in ("closed", "done") or (status.get("status") or "").lower() in STATUS_ENCERRADOS:
            ignoradas["encerradas"] += 1
            continue
        c = _campos(x)
        if not _e_apontamento_de_os(c.get("Apontamento")):
            ignoradas["outro_apontamento"] += 1
            continue
        if c.get("Agenda") == "Planejamento":
            ignoradas["planejamento"] += 1
            continue
        if c.get("Experience") == "Lixeira":
            ignoradas["lixeira"] += 1
            continue
        lista = (x.get("list") or {}).get("name", "")
        fap = extrair_fap_do_nome_lista(lista)
        if not fap:
            avisos.append(f"Tarefa '{x.get('name')}' na lista '{lista}': FAP não identificada no nome da lista.")
            continue
        minutos = _minutos_do_periodo(c.get("Período")) if c.get("Período") else None
        por_fap.setdefault(fap, {"lista": lista, "tarefas": []})["tarefas"].append({
            "id": x.get("id"), "nome": x.get("name"), "url": x.get("url"),
            "data": datetime.fromtimestamp(int(x["due_date"]) / 1000).strftime("%d/%m/%Y") if x.get("due_date") else "",
            "periodo": c.get("Período") or "", "minutos": minutos, "status": status.get("status") or "",
            "responsavel": ", ".join(a.get("username") or "" for a in x.get("assignees", [])),
        })
    return por_fap, avisos, ignoradas


def _situacao(saldo, horas, tem_pedido, ambiguo):
    if not tem_pedido:
        return "SEM PEDIDO"
    if saldo is None:
        return "CONFERIR"
    sobra = saldo - horas
    if sobra < 0:
        return "FALTAM HORAS"
    if sobra < LIMITE_BAIXO_HORAS * 60:
        return "SALDO BAIXO"
    return "CONFERIR" if ambiguo else "OK"


def _tipo_do_pedido(pedido):
    """05/11/2026 (Fragoso): sinaliza o que não é 104 - SERV MEDIÇÃO, que só tem ajuste manual."""
    tipo = " ".join(str(pedido.get("operation_type") or "").split())
    return {"tipo": tipo or "não informado", "medicao": tipo.split(" ")[0] == "104"}


def _linha_do_projeto(token, fap, grupo):
    import experience_api as exp
    from clickup_sync.saldo_pedidos import _escolher_pedidos, _fmt, _hhmm_para_minutos, _nome_limpo, _rotulo_pedido
    tarefas = sorted(grupo["tarefas"], key=lambda x: (x["data"][6:], x["data"][3:5], x["data"][:2]))
    horas = sum(x["minutos"] or 0 for x in tarefas)
    sem_periodo = sum(1 for x in tarefas if x["minutos"] is None)
    base = {"fap": fap, "parceiro": grupo["lista"], "pedidos": [], "negociado": None, "consumido": None, "saldo": None,
            "horas": horas, "sobra": None, "qtd_tarefas": len(tarefas), "sem_periodo": sem_periodo, "observacao": "",
            "tarefas": [{**x, "horas": _fmt(x["minutos"]) if x["minutos"] is not None else "sem período"} for x in tarefas]}
    projeto = exp.find_implantation_by_fap(token, fap)
    if not projeto:
        # Não dá para afirmar que falta pedido: a busca também volta vazia em falha de acesso.
        return {**base, "situacao": "CONFERIR", "observacao": "Projeto da FAP não encontrado no Experience."}
    base["parceiro"] = _nome_limpo(projeto.get("company_name") or grupo["lista"])
    pedidos, erro = exp.get_applications_by_implantation(token, projeto["id"])
    if erro:
        return {**base, "situacao": "CONFERIR", "observacao": erro}
    escolhidos = _escolher_pedidos(pedidos)
    if not escolhidos:
        return {**base, "situacao": "SEM PEDIDO", "observacao": "Nenhum pedido 110401/110501 liberado para execução."}
    leituras = [_hhmm_para_minutos(p.get("remaining_hours")) for p in escolhidos]
    saldo = None if any(v is None for v in leituras) else sum(leituras)
    somar = lambda chave: sum(_hhmm_para_minutos(p.get(chave)) or 0 for p in escolhidos)
    ambiguo = len(escolhidos) > 1
    obs = []
    if ambiguo:
        obs.append(f"{len(escolhidos)} pedidos liberados: saldo somado, confira qual será consumido.")
    if sem_periodo:
        obs.append(f"{sem_periodo} tarefa(s) sem Período, fora da conta: podem faltar mais horas.")
    pendentes = ler_json_dados(ARQ_PENDENTES, {}) or {}
    mudou = False
    for p in escolhidos:
        cod = _rotulo_pedido(p)
        if cod in pendentes:
            if (_hhmm_para_minutos(p.get("negotiated_hours")) or 0) >= pendentes[cod]["horas"] * 60:
                del pendentes[cod]
                mudou = True
            else:
                obs.append(f"Falta ajustar no Experience: pedido {cod}, de {p.get('negotiated_hours')} para {pendentes[cod]['horas']}:00.")
    if mudou:
        gravar_json_dados(ARQ_PENDENTES, pendentes)
    pedidos_linha = [{"rotulo": _rotulo_pedido(p), "natureza": p.get("nature") or "", **_tipo_do_pedido(p)} for p in escolhidos]
    return {**base, "pedidos": pedidos_linha, "medicao": all(p["medicao"] for p in pedidos_linha),
            "negociado": somar("negotiated_hours"), "consumido": somar("consumed_hours"), "saldo": saldo,
            "sobra": None if saldo is None else saldo - horas, "situacao": _situacao(saldo, horas, True, ambiguo),
            "observacao": " ".join(obs)}


ORDEM = {"FALTAM HORAS": 0, "SEM PEDIDO": 1, "SALDO BAIXO": 2, "CONFERIR": 3, "OK": 4}


ALERTAS = ("FALTAM HORAS", "SEM PEDIDO", "SALDO BAIXO")


def _fmt_h(minutos):
    if minutos is None:
        return "—"
    a = abs(minutos)
    return f"{'-' if minutos < 0 else ''}{a // 60}:{a % 60:02d}"


def _casos_para_avisar(linhas, semana):
    """Alertas novos ou que pioraram nesta semana. Devolve (casos, situação para gravar depois do envio)."""
    guardado = ler_json_dados(ARQ_AVISADOS, {}) or {}
    antes = guardado.get("avisados", {}) if guardado.get("semana") == semana else {}
    casos, agora = [], {}
    for r in linhas:
        if r["situacao"] not in ALERTAS:
            continue
        valor = r.get("sobra") if r.get("sobra") is not None else -10**9
        chave = f"{r['fap']}|{r['situacao']}"
        agora[chave] = min(valor, antes.get(chave, valor))
        if chave not in antes or valor < antes[chave]:
            casos.append(r)
    return casos, {"semana": semana, "avisados": agora}


def _enviar_email(casos, de, ate):
    """Envia pelo Gmail já configurado na Agenda, para ele mesmo. Devolve None ou o motivo da falha."""
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
    linhas = "".join(
        f"<tr><td><b>{e(r['situacao'])}</b></td><td>{e(r['parceiro'])}</td><td>{e(str(r['fap']))}</td>"
        f"<td>{e(', '.join(p['rotulo'] for p in r.get('pedidos') or []) or '-')}</td>"
        f"<td>{e(', '.join(p.get('tipo', '') for p in r.get('pedidos') or []))}"
        f"{'<br><b style=color:#b42318>Não é Medição: ajuste manual</b>' if r.get('medicao') is False else ''}</td>"
        f"<td style='text-align:right'>{_fmt_h(r.get('saldo'))}</td><td style='text-align:right'>{_fmt_h(r.get('horas'))}</td>"
        f"<td style='text-align:right;color:#b42318'><b>{_fmt_h(r.get('sobra'))}</b></td><td>{e(r.get('observacao') or '')}</td></tr>"
        for r in casos)
    corpo = (f"<p>A Verificação de Pedidos encontrou alerta no período de <b>{e(de)} a {e(ate)}</b>:</p>"
             "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:13px'>"
             "<tr style='background:#e5f3ec'><th>Situação</th><th>Parceiro</th><th>FAP</th><th>Pedido</th><th>Tipo de operação</th><th>Saldo</th>"
             f"<th>Tarefas</th><th>Sobra</th><th>Observação</th></tr>{linhas}</table>"
             "<p style='color:#5b6b63;font-size:12px'>Aviso automático da Central BP-MS. Cada alerta é avisado uma vez na "
             f"semana, a menos que piore ({datetime.now():%d/%m/%Y %H:%M}).</p>")
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Central BP-MS <{email}>"
    msg["To"] = email
    msg["Subject"] = f"[Central BP-MS] {len(casos)} pedido(s) em alerta de horas ({de} a {ate})"
    msg.attach(MIMEText(corpo, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(email, senha)
        s.sendmail(email, [email], msg.as_string())
    return None


def _avisar(linhas, ini, fim, t):
    """E-mail só para o período da semana atual. Devolve o texto mostrado na tela."""
    seg, dom = _semana_atual()
    if (ini, fim) != (seg, dom):
        return "E-mail só é enviado para a semana atual."
    casos, situacao = _casos_para_avisar(linhas, seg.isoformat())
    if not casos:
        gravar_json_dados(ARQ_AVISADOS, situacao)
        return "Nenhum alerta novo para enviar por e-mail."
    try:
        erro = _enviar_email(casos, f"{ini:%d/%m/%Y}", f"{fim:%d/%m/%Y}")
    except Exception as e:  # falha de e-mail não invalida a verificação; tenta de novo na próxima
        erro = f"{e.__class__.__name__}: {e}"
    if erro:
        t.log(f"⚠ E-mail não enviado: {erro}")
        return f"E-mail não enviado: {erro}"
    gravar_json_dados(ARQ_AVISADOS, situacao)
    t.log(f"E-mail enviado com {len(casos)} alerta(s).")
    return f"E-mail enviado com {len(casos)} alerta(s)."


def iniciar_verificacao(ini, fim, origem="manual"):
    def trabalho(t):
        import experience_api as exp
        from clickup_sync.config import EXPERIENCE_PASS, EXPERIENCE_USER
        t.log(f"Lendo as tarefas de {ini:%d/%m/%Y} a {fim:%d/%m/%Y} no ClickUp...")
        tarefas = _tarefas_do_periodo(ini, fim, t)
        por_fap, avisos, ignoradas = _classificar(tarefas)
        t.log(f"{len(tarefas)} tarefa(s) lida(s); {sum(len(g['tarefas']) for g in por_fap.values())} consomem pedido, em {len(por_fap)} FAP(s).")
        token = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
        if not token:
            # 05/11/2026: sem login tudo virava "SEM PEDIDO" e ia por e-mail. Para aqui, sem gravar nem avisar.
            # Na checagem das 08h, conta como feita: repetir o login errado pode bloquear a conta.
            if origem == "08h":
                gravar_json_dados(ARQ_AGENDA, {"ultima_ok": date.today().isoformat()})
            raise ErroUsuario("O Experience recusou o login, por isso a verificação parou e nada foi avisado. O motivo está no log "
                              "acima. Se a senha expirou: troque no Experience e grave a nova na tela Credenciais.")
        linhas = []
        for i, (fap, grupo) in enumerate(sorted(por_fap.items()), 1):
            try:
                linha = _linha_do_projeto(token, fap, grupo)
            except Exception as e:  # uma FAP com problema não derruba a verificação
                linha = {"fap": fap, "parceiro": grupo["lista"], "pedidos": [], "situacao": "CONFERIR", "horas": 0,
                         "qtd_tarefas": len(grupo["tarefas"]), "sem_periodo": 0, "tarefas": [], "observacao": f"Falha ao consultar: {e}"}
            linhas.append(linha)
            t.log(f"[{i}/{len(por_fap)}] FAP {fap} {linha['parceiro']}: {linha['situacao']}"
                  + (f" (saldo {_fmt_h(linha.get('saldo'))}, tarefas {_fmt_h(linha.get('horas'))})" if linha.get("saldo") is not None else ""))
        linhas.sort(key=lambda r: (ORDEM.get(r["situacao"], 9), r["sobra"] if r.get("sobra") is not None else 10**9))
        alertas = sum(1 for r in linhas if r["situacao"] in ALERTAS)
        email = _avisar(linhas, ini, fim, t)
        resultado = {"de": ini.strftime("%d/%m/%Y"), "ate": fim.strftime("%d/%m/%Y"), "quando": datetime.now().strftime("%d/%m/%Y %H:%M"),
                     "origem": origem, "email": email, "linhas": linhas, "avisos": avisos, "ignoradas": ignoradas,
                     "alertas": alertas, "limite_baixo": LIMITE_BAIXO_HORAS, "sugestao_minima": SUGESTAO_MINIMA_HORAS}
        gravar_json_dados(ARQ, resultado)
        marcar_uso("pedidos")
        if origem == "08h":
            gravar_json_dados(ARQ_AGENDA, {"ultima_ok": date.today().isoformat()})
        return {"mensagem": f"Verificação concluída: {alertas} pedido(s) em alerta. {email}" if alertas
                else f"Verificação concluída: nenhum alerta. {email}", "resultado": resultado}

    return GERENTE.iniciar("pedidos", "Verificação de Pedidos" + (" (08h)" if origem == "08h" else ""), trabalho)


@rota("POST", "/api/pedidos/verificar")
def verificar(req):
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate")) if req.corpo.get("de") else _semana_atual()
    return 200, {"tarefa": iniciar_verificacao(ini, fim).id}


def checagem_devida(agora, ultima_ok):
    """Segunda a sexta, a partir das 08h, uma vez por dia. PC ligado mais tarde verifica ao abrir o serviço."""
    return agora.weekday() < 5 and agora.hour >= HORA_CHECAGEM and ultima_ok != agora.date().isoformat()


def _laco_checagem():
    ultima_tentativa = 0
    while True:
        try:
            ultima_ok = (ler_json_dados(ARQ_AGENDA, {}) or {}).get("ultima_ok")
            if checagem_devida(datetime.now(), ultima_ok) and time.time() - ultima_tentativa >= ESPERA_NOVA_TENTATIVA:
                ultima_tentativa = time.time()
                seg, dom = _semana_atual()
                iniciar_verificacao(seg, dom, "08h")
        except Ocupado:
            ultima_tentativa = time.time() - ESPERA_NOVA_TENTATIVA + 300   # outro processo rodando: tenta em 5 min
        except Exception as e:  # a checagem automática nunca derruba o serviço
            print(f"[Pedidos] Falha na checagem automática: {e}")
        time.sleep(60)


threading.Thread(target=_laco_checagem, daemon=True, name="pedidos-08h").start()


def _ajustador():
    from om_ajuste_pedido import Ajustador
    from om_sessao import OM
    if OM.estado != "conectado":
        raise ErroUsuario("Conecte ao Sankhya-OM antes de ajustar: use o botão 'Conectar ao OM' desta tela e faça o login.")
    return Ajustador(OM.chamar_central)


def _resumo_ajuste(p):
    from om_ajuste_pedido import texto_numero
    cab = p["cabecalho"]
    return {"pedido": cab.get("NUNOTA"), "parceiro": " ".join(str(cab.get("Parceiro.NOMEPARC") or "").split()),
            "tipo": f"{cab.get('CODTIPOPER')} - {' '.join(str(cab.get('TipoOperacao.DESCROPER') or '').split())}",
            "natureza": f"{cab.get('CODNAT')} - {cab.get('Natureza.DESCRNAT') or ''}", "qtd_atual": texto_numero(p["atual"]),
            "qtd_nova": texto_numero(p["nova"]), "valor_item_atual": p["item"].get("VLRTOT"), "valor_item_novo": p["calculado"].get("VLRTOT"),
            "valor_nota_atual": cab.get("VLRNOTA"), "dtalter": p["item"].get("DTALTER")}


def _registrar_ajuste(**campos):
    linha = json.dumps({"quando": datetime.now().isoformat(timespec="seconds"), **campos}, ensure_ascii=False)
    with open(dados_arquivo(ARQ_LOG_AJUSTES), "a", encoding="utf-8") as f:
        f.write(linha + "\n")


@rota("POST", "/api/pedidos/ajuste/preparar")
def preparar_ajuste(req):
    """Só leitura: confere as regras e pede ao OM o recálculo, sem gravar."""
    from om_ajuste_pedido import AjusteRecusado, item_de_horas, numero, texto_numero, validar_cabecalho
    pedido = str(req.corpo.get("pedido") or "").strip()
    try:
        horas = int(req.corpo.get("horas_somar"))
    except (TypeError, ValueError):
        raise ErroUsuario("Digite as horas a somar em número inteiro.")
    if not 1 <= horas <= MAX_HORAS_POR_AJUSTE:
        raise ErroUsuario(f"As horas a somar precisam estar entre 1 e {MAX_HORAS_POR_AJUSTE}.")
    aj = _ajustador()
    try:
        cab, itens = aj.ler(pedido)
        validar_cabecalho(cab)
        nova = numero(item_de_horas(itens)["QTDNEG"]) + horas
        return 200, _resumo_ajuste(aj.preparar(pedido, texto_numero(nova)))
    except AjusteRecusado as e:
        raise ErroUsuario(str(e))
    except RuntimeError as e:
        raise ErroUsuario(f"{e} Nada foi gravado.")


@rota("POST", "/api/pedidos/ajuste/gravar")
def gravar_ajuste(req):
    """Grava só depois da confirmação na tela. Confere as regras de novo e o resultado no OM."""
    from om_ajuste_pedido import AjusteRecusado, texto_numero
    exigir_confirmacao(req)
    pedido = str(req.corpo.get("pedido") or "").strip()
    qtd_nova = str(req.corpo.get("qtd_nova") or "").strip()
    aj = _ajustador()
    try:
        r = aj.gravar(pedido, qtd_nova, req.corpo.get("dtalter"))
    except AjusteRecusado as e:
        _registrar_ajuste(pedido=pedido, qtd_nova=qtd_nova, ok=False, motivo=str(e))
        raise ErroUsuario(str(e))
    except RuntimeError as e:
        _registrar_ajuste(pedido=pedido, qtd_nova=qtd_nova, ok=False, motivo=str(e))
        raise ErroUsuario(f"{e} Confira o pedido no OM antes de tentar de novo.")
    resumo = _resumo_ajuste(r)
    resumo["valor_item_gravado"] = r["item_depois"].get("VLRTOT")
    resumo["valor_nota_nova"] = (r.get("cabecalho_depois") or {}).get("VLRNOTA")
    resumo["surpresas"] = r["surpresas"]
    _registrar_ajuste(ok=True, **resumo)
    pendentes = ler_json_dados(ARQ_PENDENTES, {}) or {}
    pendentes[pedido] = {"horas": int(numero_horas(resumo["qtd_nova"])), "quando": datetime.now().strftime("%d/%m/%Y %H:%M")}
    gravar_json_dados(ARQ_PENDENTES, pendentes)
    return 200, resumo


def numero_horas(texto):
    return float(texto)


@rota("GET", "/api/pedidos/ultima")
def ultima(req):
    seg, dom = _semana_atual()
    return 200, {"resultado": ler_json_dados(ARQ), "de": seg.strftime("%d/%m/%Y"), "ate": dom.strftime("%d/%m/%Y")}


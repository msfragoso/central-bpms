# -*- coding: utf-8 -*-
"""
Aceite de OS (aceite_os/enviar_aceite_os.py) -- mesmo fluxo da tela_aceite_os.py:
"Conferir" só lê o Experience; "Enviar marcadas" gera o aceite e dispara o
e-mail do Experience para os aprovadores (sem volta), FAP a FAP, com a
reconferência que o próprio motor já faz em enviar_fap.
"""
import json
import os
from datetime import date, datetime, timedelta

from nucleo import GERENTE, PASTA_DADOS, PASTAS, ErroUsuario, exigir_confirmacao, marcar_uso, periodo_br, rota

ESTADO = {"token": None, "resultados": {}, "revisado": False, "sem_referencia": {}}


def _core():
    import enviar_aceite_os as core
    return core


def _login(core, t, novo=False):
    """Conferir sempre faz login novo; o envio reaproveita o token da conferência (como a tela Tk)."""
    if ESTADO["token"] and not novo:
        return ESTADO["token"]
    from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
    t.log("Login no Experience...")
    token = core.exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
    if not token:
        raise RuntimeError("Falha no login do Experience.")
    ESTADO["token"] = token
    return token


def _linha(r):
    if r["bloqueios"]:
        situacao = "BLOQUEADA"
    elif r["os"]:
        situacao = "PRONTA"
    else:
        situacao = "VAZIA"
    def os_(o):
        return {"id": o.get("id"), "num": o.get("numos_sankhya"), "data": o.get("date_done"), "realizado": o.get("diff_time"),
                "processo": o.get("process_names"), "ok": o.get("_realizado_ok", True),
                "executante": o.get("_executante") or "", "inicio": o.get("_inicio") or "",
                "fim": o.get("_fim") or "", "intervalo": o.get("_intervalo") or "",
                "alertas": o.get("_alertas") or [], "solucao": o.get("_solucao") or ""}
    return {
        "fap": r["fap"], "parceiro": r["parceiro"], "situacao": situacao,
        "num_os": [o.get("numos_sankhya") for o in r["os"]], "horas": r["total_horas"] if r["os"] else "",
        "aprovadores": [{"nome": a.get("person_name"), "email": a.get("email")} for a in r["aprovadores"]],
        "bloqueios": r["bloqueios"], "os": [os_(o) for o in r["os"]],
        "fora_periodo": [os_(o) for o in r["fora_periodo"]],
    }


def _preencher_executantes(token, resultados, periodo, log):
    """
    A lista de OS do aceite (available-accepted-os) não traz quem executou.
    Busca numa única consulta só de leitura (search_orders, a mesma da
    conferência) o person_name de cada OS, pelo número Sankhya.
    """
    from experience_api.orders import search_orders
    com_os = [r for r in resultados if r["impl_id"] and (r["os"] or r["fora_periodo"])]
    if not com_os:
        return
    impl_ids = sorted({r["impl_id"] for r in com_os})
    de = periodo[0].isoformat()
    ate = (periodo[1] + timedelta(days=1)).isoformat()
    nomes = {}
    try:
        for integrada in ("S", ""):
            for o in search_orders(token, impl_ids, de, ate, integrated=integrada) or []:
                num = str(o.get("numos_sankhya") or "")
                if num and o.get("person_name") and num not in nomes:
                    nomes[num] = o["person_name"]
    except Exception as e:  # executante é só informativo: nunca derruba a conferência
        log(f"Aviso: não consegui buscar os executantes ({e}).")
        return
    for r in com_os:
        for o in r["os"] + r["fora_periodo"]:
            o["_executante"] = nomes.get(str(o.get("numos_sankhya") or ""), "")


def _min(hhmm):
    try:
        h, m = str(hhmm or "").strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def _conferir_horarios(token, resultados, log):
    """
    Regras de VERIFICAR (pedido do Fragoso, 13/10/2026), só sinalizam, não bloqueiam:
      - mais de 8h realizadas sem intervalo lançado;
      - horas realizadas quebradas: fora de :00 / :30 (ex.: 15:45, 15:01, 16:03).
    O horário de início/fim/intervalo vem das tarefas da OS (get_order_tasks, só leitura).
    """
    from experience_api.orders import get_order_tasks, extrair_solucao
    todas = [o for r in resultados for o in r["os"]]
    for i, o in enumerate(todas, 1):
        alertas = []
        try:
            tarefas = get_order_tasks(token, o["id"]) or []
        except Exception as e:  # informativo: nunca derruba a conferência
            log(f"  Aviso: não consegui ler os horários da OS {o.get('numos_sankhya')} ({e}).")
            tarefas = []
        inicio = min((x.get("hour_to_start") for x in tarefas if x.get("hour_to_start")), default="")
        fim = max((x.get("hour_to_finish") for x in tarefas if x.get("hour_to_finish")), default="")
        intervalos = [_min(x.get("hour_to_lunch")) or 0 for x in tarefas]
        intervalo = sum(intervalos)
        realizado = _min(o.get("diff_time"))
        o["_inicio"], o["_fim"] = inicio, fim
        # Solução da OS (16/10/2026): mesmo texto da Consulta de OS, das tarefas da OS.
        o["_solucao"] = "\n\n".join(s for s in (extrair_solucao(x.get("additional_information")) for x in tarefas) if s)
        o["_intervalo"] = f"{intervalo // 60:02d}:{intervalo % 60:02d}" if tarefas else ""
        if realizado is not None and realizado > 8 * 60 and tarefas and intervalo == 0:
            alertas.append(f"{o.get('diff_time')} h sem intervalo lançado")
        # 13/10/2026: horas quebradas só olham o REALIZADO (início/fim/intervalo não).
        if realizado is not None and realizado % 30:
            alertas.append(f"horas realizadas quebradas: {o.get('diff_time')}")
        o["_alertas"] = alertas
        if i % 10 == 0:
            log(f"  horários conferidos: {i}/{len(todas)}")


@rota("GET", "/api/aceite/opcoes")
def opcoes(req):
    segunda = date.today() - timedelta(days=date.today().weekday())
    ini = segunda - timedelta(days=7)
    return 200, {"de": ini.strftime("%d/%m/%Y"), "ate": (ini + timedelta(days=6)).strftime("%d/%m/%Y")}


@rota("POST", "/api/aceite/conferir")
def conferir(req):
    periodo = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    faps_txt = [f.strip() for f in (req.corpo.get("faps") or "").replace(";", ",").split(",") if f.strip()]

    def trabalho(t):
        core = _core()
        token = _login(core, t, novo=True)
        faps = core.universo_de_faps(faps_txt or None, token)   # 05/11/2026: inclui os projetos ativos do Experience
        t.log(f"Período: {periodo[0]:%d/%m/%Y} a {periodo[1]:%d/%m/%Y}")
        res = core.conferir_todas(token, faps, periodo, t.log)
        t.log("Buscando os executantes das OS (só leitura)...")
        _preencher_executantes(token, res, periodo, t.log)
        t.log("Conferindo início, fim e intervalo de cada OS (só leitura)...")
        _conferir_horarios(token, res, t.log)
        verificar = sum(1 for r in res for o in r["os"] if o.get("_alertas"))
        ESTADO["resultados"] = {r["fap"]: r for r in res}
        ESTADO["sem_referencia"] = {}
        ESTADO["revisado"] = False  # 10/11/2026: toda conferência nova exige nova verificação dos textos antes do envio
        t.adicionar_arquivo("Prévia (.csv)", core.salvar_csv(res))
        prontas = sum(1 for r in res if r["os"] and not r["bloqueios"])
        bloq = sum(1 for r in res if r["bloqueios"])
        vazias = sum(1 for r in res if not r["os"] and not r["bloqueios"])
        marcar_uso("aceite")
        return {"mensagem": f"Conferência concluída: {prontas} pronta(s), {bloq} bloqueada(s), "
                            f"{vazias} FAP(s) sem OS no período (ocultas), {verificar} OS para VERIFICAR. Nada foi enviado.",
                "resultado": {"linhas": [_linha(r) for r in res if r["os"] or r["bloqueios"]]}}

    t = GERENTE.iniciar("aceite_conferir", "Aceite de OS - conferência (só leitura)", trabalho,
                        pasta=PASTAS["aceite"])
    return 200, {"tarefa": t.id}


# ---------------------------------------------------------------- revisão do texto da Solução (10/11/2026)
MARCADOR_SOLUCAO = "--- Informações Adicionais ---"
LIMITE_SOLUCAO = 8000


def _localizar_os(fap, oid):
    r = ESTADO["resultados"].get(str(fap))
    o = next((x for x in (r["os"] if r else []) if str(x["id"]) == str(oid)), None)
    if not o or r["bloqueios"]:
        raise ErroUsuario("Esta OS não está na última conferência como pronta. Clique em Conferir de novo.")
    return r, o


@rota("POST", "/api/aceite/revisar-textos")
def revisar_textos(req):
    """Só lê: passa o corretor local nas Soluções da última conferência."""
    textos = {f"{r['fap']}|{o['id']}": o.get("_solucao") or "" for r in ESTADO["resultados"].values() if not r["bloqueios"] for o in r["os"]}
    if not textos:
        raise ErroUsuario("Clique em Conferir antes de revisar os textos.")

    def trabalho(t):
        import revisor_texto
        t.log(f"Revisando {len(textos)} texto(s) neste computador. Nada é gravado nesta etapa.")
        revisoes = revisor_texto.revisar_varios(textos, t.log)
        for k, v in revisoes.items():
            v["original"] = textos[k]
        t.log("Comparando a Solução com o título e o Detalhamento das tarefas (só leitura)...")
        aderencias, sem_referencia = _aderencias(_login(_core(), t), t, revisoes)
        ESTADO["sem_referencia"] = sem_referencia
        ESTADO["revisado"] = True
        marcar_uso("aceite")
        return {"mensagem": f"Revisão concluída: {len(revisoes)} de {len(textos)} texto(s) com ajuste ou ponto a conferir e "
                            f"{len(aderencias)} para conferir a aderência à demanda. Nada foi gravado.",
                "resultado": {"revisoes": revisoes, "aderencias": aderencias, "sem_referencia": sem_referencia}}

    t = GERENTE.iniciar("aceite_revisar", "Aceite de OS - revisão dos textos", trabalho, pasta=PASTAS["aceite"])
    return 200, {"tarefa": t.id}


def _aderencias(token, t, revisoes):
    """
    Aderência da Solução à demanda (10/11/2026): acha a tarefa pela TAG do lançamento original e compara com o título
    e o Detalhamento. Só lê. Falha em uma OS não derruba a revisão.
    """
    import requests
    from concurrent.futures import ThreadPoolExecutor
    import aderencia_texto as AT
    from app_conferencia import _tag_do_lancamento
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS
    cache, alvos, sem_tarefa = {}, [], 0
    for r in ESTADO["resultados"].values():
        if r["bloqueios"]:
            continue
        for o in r["os"]:
            pedido = {"implantation_id": r["impl_id"], "person_name": o.get("_executante"), "application_code": o.get("application_code")}
            try:
                tag = _tag_do_lancamento(token, cache, pedido, o.get("date_done"), o.get("_inicio"))
            except Exception:
                tag = None
            if tag and (o.get("_solucao") or "").strip():
                alvos.append((f"{r['fap']}|{o['id']}", tag, o["_solucao"]))
            else:
                sem_tarefa += 1

    def ler(item):
        k, tag, sol = item
        try:
            resp = requests.get(f"{CLICKUP_API}/task/{tag}", headers=CLICKUP_HEADERS, timeout=20)
            resp.raise_for_status()
            tarefa = resp.json()
        except requests.RequestException:
            return k, None, sol
        det = next((c.get("value") or "" for c in tarefa.get("custom_fields") or [] if c.get("name") == "Detalhamento"), "")
        return k, (tarefa.get("name") or "", str(det or ""), tarefa.get("url") or f"https://app.clickup.com/t/{tag}", tag), sol

    termos = AT.termos()
    saida, sem_ref, contagem = {}, {}, {"conferir": 0, "ok": 0, "ignorar": 0, "falha": 0}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for k, dados, sol in ex.map(ler, alvos):
            if dados is None:
                contagem["falha"] += 1
                continue
            situacao = AT.avaliar(dados[0], dados[1], sol, termos)
            contagem[situacao] += 1
            if situacao == "conferir":
                saida[k] = {"titulo": dados[0], "detalhamento": dados[1], "url": dados[2]}
            elif situacao == "ignorar":
                texto_base = (revisoes.get(k) or {}).get("sugerido") or sol
                novo_titulo, novo_detalhe = AT.sugerir(dados[0], dados[1], texto_base, termos)
                sem_ref[k] = {"titulo": dados[0], "detalhamento": dados[1], "url": dados[2], "tarefa": dados[3], "motivo": AT.motivo_sem_referencia(dados[0], dados[1], termos),
                              "sugestao_titulo": novo_titulo, "sugestao_detalhamento": novo_detalhe}
    t.log(f"Aderência: {contagem['conferir']} a conferir, {contagem['ok']} ok, {contagem['ignorar']} sem boa referência, "
          f"{sem_tarefa} sem tarefa localizada, {contagem['falha']} com falha de leitura.")
    return saida, sem_ref


def _dados_da_gravacao(token, core, r, o, original, texto):
    """Confere se a OS pode ser alterada e monta o corpo igual ao da tela do Experience. Não grava nada."""
    from experience_api.orders import extrair_solucao, get_order_tasks, search_orders
    oid = int(o["id"])
    chk = core.post_com_retry(f"{core._BASE}/orders/check-edit", core.auth_headers(token), {"order_id": oid})
    if core._erro(chk):
        raise ErroUsuario(f"O Experience não liberou a edição: {core._erro(chk)}")
    c = chk.get("data") or {}
    motivos = [m for m, ok in (("o status do projeto não permite", c.get("impl_status_check")), ("o aceite não permite", c.get("acpt_status_check")),
                               ("a OS foi criada há mais de 30 dias", c.get("created_30days_check"))) if not ok]
    if c.get("accept_id") or c.get("accept_status"):
        motivos.append("a OS já tem aceite gerado")
    if c.get("has_integrated_orders") or c.get("was_integrated") or c.get("was_disputed"):
        motivos.append("o Experience marcou a OS como integrada ou contestada, caso ainda não testado")
    if motivos:
        raise ErroUsuario("Esta OS não pode ser alterada: " + "; ".join(motivos) + ".")
    tarefas = get_order_tasks(token, oid) or []
    if len(tarefas) != 1:
        raise ErroUsuario(f"Esta OS tem {len(tarefas)} tarefas. Por segurança, corrija direto no Experience.")
    t = tarefas[0]
    info = t.get("additional_information") or ""
    if MARCADOR_SOLUCAO not in info:
        raise ErroUsuario("Não encontrei o início da Solução nesta OS. Corrija direto no Experience.")
    if " ".join(extrair_solucao(info).split()) != " ".join((original or "").split()):
        raise ErroUsuario("O texto desta OS mudou desde a conferência. Clique em Conferir de novo.")
    data_iso = datetime.strptime(t["date_done"], "%d/%m/%Y").date()
    linhas = []
    for integrada in ("S", ""):
        linhas += search_orders(token, [r["impl_id"]], data_iso.isoformat(), (data_iso + timedelta(days=1)).isoformat(), integrated=integrada) or []
    ordem = next((x for x in linhas if str(x.get("id") or x.get("order_id")) == str(oid)), None)
    if not ordem or not ordem.get("order_type_status") or not ordem.get("stage_id"):
        raise ErroUsuario("Não consegui ler o tipo e a etapa desta OS. Corrija direto no Experience.")
    return {"date_done": t["date_done"], "order_type": ordem["order_type_status"], "order_id": oid, "hour_to_start": t["hour_to_start"], "hour_to_finish": t["hour_to_finish"],
            "hour_to_lunch": t.get("hour_to_lunch") or "00:00", "additional_information": info.split(MARCADOR_SOLUCAO, 1)[0] + MARCADOR_SOLUCAO + "\n" + texto,
            "additional_notes": t.get("additional_notes") or "", "implantation_id": r["impl_id"], "person_id": core.SOLICITANTE_PERSON_ID, "has_order_type_changed": False,
            "is_accept_os_exclusion_confirmed": False, "accept_os_id": None, "accept_status": None, "stage_id": ordem["stage_id"], "has_integrated_orders": False}


CAMPO_OBS_CLICKUP = "3578f234-88e7-4d88-aabe-a61713834101"  # X-Observações OS
MARCADOR_OBS = "Solução:\n"


def _atualizar_observacoes(token, r, o, texto):
    """
    10/11/2026 (Fragoso): depois de corrigir a OS, troca só a parte da Solução no X-Observações OS da tarefa, mantendo
    número da OS, horário e tempo. A OS já está gravada: uma falha aqui vira aviso. Devolve (ok, mensagem).
    """
    import re
    import requests
    from app_conferencia import _tag_do_lancamento
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS
    pedido = {"implantation_id": r["impl_id"], "person_name": o.get("_executante"), "application_code": o.get("application_code")}
    try:
        tag = _tag_do_lancamento(token, {}, pedido, o.get("date_done"), o.get("_inicio"))
        if not tag:
            return False, "não localizei a tarefa no ClickUp; ajuste o X-Observações OS à mão"
        url = f"{CLICKUP_API}/task/{tag}"
        leitura = requests.get(url, headers=CLICKUP_HEADERS, timeout=20)
        leitura.raise_for_status()
        atual = next((c.get("value") or "" for c in leitura.json().get("custom_fields") or [] if c.get("id") == CAMPO_OBS_CLICKUP), "")
        if not str(atual).strip():
            return True, "X-Observações OS ainda vazio; a Conferência preenche"
        num = re.search(r"OS (\d+)\]", atual)
        if num and str(o.get("numos_sankhya")) != num.group(1):
            return False, f"o X-Observações OS da tarefa é da OS {num.group(1)}; ajuste à mão"
        if MARCADOR_OBS not in atual:
            return False, "o X-Observações OS está em outro formato; ajuste à mão"
        novo = atual.split(MARCADOR_OBS, 1)[0] + MARCADOR_OBS + texto
        if novo.strip() == atual.strip():
            return True, "X-Observações OS já estava igual"
        grava = requests.post(f"{url}/field/{CAMPO_OBS_CLICKUP}", headers=CLICKUP_HEADERS, json={"value": novo}, timeout=30)
        grava.raise_for_status()
        return True, "X-Observações OS atualizado no ClickUp"
    except requests.RequestException as e:
        return False, f"falha ao atualizar o ClickUp ({e.__class__.__name__}); ajuste o X-Observações OS à mão"


CAMPO_DETALHAMENTO_CLICKUP = "e74bba2f-032d-4e2e-8f37-ec19011312c0"


@rota("POST", "/api/aceite/tarefa/ajustar")
def ajustar_tarefa(req):
    """Grava no ClickUp o título e o Detalhamento aprovados na tela, tarefa a tarefa. Só muda o que foi alterado."""
    import requests
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS
    exigir_confirmacao(req)
    k = f"{req.corpo.get('fap')}|{req.corpo.get('os')}"
    a = ESTADO["sem_referencia"].get(k)
    if not a:
        raise ErroUsuario("Esta tarefa não está na última verificação. Clique em Conferir de novo.")
    titulo, detalhamento = (req.corpo.get("titulo") or "").strip(), (req.corpo.get("detalhamento") or "").strip()
    if not titulo or len(titulo) > 200 or len(detalhamento) > LIMITE_SOLUCAO:
        raise ErroUsuario("Confira o título (até 200 caracteres) e o Detalhamento.")
    url = f"{CLICKUP_API}/task/{a['tarefa']}"

    def ler():
        resp = requests.get(url, headers=CLICKUP_HEADERS, timeout=20)
        resp.raise_for_status()
        dados = resp.json()
        return dados.get("name") or "", next((str(c.get("value") or "") for c in dados.get("custom_fields") or [] if c.get("id") == CAMPO_DETALHAMENTO_CLICKUP), "")

    try:
        nome_atual, det_atual = ler()
        if nome_atual != a["titulo"] or det_atual.strip() != a["detalhamento"].strip():
            raise ErroUsuario("A tarefa mudou no ClickUp desde a verificação. Clique em Conferir de novo.")
        mudou = []
        if detalhamento != det_atual.strip():
            requests.post(f"{url}/field/{CAMPO_DETALHAMENTO_CLICKUP}", headers=CLICKUP_HEADERS, json={"value": detalhamento}, timeout=30).raise_for_status()
            mudou.append("Detalhamento")
        if titulo != nome_atual:
            requests.put(url, headers=CLICKUP_HEADERS, json={"name": titulo}, timeout=30).raise_for_status()
            mudou.append("título")
        if not mudou:
            raise ErroUsuario("Nada foi alterado.")
        nome_novo, det_novo = ler()
    except requests.RequestException as e:
        raise ErroUsuario(f"O ClickUp recusou a alteração ({e.__class__.__name__}). Confira a tarefa antes de tentar de novo.")
    if nome_novo != titulo or det_novo.strip() != detalhamento:
        raise ErroUsuario("O ClickUp respondeu OK, mas o texto lido de volta é diferente. Confira a tarefa.")
    with open(os.path.join(PASTA_DADOS, "tarefa_ajustes.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"quando": datetime.now().isoformat(timespec="seconds"), "tarefa": a["tarefa"], "chave": k, "titulo_antes": a["titulo"], "titulo_depois": titulo,
                            "detalhamento_antes": a["detalhamento"], "detalhamento_depois": detalhamento}, ensure_ascii=False) + "\n")
    ESTADO["sem_referencia"].pop(k, None)
    marcar_uso("aceite")
    return 200, {"mensagem": f"{' e '.join(mudou).capitalize()} atualizado(s) no ClickUp."}


@rota("POST", "/api/aceite/solucao/gravar")
def gravar_solucao(req):
    """Grava no Experience o texto aprovado na tela. Não gera aceite nem envia e-mail."""
    exigir_confirmacao(req)
    original, texto = req.corpo.get("original") or "", (req.corpo.get("texto") or "").strip()
    if not texto or len(texto) > LIMITE_SOLUCAO:
        raise ErroUsuario(f"O texto precisa ter de 1 a {LIMITE_SOLUCAO} caracteres.")
    if texto == original.strip():
        raise ErroUsuario("O texto não mudou.")
    r, o = _localizar_os(req.corpo.get("fap"), req.corpo.get("os"))
    import requests
    from experience_api.orders import extrair_solucao, get_order_tasks
    from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
    core = _core()
    token = core.exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
    if not token:
        raise ErroUsuario("Falha no login do Experience.")
    corpo = _dados_da_gravacao(token, core, r, o, original, texto)
    resp = requests.post(f"{core._BASE}/orders/update", headers=core.auth_headers(token), json=corpo, timeout=60)  # sem repetição automática
    body = core._safe_json(resp)
    if resp.status_code != 200 or core._erro(body):
        raise ErroUsuario(f"O Experience recusou a alteração: {core._erro(body) or resp.status_code}. Nada foi registrado como corrigido.")
    agora = extrair_solucao((get_order_tasks(token, int(o["id"])) or [{}])[0].get("additional_information"))
    if " ".join(agora.split()) != " ".join(texto.split()):
        raise ErroUsuario("O Experience respondeu OK, mas o texto lido de volta é diferente. Confira esta OS na tela do Experience.")
    o["_solucao"] = agora
    clickup_ok, clickup_msg = _atualizar_observacoes(token, r, o, agora)
    with open(os.path.join(PASTA_DADOS, "solucao_correcoes.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"quando": datetime.now().isoformat(timespec="seconds"), "fap": r["fap"], "order_id": o["id"], "os": o.get("numos_sankhya"), "antes": original, "depois": agora, "clickup": clickup_msg}, ensure_ascii=False) + "\n")
    marcar_uso("aceite")
    return 200, {"solucao": agora, "clickup_ok": clickup_ok, "mensagem": f"Solução da OS {o.get('numos_sankhya')} corrigida no Experience. {clickup_msg}. Nenhum aceite foi gerado."}


@rota("POST", "/api/aceite/enviar")
def enviar(req):
    """Um aceite por OS (09/10/2026): itens = [{"fap": "27956", "os": <id da OS no Experience>}, ...]."""
    exigir_confirmacao(req)
    if not ESTADO.get("revisado"):
        raise ErroUsuario("A verificação dos textos precisa terminar antes do envio. Aguarde ou clique em Revisar textos.")
    itens = req.corpo.get("itens") or []
    if not itens:
        raise ErroUsuario("Nenhuma OS marcada.")
    selecionadas = []
    for it in itens:
        f, oid = str(it.get("fap") or ""), str(it.get("os") or "")
        r = ESTADO["resultados"].get(f)
        if not r:
            raise ErroUsuario(f"A FAP {f} não está na última conferência. Clique em Conferir de novo.")
        if r["bloqueios"] or not any(str(o["id"]) == oid for o in r["os"]):
            raise ErroUsuario(f"A OS {oid} da FAP {f} não está pronta para envio.")
        selecionadas.append((r, oid))

    def trabalho(t):
        core = _core()
        token = _login(core, t)
        ok_total, situacao = 0, {}
        for r, oid in selecionadas:
            ok, msg = core.enviar_os(token, r, oid)
            t.log(msg)
            situacao[f"{r['fap']}|{oid}"] = "ENVIADA" if ok else "FALHOU"
            ok_total += ok
        t.adicionar_arquivo("Registro de envios (.jsonl)", core.ARQ_LOG_ENVIOS)
        marcar_uso("aceite")
        return {"mensagem": f"Envio concluído: {ok_total} de {len(selecionadas)} aceite(s) de OS enviado(s).",
                "resultado": {"situacao": situacao}}

    t = GERENTE.iniciar("aceite_enviar", "Aceite de OS - envio", trabalho, pasta=PASTAS["aceite"])
    return 200, {"tarefa": t.id}

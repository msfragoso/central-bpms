# -*- coding: utf-8 -*-
"""
Sync tarefa ClickUp - Experience (main.py). A tela de parâmetros (ui_prompts) e a
JanelaLog viram a página sync.html; o fluxo continua sendo o
main._fluxo_principal original, sem alteração -- aqui ele recebe uma
"janela" falsa cuja fila de log manda tudo para o log da tarefa.
"""
import glob
import importlib.util
import os
import threading
import time
from datetime import datetime, timedelta

from nucleo import GERENTE, PASTAS, Cancelada, ErroUsuario, exigir_confirmacao, marcar_uso, periodo_br, rota

_cache = {"listas": None, "quando": 0}
_cache_lock = threading.Lock()
_main = {}


def _modulo_main():
    """Carrega C:\\sankhya_integracao\\main.py com outro nome (não conflita com nada)."""
    if "m" not in _main:
        caminho = os.path.join(PASTAS["raiz"], "main.py")
        spec = importlib.util.spec_from_file_location("sankhya_main", caminho)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _main["m"] = m
    return _main["m"]


def _ui():
    from clickup_sync import ui_prompts
    return ui_prompts


def _todas_listas(forcar=False):
    from clickup_sync.config import SPACE_ID_PMO_BP_MS
    from clickup_sync.list_discovery import get_all_lists_in_space
    with _cache_lock:
        if forcar or _cache["listas"] is None or time.time() - _cache["quando"] > 600:
            _cache["listas"] = get_all_lists_in_space(SPACE_ID_PMO_BP_MS)
            _cache["quando"] = time.time()
        return _cache["listas"]


@rota("GET", "/api/sync/opcoes")
def opcoes(req):
    ui = _ui()
    hoje = datetime.now()
    segunda = hoje - timedelta(days=hoje.weekday())
    ultima = ui._carregar_ultima_execucao()
    return 200, {
        "de": segunda.strftime("%d/%m/%Y"), "ate": (segunda + timedelta(days=6)).strftime("%d/%m/%Y"),
        "parceiro": ultima["parceiro"], "modelo": ultima["modelo"],
        "modelos": [{"valor": v, "rotulo": r} for v, r in ui.MODELOS_FILTRO_OPCOES],
        "consultores": _consultores(),
    }


def _consultores():
    """Membros do ClickUp (mesmo cache da tela Lançar ClickUp) para o filtro por consultor."""
    try:
        import app_lancar
        return [{"id": str(m.get("id")), "nome": m.get("nome") or ""} for m in app_lancar._motor().carregar_membros_cache()
                if m.get("id") and m.get("nome")]
    except Exception:
        return []


@rota("GET", "/api/sync/contar")
def contar(req):
    from clickup_sync.list_discovery import extrair_fap_do_nome_lista, filtrar_listas_por_nome
    texto = (req.query.get("texto") or "").strip()
    todas = _todas_listas()
    listas = filtrar_listas_por_nome(todas, texto) if texto else todas
    # 06/11/2026 (Fragoso): lista sem número de FAP fica fora do sync (o mesmo filtro está no main.py)
    listas = [l for l in listas if extrair_fap_do_nome_lista(l.get("name") or "")]
    return 200, {"total": len(listas),
                 "listas": [f"{l.get('folder_name') or ''} / {l['name']}".strip(" /") for l in listas[:30]]}


class _FilaParaTarefa:
    """Imita a queue.Queue da JanelaLog: o que o QueueWriter do main.py põe aqui vai para o log da tarefa."""
    def __init__(self, tarefa, sinal_fim):
        self.tarefa, self.sinal_fim = tarefa, sinal_fim

    def put(self, msg):
        if msg is not self.sinal_fim:
            self.tarefa.escrever(msg)


class _JanelaFalsa:
    def __init__(self, tarefa, sinal_fim):
        self.log_queue = _FilaParaTarefa(tarefa, sinal_fim)


# ============================================================================
# CONSULTOR FORA DO PROJETO (08/10/2026; automático desde 03/11/2026, pedido do Fragoso)
# ============================================================================
# O sync_engine só anota em linha["_fora_do_projeto"] os casos "não está
# vinculado ao projeto no Experience". Depois do sync, o consultor é incluído no
# projeto sem perguntar (_cadastrar_fora), o sync roda de novo só para aquela FAP
# e o resultado aparece na tela e no log. O que não der certo fica na tela com o
# motivo e o botão de tentar de novo.

ESTADO_FORA = {}   # chave -> caso que não foi cadastrado e pode ser tentado de novo


def _incluir_e_registrar(token, caso, t, origem):
    """Inclui o consultor no projeto e grava em dados/inclusoes_consultores.jsonl. Devolve (ok, mensagem)."""
    import json
    from experience_api.persons import incluir_consultor_no_projeto
    from nucleo import dados_arquivo

    t.log(f"Incluindo {caso['consultor']} ({caso['email']}) no projeto FAP {caso['fap']}, "
          f"processo {caso['process_id']}...")
    ok, msg = incluir_consultor_no_projeto(token, caso["implantation_id"], caso["email"], caso["process_id"])
    with open(dados_arquivo("inclusoes_consultores.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"quando": datetime.now().isoformat(timespec="seconds"), "ok": ok, "origem": origem,
                            "mensagem": msg, **{k: caso[k] for k in ("implantation_id", "fap", "consultor",
                                                                      "email", "process_id", "datas")}},
                           ensure_ascii=False) + "\n")
    t.log(("  OK: " if ok else "  NÃO incluído: ") + msg)
    return ok, msg


def _cadastrar_fora(fora, t, rerodar):
    """
    Cadastra os consultores fora do projeto e roda o sync de novo uma vez por FAP.
    rerodar(fap, de_iso, ate_iso) devolve os casos que continuam fora. Anota
    "situacao" e "mensagem" em cada caso; os não cadastrados ficam em ESTADO_FORA.
    """
    import experience_api as exp
    from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS

    ESTADO_FORA.clear()
    if not fora:
        return
    t.log(f"\nCadastro automático: {len(fora)} consultor(es) fora do projeto no Experience.")
    try:
        token = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
    except Exception:
        token = None
    por_fap = {}
    for c in fora:
        if not c["email"]:
            ok, msg = False, "sem e-mail na tarefa do ClickUp: cadastre pelo Experience"
        elif not token:
            ok, msg = False, "falha no login do Experience"
        else:
            try:
                ok, msg = _incluir_e_registrar(token, c, t, "automatico")
            except Exception as e:
                ok, msg = False, f"erro ao incluir: {e}"
        c.update(situacao="CADASTRADO" if ok else "NÃO CADASTRADO", mensagem=msg)
        if ok:
            por_fap.setdefault(c["fap"], []).append(c)
        else:
            t.log(f"  {c['consultor']} (FAP {c['fap']}) NÃO cadastrado: {msg}")
            ESTADO_FORA[c["chave"]] = c
    for fap, casos in por_fap.items():
        datas = sorted(d for c in casos for d in c["datas"])
        if not datas:
            for c in casos:
                c["mensagem"] += ". Rode o sync para criar o lançamento"
            continue
        t.log(f"Rodando o sync da FAP {fap} de {datas[0]} a {datas[-1]}...")
        try:
            continuam = {r["chave"] for r in rerodar(fap, datas[0], datas[-1])}
            nota = ". Sync da FAP rodado de novo; confira o relatório no log"
        except Exception as e:
            t.log(f"  Falha ao rodar o sync da FAP {fap}: {e}")
            continuam, nota = set(), ". O sync da FAP falhou: rode de novo para criar o lançamento"
        for c in casos:
            c["mensagem"] += (". O sync ainda não achou o consultor no projeto: confira no Experience"
                              if c["chave"] in continuam else nota)


def _achados_os(ja=()):
    """OS com data diferente; cada execução do sync limpa a lista, então soma o que já foi lido."""
    try:
        from clickup_sync import os_data_diferente
        novos = list(os_data_diferente.ACHADOS)
    except Exception:
        novos = []
    vistos = {a.get("lancamento_id") for a in ja}
    return list(ja) + [a for a in novos if a.get("lancamento_id") not in vistos]


def _rodar_fluxo(m, filtro, de_iso, ate_iso, modelo_filtro, cache_listas, t, consultor=None):
    """Roda main._fluxo_principal e devolve os casos de consultor fora do projeto."""
    capturado = []
    original = m.imprimir_relatorio

    def _imprimir(relatorio, *a, **k):
        capturado.extend(relatorio or [])
        return original(relatorio, *a, **k)

    m.imprimir_relatorio = _imprimir
    try:
        m._fluxo_principal(filtro, de_iso, ate_iso, modelo_filtro, cache_listas,
                           _JanelaFalsa(t, m._SINAL_FIM_EXECUCAO), consultor=consultor)
    finally:
        m.imprimir_relatorio = original

    casos = {}
    for linha in capturado:
        f = linha.get("_fora_do_projeto") if isinstance(linha, dict) else None
        if not f:
            continue
        chave = f"{f['implantation_id']}|{(f.get('email') or f.get('consultor') or '').lower()}|{f['process_id']}"
        c = casos.setdefault(chave, {"chave": chave, "implantation_id": f["implantation_id"], "fap": str(f["fap"]),
                                     "consultor": f.get("consultor") or "", "email": f.get("email") or "",
                                     "process_id": f["process_id"], "parceiro": linha.get("parceiro") or "",
                                     "datas": [], "tarefas": []})
        if f.get("data") and f["data"] not in c["datas"]:
            c["datas"].append(f["data"])
        if f.get("task_id") and f["task_id"] not in c["tarefas"]:
            c["tarefas"].append(f["task_id"])
    for c in casos.values():
        c["datas"].sort()
    return list(casos.values())


@rota("POST", "/api/sync/executar")
def executar(req):
    exigir_confirmacao(req)
    ui = _ui()
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    parceiro = (req.corpo.get("parceiro") or "").strip()
    valor_modelo = (req.corpo.get("modelo") or "todos").strip().lower()
    if valor_modelo not in [v for v, _ in ui.MODELOS_FILTRO_OPCOES]:
        raise ErroUsuario("Modelo de projetos inválido.")
    modelo_filtro = ui._resolver_modelo_filtro(valor_modelo)
    # 23/10/2026: vários consultores ("consultores": [ids]); "consultor" (um id) continua valendo
    ids = req.corpo.get("consultores")
    if not isinstance(ids, list):
        ids = [req.corpo.get("consultor")]
    ids = [str(x).strip() for x in ids if str(x or "").strip()]
    todos = {c["id"]: c for c in _consultores()} if ids else {}
    faltam = [x for x in ids if x not in todos]
    if faltam:
        raise ErroUsuario("Consultor não encontrado na lista do ClickUp. Atualize a página e escolha de novo.")
    consultor = [todos[x] for x in dict.fromkeys(ids)] or None

    def anexar_logs(t, inicio):
        logs = sorted((p for p in glob.glob(os.path.join(PASTAS["raiz"], "logs", "log_*.txt"))
                       if os.path.getmtime(p) >= inicio - 1), key=os.path.getmtime)
        for i, p in enumerate(logs):
            t.adicionar_arquivo("Log completo (.txt)" if i == 0 else f"Log do sync após cadastro {i} (.txt)", p)

    def trabalho(t):
        import parada_sync
        parada_sync.limpar()
        inicio = time.time()
        try:
            return _trabalho(t, inicio)
        except parada_sync.ParadaSolicitada:
            anexar_logs(t, inicio)
            raise Cancelada("Sync parado por você. O que já foi feito continua valendo; rode de novo para concluir o resto.")
        finally:
            parada_sync.limpar()

    def _trabalho(t, inicio):
        m = _modulo_main()
        ui._salvar_ultima_execucao(parceiro, valor_modelo)
        cache_listas = {"dados": _cache["listas"]}
        fora = _rodar_fluxo(m, parceiro or None, ini.isoformat(), fim.isoformat(), modelo_filtro, cache_listas, t,
                            consultor=consultor)
        # 26/10/2026: OS apontada com data diferente do lançamento (também vai por e-mail)
        os_data = _achados_os()
        leituras = {"os": os_data}

        def rerodar(fap, de_iso, ate_iso):
            restantes = _rodar_fluxo(m, fap, de_iso, ate_iso, None, cache_listas, t, consultor=consultor)
            leituras["os"] = _achados_os(leituras["os"])
            return restantes

        _cadastrar_fora(fora, t, rerodar)
        os_data = leituras["os"]
        anexar_logs(t, inicio)
        marcar_uso("sync")
        msg = "Execução finalizada. Confira o relatório final no log."
        feitos = sum(1 for c in fora if c.get("situacao") == "CADASTRADO")
        if feitos:
            msg += f" {feitos} consultor(es) cadastrado(s) automaticamente no projeto: veja abaixo."
        if len(fora) > feitos:
            msg += f" ⚠ {len(fora) - feitos} consultor(es) NÃO cadastrado(s): veja o motivo abaixo."
        if os_data:
            msg += f" ⚠ {len(os_data)} OS apontada(s) com data diferente do lançamento: veja abaixo."
        return {"mensagem": msg, "resultado": {"fora_do_projeto": fora, "os_data_diferente": os_data}}

    alvo = (parceiro or "todos os parceiros") + (f" · {', '.join(c['nome'] for c in consultor)}" if consultor else "")
    t = GERENTE.iniciar("sync", f"Sync tarefa ClickUp ⇄ Experience ({alvo})", trabalho, pasta=PASTAS["raiz"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/sync/parar")
def parar(req):
    """05/11/2026 (Fragoso): pede a parada do sync. Ele para no próximo ponto seguro (ver parada_sync.py)."""
    exigir_confirmacao(req)
    rodando = next((t for t in GERENTE.ativas if t.tipo == "sync"), None)
    if not rodando:
        raise ErroUsuario("Não há sincronização rodando.")
    import parada_sync
    parada_sync.pedir()
    rodando.log("\n⏹ Parada pedida na tela: termino a operação em andamento e paro no próximo ponto seguro...")
    return 200, {"ok": True}


# ============================================================================
# LANÇAMENTOS SEM APONTAMENTO DE OS (só leitura)
# ============================================================================
# No Experience cada lançamento tem "status": CONCLUDED (task_status
# "Finalizada", a OS foi apontada) ou PENDING (ainda sem OS). Esta consulta
# lista os PENDING das FAPs das listas do ClickUp (as mesmas que o sync usa).

def _lancamentos_do_periodo(token, impl_id, de_iso, ate_iso):
    from experience_api._base import TASKS_API, auth_headers, post_com_retry
    # O endpoint exige um /person/ no caminho, mas devolve o projeto inteiro
    # (ver docstring de experience_api.tasks.search_tasks); qualquer id serve.
    url = f"{TASKS_API}/filtering/implantation/{impl_id}/person/10898"
    todos, pagina = [], 1
    while pagina <= 40:
        body = post_com_retry(url, auth_headers(token), {
            "columns": [], "page": pagina, "length": 50, "order": {},
            "filters": {"period": [f"{de_iso} 00:00:00", f"{ate_iso} 23:59:59"]}})
        if body.get("response", {}).get("error"):
            raise RuntimeError(body.get("response", {}).get("message") or "falha na busca de lançamentos")
        lote = body.get("data", {}).get("result", [])
        todos.extend(lote)
        if len(lote) < 50:
            break
        pagina += 1
    return todos


ESTADO_SEM_OS = {}   # id do lançamento -> linha da última consulta (só esses podem ser excluídos)


@rota("POST", "/api/sync/sem-os")
def sem_os(req):
    from datetime import date
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    parceiro = (req.corpo.get("parceiro") or "").strip()
    incluir_futuras = bool(req.corpo.get("incluir_futuras"))

    def trabalho(t):
        import csv
        import experience_api as exp
        from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
        from clickup_sync.list_discovery import extrair_fap_do_nome_lista, filtrar_listas_por_nome
        from experience_api.clickup_tags import extrair_tag_clickup
        from clickup_sync.text_matching import normalizar_texto
        from nucleo import dados_arquivo

        t.log("Lendo as listas do ClickUp...")
        todas = _todas_listas()
        listas = filtrar_listas_por_nome(todas, parceiro) if parceiro else todas
        faps = {}
        for l in listas:
            fap = extrair_fap_do_nome_lista(l["name"])
            if fap and fap not in faps:
                faps[fap] = l["name"]
        # Lista do ClickUp arquivada (nome com "Z" na frente) some da descoberta do
        # sync, mas o lançamento esquecido continua no Experience: soma as FAPs
        # cadastradas em clickup_sync/config.py (PARCEIRO_FAP).
        from clickup_sync.config import PARCEIRO_FAP
        from clickup_sync.text_matching import normalizar_texto
        filtro = normalizar_texto(parceiro) if parceiro else ""
        for nome, fap_cfg in PARCEIRO_FAP.items():
            for f in (fap_cfg if isinstance(fap_cfg, list) else [fap_cfg]):
                f = str(f)
                if f not in faps and (not filtro or filtro in normalizar_texto(nome) or filtro == f):
                    faps[f] = nome
        if not faps:
            return {"mensagem": "Nenhuma lista com FAP bate com esse filtro.", "resultado": {"linhas": []}}
        t.log(f"{len(faps)} FAP(s) para consultar. Login no Experience...")
        token = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
        if not token:
            raise RuntimeError("Falha no login do Experience.")

        hoje = date.today()
        ate = fim if incluir_futuras else min(fim, hoje)
        if ate < ini:
            return {"mensagem": "O período escolhido é todo no futuro (marque 'Incluir datas futuras').",
                    "resultado": {"linhas": []}}
        linhas, falhas, fora_andamento = [], [], []
        for i, (fap, nome_lista) in enumerate(sorted(faps.items(), key=lambda kv: kv[1].lower()), 1):
            t.log(f"  [{i}/{len(faps)}] FAP {fap} - {nome_lista}")
            try:
                impl = exp.find_implantation_by_fap(token, fap)
                if not impl:
                    falhas.append(f"FAP {fap}: projeto não encontrado no Experience")
                    continue
                # Só projetos "Em Andamento" (pedido do Fragoso, 06/10/2026).
                if normalizar_texto(impl.get("status") or "") != "em andamento":
                    fora_andamento.append(f"{fap} ({impl.get('status') or 'sem status'})")
                    continue
                for l in _lancamentos_do_periodo(token, impl["id"], ini.isoformat(), ate.isoformat()):
                    if str(l.get("status") or "").upper() != "PENDING":
                        continue
                    try:
                        d = datetime.strptime(l.get("task_date") or "", "%d/%m/%Y").date()
                    except ValueError:
                        d = None
                    linhas.append({
                        "fap": fap, "lista": nome_lista, "parceiro": impl.get("company_name") or "",
                        "executante": l.get("person_name") or "", "data": l.get("task_date") or "",
                        "dias": (hoje - d).days if d else None,
                        "inicio": l.get("task_hour_to_start") or "", "fim": l.get("task_hour_to_finish") or "",
                        "etapa": l.get("stage_name") or "", "processo": l.get("process_name") or "",
                        "atividade": l.get("procedure_name") or "", "situacao": l.get("task_status") or "",
                        "tag_clickup": extrair_tag_clickup(l.get("additional_information")) or "",
                        "id_experience": l.get("id"), "impl_id": impl["id"],
                    })
            except Exception as e:  # uma FAP com problema não derruba a consulta inteira
                falhas.append(f"FAP {fap}: {e}")
            time.sleep(0.15)

        for f in falhas:
            t.log("  Aviso: " + f)
        if fora_andamento:
            t.log(f"  {len(fora_andamento)} FAP(s) ignorada(s) por não estarem Em Andamento: " + ", ".join(fora_andamento))
        ESTADO_SEM_OS.clear()
        ESTADO_SEM_OS.update({str(r["id_experience"]): r for r in linhas})
        linhas.sort(key=lambda r: (r["dias"] is None, -(r["dias"] or 0), r["executante"]))
        caminho = dados_arquivo(f"sem_os_{ini:%Y%m%d}_a_{ate:%Y%m%d}_{datetime.now():%H%M%S}.csv")
        cols = ["fap", "lista", "parceiro", "executante", "data", "dias", "inicio", "fim", "etapa", "processo",
                "atividade", "situacao", "tag_clickup", "id_experience"]
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=";", extrasaction="ignore")
            w.writeheader()
            w.writerows(linhas)
        t.adicionar_arquivo("Lançamentos sem OS (.csv)", caminho)
        consultadas = len(faps) - len(fora_andamento) - len([f for f in falhas if "não encontrado" in f])
        msg = (f"{len(linhas)} lançamento(s) sem apontamento de OS entre {ini:%d/%m/%Y} e {ate:%d/%m/%Y}, "
               f"em {consultadas} FAP(s) Em Andamento. Nada foi alterado.")
        if falhas:
            msg += f" {len(falhas)} FAP(s) com aviso (ver log)."
        return {"mensagem": msg, "resultado": {"linhas": linhas}}

    alvo = parceiro or "todos os parceiros"
    t = GERENTE.iniciar("sync_sem_os", f"Lançamentos sem OS ({alvo})", trabalho, pasta=PASTAS["raiz"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/sync/sem-os/excluir")
def sem_os_excluir(req):
    """
    Exclui do Experience os lançamentos pendentes marcados na tabela. Antes de
    cada exclusão, busca de novo o dia daquele projeto e só exclui se o
    lançamento ainda existir e continuar PENDING (sem OS). Cada exclusão fica
    em log_exclusoes_orfaos.jsonl (o mesmo log das exclusões do sync), com
    origem "faxina_sem_os".
    """
    exigir_confirmacao(req)
    ids = [str(i) for i in (req.corpo.get("ids") or [])]
    if not ids:
        raise ErroUsuario("Nenhum lançamento marcado.")
    faltando = [i for i in ids if i not in ESTADO_SEM_OS]
    if faltando:
        raise ErroUsuario("Alguns lançamentos não estão na última consulta. Consulte de novo antes de excluir.")
    alvos = [ESTADO_SEM_OS[i] for i in ids]

    def trabalho(t):
        import experience_api as exp
        from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
        from clickup_sync.orphan_check import registrar_exclusao, CAMINHO_LOG_EXCLUSOES_PADRAO

        token = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
        if not token:
            raise RuntimeError("Falha no login do Experience.")
        situacao, ok, pulados, erros = {}, 0, 0, 0
        cache_dia = {}
        for i, r in enumerate(alvos, 1):
            rotulo = f"{r['id_experience']} ({r['executante']}, FAP {r['fap']}, {r['data']}, {r['atividade'] or r['etapa']})"
            try:
                d = datetime.strptime(r["data"], "%d/%m/%Y").date().isoformat()
                chave = (r["impl_id"], d)
                if chave not in cache_dia:
                    cache_dia[chave] = {str(x.get("id")): x for x in _lancamentos_do_periodo(token, r["impl_id"], d, d)}
                atual = cache_dia[chave].get(str(r["id_experience"]))
                if not atual:
                    situacao[str(r["id_experience"])] = "JÁ NÃO EXISTE"
                    t.log(f"  [{i}/{len(alvos)}] pulado, já não existe: {rotulo}")
                    pulados += 1
                    continue
                if str(atual.get("status") or "").upper() != "PENDING":
                    situacao[str(r["id_experience"])] = "TEM OS"
                    t.log(f"  [{i}/{len(alvos)}] pulado, já está {atual.get('status')} ({atual.get('task_status')}): {rotulo}")
                    pulados += 1
                    continue
                resp = exp.delete_task(token, r["id_experience"])
                erro = (resp.get("response") or {}).get("error")
                mensagem = (resp.get("response") or {}).get("message") or ""
                registrar_exclusao(CAMINHO_LOG_EXCLUSOES_PADRAO, {
                    "origem": "faxina_sem_os", "motivo": "lancamento_sem_apontamento_de_os",
                    "lancamento_id": r["id_experience"], "clickup_task_id": r["tag_clickup"] or None,
                    "implantation_id": r["impl_id"], "fap": r["fap"], "person_name": r["executante"],
                    "task_date": r["data"], "horario": f"{r['inicio']}-{r['fim']}", "etapa": r["etapa"],
                    "atividade": r["atividade"], "status_exclusao": "falha" if erro else "sucesso",
                    "mensagem": mensagem if erro else None,
                })
                if erro:
                    situacao[str(r["id_experience"])] = "FALHOU"
                    t.log(f"  [{i}/{len(alvos)}] FALHOU: {rotulo}: {mensagem}")
                    erros += 1
                else:
                    situacao[str(r["id_experience"])] = "EXCLUÍDO"
                    t.log(f"  [{i}/{len(alvos)}] excluído: {rotulo}")
                    ESTADO_SEM_OS.pop(str(r["id_experience"]), None)
                    ok += 1
            except Exception as e:
                situacao[str(r["id_experience"])] = "FALHOU"
                t.log(f"  [{i}/{len(alvos)}] FALHOU: {rotulo}: {e}")
                erros += 1
            time.sleep(0.2)
        t.adicionar_arquivo("Log de exclusões (.jsonl)", CAMINHO_LOG_EXCLUSOES_PADRAO)
        return {"mensagem": f"{ok} lançamento(s) excluído(s), {pulados} pulado(s), {erros} com falha.",
                "resultado": {"situacao": situacao}}

    t = GERENTE.iniciar("sync_sem_os_excluir", f"Exclusão de {len(alvos)} lançamento(s) sem OS", trabalho,
                        pasta=PASTAS["raiz"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/sync/incluir-consultor")
def incluir_consultor(req):
    """
    Tenta de novo o cadastro que o sync automático não conseguiu: inclui no
    projeto do Experience (como Consultor(a)/Analista, no processo da tarefa) e
    roda o sync de novo só para aquela FAP e aquelas datas, o que cria o lançamento.
    Cada inclusão fica em dados/inclusoes_consultores.jsonl.
    """
    exigir_confirmacao(req)
    chave = str(req.corpo.get("chave") or "")
    caso = ESTADO_FORA.get(chave)
    if not caso:
        raise ErroUsuario("Esse caso não está na última execução do sync. Rode o sync de novo.")
    if not caso["email"]:
        raise ErroUsuario(f"Sem e-mail de {caso['consultor']} na tarefa do ClickUp: cadastre pelo Experience.")

    def trabalho(t):
        import experience_api as exp
        from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS

        token = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
        if not token:
            raise RuntimeError("Falha no login do Experience.")
        ok, msg = _incluir_e_registrar(token, caso, t, "manual")
        if not ok:
            raise RuntimeError(f"Consultor não incluído: {msg}")
        ESTADO_FORA.pop(chave, None)
        if not caso["datas"]:
            return {"mensagem": msg + ". Rode o sync para criar o lançamento."}
        t.log(f"Rodando o sync da FAP {caso['fap']} de {caso['datas'][0]} a {caso['datas'][-1]}...")
        m = _modulo_main()
        _rodar_fluxo(m, caso["fap"], caso["datas"][0], caso["datas"][-1], None,
                     {"dados": _cache["listas"]}, t)
        return {"mensagem": msg + ". Sync da FAP rodado de novo; confira o relatório no log."}

    t = GERENTE.iniciar("sync_incluir", f"Cadastrar {caso['consultor']} na FAP {caso['fap']} e lançar", trabalho,
                        pasta=PASTAS["raiz"])
    return 200, {"tarefa": t.id}

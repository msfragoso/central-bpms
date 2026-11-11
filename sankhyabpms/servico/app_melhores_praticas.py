# -*- coding: utf-8 -*-
"""
Liberação GP de Melhores Práticas (11/11/2026, pedido do Fragoso).

Na etapa "Validação do escopo" de uma FAP, lista os módulos (processos), as
atividades e os procedimentos de melhores práticas, e grava, procedimento por
procedimento, "MP Completa" com a Liberação GP marcada: o mesmo POST que a tela
do Experience faz (HAR de 11/11/2026, implantations/customization-procedure).

Regras aprovadas pelo Fragoso em 11/11/2026:
 1. Só procedimento pendente (sem aderência preenchida). Preenchido nunca muda.
 2. "Não se aplica" fica de fora.
 3. Aderência sempre "MP Completa" (C) com release_scope = true. Parcial e
    Não aderente pedem justificativa: continuam manuais.
 4. Procedimentos do cliente (is_client_procedure) ficam de fora.
 5. Nada é gravado sem confirmação na tela. ClickUp e OM não são tocados.
Etapas: Validação do escopo (42) e Folha | Validação do escopo (60).
"""
import time

import requests

from nucleo import GERENTE, ErroUsuario, marcar_uso, rota

# Etapas de validação do escopo atendidas (id -> código conferido a cada leitura).
# 11/11/2026: incluída a "Folha | Validação do escopo" (60), pedido do Fragoso.
ETAPAS = {42: "3_3_VALIDACAO_DO_ESCOPO", 60: "FOLHA_VALIDACAO_DO_ESCOPO"}
ADERENCIA_COMPLETA = "C"      # aparece na leitura como "MP Completa"
ESTADO = {"token": None, "person_id": None, "leituras": {}}


def _base():
    from experience_api._base import _BASE, auth_headers
    return _BASE, auth_headers


def _login(log, novo=False):
    if ESTADO["token"] and not novo:
        return ESTADO["token"]
    import experience_api as exp
    from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
    log("Login no Experience...")
    tk = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
    if not tk:
        raise RuntimeError("Falha no login do Experience.")
    ESTADO["token"] = tk
    return tk


def _get(tk, caminho, **params):
    base, cab = _base()
    for tentativa in range(3):
        r = requests.get(f"{base}/{caminho}", headers=cab(tk), params=params, timeout=40)
        if r.status_code < 500:
            break
        time.sleep(1 + tentativa)
    j = r.json()
    if r.status_code != 200 or (j.get("response") or {}).get("error"):
        raise RuntimeError(f"Experience: {caminho} -> HTTP {r.status_code} {(j.get('response') or {}).get('message', '')}")
    return j.get("data")


def _pessoa(tk, impl):
    """person_id do usuário logado no projeto (o Experience pede na lista de módulos)."""
    if ESTADO["person_id"]:
        return ESTADO["person_id"]
    import base64
    import json
    try:
        carga = tk.split(".")[1]
        dados = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))
        for chave in ("person_id", "personId", "custom:person_id"):
            if dados.get(chave):
                ESTADO["person_id"] = int(dados[chave])
                return ESTADO["person_id"]
    except Exception:
        pass
    import enviar_aceite_os as aceite  # mesmo solicitante usado no Aceite de OS
    ESTADO["person_id"] = int(aceite.SOLICITANTE_PERSON_ID)
    return ESTADO["person_id"]


def _implantacao(tk, fap):
    import experience_api as exp
    proj = exp.find_implantation_by_fap(tk, str(fap))
    if not proj:
        raise ErroUsuario(f"FAP {fap} não encontrada no Experience (ou você não tem acesso a ela).")
    return proj


def _situacao(p):
    if p["not_applicable"]:
        return "nao_aplica"
    if p["is_client_procedure"]:
        return "cliente"
    if p["best_practice_adherence"] is None:
        return "pendente"
    return "liberado" if p.get("release_scope") else "preenchido"


def ler_fap(tk, fap, log):
    proj = _implantacao(tk, fap)
    impl = int(proj["id"])
    pessoa = _pessoa(tk, impl)
    modulos, nomes_etapas, vistos = [], [], set()
    for id_etapa, codigo in ETAPAS.items():
        etapa = _get(tk, f"stages/{id_etapa}", implantation_id=impl) or {}
        if etapa.get("code") != codigo:
            raise RuntimeError(f"A etapa {id_etapa} do Experience não é mais a {codigo}. Nada foi feito; avise para revisar a Central.")
        lista = _get(tk, f"processes/implantation/{impl}/stage/{id_etapa}/person/{pessoa}", isBetterPractices="true") or []
        log(f"FAP {fap} · {proj.get('company_name')} · {etapa.get('name')}: {len(lista)} módulo(s) com melhores práticas.")
        if lista:
            nomes_etapas.append(etapa.get("name"))
        for m in lista:
            if m["id"] not in vistos:
                vistos.add(m["id"])
                modulos.append(dict(m, etapa=etapa.get("name")))
    saida = []
    for m in modulos:
        atividades = []
        for a in _get(tk, f"implantations/{impl}/activities-tree-bp/{m['id']}") or []:
            itens, pag = [], 1
            while True:
                r = (_get(tk, f"procedures/implantation/{impl}/activity/{a['activity_id']}/get-best-practices-info",
                          columns="[]", page=pag, length=50, order="{}") or {}).get("result") or []
                itens += r
                if not r or len(itens) >= int(r[0].get("full_count") or 0):
                    break
                pag += 1
            procs = [{"id": p["procedure_id"], "codigo": p["procedure_code"], "nome": p["procedure_name"],
                      "aderencia": p["best_practice_adherence"], "liberacao": p.get("release_scope"),
                      "situacao": _situacao(p), "tempo": p.get("expected_formatted_time")} for p in itens]
            atividades.append({"id": a["activity_id"], "nome": a["activity_name"], "procedimentos": procs})
        n = sum(1 for a in atividades for p in a["procedimentos"] if p["situacao"] == "pendente")
        log(f"  {m['name']}: {sum(len(a['procedimentos']) for a in atividades)} procedimento(s), {n} pendente(s).")
        saida.append({"id": m["id"], "nome": m["name"], "etapa": m["etapa"], "atividades": atividades})
    resultado = {"fap": str(fap), "implantacao": impl, "cliente": proj.get("company_name"), "projeto": proj.get("project_name"),
                 "etapa": " e ".join(nomes_etapas) or "Validação do escopo (sem melhores práticas nesta FAP)", "modulos": saida}
    ESTADO["leituras"][str(fap)] = resultado
    return resultado


@rota("POST", "/api/mp/ler")
def ler(req):
    fap = "".join(ch for ch in str(req.corpo.get("fap") or "") if ch.isdigit())
    if not fap:
        raise ErroUsuario("Informe o número da FAP.")

    def trabalho(t):
        tk = _login(t.log, novo=True)
        r = ler_fap(tk, fap, t.log)
        marcar_uso("melhores_praticas")
        pend = sum(1 for m in r["modulos"] for a in m["atividades"] for p in a["procedimentos"] if p["situacao"] == "pendente")
        return {"mensagem": f"Leitura concluída: {pend} procedimento(s) pendente(s). Nada foi alterado.", "resultado": r}

    t = GERENTE.iniciar("mp_ler", f"Melhores práticas da FAP {fap} (leitura)", trabalho)
    return 200, {"tarefa": t.id}


@rota("POST", "/api/mp/liberar")
def liberar(req):
    c = req.corpo
    if c.get("confirmar") is not True:
        raise ErroUsuario("Ação não confirmada.")
    fap = str(c.get("fap") or "")
    escolhidos = {int(x) for x in (c.get("procedimentos") or [])}
    leitura = ESTADO["leituras"].get(fap)
    if not leitura:
        raise ErroUsuario("Leia a FAP de novo antes de liberar.")
    if not escolhidos:
        raise ErroUsuario("Marque ao menos um procedimento.")

    def trabalho(t):
        base, cab = _base()
        tk = _login(t.log)
        impl = leitura["implantacao"]
        t.log("Relendo a FAP para conferir a situação atual antes de gravar...")
        atual = ler_fap(tk, fap, t.log)
        alvo = []
        for m in atual["modulos"]:
            for a in m["atividades"]:
                for p in a["procedimentos"]:
                    if p["id"] in escolhidos:
                        if p["situacao"] == "pendente":
                            alvo.append((m, a, p))
                        else:
                            t.log(f"  pulado {p['codigo']} {p['nome']}: não está mais pendente ({p['situacao']}).")
        t.log(f"Gravando {len(alvo)} procedimento(s): MP Completa + Liberação GP...")
        ok, erros = [], []
        for m, a, p in alvo:
            corpo = {"procedure_id": p["id"], "implantation_id": impl, "best_practice_adherence": ADERENCIA_COMPLETA,
                     "procedure_name": p["nome"], "link_data": {}, "process_id": m["id"], "activity_name": a["nome"],
                     "release_scope": True}
            try:
                r = requests.post(f"{base}/implantations/customization-procedure", headers=cab(tk), json=corpo, timeout=40)
                j = r.json() if r.content else {}
                if r.status_code == 200 and not (j.get("response") or {}).get("error"):
                    ok.append(p["id"])
                    t.log(f"  ✓ {m['nome']} · {p['codigo']} {p['nome']}")
                else:
                    erros.append(p["id"])
                    t.log(f"  ✗ {p['codigo']} {p['nome']}: HTTP {r.status_code} {(j.get('response') or {}).get('message', '')}")
            except Exception as e:
                erros.append(p["id"])
                t.log(f"  ✗ {p['codigo']} {p['nome']}: {e}")
            time.sleep(0.3)
        t.log("Conferindo no Experience...")
        final = ler_fap(tk, fap, t.log)
        situ = {p["id"]: p for m in final["modulos"] for a in m["atividades"] for p in a["procedimentos"]}
        nao_conferem = [i for i in ok if situ.get(i, {}).get("situacao") != "liberado"]
        for i in nao_conferem:
            t.log(f"  ⚠ {situ.get(i, {}).get('codigo', i)} gravado, mas a releitura não mostra MP Completa + Liberação GP.")
        marcar_uso("melhores_praticas")
        msg = f"{len(ok) - len(nao_conferem)} procedimento(s) liberado(s) e conferido(s)"
        if erros or nao_conferem:
            msg += f"; {len(erros)} com erro e {len(nao_conferem)} para conferir"
        return {"mensagem": msg + ". ClickUp e OM não foram alterados.", "resultado": final}

    t = GERENTE.iniciar("mp_liberar", f"Liberação GP de melhores práticas da FAP {fap}", trabalho)
    return 200, {"tarefa": t.id}

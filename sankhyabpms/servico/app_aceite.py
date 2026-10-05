# -*- coding: utf-8 -*-
"""
Aceite de OS (aceite_os/enviar_aceite_os.py) -- mesmo fluxo da tela_aceite_os.py:
"Conferir" só lê o Experience; "Enviar marcadas" gera o aceite e dispara o
e-mail do Experience para os aprovadores (sem volta), FAP a FAP, com a
reconferência que o próprio motor já faz em enviar_fap.
"""
from datetime import date, timedelta

from nucleo import GERENTE, PASTAS, ErroUsuario, exigir_confirmacao, marcar_uso, periodo_br, rota

ESTADO = {"token": None, "resultados": {}}


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
        return {"num": o.get("numos_sankhya"), "data": o.get("date_done"), "realizado": o.get("diff_time"),
                "processo": o.get("process_names"), "ok": o.get("_realizado_ok", True)}
    return {
        "fap": r["fap"], "parceiro": r["parceiro"], "situacao": situacao,
        "num_os": [o.get("numos_sankhya") for o in r["os"]], "horas": r["total_horas"] if r["os"] else "",
        "aprovadores": [{"nome": a.get("person_name"), "email": a.get("email")} for a in r["aprovadores"]],
        "bloqueios": r["bloqueios"], "os": [os_(o) for o in r["os"]],
        "fora_periodo": [os_(o) for o in r["fora_periodo"]],
    }


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
        faps = core.universo_de_faps(faps_txt or None)
        token = _login(core, t, novo=True)
        t.log(f"Período: {periodo[0]:%d/%m/%Y} a {periodo[1]:%d/%m/%Y}")
        res = core.conferir_todas(token, faps, periodo, t.log)
        ESTADO["resultados"] = {r["fap"]: r for r in res}
        t.adicionar_arquivo("Prévia (.csv)", core.salvar_csv(res))
        prontas = sum(1 for r in res if r["os"] and not r["bloqueios"])
        bloq = sum(1 for r in res if r["bloqueios"])
        vazias = sum(1 for r in res if not r["os"] and not r["bloqueios"])
        marcar_uso("aceite")
        return {"mensagem": f"Conferência concluída: {prontas} pronta(s), {bloq} bloqueada(s), "
                            f"{vazias} FAP(s) sem OS no período (ocultas). Nada foi enviado.",
                "resultado": {"linhas": [_linha(r) for r in res if r["os"] or r["bloqueios"]]}}

    t = GERENTE.iniciar("aceite_conferir", "Aceite de OS - conferência (só leitura)", trabalho,
                        pasta=PASTAS["aceite"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/aceite/enviar")
def enviar(req):
    exigir_confirmacao(req)
    faps = [str(f) for f in (req.corpo.get("faps") or [])]
    if not faps:
        raise ErroUsuario("Nenhuma FAP marcada.")
    selecionadas = []
    for f in faps:
        r = ESTADO["resultados"].get(f)
        if not r:
            raise ErroUsuario(f"A FAP {f} não está na última conferência. Clique em Conferir de novo.")
        if r["bloqueios"] or not r["os"]:
            raise ErroUsuario(f"A FAP {f} não está pronta para envio.")
        selecionadas.append(r)

    def trabalho(t):
        core = _core()
        token = _login(core, t)
        ok_total, situacao = 0, {}
        for r in selecionadas:
            ok, msg = core.enviar_fap(token, r)
            t.log(msg)
            situacao[r["fap"]] = "ENVIADA" if ok else "FALHOU"
            ok_total += ok
        t.adicionar_arquivo("Registro de envios (.jsonl)", core.ARQ_LOG_ENVIOS)
        marcar_uso("aceite")
        return {"mensagem": f"Envio concluído: {ok_total} de {len(selecionadas)} aceite(s) enviado(s).",
                "resultado": {"situacao": situacao}}

    t = GERENTE.iniciar("aceite_enviar", "Aceite de OS - envio", trabalho, pasta=PASTAS["aceite"])
    return 200, {"tarefa": t.id}

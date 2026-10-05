# -*- coding: utf-8 -*-
"""
Fase 3 -- apontamentos travados fora do prazo (conferencia_os/fase3_prazo_retroativo.py).
Só lê o Experience; escreve na planilha Google (se marcado) e gera o .xlsx local.
"""
import os

from nucleo import GERENTE, PASTAS, ErroUsuario, exigir_confirmacao, marcar_uso, periodo_br, rota


def _motor_sem_chdir():
    # O módulo faz os.chdir(conferencia_os) ao ser importado; desfaz isso aqui.
    # (As tarefas rodam nessa pasta de qualquer jeito -- ver GERENTE.iniciar.)
    cwd = os.getcwd()
    try:
        import fase3_prazo_retroativo as m
        return m
    finally:
        os.chdir(cwd)


@rota("GET", "/api/fase3/opcoes")
def opcoes(req):
    m = _motor_sem_chdir()
    ini, fim = m.ciclo_de(m.hoje_local())
    cfg = m.ler_config()
    return 200, {"de": ini.strftime("%d/%m/%Y"), "ate": fim.strftime("%d/%m/%Y"),
                 "aba": m.nome_aba(ini, fim), "url": cfg.get("url", "")}


@rota("GET", "/api/fase3/aba")
def aba(req):
    m = _motor_sem_chdir()
    try:
        a, b = periodo_br(req.query.get("de"), req.query.get("ate"))
    except ErroUsuario:
        return 200, {"aba": None}
    return 200, {"aba": m.nome_aba(a, b)}


def _salvar_url(m, url):
    cfg = m.ler_config()
    if url is not None and url.strip() != cfg.get("url", ""):
        cfg["url"] = url.strip()
        m.gravar_config(cfg)
    return cfg


@rota("POST", "/api/fase3/testar")
def testar(req):
    m = _motor_sem_chdir()
    cfg = _salvar_url(m, req.corpo.get("url"))
    if not cfg["url"]:
        raise ErroUsuario("Cole a URL do Apps Script primeiro.")
    r = m.testar_planilha(cfg)
    if not r.get("ok"):
        raise ErroUsuario(str(r.get("erro") or "A planilha recusou a conexão."))
    return 200, {"planilha": r.get("planilha")}


@rota("POST", "/api/fase3/executar")
def executar(req):
    m = _motor_sem_chdir()
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    enviar = bool(req.corpo.get("enviar"))
    cfg = _salvar_url(m, req.corpo.get("url"))
    if enviar:
        exigir_confirmacao(req)
        if not cfg["url"]:
            raise ErroUsuario("Cole a URL do Apps Script ou desmarque o envio.")

    def trabalho(t):
        resumo, arq, resp = m.executar(ini, fim, enviar, cfg, t.log)
        t.adicionar_arquivo("Cópia local (.xlsx)", arq)
        marcar_uso("fase3")
        msg = (f"Travadas no período: {resumo['travadas']} · Ainda no prazo: {resumo['no_prazo']} · "
               f"Fora do prazo: {resumo['fora']}")
        if resp:
            msg += f" · Planilha ({resp['aba']}): {resp['inseridas']} nova(s), {resp['ja_existiam']} já existiam"
        return {"mensagem": msg, "resultado": {"resumo": resumo, "planilha": resp}}

    t = GERENTE.iniciar("fase3", "Fase 3 - apontamentos travados", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}

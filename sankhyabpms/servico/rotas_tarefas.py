# -*- coding: utf-8 -*-
"""Rotas comuns: status do serviço, acompanhamento de tarefas, arquivos de saída."""
import os

from nucleo import GERENTE, MOTORES, ErroUsuario, ler_json_dados, rota


@rota("GET", "/api/status")
def status(req):
    ativa = GERENTE.ativa
    return 200, {
        "ok": True,
        "pasta_motores": MOTORES,
        "motores_encontrados": os.path.isdir(MOTORES),
        "ultimo_uso": ler_json_dados("ultimo_uso.json", {}) or {},
        "ativa": ativa.estado_json(10**9) if ativa and ativa.estado in ("rodando", "aguardando") else None,
    }


@rota("GET", "/api/tarefas/*")
def tarefa(req):
    t = GERENTE.obter(req.partes[0])
    if not t:
        return 404, {"erro": "Tarefa não encontrada (o serviço pode ter sido reiniciado)."}
    try:
        desde = int(req.query.get("desde", "0"))
    except ValueError:
        desde = 0
    return 200, t.estado_json(desde)


@rota("POST", "/api/tarefas/*/responder")
def responder(req):
    t = GERENTE.obter(req.partes[0])
    if not t:
        return 404, {"erro": "Tarefa não encontrada."}
    if not t.responder(req.corpo.get("pergunta_id"), req.corpo.get("valor")):
        raise ErroUsuario("Essa pergunta não está mais aberta.")
    return 200, {"ok": True}


def arquivo_da_tarefa(tarefa_id, indice):
    """Devolve o caminho de um arquivo registrado pela tarefa (só esses podem ser baixados)."""
    t = GERENTE.obter(tarefa_id)
    if not t:
        return None
    try:
        return t.arquivos[int(indice)][1]
    except (ValueError, IndexError):
        return None

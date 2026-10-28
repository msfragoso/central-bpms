# -*- coding: utf-8 -*-
"""Rotas comuns: status do serviço, acompanhamento de tarefas, arquivos de saída."""
import os

from nucleo import GERENTE, MOTORES, ErroUsuario, ler_json_dados, rota


# Data da última atualização de cada módulo (22/10/2026): a mais recente entre os
# arquivos da tela, do serviço e dos motores daquele módulo (não conta o comum.js,
# que é de todas as telas).
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ARQUIVOS_MODULO = {
    "lancar": ["web/lancar.html", "servico/app_lancar.py", "@clickup_tasks/lancar_tarefas_clickup.py"],
    "sync": ["web/sync.html", "servico/app_sync.py", "@main.py", "@clickup_sync/sync_engine.py",
             "@clickup_sync/orphan_check.py", "@clickup_sync/clickup_client.py", "@clickup_sync/config.py"],
    "conferencia": ["web/conferencia.html", "servico/app_conferencia.py", "servico/app_om.py", "servico/om_sessao.py",
                    "@conferencia_os/motor_conferencia.py", "@conferencia_os/html_conferencia.py",
                    "@conferencia_os/dados_conferencia.py", "@conferencia_os/config_conferencia.py"],
    "fase3": ["web/fase3.html", "servico/app_fase3.py", "@conferencia_os/fase3_prazo_retroativo.py"],
    "aceite": ["web/aceite.html", "servico/app_aceite.py", "@aceite_os/enviar_aceite_os.py"],
    "agenda": ["web/agenda.html", "servico/app_agenda.py", "servico/agenda_layout.py"],
    "atendimentos": ["web/atendimentos.html", "servico/app_atendimentos.py", "@atendimentos_whatsapp/gerar_relatorio.py"],
    "permissoes": ["web/permissoes.html", "servico/app_permissoes.py", "servico/clickup_sessao.py"],
    "backlog": ["web/backlog.html", "servico/app_backlog.py"],
    "planilhas": ["web/planilhas.html", "servico/app_planilhas.py", "@conferencia_os/conferencia_planilhas.py"],
}
_cache_atualizado = {"quando": 0, "dados": {}}


def _atualizacoes():
    import time
    from datetime import datetime
    if time.time() - _cache_atualizado["quando"] < 60:
        return _cache_atualizado["dados"]
    saida = {}
    for mod, arquivos in _ARQUIVOS_MODULO.items():
        datas = []
        for a in arquivos:
            cam = os.path.join(MOTORES, a[1:]) if a.startswith("@") else os.path.join(_RAIZ, a)
            if os.path.isfile(cam):
                datas.append(os.path.getmtime(cam))
        if datas:
            saida[mod] = datetime.fromtimestamp(max(datas)).strftime("%d/%m/%Y %H:%M")
    _cache_atualizado.update(quando=time.time(), dados=saida)
    return saida


@rota("GET", "/api/status")
def status(req):
    ativa = GERENTE.ativa
    return 200, {
        "ok": True,
        "pasta_motores": MOTORES,
        "motores_encontrados": os.path.isdir(MOTORES),
        "ultimo_uso": ler_json_dados("ultimo_uso.json", {}) or {},
        "atualizado": _atualizacoes(),
        "ativa": ativa.estado_json(10**9) if ativa and ativa.estado in ("rodando", "aguardando") else None,
        # v1.2.0: todos os processos rodando agora (sem o log, só o resumo)
        "ativas": [{k: v for k, v in t.estado_json(10**9).items() if k != "linhas"} for t in GERENTE.ativas],
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

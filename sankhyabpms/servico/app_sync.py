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

from nucleo import GERENTE, PASTAS, ErroUsuario, exigir_confirmacao, marcar_uso, periodo_br, rota

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
    }


@rota("GET", "/api/sync/contar")
def contar(req):
    from clickup_sync.list_discovery import filtrar_listas_por_nome
    texto = (req.query.get("texto") or "").strip()
    todas = _todas_listas()
    listas = filtrar_listas_por_nome(todas, texto) if texto else todas
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

    def trabalho(t):
        m = _modulo_main()
        ui._salvar_ultima_execucao(parceiro, valor_modelo)
        inicio = time.time()
        cache_listas = {"dados": _cache["listas"]}
        m._fluxo_principal(parceiro or None, ini.isoformat(), fim.isoformat(), modelo_filtro,
                           cache_listas, _JanelaFalsa(t, m._SINAL_FIM_EXECUCAO))
        logs = [p for p in glob.glob(os.path.join(PASTAS["raiz"], "logs", "log_*.txt"))
                if os.path.getmtime(p) >= inicio - 1]
        if logs:
            t.adicionar_arquivo("Log completo (.txt)", max(logs, key=os.path.getmtime))
        marcar_uso("sync")
        return {"mensagem": "Execução finalizada. Confira o relatório final no log."}

    alvo = parceiro or "todos os parceiros"
    t = GERENTE.iniciar("sync", f"Sync tarefa ClickUp ⇄ Experience ({alvo})", trabalho, pasta=PASTAS["raiz"])
    return 200, {"tarefa": t.id}

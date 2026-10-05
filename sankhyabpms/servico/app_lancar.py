# -*- coding: utf-8 -*-
"""
Lançar tarefa no ClickUp -- mesma regra da tela_lancamento.py (Tkinter),
usando o motor clickup_tasks/lancar_tarefas_clickup.py sem alteração.
"""
import json
import os
from datetime import date

from nucleo import PASTAS, ErroUsuario, data_br, exigir_confirmacao, gravar_json_dados, ler_json_dados, marcar_uso, rota

ARQ_MEMORIA = "ultimo_lancamento.json"


def _motor():
    import lancar_tarefas_clickup as m  # importa credenciais (cofre do Windows) na 1ª vez
    return m


def _memoria():
    dados = ler_json_dados(ARQ_MEMORIA)
    if dados is None:
        # 1ª vez: aproveita o último lançamento da tela antiga
        try:
            with open(os.path.join(PASTAS["clickup_tasks"], "ultimo_lancamento.json"), encoding="utf-8") as f:
                dados = json.load(f)
        except (OSError, ValueError):
            dados = {}
    return dados


@rota("GET", "/api/lancar/opcoes")
def opcoes(req):
    m = _motor()
    return 200, {
        "parceiros": sorted(m.OPCOES_PARCEIRO.keys(), key=lambda s: m.remover_acentos(s).lower()),
        "origens": list(m.OPCOES_ORIGEM.keys()),
        "periodos": list(m.OPCOES_PERIODO.keys()),
        "membros": m.carregar_membros_cache(),
        "memoria": _memoria(),
    }


@rota("POST", "/api/lancar/membros")
def atualizar_membros(req):
    m = _motor()
    membros = m.listar_membros_workspace()
    m.salvar_membros_cache(membros)
    return 200, {"membros": membros}


@rota("GET", "/api/lancar/faps")
def faps(req):
    m = _motor()
    parceiro = req.query.get("parceiro", "")
    if parceiro not in m.OPCOES_PARCEIRO:
        raise ErroUsuario(f"O parceiro '{parceiro}' não é válido. Selecione um da lista.")
    lista = m.listar_faps_do_parceiro(parceiro, req.query.get("forcar") == "1")
    return 200, {"faps": lista}


@rota("GET", "/api/lancar/periodo")
def periodo(req):
    return 200, {"periodo": _motor().interpretar_periodo(req.query.get("texto", ""))}


@rota("POST", "/api/lancar")
def lancar(req):
    exigir_confirmacao(req)
    m = _motor()
    c = req.corpo
    parceiro = (c.get("parceiro") or "").strip()
    origem = (c.get("origem") or "").strip()
    titulo = (c.get("titulo") or "").strip()
    usuario = (c.get("usuario") or "").strip()
    detalhamento = (c.get("detalhamento") or "").strip()

    if not parceiro or not origem or not titulo or not detalhamento:
        raise ErroUsuario("Parceiro, Origem, Título e Detalhamento são obrigatórios!")
    if parceiro not in m.OPCOES_PARCEIRO:
        raise ErroUsuario(f"O parceiro '{parceiro}' não é válido. Selecione um da lista!")
    if origem not in m.OPCOES_ORIGEM:
        raise ErroUsuario("Selecione uma origem válida da lista!")
    list_id = str(c.get("fap_id") or "").strip()
    if not list_id:
        raise ErroUsuario("Selecione a FAP em que a demanda deve ser lançada.")

    responsavel_id = c.get("responsavel_id") or None
    data_venc = data_br(c["vencimento"], "Data de vencimento") if (c.get("vencimento") or "").strip() else None

    periodo = None
    if (c.get("periodo") or "").strip():
        periodo = m.interpretar_periodo(c["periodo"])
        if not periodo:
            raise ErroUsuario(f"Período '{c['periodo']}' não existe no ClickUp. Selecione uma opção da lista (ex.: 08h-10h).")
        if not data_venc:
            raise ErroUsuario("Período preenchido sem data. Informe a data de vencimento (dia do atendimento) ou apague o período.")

    avisos = []
    task_id = m.criar_demanda_padrao(
        titulo=titulo, detalhamento=detalhamento, parceiro=parceiro, usuario_cliente=usuario,
        origem=origem, responsavel_id=responsavel_id, data_vencimento=data_venc, periodo=periodo,
        list_id=list_id, avisos=avisos,
    )
    gravar_json_dados(ARQ_MEMORIA, {"parceiro": parceiro, "origem": origem, "titulo": titulo,
                                    "usuario": usuario, "detalhamento": detalhamento})
    marcar_uso("lancar")
    return 200, {"task_id": task_id, "avisos": avisos, "periodo": periodo,
                 "vencimento": data_venc.strftime("%d/%m/%Y") if data_venc else None,
                 "no_passado": bool(data_venc and data_venc < date.today())}

# -*- coding: utf-8 -*-
"""
Organograma (06/11/2026, pedido do Fragoso): as pessoas da Sankhya que interessam ao PMO, por grupo
(ex.: "PO de Produtos") e área/produto. Montado aos poucos pela própria tela.

Os nomes ficam só neste computador, em dados/organograma.json (dados/ não vai para o GitHub). O código
da tela e deste serviço não leva nenhum nome.
"""
import re
from datetime import datetime

from nucleo import ErroUsuario, exigir_confirmacao, gravar_json_dados, ler_json_dados, marcar_uso, rota

ARQ = "organograma.json"
LIMITE_GRUPOS = 50
LIMITE_ITENS = 200
LIMITE_PESSOAS = 20
LIMITE_TEXTO = 120
LIMITE_DEMANDAS = 60


def _texto(v, campo, obrigatorio=True):
    t = re.sub(r"\s+", " ", str(v or "")).strip()
    if obrigatorio and not t:
        raise ErroUsuario(f"Preencha {campo}.")
    if len(t) > LIMITE_TEXTO:
        raise ErroUsuario(f"{campo.capitalize()} passa de {LIMITE_TEXTO} letras: {t[:40]}…")
    return t


def _validar(dados):
    grupos = dados.get("grupos")
    if not isinstance(grupos, list) or len(grupos) > LIMITE_GRUPOS:
        raise ErroUsuario("Organograma inválido.")
    saida = []
    for g in grupos:
        itens = g.get("itens") or []
        if not isinstance(itens, list) or len(itens) > LIMITE_ITENS:
            raise ErroUsuario("Grupo com itens demais.")
        novo = {"nome": _texto(g.get("nome"), "o nome do grupo"), "itens": []}
        for it in itens:
            pessoas = [_texto(p, "o nome da pessoa") for p in (it.get("pessoas") or []) if str(p or "").strip()]
            if len(pessoas) > LIMITE_PESSOAS:
                raise ErroUsuario("Área com pessoas demais.")
            # 06/11/2026 (Fragoso): demandas resumidas de cada área, para achar o PO/SUP certo pela busca
            demandas = [_texto(d, "a demanda") for d in (it.get("demandas") or []) if str(d or "").strip()]
            if len(demandas) > LIMITE_DEMANDAS:
                raise ErroUsuario(f"Área com mais de {LIMITE_DEMANDAS} demandas.")
            novo["itens"].append({"area": _texto(it.get("area"), "a área"), "pessoas": pessoas, "demandas": demandas,
                                  "obs": _texto(it.get("obs"), "a observação", obrigatorio=False)})
        saida.append(novo)
    return {"grupos": saida}


@rota("GET", "/api/organograma")
def ler(req):
    dados = ler_json_dados(ARQ, None) or {"grupos": []}
    return 200, dados


@rota("POST", "/api/organograma")
def gravar(req):
    exigir_confirmacao(req)
    dados = _validar(req.corpo.get("organograma") or {})
    dados["atualizado"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    gravar_json_dados(ARQ, dados)
    marcar_uso("organograma")
    return 200, dados

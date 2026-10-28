# -*- coding: utf-8 -*-
"""Textos editáveis das telas (títulos e descrições), salvos em dados/textos.json,
e a ordem dos módulos (dados/ordem_modulos.json)."""
import re

from nucleo import ErroUsuario, gravar_json_dados, ler_json_dados, rota

ARQ = "textos.json"
CHAVE_OK = re.compile(r"^[a-z0-9_.-]{1,60}$")


@rota("GET", "/api/textos")
def ler(req):
    return 200, {"textos": ler_json_dados(ARQ, {}) or {}}


@rota("POST", "/api/textos")
def gravar(req):
    novos = req.corpo.get("textos")
    if not isinstance(novos, dict):
        raise ErroUsuario("Formato inválido.")
    atuais = ler_json_dados(ARQ, {}) or {}
    for chave, valor in novos.items():
        if not CHAVE_OK.match(str(chave)):
            raise ErroUsuario(f"Chave inválida: {chave}")
        if valor is None:
            atuais.pop(chave, None)          # volta ao texto padrão
            continue
        valor = str(valor).strip()
        if not valor or len(valor) > 600:
            raise ErroUsuario("Cada texto precisa ter entre 1 e 600 caracteres.")
        atuais[chave] = valor
    gravar_json_dados(ARQ, atuais)
    return 200, {"textos": atuais}


# 28/10/2026 (Fragoso): ordem dos módulos (cartões do Início e menu do topo), arrastando os cartões.
ARQ_ORDEM = "ordem_modulos.json"
ID_OK = re.compile(r"^[a-z0-9_-]{1,40}$")


@rota("GET", "/api/ordem")
def ler_ordem(req):
    return 200, {"ordem": ler_json_dados(ARQ_ORDEM, []) or []}


@rota("POST", "/api/ordem")
def gravar_ordem(req):
    ordem = req.corpo.get("ordem")
    if not isinstance(ordem, list) or len(ordem) > 60 or not all(ID_OK.match(str(i)) for i in ordem):
        raise ErroUsuario("Ordem inválida.")
    gravar_json_dados(ARQ_ORDEM, [str(i) for i in ordem])
    return 200, {"ordem": ordem}

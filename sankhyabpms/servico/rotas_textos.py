# -*- coding: utf-8 -*-
"""Textos editáveis das telas (títulos e descrições), salvos em dados/textos.json."""
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

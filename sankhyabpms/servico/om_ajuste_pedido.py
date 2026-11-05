# -*- coding: utf-8 -*-
"""
Ajuste de horas de pedido no Sankhya-OM (05/11/2026, pedido do Fragoso).

Regras dele:
- Só pedido com Tipo de Operação 104 - SERV MEDIÇÃO e natureza 110401 ou 110501.
- Só a quantidade do item de horas. Os demais campos voltam como estão, e os valores são os
  que o próprio OM recalcula.
- Sempre com a confirmação dele na tela. O ajuste no Experience continua manual.

As chamadas repetem as da Central de Vendas (HAR de 05/11/2026; modelo em om_ajuste_modelo.json).
Qualquer resposta diferente de sucesso interrompe: a Central nunca responde sozinha a aviso do OM.
"""
import copy
import json
import os
import re
import uuid
from decimal import Decimal, InvalidOperation

TIPO_PERMITIDO = "104"
NATUREZAS = ("110401", "110501")
VOLUME_HORAS = "H"
# Campos do item que mudam junto com a quantidade (visto no HAR, depois de gravar).
MUDANCA_ESPERADA = {"QTDNEG", "QTDUNIDPAD", "VLRTOT", "VLRTOTLIQ", "BASEISS", "VLRISS", "QTDPENDENTE", "RESERVADO", "DTALTER"}

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "om_ajuste_modelo.json"), encoding="utf-8") as _f:
    MODELO = json.load(_f)


class AjusteRecusado(Exception):
    """O ajuste não pode seguir. A mensagem é mostrada na tela."""


def numero(valor):
    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise AjusteRecusado(f"Valor inválido vindo do OM: {valor!r}")


def texto_numero(valor):
    """22245.60 -> '22245.6'; 130.00 -> '130' (como a tela do OM envia)."""
    d = numero(valor).normalize()
    return format(d, "f")


def corpo_leitura_itens(nunota):
    corpo = copy.deepcopy(MODELO["leitura_itens"])
    corpo["criteria"]["parameters"][0]["value"] = str(nunota)
    return corpo


def corpo_leitura_cabecalho(nunota):
    return {"dataSetID": "001", "entityName": "CabecalhoNota", "standAlone": True,
            "fields": ["NUNOTA", "CODPARC", "Parceiro.NOMEPARC", "CODTIPOPER", "TipoOperacao.DESCROPER", "CODNAT",
                       "Natureza.DESCRNAT", "VLRNOTA", "STATUSNOTA", "PENDENTE", "DTALTER"],
            "tryJoinedFields": True, "parallelLoader": True,
            "criteria": {"expression": f"( this.NUNOTA = {int(nunota)} )", "parameters": []},
            "ignoreListenerMethods": "", "useDefaultRowsLimit": True}


def linhas_da_resposta(resposta, campos):
    return [dict(zip(campos, l)) for l in (resposta.get("responseBody") or {}).get("result") or []]


def item_de_horas(itens):
    horas = [i for i in itens if str(i.get("CODVOL") or "").strip().upper() == VOLUME_HORAS]
    if len(horas) != 1:
        raise AjusteRecusado(f"O pedido tem {len(horas)} item(ns) em horas. Só ajusto quando há exatamente 1: faça este manualmente.")
    return horas[0]


def validar_cabecalho(cab):
    if not cab:
        raise AjusteRecusado("Pedido não encontrado no OM.")
    tipo = str(cab.get("CODTIPOPER") or "").strip()
    if tipo != TIPO_PERMITIDO:
        raise AjusteRecusado(f"Ajuste manual: tipo de operação {tipo} - {' '.join(str(cab.get('TipoOperacao.DESCROPER') or '').split())} não permitido. Só 104 - SERV MEDIÇÃO.")
    natureza = str(cab.get("CODNAT") or "").strip()
    if natureza not in NATUREZAS:
        raise AjusteRecusado(f"Ajuste manual: natureza {natureza} fora de 110401 e 110501.")


def corpo_calculo(item, qtd_nova):
    dados = {k: ("" if item.get(k) is None else item.get(k)) for k in MODELO["campos_calculo"]}
    dados["QTDNEG"] = texto_numero(qtd_nova)
    return {"ITEM": {"CAMPO": "QTDNEG", "VLRANTERIORCAMPO": texto_numero(item["QTDNEG"]), "VLRMOEDA": "0",
                     "CALCULAVALORESCENTRAL": "S", **dados},
            "clientEventList": copy.deepcopy(MODELO["eventos"])}


def corpo_gravacao(item, qtd_nova, calculado, dono=None):
    dados = {}
    for k in MODELO["campos_item"]:
        v = item.get(k)
        dados[k] = {"$": "" if v is None else str(v)}
    qtd = texto_numero(qtd_nova)
    dados["QTDNEG"] = {"$": qtd}
    dados["QTDUNIDPAD"] = {"$": qtd}
    dados["VLRTOT"] = {"$": texto_numero(calculado["VLRTOT"])}
    dados["VLRTOTLIQ"] = {"$": texto_numero(calculado["VLRTOTLIQ"])}
    return {"nota": {"NUNOTA": str(item["NUNOTA"]), "txProperties": copy.deepcopy(MODELO["tx_properties"]),
                     "ownerServiceCall": dono or f"GradeItens_{uuid.uuid4().hex[:9]}",
                     "showClientEventAlteracaoValorVendaMais": "true",
                     "itens": {"ATUALIZACAO_ONLINE": "false", "item": dados}},
            "clientEventList": copy.deepcopy(MODELO["eventos"])}


def conferir_resultado(antes, depois, cab_antes, cab_depois, sequencia):
    """Mudanças além da quantidade e do recálculo esperado. Lista vazia = só o esperado."""
    surpresas = []
    por_seq = lambda lista: {str(i.get("SEQUENCIA")): i for i in lista}
    a, d = por_seq(antes), por_seq(depois)
    if set(a) != set(d):
        surpresas.append(f"Itens do pedido mudaram: {sorted(a)} para {sorted(d)}.")
    for seq in set(a) & set(d):
        for campo in set(a[seq]) | set(d[seq]):
            if a[seq].get(campo) == d[seq].get(campo):
                continue
            if seq == str(sequencia) and campo in MUDANCA_ESPERADA:
                continue
            surpresas.append(f"Item {seq}, campo {campo}: {a[seq].get(campo)!r} para {d[seq].get(campo)!r}.")
    for campo in ("CODTIPOPER", "CODNAT", "CODPARC", "STATUSNOTA", "PENDENTE"):
        if (cab_antes or {}).get(campo) != (cab_depois or {}).get(campo):
            surpresas.append(f"Cabeçalho, campo {campo}: {(cab_antes or {}).get(campo)!r} para {(cab_depois or {}).get(campo)!r}.")
    return surpresas


class Ajustador:
    """Fala com o OM por `chamar(modulo, servico, corpo)`, que devolve o JSON com status "1" ou levanta erro."""

    def __init__(self, chamar):
        self.chamar = chamar

    def ler(self, nunota):
        if not re.fullmatch(r"\d{1,12}", str(nunota)):
            raise AjusteRecusado("Número de pedido inválido.")
        corpo_cab = corpo_leitura_cabecalho(nunota)
        cab = linhas_da_resposta(self.chamar("mge", "DatasetSP.loadRecords", corpo_cab), corpo_cab["fields"])
        corpo_itens = corpo_leitura_itens(nunota)
        itens = linhas_da_resposta(self.chamar("mge", "DatasetSP.loadRecords", corpo_itens), corpo_itens["fields"])
        return (cab[0] if cab else None), itens

    def preparar(self, nunota, qtd_nova):
        cab, itens = self.ler(nunota)
        validar_cabecalho(cab)
        item = item_de_horas(itens)
        atual, nova = numero(item["QTDNEG"]), numero(qtd_nova)
        if nova <= atual:
            raise AjusteRecusado(f"A nova quantidade ({texto_numero(nova)}h) precisa ser maior que a atual ({texto_numero(atual)}h).")
        calculado = self.chamar("mgecom", "CACSP.calculaValoresItemNota", corpo_calculo(item, nova))["responseBody"]["ITEM"]
        if numero(calculado.get("QTDNEG")) != nova:
            raise AjusteRecusado("O OM devolveu outra quantidade no recálculo. Nada foi gravado.")
        return {"cabecalho": cab, "itens": itens, "item": item, "calculado": calculado, "atual": atual, "nova": nova}

    def gravar(self, nunota, qtd_nova, dtalter_visto):
        p = self.preparar(nunota, qtd_nova)
        if str(p["item"].get("DTALTER")) != str(dtalter_visto):
            raise AjusteRecusado("O pedido mudou no OM depois que você abriu o ajuste. Abra o ajuste de novo. Nada foi gravado.")
        self.chamar("mgecom", "CACSP.incluirAlterarItemNota", corpo_gravacao(p["item"], qtd_nova, p["calculado"]))
        cab_depois, itens_depois = self.ler(nunota)
        item_depois = item_de_horas(itens_depois)
        if numero(item_depois["QTDNEG"]) != p["nova"]:
            raise AjusteRecusado(f"O OM respondeu sucesso, mas a quantidade está em {item_depois['QTDNEG']}. Confira o pedido no OM.")
        return {**p, "cabecalho_depois": cab_depois, "item_depois": item_depois,
                "surpresas": conferir_resultado(p["itens"], itens_depois, p["cabecalho"], cab_depois, p["item"].get("SEQUENCIA"))}

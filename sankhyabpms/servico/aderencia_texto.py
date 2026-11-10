# -*- coding: utf-8 -*-
"""
Aderência da Solução à demanda (10/11/2026, pedido do Fragoso): sinaliza a OS cuja Solução não tem nenhuma palavra
importante em comum com o título e o Detalhamento da tarefa. É só um aviso para a pessoa olhar: compara palavras, não sentido.

Fica de fora, por decisão do Fragoso, a tarefa sem Detalhamento ou com título genérico (sem boa referência).
Os termos da equipe ficam em dados/termos_equivalentes.json ({"grupos": [[...]], "titulos_genericos": [...]}), somados
aos padrões abaixo. Tudo roda neste computador.
"""
import re
import unicodedata

from nucleo import ler_json_dados

ARQ_TERMOS = "termos_equivalentes.json"
MINIMO_PALAVRAS_REFERENCIA = 3
GRUPOS_PADRAO = [["faturamento", "faturar", "vendas", "venda", "vender"]]
TITULOS_GENERICOS = {"diversas", "diversos", "geral", "gerais", "outros", "outras", "varios", "varias"}
PARADA = set("""para com sobre pela pelo pelos pelas uma umas uns que como mais apos antes entre desde durante quando onde este esta esse essa isso aquele
foram foi sera ser sao tem tendo feito feita realizado realizada realizar atendimento apoio ajuste ajustes acompanhamento alinhamento reuniao demanda demandas
cliente usuario usuarios sistema sankhya tela telas processo processos validacao analise suporte duvida duvidas teste testes agenda atividade consultor nao dos das nos nas
por the and segue anexo modelo interno interna remoto""".split())
_EMAIL = re.compile(r"\S+@\S+")


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c)).lower()


def _radical(p):
    return (p[:-1] if p.endswith("s") and len(p) > 4 else p)[:6]


def termos():
    t = ler_json_dados(ARQ_TERMOS, {}) or {}
    equivalente = {}
    for grupo in GRUPOS_PADRAO + list(t.get("grupos") or []):
        radicais = [_radical(_sem_acento(x)) for x in grupo if str(x).strip()]
        for r in radicais:
            equivalente[r] = radicais[0]
    return {"equivalente": equivalente, "genericos": TITULOS_GENERICOS | {_sem_acento(x) for x in t.get("titulos_genericos") or []}}


def palavras(texto, equivalente):
    limpo = _EMAIL.sub(" ", _sem_acento(texto))
    return {equivalente.get(_radical(p), _radical(p)) for p in re.findall(r"[a-z0-9]{3,}", limpo) if p not in PARADA and not p.isdigit()}


def titulo_generico(titulo, genericos):
    uteis = [p for p in re.findall(r"[a-z0-9]{3,}", _sem_acento(titulo)) if p not in PARADA]
    return not uteis or any(p in genericos for p in uteis)


def motivo_sem_referencia(titulo, detalhamento, t=None):
    """Por que a tarefa não serve de referência; usado no selo "Sem referência" do Aceite."""
    t = t or termos()
    if titulo_generico(titulo, t["genericos"]):
        return "Título genérico"
    if not "\n".join(x for x in str(detalhamento or "").splitlines() if "@" not in x).strip():
        return "Sem Detalhamento"
    return "Título e Detalhamento com poucas informações"


_PREFIXO_SOLUCAO = re.compile(r"^\s*(agenda\s+\w+\s*-?\s*\w*\s*>|atendimento interno\s*-|nesta agenda,?|durante a agenda,?)\s*", re.I)
LIMITE_TITULO = 80
LIMITE_DETALHAMENTO = 500


def _cortar(texto, limite):
    if len(texto) <= limite:
        return texto
    return texto[:limite].rsplit(" ", 1)[0].rstrip(" ,;:-")


def sugerir(titulo, detalhamento, solucao, t=None):
    """
    Sugere título e Detalhamento a partir da Solução, só no que falta; a pessoa edita e aprova na tela.
    Devolve (titulo, detalhamento). O que já está bom volta igual.
    """
    t = t or termos()
    texto = _PREFIXO_SOLUCAO.sub("", " ".join(str(solucao or "").split())).strip()
    if not texto:
        return titulo, detalhamento
    texto = texto[:1].upper() + texto[1:]
    frases = [x.strip() for x in re.split(r"(?<=[.!?])\s+", texto) if x.strip()]
    novo_titulo = _cortar(frases[0].rstrip(".!?"), LIMITE_TITULO) if titulo_generico(titulo, t["genericos"]) else titulo
    sem_contato = "\n".join(x for x in str(detalhamento or "").splitlines() if "@" not in x).strip()
    novo_detalhe = detalhamento
    if not sem_contato or len(palavras(f"{titulo} {detalhamento}", t["equivalente"])) < MINIMO_PALAVRAS_REFERENCIA:
        novo_detalhe = _cortar(texto, LIMITE_DETALHAMENTO)
    return novo_titulo, novo_detalhe


def avaliar(titulo, detalhamento, solucao, t=None):
    """Devolve "ignorar" (sem boa referência), "ok" ou "conferir"."""
    t = t or termos()
    # linha só com contato (ex.: "Consultor Fulano fulano@empresa.com") não descreve a demanda
    detalhamento = "\n".join(x for x in str(detalhamento or "").splitlines() if "@" not in x)
    if not detalhamento.strip() or titulo_generico(titulo, t["genericos"]) or not str(solucao or "").strip():
        return "ignorar"
    referencia = palavras(f"{titulo} {detalhamento}", t["equivalente"])
    if len(referencia) < MINIMO_PALAVRAS_REFERENCIA:
        return "ignorar"
    return "conferir" if not referencia & palavras(solucao, t["equivalente"]) else "ok"

# -*- coding: utf-8 -*-
"""
Relatório mensal de atendimentos WhatsApp (Total Chat) -- integra o projeto
atendimentos_whatsapp/gerar_relatorio.py (14/10/2026) na Central:
1) a página envia os CSVs exportados do Total Chat, que ficam em
   atendimentos_whatsapp/dados/ (o mesmo lugar que o script usa sozinho);
2) a Central lista os meses encontrados e gera o PDF comparando dois meses.
O script original não foi alterado: aqui só chamamos as funções dele.
"""
import base64
import glob
import importlib.util
import os
import re

from nucleo import GERENTE, PASTAS, ErroUsuario, marcar_uso, rota

PASTA = os.path.join(PASTAS["raiz"], "atendimentos_whatsapp")
PASTA_DADOS = os.path.join(PASTA, "dados")
PASTA_SAIDA = os.path.join(PASTA, "saida")
_mod = {}


def _motor():
    """Carrega gerar_relatorio.py pelo caminho (o nome não conflita com nada da Central)."""
    if "m" not in _mod:
        caminho = os.path.join(PASTA, "gerar_relatorio.py")
        if not os.path.exists(caminho):
            raise ErroUsuario(f"Não achei {caminho}.")
        spec = importlib.util.spec_from_file_location("atendimentos_gerar_relatorio", caminho)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _mod["m"] = m
    return _mod["m"]


def _ler(m, caminho):
    """ler_csv do script faz sys.exit() quando falta coluna: vira erro amigável."""
    try:
        return m.ler_csv(caminho)
    except SystemExit as e:
        raise ErroUsuario(str(e))


def _meses():
    """{Period: (caminho, linhas)} -- mesmo critério do script: mês = moda de HrInicio; repetido fica o maior."""
    m = _motor()
    por_mes = {}
    for c in sorted(glob.glob(os.path.join(PASTA_DADOS, "*.csv"))):
        try:
            df = _ler(m, c)
        except ErroUsuario:
            continue
        if df.empty:
            continue
        p = m.mes_do_arquivo(df)
        if p not in por_mes or len(df) > por_mes[p][1]:
            por_mes[p] = (c, len(df))
    return por_mes


@rota("GET", "/api/atendimentos/opcoes")
def opcoes(req):
    m = _motor()
    por_mes = _meses()
    lista = [{"mes": str(p), "rotulo": m.rotulo(p), "arquivo": os.path.basename(c), "linhas": n}
             for p, (c, n) in sorted(por_mes.items())]
    return 200, {"meses": lista, "pasta": PASTA_DADOS}


@rota("POST", "/api/atendimentos/enviar-csv")
def enviar_csv(req):
    """Grava o CSV do Total Chat em atendimentos_whatsapp/dados/ (não apaga nada; nome repetido ganha sufixo)."""
    nome = re.sub(r"[^\w.\- ()]", "_", os.path.basename(req.corpo.get("nome") or "atendimentos.csv"))[:120]
    if not nome.lower().endswith(".csv"):
        raise ErroUsuario("Envie o arquivo .csv exportado do Total Chat.")
    try:
        conteudo = base64.b64decode(req.corpo.get("conteudo_b64") or "", validate=True)
    except ValueError:
        raise ErroUsuario("Arquivo inválido.")
    if not conteudo:
        raise ErroUsuario("Arquivo vazio.")
    os.makedirs(PASTA_DADOS, exist_ok=True)
    destino, n = os.path.join(PASTA_DADOS, nome), 1
    while os.path.exists(destino):
        base, ext = os.path.splitext(nome)
        destino, n = os.path.join(PASTA_DADOS, f"{base} ({n}){ext}"), n + 1
    with open(destino, "wb") as f:
        f.write(conteudo)
    m = _motor()
    try:
        df = _ler(m, destino)
    except ErroUsuario:
        os.remove(destino)  # o arquivo acabou de ser criado por esta rota
        raise
    if df.empty:
        os.remove(destino)
        raise ErroUsuario("O CSV não tem atendimentos com data de início válida.")
    p = m.mes_do_arquivo(df)
    return 200, {"arquivo": os.path.basename(destino), "mes": str(p), "rotulo": m.rotulo(p), "linhas": len(df)}


@rota("POST", "/api/atendimentos/gerar")
def gerar(req):
    anterior, atual = str(req.corpo.get("anterior") or ""), str(req.corpo.get("atual") or "")
    excluir = [e.strip() for e in str(req.corpo.get("excluir") or "PMO").split(",") if e.strip()] or ["PMO"]
    por_mes = {str(p): (p, c) for p, (c, _) in _meses().items()}
    if anterior not in por_mes or atual not in por_mes:
        raise ErroUsuario("Escolha os dois meses na lista (envie os CSVs se faltar algum).")
    if anterior >= atual:
        raise ErroUsuario("O mês anterior precisa ser antes do mês atual.")

    def trabalho(t):
        m = _motor()
        pa, ca = por_mes[anterior]
        pb, cb = por_mes[atual]
        t.log(f"Lendo {os.path.basename(ca)} ({m.rotulo(pa)}) e {os.path.basename(cb)} ({m.rotulo(pb)})...")
        df_a, df_b = _ler(m, ca), _ler(m, cb)
        a, b = m.metricas(df_a, excluir), m.metricas(df_b, excluir)
        t.log(f"  {m.rotulo(pa)}: {a['n']} atendimentos · {m.rotulo(pb)}: {b['n']} atendimentos")
        t.log(f"  Fora do ranking de clientes: {', '.join(excluir)}")
        os.makedirs(PASTA_SAIDA, exist_ok=True)
        destino = os.path.join(PASTA_SAIDA, f"Atendimentos_{pa.year}-{pa.month:02d}_vs_{pb.year}-{pb.month:02d}.pdf")
        t.log("Gerando a apresentação em PDF...")
        try:
            m.gerar(a, b, pa, pb, df_a, df_b, excluir, destino)
        except SystemExit as e:
            raise ErroUsuario(str(e))
        t.adicionar_arquivo("Apresentação (PDF)", destino)
        marcar_uso("atendimentos")
        return {"mensagem": f"PDF gerado: {m.rotulo(pa)} vs. {m.rotulo(pb)} "
                            f"({a['n']} → {b['n']} atendimentos)."}

    t = GERENTE.iniciar("atendimentos", "Relatório de atendimentos WhatsApp", trabalho, pasta=PASTA)
    return 200, {"tarefa": t.id}

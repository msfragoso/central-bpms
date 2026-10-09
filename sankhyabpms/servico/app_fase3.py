# -*- coding: utf-8 -*-
"""
Fase 3 -- apontamentos travados fora do prazo (conferencia_os/fase3_prazo_retroativo.py).
Só lê o Experience; escreve na planilha Google (se marcado) e gera o .xlsx local.
"""
import os

from nucleo import GERENTE, PASTAS, ErroUsuario, exigir_confirmacao, marcar_uso, periodo_br, rota


def _motor_sem_chdir():
    # O módulo faz os.chdir(conferencia_os) ao ser importado; desfaz isso aqui.
    # (As tarefas rodam nessa pasta de qualquer jeito -- ver GERENTE.iniciar.)
    cwd = os.getcwd()
    try:
        import fase3_prazo_retroativo as m
        return m
    finally:
        os.chdir(cwd)


@rota("GET", "/api/fase3/opcoes")
def opcoes(req):
    m = _motor_sem_chdir()
    ini, fim = m.ciclo_de(m.hoje_local())
    cfg = m.ler_config()
    return 200, {"de": ini.strftime("%d/%m/%Y"), "ate": fim.strftime("%d/%m/%Y"),
                 "aba": m.nome_aba(ini, fim), "url": cfg.get("url", "")}


@rota("GET", "/api/fase3/aba")
def aba(req):
    m = _motor_sem_chdir()
    try:
        a, b = periodo_br(req.query.get("de"), req.query.get("ate"))
    except ErroUsuario:
        return 200, {"aba": None}
    return 200, {"aba": m.nome_aba(a, b)}


def _salvar_url(m, url):
    cfg = m.ler_config()
    if url is not None and url.strip() != cfg.get("url", ""):
        cfg["url"] = url.strip()
        m.gravar_config(cfg)
    return cfg


@rota("POST", "/api/fase3/testar")
def testar(req):
    m = _motor_sem_chdir()
    cfg = _salvar_url(m, req.corpo.get("url"))
    if not cfg["url"]:
        raise ErroUsuario("Cole a URL do Apps Script primeiro.")
    r = m.testar_planilha(cfg)
    if not r.get("ok"):
        raise ErroUsuario(str(r.get("erro") or "A planilha recusou a conexão."))
    return 200, {"planilha": r.get("planilha")}


@rota("POST", "/api/fase3/executar")
def executar(req):
    m = _motor_sem_chdir()
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    enviar = bool(req.corpo.get("enviar"))
    cfg = _salvar_url(m, req.corpo.get("url"))
    if enviar:
        exigir_confirmacao(req)
        if not cfg["url"]:
            raise ErroUsuario("Cole a URL do Apps Script ou desmarque o envio.")

    def trabalho(t):
        resumo, arq, resp = m.executar(ini, fim, enviar, cfg, t.log)
        t.adicionar_arquivo("Cópia local (.xlsx)", arq)
        marcar_uso("fase3")
        msg = (f"Travadas no período: {resumo['travadas']} · Ainda no prazo: {resumo['no_prazo']} · "
               f"Fora do prazo: {resumo['fora']}")
        if resp:
            msg += f" · Planilha ({resp['aba']}): {resp['inseridas']} nova(s), {resp['ja_existiam']} já existiam"
        return {"mensagem": msg, "resultado": {"resumo": resumo, "planilha": resp}}

    t = GERENTE.iniciar("fase3", "Fase 3 - apontamentos travados", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}


# ============================================================================
# RELATÓRIO DO CICLO (lê a aba da planilha, que funciona como base de dados)
# ============================================================================
# A planilha "BP MS - Tarefas Pendentes de Apontamentos de OSs" só acumula
# (nunca apaga, nem depois do destravamento). No fim do ciclo de produtividade,
# lê a aba do ciclo pelo Apps Script (GET ?aba=) e gera relatório HTML + PDF.

def _get_apps_script(cfg, **params):
    import requests
    r = requests.get(cfg["url"], params=dict(params, token=cfg["token"]), timeout=120)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        raise ErroUsuario("O Apps Script não devolveu dados. Confira a URL na tela da Fase 3.")


@rota("GET", "/api/fase3/abas")
def abas(req):
    m = _motor_sem_chdir()
    cfg = m.ler_config()
    ini, fim = m.ciclo_de(m.hoje_local())
    atual = m.nome_aba(ini, fim)
    lista = []
    if cfg.get("url"):
        try:
            lista = _get_apps_script(cfg, listar="1").get("abas") or []
        except Exception:
            lista = []
    if atual not in lista:
        lista = [atual] + lista
    return 200, {"abas": lista, "atual": atual}


def _num(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _html_relatorio(aba, linhas, gerado_em):
    from html import escape as e
    sim = lambda r: str(r.get("Desconta", "")).strip().upper() == "SIM"
    por_exec = {}
    for r in linhas:
        por_exec.setdefault(str(r.get("Executante", "")).strip() or "(sem executante)", []).append(r)
    total, total_sim = len(linhas), sum(1 for r in linhas if sim(r))
    resumo = "".join(
        f"<tr><td>{e(n)}</td><td class='c'>{len(rs)}</td><td class='c'>{sum(1 for r in rs if sim(r))}</td>"
        f"<td class='c'>{max([_num(r.get('Dias de atraso')) or 0 for r in rs] or [0])}</td></tr>"
        for n, rs in sorted(por_exec.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    cartoes = []
    for nome, rs in sorted(por_exec.items()):
        rs = sorted(rs, key=lambda r: (str(r.get("Data de Execução", ""))[6:], str(r.get("Data de Execução", ""))[3:5],
                                       str(r.get("Data de Execução", ""))[:2]))
        corpo = "".join(
            f"<tr class='{'sim' if sim(r) else ''}'><td>{e(str(r.get('Data de Execução', '')))}</td>"
            f"<td>{e(str(r.get('Parceiro', '')))}</td><td>{e(str(r.get('Num. OS', '')))}</td>"
            f"<td class='c'>{e(str(r.get('Dias de atraso', '')))}</td><td class='c'>{e(str(r.get('Desconta', '')))}</td>"
            f"<td>{e(str(r.get('Motivo', '')))}</td><td>{e(str(r.get('Data do Lançamento', '')))}</td></tr>"
            for r in rs)
        cartoes.append(f"""
  <div class="card"><div class="cab">{e(nome)} <span>{len(rs)} OS · {sum(1 for r in rs if sim(r))} com desconto</span></div>
  <table><tr><th>Execução</th><th>Parceiro</th><th>Num. OS</th><th>Dias de atraso</th><th>Desconta</th><th>Motivo</th><th>Visto travado em</th></tr>{corpo}</table></div>""")
    ciclo = aba.replace("#RETRO-", "")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Apontamentos travados {e(ciclo)}</title><style>
@page {{ size: A4; margin: 14mm; }}
body {{ font-family: sans-serif; color: #333; }}
h1 {{ color: #1b5e20; font-size: 22px; margin: 0 0 4px; }}
.sub {{ color: gray; font-size: 12px; margin-bottom: 16px; }}
.resumo {{ background: #f0fff0; border: 2px solid #32cd32; border-radius: 8px; padding: 12px 14px; margin-bottom: 18px; font-size: 13px; }}
.card {{ margin-bottom: 16px; break-inside: avoid; page-break-inside: avoid; }}
.cab {{ background: #2e7d32; color: #fff; padding: 8px 10px; font-weight: bold; border-radius: 5px 5px 0 0; font-size: 13px;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.cab span {{ font-weight: normal; font-size: 11px; margin-left: 8px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 6px 7px; text-align: left; }}
th {{ background: #f5f5f5; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
td.c, th.c {{ text-align: center; }}
tr.sim td {{ background: #fff3e0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
tr {{ break-inside: avoid; }}
</style></head><body>
<h1>Apontamentos travados fora do prazo</h1>
<div class="sub">Ciclo {e(ciclo)} (aba {e(aba)}) · relatório gerado em {e(gerado_em)} · fonte: planilha "BP MS - Tarefas Pendentes de Apontamentos de OSs"</div>
<div class="resumo"><b>Resumo do ciclo</b><br>
Total de OS travadas fora do prazo: <b>{total}</b> &nbsp; Com desconto (Desconta = SIM): <b>{total_sim}</b> &nbsp; Executantes: <b>{len(por_exec)}</b>
<table style="margin-top:8px"><tr><th>Executante</th><th class="c">OS</th><th class="c">Com desconto</th><th class="c">Maior atraso (dias úteis)</th></tr>{resumo}</table>
<div style="font-size:11px;color:#8a4b0f;margin-top:6px">Linhas em laranja: Desconta = SIM.</div></div>
{''.join(cartoes) if cartoes else '<p>Nenhuma OS registrada nesta aba.</p>'}
</body></html>"""


@rota("POST", "/api/fase3/relatorio")
def relatorio(req):
    import re
    from datetime import datetime
    from nucleo import dados_arquivo
    m = _motor_sem_chdir()
    cfg = m.ler_config()
    if not cfg.get("url"):
        raise ErroUsuario("Cole a URL do Apps Script na tela da Fase 3 primeiro.")
    aba = (req.corpo.get("aba") or "").strip()
    if not aba.startswith("#RETRO-"):
        raise ErroUsuario("Escolha a aba do ciclo (ex.: #RETRO-SET/OUT-26).")

    def trabalho(t):
        from pdf_relatorio import html_para_pdf
        t.log(f"Lendo a aba {aba} da planilha (só leitura)...")
        resp = _get_apps_script(cfg, aba=aba)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("erro") or "a planilha recusou a leitura")
        if "linhas" not in resp:
            raise RuntimeError("O Apps Script publicado ainda é a versão antiga (não sabe ler a aba). "
                               "Atualize o script da planilha com o fase3_apps_script.gs novo.")
        # As colunas são lidas pela POSIÇÃO (A..K), não pelo nome: o cabeçalho da aba
        # pode ter sido escrito à mão ("Dias úteis de atraso", "Data do Lançamneto"...).
        padrao = ["Executante", "Parceiro", "Data de Execução", "Data do Lançamento", "Num. OS", "Desconta",
                  "Motivo", "Dias de atraso", "Código Sankhya", "Mensagem Sankhya", "ID Experience"]
        cab = resp.get("cabecalho") or []
        linhas = [{(padrao[i] if i < len(padrao) else c): l.get(c, "") for i, c in enumerate(cab)}
                  for l in resp["linhas"]] if cab else resp["linhas"]
        t.log(f"  {len(linhas)} linha(s) na aba.")
        agora = datetime.now()
        nome = re.sub(r"[^\w\-]+", "-", aba.replace("#RETRO-", "")).strip("-")
        pasta = dados_arquivo("relatorios")
        os.makedirs(pasta, exist_ok=True)
        html_path = os.path.join(pasta, f"Apontamentos travados {nome} - {agora:%d-%m-%Y %Hh%M}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(_html_relatorio(aba, linhas, agora.strftime("%d/%m/%Y às %Hh%M")))
        t.adicionar_arquivo("Relatório do ciclo (HTML)", html_path)
        t.log("Gerando o PDF...")
        t.adicionar_arquivo("Relatório do ciclo (PDF)", html_para_pdf(html_path))
        marcar_uso("fase3")
        sim = sum(1 for r in linhas if str(r.get("Desconta", "")).strip().upper() == "SIM")
        return {"mensagem": f"Relatório do ciclo {aba}: {len(linhas)} OS, {sim} com desconto. Nada foi alterado na planilha."}

    t = GERENTE.iniciar("fase3_relatorio", f"Relatório do ciclo {aba}", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}

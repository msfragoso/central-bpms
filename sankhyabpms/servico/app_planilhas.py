# -*- coding: utf-8 -*-
"""
Conferência dos apontamentos em planilha (27/10/2026) -- motor em
conferencia_os/conferencia_planilhas.py. Lê o ClickUp, as planilhas dos
consultores (Drive, G:\\) -- sem o OM. Só escreve quando o
Fragoso responde "Sim" a "Já podemos fechar a planilha e preencher a OBS?": preenche
a OBS das linhas conferidas (backup antes; OBS com texto não é sobrescrita).
"""
import json
import os
from datetime import datetime

from nucleo import (CONFIG, GERENTE, PASTAS, ErroUsuario, dados_arquivo, exigir_confirmacao, marcar_uso,
                    periodo_br, rota)

PASTA = "planilhas_conferencia"


def _motor():
    import conferencia_planilhas as cp
    return cp


def _arq_resultado(tarefa_id):
    return os.path.join(dados_arquivo(PASTA), f"resultado_{tarefa_id}.json")


@rota("GET", "/api/planilhas/opcoes")
def opcoes(req):
    from datetime import date, timedelta
    cp = _motor()
    ini, fim = cp.ciclo_de(date.today())
    ant_fim = ini.replace(day=20)
    ant_ini, ant_fim = cp.ciclo_de(ant_fim)
    raiz = cp.raiz_planilhas(CONFIG.get("planilhas_raiz"))
    consultores = []
    if raiz:
        consultores = [{"chave": k, "pasta": v["pasta"]} for k, v in sorted(cp.planilhas_por_consultor(raiz, lambda *_: None).items())]
    return 200, {"de": f"{ini:%d/%m/%Y}", "ate": f"{fim:%d/%m/%Y}",
                 "anterior": {"de": f"{ant_ini:%d/%m/%Y}", "ate": f"{ant_fim:%d/%m/%Y}"},
                 "raiz": raiz, "consultores": consultores,
                 "apontamentos": list(cp.APONTAMENTOS_PLANILHA)}


def _sem_item(planilhas, res):
    """Pastas de consultor que não aparecem no relatório -- servem para achar o dono de um travado
    pelo 1º nome (quem já tem item vai pelo nome do relatório)."""
    com_item = {x.get("chave") for x in res}
    return [v.get("pasta") or k for k, v in planilhas.items() if k not in com_item]


def _travados_do_ciclo(ini, log):
    """28/10/2026 (Fragoso): apontamentos travados do módulo Fase 3 (aba #RETRO- do ciclo), só leitura.
    Sem a URL do Apps Script ou com erro, o relatório sai sem essa parte (None)."""
    try:
        import app_fase3
        m = app_fase3._motor_sem_chdir()
        cfg = m.ler_config()
        if not cfg.get("url"):
            log("Apontamentos travados: URL do Apps Script da Fase 3 não configurada -- relatório sem essa parte.")
            return None
        aba = m.nome_aba(*m.ciclo_de(ini))
        linhas = app_fase3.ler_aba(cfg, aba)
        log(f"Apontamentos travados: {len(linhas)} OS na aba {aba} (só leitura).")
        return linhas
    except Exception as e:
        log(f"⚠ Apontamentos travados não lidos ({e}); o relatório sai sem essa parte.")
        return None


@rota("POST", "/api/planilhas/executar")
def executar(req):
    # 27/10/2026 (Fragoso): esta conferência cruza só planilhas do Drive x tarefas do ClickUp -- sem OM.
    # "Já tem OS" vem do campo OS Sankhya da tarefa e do Nº de OS que o consultor anota na planilha.
    c = req.corpo
    ini, fim = periodo_br(c.get("de"), c.get("ate"))
    consultor = c.get("consultor") or "Todos"

    def trabalho(t):
        from pdf_relatorio import html_para_pdf
        cp = _motor()
        res, planilhas = cp.executar(ini, fim, om_df=None, consultor=consultor, cfg_raiz=CONFIG.get("planilhas_raiz"), log=t.log)
        travados = _travados_do_ciclo(ini, t.log)
        r = cp.resumo(res)
        pasta = dados_arquivo("relatorios")
        os.makedirs(pasta, exist_ok=True)
        filtro = "" if consultor == "Todos" else f"consultor {consultor}"
        base = os.path.join(pasta, f"Conferencia planilhas {ini:%d-%m-%Y} a {fim:%d-%m-%Y}"
                                   + (f" {consultor}" if filtro else "") + f" - {datetime.now():%Hh%M}")
        cp.gerar_html(res, ini, fim, base + ".html", filtro, travados=travados,
                      conhecidos=_sem_item(planilhas, res))
        t.adicionar_arquivo("Relatório (HTML)", base + ".html")
        try:
            t.adicionar_arquivo("Relatório (PDF)", html_para_pdf(base + ".html"))
        except Exception as e:
            t.log(f"⚠ PDF não gerado ({e}); o HTML está pronto.")
        with open(_arq_resultado(t.id), "w", encoding="utf-8") as f:
            json.dump({"de": f"{ini:%d/%m/%Y}", "ate": f"{fim:%d/%m/%Y}", "consultor": consultor, "itens": res}, f, ensure_ascii=False, default=str)
        marcar_uso("planilhas")
        msg = (f"{r['ok']} conferido(s) · {r['horario'] + r['cliente']} com diferença · {r['falta']} falta(m) na planilha · "
               f"{r['sem_tarefa']} sem tarefa no ClickUp · {r['com_os']} com OS. Nada foi alterado.")
        return {"mensagem": msg, "resultado": {"itens": res, "resumo": r}}

    t = GERENTE.iniciar("planilhas", "Conferência das planilhas", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/planilhas/gravar")
def gravar(req):
    exigir_confirmacao(req)
    origem = str(req.corpo.get("tarefa") or "")
    try:
        with open(_arq_resultado(origem), encoding="utf-8") as f:
            salvo = json.load(f)
    except (OSError, ValueError):
        raise ErroUsuario("Conferência não encontrada. Rode a conferência de novo antes de gravar.")
    ini, fim = periodo_br(salvo["de"], salvo["ate"])
    # 27/10/2026 (Fragoso): a página pergunta "Já podemos fechar a planilha e preencher a OBS?" e, no "Sim",
    # preenche a OBS das linhas conferidas e o VISTO das planilhas vazias. A aba CONF-<ciclo> foi retirada
    # do processo a pedido dele (27/10/2026): nada de aba nova de conferência nas planilhas.

    def trabalho(t):
        cp = _motor()
        raiz = cp.raiz_planilhas(CONFIG.get("planilhas_raiz"))
        quem = salvo.get("consultor") or "Todos"
        arqs = {v["pasta"]: v["arquivo"] for k, v in cp.planilhas_por_consultor(raiz, t.log).items()
                if quem in ("Todos", k)}
        t.log("Fechando as planilhas: preenchendo a OBS (e VISTO nas planilhas vazias)...")
        obs = cp.fechar_planilhas(salvo["itens"], ini, arqs, dados_arquivo(os.path.join(PASTA, "backup")),
                                  dados_arquivo(PASTA), t.log)
        for v in obs:
            nome = os.path.basename(v.get("arquivo") or "")
            t.log(f"  ❌ {nome}: {v['erro']}" if v.get("erro") else
                  f"  ✔ {nome}: {v.get('escritas')} OBS preenchida(s)"
                  + (f", {v.get('ja_tinham')} já tinham texto (mantidas)" if v.get("ja_tinham") else ""))
        erros = sum(1 for v in obs if v.get("erro"))
        # 27/10/2026 (Fragoso): depois de fechar, a página pergunta se pode criar a aba do ciclo seguinte
        from datetime import timedelta
        a_prox, b_prox = cp.ciclo_de(fim + timedelta(days=1))
        proximo = {"de": f"{a_prox:%d/%m/%Y}", "ate": f"{b_prox:%d/%m/%Y}", "nome": cp._nome_ciclo(a_prox, b_prox),
                   "consultor": quem}
        marcar_uso("planilhas")
        return {"mensagem": f"OBS preenchida em {len(obs) - erros} planilha(s)" + (f", {erros} com erro (veja o log)" if erros else "")
                            + (". Nada para preencher." if not obs else "."),
                "resultado": {"obs": obs, "proximo": proximo}}

    t = GERENTE.iniciar("planilhas_gravar", "Fechar planilhas (preencher OBS)", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/planilhas/aba-ciclo")
def aba_ciclo(req):
    """Cria em cada planilha a aba vazia do ciclo (cópia da aba do ciclo anterior, campos limpos).
    Chamada só pela pergunta automática depois de fechar a conferência (o cartão "Aba do ciclo" saiu da tela
    a pedido do Fragoso, 27/10/2026)."""
    from datetime import date, timedelta
    exigir_confirmacao(req)
    cp = _motor()
    ini, fim = cp.ciclo_de(date.today())
    if req.corpo.get("ciclo") == "proximo":
        ini = fim + timedelta(days=1)
    if req.corpo.get("de"):  # ciclo explícito (pergunta automática depois de fechar a conferência)
        ini = periodo_br(req.corpo["de"], req.corpo["de"])[0]
    consultor = req.corpo.get("consultor") or "Todos"

    def trabalho(t):
        raiz = cp.raiz_planilhas(CONFIG.get("planilhas_raiz"))
        if not raiz:
            raise ErroUsuario("Pasta '01. Planilhas Consultores' não encontrada no G:\\ (atalho no Meu Drive).")
        pl = cp.planilhas_por_consultor(raiz, t.log)
        arqs = {v["pasta"]: v["arquivo"] for k, v in pl.items() if consultor in ("Todos", k)}
        a, b = cp.ciclo_de(ini)
        t.log(f"Aba {cp._nome_ciclo(a, b)} ({a:%d/%m/%Y} a {b:%d/%m/%Y}) em {len(arqs)} planilha(s)...")
        res = cp.criar_abas_proximo_ciclo(ini, arqs, dados_arquivo(os.path.join(PASTA, "backup")), dados_arquivo(PASTA), t.log)
        criadas = [r for r in res if r.get("criada")]
        ja = [r for r in res if r.get("ja_existia")]
        erros = [r for r in res if r.get("erro")]
        for r in erros:
            t.log(f"  ❌ {os.path.basename(r['arquivo'])}: {r['erro']}")
        for r in criadas:
            t.log(f"  ✔ {os.path.basename(r['arquivo'])}: aba {r['alvo']} criada")
        marcar_uso("planilhas")
        return {"mensagem": f"Aba {cp._nome_ciclo(a, b)}: criada em {len(criadas)} planilha(s), já existia em {len(ja)}"
                            + (f", {len(erros)} com erro (veja o log)" if erros else "") + "."}

    t = GERENTE.iniciar("planilhas_aba", "Criar aba do ciclo nas planilhas", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}

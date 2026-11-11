# -*- coding: utf-8 -*-
"""
Indicador de prazo de apontamento das OS (11/11/2026, pedido do Fragoso).

Mede quantos dias cada consultor da unidade leva entre a execução da OS e o
fechamento dela no Sankhya-OM (OrdemServico.DTFECHAMENTO). Só OS: lançamentos
em planilha não entram. Gera um HTML5 (abre no navegador e imprime em PDF) e
um Excel com fórmulas. Só leitura.

Quem é da unidade fica em dados/indicador_prazo.json (local, não vai para o
GitHub), no formato:
  {"unidade": {"NOMEUSU.DO.OM": "Nome para o relatório", ...},
   "prazo_dias_uteis": 3, "feriados": ["07/09/2026", ...]}
Sem o arquivo, entram todos os executantes da consulta.
"""
import html
import os
from datetime import date, datetime

FERIADOS_PADRAO = ["01/01/2026", "16/02/2026", "17/02/2026", "03/04/2026", "21/04/2026", "01/05/2026", "04/06/2026",
                   "07/09/2026", "12/10/2026", "02/11/2026", "15/11/2026", "20/11/2026", "25/12/2026"]
NAVY, VERDE, VERDE_CLARO, CINZA, VERDE_OK, LARANJA = "#1C2430", "#66CB66", "#E9F9EA", "#475569", "#3AA552", "#C2410C"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def configuracao():
    from nucleo import ler_json_dados
    c = ler_json_dados("indicador_prazo.json", {}) or {}
    feriados = [datetime.strptime(f, "%d/%m/%Y").date() for f in (c.get("feriados") or FERIADOS_PADRAO)]
    return c.get("unidade") or {}, int(c.get("prazo_dias_uteis") or 3), feriados


def _nome_padrao(usuario):
    return " ".join(p.capitalize() for p in str(usuario).split("."))


def preparar(linhas, campos, log=print):
    """linhas da consulta ItemOrdemServico (com OrdemServico.DTFECHAMENTO) -> DataFrame do indicador."""
    import numpy as np
    import pandas as pd
    unidade, prazo, feriados = configuracao()
    d = pd.DataFrame(linhas, columns=campos)
    if unidade:
        fora = d.loc[~d["Executante.NOMEUSU"].isin(unidade), "Executante.NOMEUSU"]
        if len(fora):
            log(f"{len(fora)} OS de {fora.nunique()} executante(s) fora da unidade não entram no indicador.")
        d = d[d["Executante.NOMEUSU"].isin(unidade)].copy()
    else:
        log("⚠ dados/indicador_prazo.json sem a lista da unidade: entram todos os executantes da consulta.")
    d["cliente"] = d["OrdemServico.Parceiro.NOMEPARC"].fillna("")
    d["fap"] = d["OrdemServico.NUFAP"].fillna("")
    d["consultor"] = d["Executante.NOMEUSU"].map(lambda u: unidade.get(u) or _nome_padrao(u))
    d["exec"] = pd.to_datetime(d["INICEXEC"], format="%d/%m/%Y", errors="coerce")
    d["fech"] = pd.to_datetime(d["OrdemServico.DTFECHAMENTO"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    sem = int(d["fech"].isna().sum())
    if sem:
        log(f"{sem} OS ainda sem data de fechamento no OM não entram no cálculo.")
    d = d[d["exec"].notna() & d["fech"].notna()].copy()
    d["dias"] = (d["fech"].dt.normalize() - d["exec"]).dt.days.clip(lower=0)
    d["uteis"] = [int(np.busday_count(a.date(), b.date(), holidays=feriados)) if b.normalize() > a else 0
                  for a, b in zip(d["exec"], d["fech"])]
    d["mes"] = d["exec"].dt.to_period("M")
    return d, prazo, feriados


def resumo(d, prazo):
    g = d.groupby("consultor").agg(os=("dias", "size"), media=("dias", "mean"), mediana=("dias", "median"),
                                   maximo=("dias", "max"), uteis=("uteis", "mean"),
                                   no_prazo=("uteis", lambda s: (s <= prazo).mean()))
    meses = sorted(d["mes"].unique())
    for m in meses:
        g[str(m)] = d[d["mes"] == m].groupby("consultor")["uteis"].mean()
    g = g.sort_values("uteis")
    tot = dict(os=len(d), media=d["dias"].mean(), mediana=d["dias"].median(), maximo=d["dias"].max(),
               uteis=d["uteis"].mean(), no_prazo=(d["uteis"] <= prazo).mean(),
               **{str(m): d[d["mes"] == m]["uteis"].mean() for m in meses})
    return g, tot, meses


def gerar_html(d, ini, fim, prazo, feriados, caminho):
    import pandas as pd
    g, tot, meses = resumo(d, prazo)
    esc = html.escape
    n1 = lambda v: f"{v:.1f}".replace(".", ",") if pd.notna(v) else "–"
    rot_mes = lambda m: f"{MESES[m.month - 1]}/{str(m.year)[2:]}"
    mx = max(float(g["uteis"].max() or 0), prazo + 1)
    barras = ""
    for c, r in g.iterrows():
        cor = VERDE_OK if round(r.uteis, 1) <= prazo else LARANJA
        barras += (f'<div class="lin"><div class="rot">{esc(c)}</div><div class="pista" title="{esc(c)}: {n1(r.uteis)} dias úteis">'
                   f'<i style="width:{r.uteis / mx * 100:.1f}%;background:{cor}"></i><b class="marca" style="left:{prazo / mx * 100:.1f}%"></b></div>'
                   f'<div class="val"><b>{n1(r.uteis)}</b> d.u.</div></div>')
    cab_m = "".join(f"<th class='n'>{rot_mes(m)}</th>" for m in meses)
    linhas = "".join(
        f"<tr><td>{esc(c)}</td><td class='n'>{int(r.os)}</td><td class='n'><b>{n1(r.uteis)}</b></td><td class='n'>{n1(r.media)}</td>"
        f"<td class='n'>{n1(r.mediana)}</td><td class='n'>{int(r.maximo)}</td><td class='n'>{r.no_prazo * 100:.0f}%</td>"
        + "".join(f"<td class='n'>{n1(r[str(m)])}</td>" for m in meses) + "</tr>" for c, r in g.iterrows())
    linhas += (f"<tr class='tot'><td>Unidade</td><td class='n'>{tot['os']}</td><td class='n'>{n1(tot['uteis'])}</td><td class='n'>{n1(tot['media'])}</td>"
               f"<td class='n'>{n1(tot['mediana'])}</td><td class='n'>{int(tot['maximo'])}</td><td class='n'>{tot['no_prazo'] * 100:.0f}%</td>"
               + "".join(f"<td class='n'>{n1(tot[str(m)])}</td>" for m in meses) + "</tr>")
    fora = g[g["uteis"].round(1) > prazo]
    fer = ", ".join(f"{f:%d/%m}" for f in feriados if ini <= f <= max(fim, d["fech"].max().date()))
    det = "".join(
        f"<tr><td>{esc(r.consultor)}</td><td>{esc(str(r.NUMOS))}</td><td>{esc(str(r.cliente))}</td><td>{r.exec:%d/%m/%Y}</td>"
        f"<td>{r.fech:%d/%m/%Y %H:%M}</td><td class='n'>{r.dias}</td><td class='n {'' if r.uteis <= prazo else 'atraso'}'>{r.uteis}</td></tr>"
        for r in d.sort_values(["consultor", "exec"]).itertuples())
    doc = f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prazo de apontamento das OS</title><style>
@page{{size:A4;margin:12mm}}*{{box-sizing:border-box}}
body{{font-family:Arial,Helvetica,sans-serif;color:{NAVY};font-size:10pt;margin:0 auto;max-width:980px;padding:16px;background:#fff}}
.topo{{background:{NAVY};color:#fff;border-radius:8px;padding:14px 16px;border-left:8px solid {VERDE};margin-bottom:12px}}
.topo h1{{margin:0;font-size:17pt}}.topo div{{color:#cfd8e3;font-size:9.4pt;margin-top:3px}}
h2{{font-size:12pt;border-bottom:2px solid {VERDE};padding-bottom:3px;margin:18px 0 8px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}}
.kpi{{background:{VERDE_CLARO};border-left:4px solid {VERDE};border-radius:8px;padding:8px 10px}}.kpi b{{display:block;font-size:16pt}}.kpi span{{font-size:8.5pt;color:{CINZA}}}
.lin{{display:grid;grid-template-columns:minmax(120px,190px) 1fr 74px;gap:8px;align-items:center;margin:5px 0;font-size:9.2pt}}
.pista{{position:relative;height:13px;background:#f1f5f9;border-radius:3px}}.pista i{{display:block;height:13px;border-radius:0 4px 4px 0}}
.marca{{position:absolute;top:-3px;bottom:-3px;width:2px;background:{NAVY}}}.val{{text-align:right}}
.tab{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:8.6pt}}th{{background:{NAVY};color:#fff;padding:5px;text-align:left;position:sticky;top:0}}
td{{padding:4px 5px;border-bottom:1px solid #e2e8f0}}.n{{text-align:right;white-space:nowrap}}tr.tot td{{background:{VERDE_CLARO};font-weight:700}}
td.atraso{{color:{LARANJA};font-weight:700}}.nota{{font-size:8.4pt;color:{CINZA};margin-top:6px}}
details{{margin-top:14px}}summary{{cursor:pointer;font-weight:700}}#busca{{margin:8px 0;padding:6px 8px;width:100%;max-width:320px;border:1px solid #cbd5e1;border-radius:6px}}
@media print{{details{{display:none}}body{{padding:0}}}}
</style></head><body>
<div class="topo"><h1>Prazo de apontamento das OS</h1><div>Consultores da unidade · OS executadas de {ini:%d/%m/%Y} a {fim:%d/%m/%Y} · fonte: Sankhya-OM · gerado em {datetime.now():%d/%m/%Y %H:%M}</div></div>
<div class="kpis"><div class="kpi"><b>{n1(tot['uteis'])} d.u.</b><span>média da unidade (dias úteis)</span></div>
<div class="kpi"><b>{n1(tot['media'])} dias</b><span>média em dias corridos (mediana {n1(tot['mediana'])})</span></div>
<div class="kpi"><b>{tot['no_prazo'] * 100:.0f}%</b><span>das OS fechadas em até {prazo} dias úteis</span></div>
<div class="kpi"><b>{tot['os']}</b><span>OS de {len(g)} consultores</span></div></div>
<h2>Média de dias úteis para apontar, por consultor</h2>{barras}
<div class="nota">A linha escura marca o prazo de {prazo} dias úteis. Barras em laranja: média acima do prazo.</div>
<h2>Indicador por consultor</h2>
<div class="tab"><table><tr><th>Consultor</th><th class="n">OS</th><th class="n">Média (d.u.)</th><th class="n">Média (corridos)</th><th class="n">Mediana</th>
<th class="n">Máximo</th><th class="n">No prazo</th>{cab_m}</tr>{linhas}</table></div>
<div class="nota">Dias entre a data de execução e a data de fechamento da OS no Sankhya-OM. Dias úteis descontam fins de semana{(' e os feriados de ' + fer) if fer else ''}.
Colunas por mês: média em dias úteis pelo mês de execução. Não entram lançamentos em planilha nem consultores de parceiros.
{'Média acima do prazo: ' + ', '.join(fora.index) + '.' if len(fora) else 'Todos os consultores estão, em média, dentro do prazo.'}</div>
<details><summary>Detalhe das {len(d)} OS</summary><input id="busca" placeholder="Filtrar por consultor, OS ou cliente">
<div class="tab"><table id="det"><thead><tr><th>Consultor</th><th>OS</th><th>Cliente</th><th>Execução</th><th>Fechamento</th><th class="n">Dias</th><th class="n">Dias úteis</th></tr></thead><tbody>{det}</tbody></table></div></details>
<script>document.getElementById("busca").addEventListener("input",function(e){{var t=e.target.value.toLowerCase();
document.querySelectorAll("#det tbody tr").forEach(function(r){{r.style.display=r.textContent.toLowerCase().indexOf(t)>-1?"":"none";}});}});</script>
</body></html>"""
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(doc)
    return caminho


def gerar_excel(d, ini, fim, prazo, feriados, caminho):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.formula import ArrayFormula
    g, tot, meses = resumo(d, prazo)
    F, FN = Font(name="Arial", size=10), Font(name="Arial", size=10, bold=True)
    CABF, CAB, FUNDO = Font(name="Arial", size=10, bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1C2430"), PatternFill("solid", fgColor="E9F9EA")
    wb = Workbook()
    wo = wb.active
    wo.title = "OS"
    for j, c in enumerate(["OS", "Item", "Consultor", "Cliente", "FAP", "Execução", "Fechamento", "Dias corridos", "Dias úteis", "Mês"], 1):
        x = wo.cell(1, j, c)
        x.font, x.fill = CABF, CAB
    dd = d.sort_values(["consultor", "exec"])
    nf = len(feriados) + 1
    for i, r in enumerate(dd.itertuples(), 2):
        vals = [r.NUMOS, r.NUMITEM, r.consultor, r.cliente, r.fap, r.exec.to_pydatetime(), r.fech.to_pydatetime(), f"=MAX(0,INT(G{i})-F{i})",
                f"=IF(INT(G{i})>F{i},NETWORKDAYS(F{i},INT(G{i})-1,Feriados!$A$2:$A${nf}),0)", f"=YEAR(F{i})*100+MONTH(F{i})"]
        for j, v in enumerate(vals, 1):
            wo.cell(i, j, v).font = F
        wo.cell(i, 6).number_format, wo.cell(i, 7).number_format = "dd/mm/yyyy", "dd/mm/yyyy hh:mm"
    n = len(dd) + 1
    for c, w in zip("ABCDEFGHIJ", (10, 6, 24, 40, 8, 12, 17, 9, 9, 9)):
        wo.column_dimensions[c].width = w
    wo.freeze_panes, wo.auto_filter.ref = "A2", f"A1:J{n}"
    wf = wb.create_sheet("Feriados")
    wf["A1"], wf["A1"].font, wf["A1"].fill = "Feriados", CABF, CAB
    for i, f in enumerate(feriados, 2):
        wf.cell(i, 1, f).number_format = "dd/mm/yyyy"
    wf.column_dimensions["A"].width = 16
    ws = wb.create_sheet("Indicador", 0)
    ws["A1"], ws["A1"].font = f"Prazo de apontamento das OS · consultores da unidade · {ini:%d/%m/%Y} a {fim:%d/%m/%Y}", Font(name="Arial", size=13, bold=True, color="1C2430")
    ws["A2"], ws["A2"].font = "Dias entre a execução da OS e o fechamento no Sankhya-OM. Só OS (planilhas fora). Feriados na aba Feriados.", F
    ws["A3"], ws["A3"].font, ws["B3"], ws["B3"].font = "Prazo (dias úteis):", F, prazo, FN
    cab = ["Consultor", "OS", "Média (dias úteis)", "Média (dias corridos)", "Mediana (dias corridos)", "Máximo (dias corridos)", "% no prazo"] + \
          [f"{MESES[m.month - 1]}/{str(m.year)[2:]} (dias úteis)" for m in meses]
    for j, c in enumerate(cab, 1):
        x = ws.cell(5, j, c)
        x.font, x.fill, x.alignment = CABF, CAB, Alignment(wrap_text=True, vertical="center")
    rg = lambda c: f"OS!${c}$2:${c}${n}"
    fmt = {3: "0.0", 4: "0.0", 5: "0.0", 6: "0", 7: "0%"}
    for i, c in enumerate(g.index, 6):
        vals = [c, f'=COUNTIF({rg("C")},A{i})', f'=AVERAGEIF({rg("C")},A{i},{rg("I")})', f'=AVERAGEIF({rg("C")},A{i},{rg("H")})', None,
                f'=_xlfn.MAXIFS({rg("H")},{rg("C")},A{i})', f'=COUNTIFS({rg("C")},A{i},{rg("I")},"<="&$B$3)/B{i}'] + \
               [f'=IFERROR(AVERAGEIFS({rg("I")},{rg("C")},$A{i},{rg("J")},{m.year * 100 + m.month}),"")' for m in meses]
        for j, v in enumerate(vals, 1):
            if v is not None:
                ws.cell(i, j, v)
        ws[f"E{i}"] = ArrayFormula(f"E{i}", f'=MEDIAN(IF({rg("C")}=A{i},{rg("H")}))')
        for j in range(1, len(cab) + 1):
            x = ws.cell(i, j)
            x.font, x.number_format = F, fmt.get(j, "0.0" if j > 7 else "General")
    t = 6 + len(g)
    vals = ["Unidade", f"=SUM(B6:B{t - 1})", f"=AVERAGE({rg('I')})", f"=AVERAGE({rg('H')})", f"=MEDIAN({rg('H')})", f"=MAX({rg('H')})",
            f'=COUNTIF({rg("I")},"<="&$B$3)/B{t}'] + [f'=IFERROR(AVERAGEIF({rg("J")},{m.year * 100 + m.month},{rg("I")}),"")' for m in meses]
    for j, v in enumerate(vals, 1):
        x = ws.cell(t, j, v)
        x.font, x.fill, x.number_format = FN, FUNDO, fmt.get(j, "0.0" if j > 7 else "General")
    ws.column_dimensions["A"].width = 26
    for j in range(2, len(cab) + 1):
        ws.column_dimensions[chr(64 + j)].width = 12
    ws.row_dimensions[5].height = 45
    ws.freeze_panes = "B6"
    wb.calculation.fullCalcOnLoad = True
    wb.save(caminho)
    return caminho


def gerar(linhas, campos, ini, fim, pasta, log=print):
    d, prazo, feriados = preparar(linhas, campos, log)
    if d.empty:
        return None, None, 0
    os.makedirs(pasta, exist_ok=True)
    base = os.path.join(pasta, f"Prazo de apontamento OS {ini:%d-%m-%Y} a {fim:%d-%m-%Y}")
    h = gerar_html(d, ini, fim, prazo, feriados, base + ".html")
    x = gerar_excel(d, ini, fim, prazo, feriados, base + ".xlsx")
    return h, x, len(d)

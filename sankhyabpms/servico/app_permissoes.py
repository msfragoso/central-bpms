# -*- coding: utf-8 -*-
"""
Permissões do ClickUp em lote (21/10/2026, autorizado pelo Fragoso): escolhe o
usuário, marca pastas e listas do espaço PMO BP-MS e o nível de acesso; a
Central aplica uma por uma, SEMPRE depois da confirmação na tela.

- Estrutura (pastas/listas) e usuários: API oficial, com o token do cofre.
- Ler e gravar o acesso: o mesmo caminho da tela do ClickUp (frontdoor
  /v3-user/access/...), pela sessão web do login assistido (clickup_sessao.py),
  porque a API oficial só faz isso no plano Enterprise.

Níveis confirmados no HAR do Fragoso: 1 = Ver, 5 = Edição total. Remoção ainda
não mapeada (precisa de um HAR removendo alguém).
"""
import json
import time
from datetime import datetime

from nucleo import GERENTE, ErroUsuario, dados_arquivo, exigir_confirmacao, marcar_uso, rota
from clickup_sessao import CLICKUP_WEB

NIVEIS = {1: "Ver", 5: "Edição total"}
PAPEIS = {1: "Proprietário", 2: "Administrador", 3: "Membro", 4: "Convidado"}
ARQ_LOG = "permissoes_clickup.jsonl"


def _cfg():
    from clickup_sync.config import SPACE_ID_PMO_BP_MS, CLICKUP_API, CLICKUP_HEADERS
    return SPACE_ID_PMO_BP_MS, CLICKUP_API, CLICKUP_HEADERS


def _workspace_e_membros():
    import requests
    _, api, cab = _cfg()
    t = requests.get(f"{api}/team", headers=cab, timeout=30).json()["teams"][0]
    membros = sorted(({"id": str(m["user"]["id"]), "nome": m["user"].get("username") or m["user"].get("email"),
                       "email": m["user"].get("email") or "", "papel": PAPEIS.get(m["user"].get("role"), "?")}
                      for m in t["members"] if m["user"].get("id") and m["user"]["id"] > 0),
                     key=lambda x: (x["nome"] or "").lower())
    return str(t["id"]), membros


@rota("POST", "/api/permissoes/conectar")
def conectar(req):
    CLICKUP_WEB.conectar()
    return 200, CLICKUP_WEB.status()


@rota("GET", "/api/permissoes/status")
def status(req):
    return 200, CLICKUP_WEB.status()


@rota("GET", "/api/permissoes/estrutura")
def estrutura(req):
    import requests
    space, api, cab = _cfg()
    workspace, membros = _workspace_e_membros()
    pastas = requests.get(f"{api}/space/{space}/folder?archived=false", headers=cab, timeout=60).json().get("folders", [])
    soltas = requests.get(f"{api}/space/{space}/list?archived=false", headers=cab, timeout=60).json().get("lists", [])
    # "pai": subpasta (ex.: Produtos BP-MS, Adm, MMS e Trading ficam dentro de 1-BP-MS).
    arvore = [{"id": str(f["id"]), "nome": f["name"],
               "pai": str((f.get("parent_folder") or {}).get("id") if isinstance(f.get("parent_folder"), dict)
                          else f.get("parent_folder") or ""),
               "listas": [{"id": str(l["id"]), "nome": l["name"]} for l in f.get("lists", [])]}
              for f in sorted(pastas, key=lambda x: x["name"].lower())]
    if soltas:
        arvore.append({"id": "", "nome": "(listas fora de pasta)",
                       "listas": [{"id": str(l["id"]), "nome": l["name"]} for l in soltas]})
    return 200, {"workspace": workspace, "membros": membros, "pastas": arvore,
                 "niveis": [{"valor": k, "rotulo": v} for k, v in NIVEIS.items()]}


def _acls(workspace, tipo, ids):
    """{id: {user_id: {nivel, herdado}}} lendo em lotes pelo frontdoor (só leitura)."""
    saida = {}
    for i in range(0, len(ids), 50):
        r = CLICKUP_WEB.chamar("POST", f"/v3-user/access/{workspace}/{tipo}/acls/bulk?include_parents=default&expand_groups=true",
                               {"ids": ids[i:i + 50]}, workspace_id=workspace)
        for a in r.get("acls", []):
            ent = (a.get("data") or {}).get("entries") or []
            saida[str(a.get("object_id"))] = {str(e.get("id")): {"nivel": e.get("permission_level"),
                                                                "herdado": e.get("from_parent_type")}
                                              for e in ent if e.get("kind") == "user"}
    return saida


@rota("POST", "/api/permissoes/acessos")
def acessos(req):
    """Nível atual do usuário em cada pasta/lista (só leitura)."""
    user = str(req.corpo.get("usuario") or "")
    pastas = [str(x) for x in req.corpo.get("pastas") or [] if x]
    listas = [str(x) for x in req.corpo.get("listas") or [] if x]
    workspace = str(req.corpo.get("workspace") or "")
    if not user or not workspace:
        raise ErroUsuario("Escolha o usuário.")
    ap, al = _acls(workspace, "folder", pastas), _acls(workspace, "list", listas)
    return 200, {"pastas": {k: v.get(user) for k, v in ap.items()}, "listas": {k: v.get(user) for k, v in al.items()}}


NOMES_EXIBICAO = {1: "Ver", 3: "Comentar", 4: "Editar", 5: "Edição total"}


def _html_relatorio(pastas, membros, ap, al, gerado_em):
    """PDF navegável: índice com links para cada pasta; em cada pasta, quem tem acesso e as listas."""
    from html import escape as e
    nomes = {m["id"]: m for m in membros}
    cor = lambda n: "#2e7d32" if n >= 5 else ("#e07b1a" if n == 1 else "#a15c00")

    def tabela(acl):
        linhas = []
        for uid, a in sorted((acl or {}).items(), key=lambda kv: (-(kv[1]["nivel"] or 0), (nomes.get(kv[0], {}).get("nome") or kv[0]).lower())):
            if uid.startswith("-") or uid not in nomes:
                continue  # grupos/ids internos do ClickUp
            m, n = nomes[uid], a["nivel"] or 0
            linhas.append(f"<tr><td>{e(m['nome'])}</td><td>{e(m['papel'])}</td>"
                          f"<td><span class='et' style='background:{cor(n)}'>{e(NOMES_EXIBICAO.get(n, f'nível {n}'))}</span></td>"
                          f"<td>{'herdado' + (' do espaço' if a.get('herdado') == 'space' else ' da pasta') if a.get('herdado') else 'direto'}</td></tr>")
        return ("<table><tr><th>Usuário</th><th>Papel</th><th>Nível</th><th>Origem</th></tr>" + "".join(linhas) + "</table>"
                if linhas else "<p class='vazio'>Ninguém com acesso direto (só quem herda do espaço).</p>")

    ids = {p["id"] for p in pastas}
    ordem = []

    def visitar(pai, nivel):
        for p in pastas:
            if (p.get("pai") or "") == pai or (not pai and p.get("pai") and p["pai"] not in ids):
                ordem.append((p, nivel))
                if p["id"]:
                    visitar(p["id"], nivel + 1)
    visitar("", 0)
    indice = "".join(f"<li style='margin-left:{n * 18}px'><a href='#p{e(p['id'] or 'soltas')}'>{e(p['nome'])}</a>"
                     f" <span class='cinza'>({len(p['listas'])} lista(s))</span></li>" for p, n in ordem)
    corpo = ""
    for p, n in ordem:
        aid = p["id"] or "soltas"
        listas = "".join(f"<div class='lista' id='l{e(l['id'])}'><h3>📄 {e(l['nome'])}</h3>{tabela(al.get(l['id']))}</div>"
                         for l in p["listas"])
        corpo += (f"<section class='pasta' id='p{e(aid)}'><h2>📁 {e(p['nome'])}</h2>"
                  f"<p class='cinza'><a href='#indice'>↑ voltar ao índice</a>"
                  + "".join(f" · <a href='#l{e(l['id'])}'>{e(l['nome'])}</a>" for l in p["listas"]) + "</p>"
                  f"{tabela(ap.get(p['id'])) if p['id'] else ''}{listas}</section>")
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Permissões ClickUp — PMO BP-MS</title>
<style>@page{{size:A4;margin:12mm}} body{{font-family:Segoe UI,Arial,sans-serif;color:#14211b;font-size:11px}}
h1{{color:#0a7a52;font-size:20px;margin:0}} h2{{color:#0a7a52;font-size:15px;margin:0 0 4px;border-bottom:2px solid #0a7a52}}
h3{{font-size:12px;margin:10px 0 4px}} a{{color:#0a7a52;text-decoration:none}} .cinza{{color:#5b6b63}} .vazio{{color:#5b6b63;font-style:italic}}
.pasta{{break-before:page}} .lista{{margin-left:14px}} table{{border-collapse:collapse;width:100%;margin-bottom:6px}}
th{{background:#e5f3ec;text-align:left;padding:4px 6px}} td{{border-bottom:1px solid #d7e0db;padding:3px 6px}}
.et{{color:#fff;border-radius:4px;padding:1px 6px;font-weight:600}} th,td,.et{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
ul{{list-style:none;padding:0;columns:2}} li{{margin:2px 0;break-inside:avoid}}</style></head><body>
<h1 id="indice">Permissões ClickUp — espaço PMO BP-MS</h1>
<p class="cinza">Gerado em {gerado_em} · clique numa pasta para ver quem tem acesso a ela e a cada lista · Verde = Edição total · Laranja = Ver</p>
<ul>{indice}</ul>{corpo}</body></html>"""


@rota("POST", "/api/permissoes/relatorio")
def relatorio(req):
    """PDF com as permissões de todas as pastas e listas (só leitura)."""
    import os
    workspace = str(req.corpo.get("workspace") or "")
    if not workspace:
        raise ErroUsuario("Abra a tela de novo (faltou o workspace).")

    def trabalho(t):
        _, d = estrutura(None)
        pastas = d["pastas"]
        t.log(f"Lendo as permissões de {len(pastas)} pasta(s) e {sum(len(p['listas']) for p in pastas)} lista(s) (só leitura)...")
        ap = _acls(workspace, "folder", [p["id"] for p in pastas if p["id"]])
        al = _acls(workspace, "list", [l["id"] for p in pastas for l in p["listas"]])
        agora = datetime.now()
        os.makedirs(dados_arquivo("relatorios"), exist_ok=True)
        base = os.path.join(dados_arquivo("relatorios"), f"Permissoes ClickUp {agora:%d-%m-%Y %Hh%M}")
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(_html_relatorio(pastas, d["membros"], ap, al, agora.strftime("%d/%m/%Y às %Hh%M")))
        t.adicionar_arquivo("Permissões (HTML)", base + ".html")
        from pdf_relatorio import html_para_pdf
        t.adicionar_arquivo("Permissões (PDF)", html_para_pdf(base + ".html"))
        return {"mensagem": "PDF das permissões gerado. Nada foi alterado no ClickUp."}

    t = GERENTE.iniciar("permissoes_relatorio", "Permissões ClickUp - relatório (só leitura)", trabalho)
    return 200, {"tarefa": t.id}


def _html_relatorio_usuario(pastas, membro, ap, al, gerado_em):
    """PDF de UM usuário: índice clicável das pastas e, em cada pasta, o nível dele na pasta e nas listas."""
    from html import escape as e
    uid = membro["id"]
    cor = lambda n: "#2e7d32" if n >= 5 else ("#e07b1a" if n == 1 else "#a15c00")

    def et(a, eh_lista=False):
        if not a or not a.get("nivel"):
            return "<span class='sem'>sem acesso</span>"
        n = a["nivel"]
        origem = ("só na lista" if eh_lista else "direto") if not a.get("herdado") else \
                 ("herdado do espaço" if a.get("herdado") == "space" else "herdado da pasta")
        return f"<span class='et' style='background:{cor(n)}'>{e(NOMES_EXIBICAO.get(n, f'nível {n}'))}</span> <span class='cinza'>{e(origem)}</span>"

    ids = {p["id"] for p in pastas}
    ordem = []

    def visitar(pai, nivel):
        for p in pastas:
            if (p.get("pai") or "") == pai or (not pai and p.get("pai") and p["pai"] not in ids):
                ordem.append((p, nivel))
                if p["id"]:
                    visitar(p["id"], nivel + 1)
    visitar("", 0)
    acesso = lambda p: (ap.get(p["id"]) or {}).get(uid) if p["id"] else None
    com_acesso = sum(1 for p, _ in ordem if acesso(p))
    indice = "".join(f"<tr><td style='padding-left:{6 + n * 16}px'><a href='#p{e(p['id'] or 'soltas')}'>{e(p['nome'])}</a></td>"
                     f"<td>{et(acesso(p)) if p['id'] else ''}</td>"
                     f"<td class='c'>{sum(1 for l in p['listas'] if (al.get(l['id']) or {}).get(uid))}/{len(p['listas'])}</td></tr>"
                     for p, n in ordem)
    corpo = ""
    for p, n in ordem:
        linhas = "".join(f"<tr><td>📄 {e(l['nome'])}</td><td>{et((al.get(l['id']) or {}).get(uid), True)}</td></tr>" for l in p["listas"])
        corpo += (f"<section id='p{e(p['id'] or 'soltas')}'><h2>📁 {e(p['nome'])} {et(acesso(p)) if p['id'] else ''}</h2>"
                  f"<p class='cinza'><a href='#indice'>↑ voltar ao índice</a></p>"
                  f"<table><tr><th>Lista</th><th>Acesso de {e(membro['nome'])}</th></tr>{linhas or '<tr><td colspan=2>sem listas</td></tr>'}</table></section>")
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Permissões — {e(membro['nome'])}</title>
<style>@page{{size:A4;margin:12mm}} body{{font-family:Segoe UI,Arial,sans-serif;color:#14211b;font-size:11px}}
h1{{color:#0a7a52;font-size:20px;margin:0}} h2{{color:#0a7a52;font-size:14px;margin:14px 0 2px;border-bottom:2px solid #0a7a52}}
a{{color:#0a7a52;text-decoration:none}} .cinza{{color:#5b6b63}} .sem{{color:#9aa5a0;font-style:italic}} .c{{text-align:center}}
table{{border-collapse:collapse;width:100%}} th{{background:#e5f3ec;text-align:left;padding:4px 6px}}
td{{border-bottom:1px solid #d7e0db;padding:3px 6px}} section{{break-inside:avoid}} tr{{break-inside:avoid}}
.et{{color:#fff;border-radius:4px;padding:1px 6px;font-weight:600}} th,td,.et{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.secao-indice{{break-after:page}}</style></head><body>
<div class="secao-indice"><h1 id="indice">Permissões ClickUp — {e(membro['nome'])}</h1>
<p class="cinza">{e(membro['papel'])}{' · ' + e(membro['email']) if membro.get('email') else ''} · espaço PMO BP-MS · gerado em {gerado_em}<br>
Acesso direto ou herdado em {com_acesso} de {sum(1 for p, _ in ordem if p['id'])} pasta(s) · clique numa pasta para ver as listas · Verde = Edição total · Laranja = Ver</p>
<table><tr><th>Pasta</th><th>Acesso na pasta</th><th class="c">Listas com acesso</th></tr>{indice}</table></div>
{corpo}</body></html>"""


@rota("POST", "/api/permissoes/relatorio-usuario")
def relatorio_usuario(req):
    """PDF das permissões de UM usuário em todas as pastas e listas (só leitura)."""
    import os
    workspace, uid = str(req.corpo.get("workspace") or ""), str(req.corpo.get("usuario") or "")
    if not workspace or not uid:
        raise ErroUsuario("Escolha o usuário.")

    def trabalho(t):
        _, d = estrutura(None)
        membro = next((m for m in d["membros"] if m["id"] == uid), None)
        if not membro:
            raise ErroUsuario("Usuário não encontrado no workspace.")
        pastas = d["pastas"]
        t.log(f"Lendo as permissões de {membro['nome']} em {len(pastas)} pasta(s) e "
              f"{sum(len(p['listas']) for p in pastas)} lista(s) (só leitura)...")
        ap = _acls(workspace, "folder", [p["id"] for p in pastas if p["id"]])
        al = _acls(workspace, "list", [l["id"] for p in pastas for l in p["listas"]])
        agora = datetime.now()
        os.makedirs(dados_arquivo("relatorios"), exist_ok=True)
        nome_arq = "".join(ch for ch in membro["nome"] if ch.isalnum() or ch in " -_").strip() or uid
        base = os.path.join(dados_arquivo("relatorios"), f"Permissoes ClickUp - {nome_arq} {agora:%d-%m-%Y %Hh%M}")
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(_html_relatorio_usuario(pastas, membro, ap, al, agora.strftime("%d/%m/%Y às %Hh%M")))
        t.adicionar_arquivo("Permissões do usuário (HTML)", base + ".html")
        from pdf_relatorio import html_para_pdf
        t.adicionar_arquivo("Permissões do usuário (PDF)", html_para_pdf(base + ".html"))
        return {"mensagem": f"PDF das permissões de {membro['nome']} gerado. Nada foi alterado no ClickUp."}

    t = GERENTE.iniciar("permissoes_relatorio", "Permissões ClickUp - relatório do usuário (só leitura)", trabalho)
    return 200, {"tarefa": t.id}


@rota("POST", "/api/permissoes/aplicar")
def aplicar(req):
    exigir_confirmacao(req)
    c = req.corpo
    user, workspace = str(c.get("usuario") or ""), str(c.get("workspace") or "")
    try:
        nivel = int(c.get("nivel"))
    except (TypeError, ValueError):
        nivel = 0
    if nivel not in NIVEIS:
        raise ErroUsuario("Nível de acesso inválido.")
    itens = [(i.get("tipo"), str(i.get("id")), i.get("nome") or "") for i in c.get("itens") or []
             if i.get("tipo") in ("folder", "list") and i.get("id")]
    if not user or not workspace or not itens:
        raise ErroUsuario("Escolha o usuário e marque pelo menos uma pasta ou lista.")
    nome_user = c.get("nome_usuario") or user

    def trabalho(t):
        ok = erros = 0
        situacao = {}
        for n, (tipo, oid, nome) in enumerate(itens, 1):
            rotulo = f"{'Pasta' if tipo == 'folder' else 'Lista'} {nome or oid}"
            try:
                r = CLICKUP_WEB.chamar("PATCH", f"/v3-user/access/{workspace}/{tipo}/{oid}/acls?include_parents=default&expand_groups=true",
                                       {"entries": [{"id": int(user), "kind": "user", "permission_level": nivel}]},
                                       workspace_id=workspace)
                ent = ((r.get("acls") or [{}])[0].get("data") or {}).get("entries") or []
                atual = next((e.get("permission_level") for e in ent if str(e.get("id")) == user), None)
                if atual == nivel:
                    ok += 1
                    situacao[f"{tipo}:{oid}"] = "OK"
                    t.log(f"  [{n}/{len(itens)}] {rotulo}: {NIVEIS[nivel]} ✓")
                    resultado = "ok"
                else:
                    erros += 1
                    situacao[f"{tipo}:{oid}"] = "CONFERIR"
                    t.log(f"  [{n}/{len(itens)}] {rotulo}: o ClickUp respondeu, mas o nível ficou {atual} -- conferir")
                    resultado = "conferir"
            except Exception as e:
                erros += 1
                situacao[f"{tipo}:{oid}"] = "FALHOU"
                resultado = f"falha: {e}"
                t.log(f"  [{n}/{len(itens)}] {rotulo}: FALHOU ({e})")
                if CLICKUP_WEB.estado != "conectado":
                    # Sem sessão não adianta seguir: para aqui e não tenta os demais.
                    t.log(f"  Parado: a sessão do ClickUp caiu. {len(itens) - n} item(ns) NÃO foram tentados. "
                          "Conecte de novo e aplique outra vez.")
                    with open(dados_arquivo(ARQ_LOG), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"quando": datetime.now().isoformat(timespec="seconds"), "usuario": user,
                                            "nome_usuario": nome_user, "tipo": tipo, "id": oid, "nome": nome,
                                            "nivel": nivel, "resultado": resultado}, ensure_ascii=False) + "\n")
                    break
            with open(dados_arquivo(ARQ_LOG), "a", encoding="utf-8") as f:
                f.write(json.dumps({"quando": datetime.now().isoformat(timespec="seconds"), "usuario": user,
                                    "nome_usuario": nome_user, "tipo": tipo, "id": oid, "nome": nome,
                                    "nivel": nivel, "resultado": resultado}, ensure_ascii=False) + "\n")
            time.sleep(0.3)
        t.adicionar_arquivo("Registro de permissões (.jsonl)", dados_arquivo(ARQ_LOG))
        marcar_uso("permissoes")
        return {"mensagem": f"{ok} acesso(s) aplicado(s) para {nome_user}, {erros} com problema.",
                "resultado": {"situacao": situacao}}

    t = GERENTE.iniciar("permissoes", f"Permissões ClickUp: {nome_user} ({len(itens)} item(ns))", trabalho)
    return 200, {"tarefa": t.id}

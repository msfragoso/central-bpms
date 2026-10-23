# -*- coding: utf-8 -*-
"""
Lançar tarefa no ClickUp -- mesma regra da tela_lancamento.py (Tkinter),
usando o motor clickup_tasks/lancar_tarefas_clickup.py sem alteração.
"""
import json
import os
from datetime import date

from nucleo import PASTAS, ErroUsuario, data_br, exigir_confirmacao, gravar_json_dados, ler_json_dados, marcar_uso, rota

ARQ_MEMORIA = "ultimo_lancamento.json"


def _motor():
    import lancar_tarefas_clickup as m  # importa credenciais (cofre do Windows) na 1ª vez
    return m


def _memoria():
    dados = ler_json_dados(ARQ_MEMORIA)
    if dados is None:
        # 1ª vez: aproveita o último lançamento da tela antiga
        try:
            with open(os.path.join(PASTAS["clickup_tasks"], "ultimo_lancamento.json"), encoding="utf-8") as f:
                dados = json.load(f)
        except (OSError, ValueError):
            dados = {}
    return dados


@rota("GET", "/api/lancar/opcoes")
def opcoes(req):
    m = _motor()
    return 200, {
        "parceiros": sorted(m.OPCOES_PARCEIRO.keys(), key=lambda s: m.remover_acentos(s).lower()),
        "origens": list(m.OPCOES_ORIGEM.keys()),
        "periodos": list(m.OPCOES_PERIODO.keys()),
        "membros": m.carregar_membros_cache(),
        "memoria": _memoria(),
    }


@rota("POST", "/api/lancar/membros")
def atualizar_membros(req):
    m = _motor()
    membros = m.listar_membros_workspace()
    m.salvar_membros_cache(membros)
    return 200, {"membros": membros}


@rota("GET", "/api/lancar/faps")
def faps(req):
    m = _motor()
    parceiro = req.query.get("parceiro", "")
    if parceiro not in m.OPCOES_PARCEIRO:
        raise ErroUsuario(f"O parceiro '{parceiro}' não é válido. Selecione um da lista.")
    lista = m.listar_faps_do_parceiro(parceiro, req.query.get("forcar") == "1")
    return 200, {"faps": lista}


@rota("GET", "/api/lancar/periodo")
def periodo(req):
    return 200, {"periodo": _motor().interpretar_periodo(req.query.get("texto", ""))}


PARCEIRO_HC = "X-Horas Cruzadas"
PARCEIRO_INTERNO = "X-Interno"
_cache_interno = {}


def _lista_interno():
    """Id da lista 'Particular' da pasta 'Adm' (subpasta de 1-BP-MS) do PMO BP-MS."""
    if "id" not in _cache_interno:
        from clickup_sync.config import SPACE_ID_PMO_BP_MS
        pastas = _cu_get(f"/space/{SPACE_ID_PMO_BP_MS}/folder?archived=false").get("folders", [])
        adm = next((f for f in pastas if f["name"].strip().lower() == "adm"), None)
        lista = next((l for l in (adm or {}).get("lists", []) if l["name"].strip().lower() == "particular"), None)
        if not lista:
            raise ErroUsuario("Não achei a lista 'Adm / Particular' no PMO BP-MS para o X-Interno.")
        _cache_interno["id"], _cache_interno["nome"] = str(lista["id"]), f"Adm / {lista['name']}"
    return _cache_interno["id"]


@rota("GET", "/api/lancar/interno")
def interno(req):
    _lista_interno()
    return 200, {"lista": _cache_interno["nome"]}


def _cu_get(caminho):
    import requests
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS
    r = requests.get(f"{CLICKUP_API}{caminho}", headers=CLICKUP_HEADERS, timeout=60)
    if r.status_code != 200:
        raise ErroUsuario(f"ClickUp respondeu HTTP {r.status_code} ao listar ({caminho.split('?')[0]}).")
    return r.json()


@rota("GET", "/api/lancar/hc/pastas")
def hc_pastas(req):
    """X-Horas Cruzadas: pastas (e subpastas) do PMO BP-MS com as listas abertas (sem 'Z' na frente)."""
    from clickup_sync.config import SPACE_ID_PMO_BP_MS
    pastas = _cu_get(f"/space/{SPACE_ID_PMO_BP_MS}/folder?archived=false").get("folders", [])
    saida = [{"id": str(f["id"]), "nome": f["name"],
              "listas": [{"id": str(l["id"]), "nome": l["name"]} for l in f.get("lists", [])
                         if not l["name"].strip().upper().startswith("Z")]}
             for f in sorted(pastas, key=lambda x: x["name"].lower())]
    padrao = next((p["id"] for p in saida if "horas cruzadas" in p["nome"].lower()), "")
    return 200, {"pastas": saida, "padrao": padrao}


@rota("GET", "/api/lancar/hc/tarefas")
def hc_tarefas(req):
    """Tarefas pai possíveis da lista (só as de 1º nível, abertas)."""
    lista = (req.query.get("lista") or "").strip()
    if not lista.isdigit():
        raise ErroUsuario("Lista inválida.")
    tarefas, pagina = [], 0
    while pagina < 10:
        lote = _cu_get(f"/list/{lista}/task?archived=false&subtasks=false&include_closed=false&page={pagina}").get("tasks", [])
        tarefas += [{"id": t["id"], "nome": t["name"], "status": (t.get("status") or {}).get("status", "")}
                    for t in lote if not t.get("parent")]
        if len(lote) < 100:
            break
        pagina += 1
    return 200, {"tarefas": sorted(tarefas, key=lambda t: t["nome"].lower())}


@rota("GET", "/api/lancar/hc/pais")
def hc_pais(req):
    """
    X-Horas Cruzadas (22/10/2026, ajuste do Fragoso): a tela mostra só as TAREFAS PAI
    (elas já têm o nome e o código do parceiro, ex.: "Tratalyx ... (83410)"), de todas as
    listas abertas da pasta "Horas Cruzadas". A lista sai da própria tarefa pai.
    """
    _, d = hc_pastas(req)
    pasta = next((p for p in d["pastas"] if p["id"] == d["padrao"]), None)
    if not pasta:
        raise ErroUsuario("Não achei a pasta 'Horas Cruzadas' no PMO BP-MS.")
    pais = []
    for l in pasta["listas"]:
        class _Q:  # reaproveita hc_tarefas
            query = {"lista": l["id"]}
        _, t = hc_tarefas(_Q())
        apelidos = ler_json_dados(ARQ_APELIDOS_HC) or {}
        pais += [{"id": x["id"], "nome": x["nome"].strip(), "status": x["status"],
                  "lista_id": l["id"], "lista": l["nome"],
                  "apelido": apelidos.get(x["id"]) or nome_curto_parceiro(x["nome"])} for x in t["tarefas"]]
    return 200, {"pasta": pasta["nome"], "pais": sorted(pais, key=lambda x: x["nome"].lower())}


ARQ_APELIDOS_HC = "hc_apelidos.json"  # {id da tarefa pai: nome curto do parceiro}
_PALAVRAS_RAZAO_SOCIAL = {"serv", "servicos", "servico", "comercio", "com", "ind", "industria", "ltda", "sa", "s/a",
                          "me", "epp", "eireli", "transportes", "transporte", "seguranca", "ambientais", "solucoes",
                          "franchising", "franquias", "de", "do", "da", "dos", "das", "e", "&", "-"}


def nome_curto_parceiro(nome_pai):
    """
    Nome curto do parceiro (23/10/2026): "Tratalyx Serv. Ambientais do brasil Ltda (83410)" -> "Tratalyx".
    Tira o código "(nnnn)" e o que vem depois, e corta na 1ª palavra de razão social
    (Serv., Comércio, Ind., Ltda, Transportes...). A tela deixa editar e guarda por tarefa pai.
    """
    import re
    import unicodedata
    m = re.match(r"^(.*?)\s*\(\d+\)", nome_pai or "")
    nome = re.sub(r"\s*\(.*?\)", "", (m.group(1) if m else (nome_pai or ""))).strip()
    palavras = nome.split()
    curto = []
    for p in palavras:
        chave = unicodedata.normalize("NFKD", p).encode("ascii", "ignore").decode().lower().strip(".,")
        if chave in _PALAVRAS_RAZAO_SOCIAL:
            break
        curto.append(p)
    return " ".join(curto) or (palavras[0] if palavras else "")


def titulo_hc(nome_lista, parceiro, titulo):
    """
    X-Horas Cruzadas (23/10/2026, pedido do Fragoso): o título sempre começa com
    "<lista> (<parceiro curto>) - ", ex.: "Filial DC (Tratalyx) - Ajuste na nota fiscal".
    Se o título já vier com o prefixo, não repete.
    """
    prefixo = f"{(nome_lista or '').strip()} ({(parceiro or '').strip()}) - "
    titulo = (titulo or "").strip()
    return titulo if titulo.lower().startswith(prefixo.lower()) else prefixo + titulo


LIMITE_ANEXOS = 25 * 1024 * 1024  # soma dos arquivos


def _ler_anexos(lista):
    """[{nome, conteudo_b64}] da página -> [(nome, bytes)] (21/10/2026: anexar arquivo na tarefa)."""
    import base64
    import re
    saida, total = [], 0
    for a in lista or []:
        nome = re.sub(r'[\\/:*?"<>|]', "_", os.path.basename(str(a.get("nome") or "arquivo")))[:150]
        try:
            dados = base64.b64decode(a.get("conteudo_b64") or "", validate=True)
        except ValueError:
            raise ErroUsuario(f"Anexo '{nome}' inválido. Selecione o arquivo de novo.")
        total += len(dados)
        if total > LIMITE_ANEXOS:
            raise ErroUsuario("Os anexos passam de 25 MB no total. Anexe os maiores direto no ClickUp.")
        if dados:
            saida.append((nome, dados))
    return saida


def _enviar_anexos(task_id, anexos):
    """Anexa os arquivos na tarefa (API oficial: POST /task/{id}/attachment). Devolve avisos."""
    import requests
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS
    ok, falhas = [], []
    for nome, dados in anexos:
        try:
            r = requests.post(f"{CLICKUP_API}/task/{task_id}/attachment",
                              headers={"Authorization": CLICKUP_HEADERS["Authorization"]},
                              files={"attachment": (nome, dados)}, timeout=120)
            if r.status_code in (200, 201):
                ok.append(nome)
            else:
                falhas.append(f"{nome} (HTTP {r.status_code})")
        except requests.RequestException as e:
            falhas.append(f"{nome} ({e})")
    avisos = []
    if ok:
        avisos.append(f"📎 {len(ok)} anexo(s) incluído(s): {', '.join(ok)}")
    if falhas:
        avisos.append(f"⚠ Anexo(s) que NÃO entraram (anexe à mão no ClickUp): {', '.join(falhas)}")
    return avisos


@rota("POST", "/api/lancar")
def lancar(req):
    exigir_confirmacao(req)
    m = _motor()
    c = req.corpo
    parceiro = (c.get("parceiro") or "").strip()
    origem = (c.get("origem") or "").strip()
    titulo = titulo_digitado = (c.get("titulo") or "").strip()
    usuario = (c.get("usuario") or "").strip()
    detalhamento = (c.get("detalhamento") or "").strip()

    if not parceiro or not origem or not titulo or not detalhamento or not usuario:
        raise ErroUsuario("Parceiro, Origem, Título, Usuário cliente e Detalhamento são obrigatórios!")
    anexos = _ler_anexos(c.get("anexos"))
    if parceiro not in m.OPCOES_PARCEIRO:
        raise ErroUsuario(f"O parceiro '{parceiro}' não é válido. Selecione um da lista!")
    if origem not in m.OPCOES_ORIGEM:
        raise ErroUsuario("Selecione uma origem válida da lista!")
    parent_id = None
    if parceiro == PARCEIRO_HC:
        # X-Horas Cruzadas (22/10/2026): pasta, lista e tarefa pai escolhidas na tela.
        list_id = str(c.get("hc_lista_id") or "").strip()
        parent_id = str(c.get("hc_pai_id") or "").strip() or None
        if not list_id or not parent_id:
            raise ErroUsuario("Para X-Horas Cruzadas, escolha a pasta, a lista e a tarefa pai.")
        pai = _cu_get(f"/task/{parent_id}")
        apelido = (c.get("hc_apelido") or "").strip() or nome_curto_parceiro(pai.get("name"))
        titulo = titulo_hc((pai.get("list") or {}).get("name"), apelido, titulo)
        apelidos = ler_json_dados(ARQ_APELIDOS_HC) or {}
        if apelidos.get(parent_id) != apelido:
            apelidos[parent_id] = apelido
            gravar_json_dados(ARQ_APELIDOS_HC, apelidos)
    elif parceiro == PARCEIRO_INTERNO:
        list_id = _lista_interno()   # Adm / Particular; o pai é o mês, resolvido abaixo
    else:
        list_id = str(c.get("fap_id") or "").strip()
    if not list_id:
        raise ErroUsuario("Selecione a FAP em que a demanda deve ser lançada.")

    responsavel_id = c.get("responsavel_id") or None
    data_venc = data_br(c["vencimento"], "Data de vencimento") if (c.get("vencimento") or "").strip() else None
    if parceiro == PARCEIRO_INTERNO:
        # X-Interno (22/10/2026): subtarefa do mês ("2026-10 Outubro"), que é tarefa de 1º
        # nível da lista Particular (sem "1-Atendimento Base"). Cria o mês se não existir.
        nome_mes = m.gerar_nome_mes_atual(data_venc if (data_venc and m.MES_PELA_DATA_VENCIMENTO) else None)
        parent_id = m.obter_ou_criar_subtarefa_mensal(list_id, None, nome_mes, m.OPCOES_PARCEIRO.get(parceiro))

    periodo = None
    if (c.get("periodo") or "").strip():
        periodo = m.interpretar_periodo(c["periodo"])
        if not periodo:
            raise ErroUsuario(f"Período '{c['periodo']}' não existe no ClickUp. Selecione uma opção da lista (ex.: 08h-10h).")
        if not data_venc:
            raise ErroUsuario("Período preenchido sem data. Informe a data de vencimento (dia do atendimento) ou apague o período.")

    avisos = []
    task_id = m.criar_demanda_padrao(
        titulo=titulo, detalhamento=detalhamento, parceiro=parceiro, usuario_cliente=usuario,
        origem=origem, responsavel_id=responsavel_id, data_vencimento=data_venc, periodo=periodo,
        list_id=list_id, avisos=avisos, parent_task_id=parent_id,
    )
    if anexos:
        avisos.extend(_enviar_anexos(task_id, anexos))
    gravar_json_dados(ARQ_MEMORIA, {"parceiro": parceiro, "origem": origem, "titulo": titulo_digitado,
                                    "usuario": usuario, "detalhamento": detalhamento})
    marcar_uso("lancar")
    return 200, {"task_id": task_id, "avisos": avisos, "periodo": periodo,
                 "vencimento": data_venc.strftime("%d/%m/%Y") if data_venc else None,
                 "no_passado": bool(data_venc and data_venc < date.today())}

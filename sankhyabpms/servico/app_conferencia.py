# -*- coding: utf-8 -*-
"""
Conferência de OS (conferencia_os/conferencia.py) -- mesmas etapas da tela Tk:
1) Sankhya (Excel enviado ou leitura direta do Experience), 2) CSV ClickUp,
3) cruzamento (pergunta de divergência vai para a página), 4) relatório HTML,
5) opcional: atualizar ClickUp. E a Borracha Mágica, à parte.
"""
import base64
import os
import re
import uuid
from datetime import datetime

from nucleo import (GERENTE, PASTAS, Cancelada, ErroUsuario, dados_arquivo, exigir_confirmacao,
                    marcar_uso, periodo_br, rota)

PASTA_UPLOADS = dados_arquivo("uploads")
PASTA_CLICKUP = dados_arquivo("clickup")


def _origem_api(corpo):
    """origem_clickup = "api" (buscar da visualização pela API) ou "csv" (arquivo enviado)."""
    return (corpo.get("origem_clickup") or "csv") == "api"


def _csv_da_api(t, ini, fim):
    """Gera dentro da tarefa o CSV da visualização 'Visão para IA' (ver clickup_visao.py)."""
    import clickup_visao
    nome = f"ClickUp_{ini:%Y%m%d}_a_{fim:%Y%m%d}_{datetime.now():%H%M%S}.csv"
    caminho, _ = clickup_visao.gerar_csv(os.path.join(PASTA_CLICKUP, nome), ini, fim, t.log)
    t.adicionar_arquivo("CSV do ClickUp (gerado pela API)", caminho)
    return caminho


@rota("POST", "/api/upload")
def upload(req):
    nome = os.path.basename(req.corpo.get("nome") or "arquivo")
    nome = re.sub(r"[^\w.\- ]", "_", nome)[:120]
    try:
        conteudo = base64.b64decode(req.corpo.get("conteudo_b64") or "", validate=True)
    except ValueError:
        raise ErroUsuario("Arquivo inválido.")
    if not conteudo:
        raise ErroUsuario("Arquivo vazio.")
    os.makedirs(PASTA_UPLOADS, exist_ok=True)
    arq_id = uuid.uuid4().hex[:10]
    with open(os.path.join(PASTA_UPLOADS, f"{arq_id}__{nome}"), "wb") as f:
        f.write(conteudo)
    return 200, {"id": arq_id, "nome": nome, "tamanho": len(conteudo)}


def _caminho_upload(arq_id, obrigatorio, rotulo):
    if not arq_id:
        if obrigatorio:
            raise ErroUsuario(f"Selecione o {rotulo}.")
        return ""
    if not re.fullmatch(r"[0-9a-f]{10}", str(arq_id)):
        raise ErroUsuario(f"{rotulo}: envio inválido, selecione o arquivo de novo.")
    for nome in os.listdir(PASTA_UPLOADS) if os.path.isdir(PASTA_UPLOADS) else []:
        if nome.startswith(f"{arq_id}__"):
            return os.path.join(PASTA_UPLOADS, nome)
    raise ErroUsuario(f"{rotulo}: arquivo não encontrado, selecione de novo.")


@rota("GET", "/api/conferencia/opcoes")
def opcoes(req):
    from config_conferencia import CAMINHO_DESTINO_PADRAO, CORES
    try:
        from dados_conferencia import SANKHYA_API_DISPONIVEL
    except Exception:
        SANKHYA_API_DISPONIVEL = False
    return 200, {"consultores": ["Todos"] + sorted(CORES.keys()), "destino": CAMINHO_DESTINO_PADRAO,
                 "sankhya_api": bool(SANKHYA_API_DISPONIVEL)}


def _tag_id_do_experience(t, om_df, ini, fim, caminho_cu=None):
    """
    As OS do OM não trazem a TAG ID ([ClickUp:id]) que o sync grava no lançamento
    do Experience. O vínculo (descoberto em 07/10/2026) é:
        Núm. OS -> OS no Experience (search_orders) -> sub-tarefa da OS
        (get_order_tasks; o "id" dela é o id do lançamento) -> lançamento
        (additional_information com [ClickUp:id]) -> TAG ID.
    Só leitura, e só nas FAPs que temos no Experience; o que ficar sem TAG ID
    (ex.: horas cruzadas de outras BPs) segue a Fase 2 (data, parceiro,
    consultor e horário).
    """
    import time
    import experience_api as exp
    from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
    from experience_api.orders import search_orders, get_order_tasks
    from experience_api.clickup_tags import extrair_tag_clickup
    from app_sync import _lancamentos_do_periodo

    t.log("TAG ID: buscando no Experience a TAG ID de cada OS (só leitura)...")
    token = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
    if not token:
        t.log("⚠ TAG ID: falha no login do Experience. Seguindo sem TAG ID.")
        return om_df
    om_df = om_df.copy()
    nums_om = om_df["Núm. OS"].astype(str).str.strip().str.replace(".0", "", regex=False)
    de, ate = ini.isoformat(), fim.isoformat()
    tags, sem_acesso = {}, []
    for fap in sorted({str(f).replace(".0", "") for f in om_df["Número Unico FAP"].dropna()}):
        try:
            impl = exp.find_implantation_by_fap(token, fap)
            if not impl:
                sem_acesso.append(fap)
                continue
            lanc_tag = {str(l.get("id")): extrair_tag_clickup(l.get("additional_information"))
                        for l in _lancamentos_do_periodo(token, impl["id"], de, ate)}
            for o in search_orders(token, [impl["id"]], de, ate, integrated="S") or []:
                num = str(o.get("numos_sankhya") or "")
                if not num or num not in set(nums_om):
                    continue
                for st in get_order_tasks(token, o.get("id") or o.get("order_id")) or []:
                    tag = lanc_tag.get(str(st.get("id")))
                    if tag:
                        tags.setdefault(num, tag)
                        break
                time.sleep(0.1)
        except Exception as e:  # uma FAP com problema não derruba a conferência
            t.log(f"  ⚠ TAG ID: FAP {fap}: {e}")
    vazia = om_df["Tag ClickUp"].isna() | om_df["Tag ClickUp"].astype(str).str.strip().isin(["", "None", "nan"])
    novas = nums_om.map(tags)
    om_df.loc[vazia & novas.notna(), "Tag ClickUp"] = novas[vazia & novas.notna()]
    t.log(f"TAG ID: {int(novas.notna().sum())} de {len(om_df)} OS do OM vinculadas pela TAG ID do Experience"
          + (f"; FAP(s) fora do Experience (horas cruzadas): {', '.join(sem_acesso)}" if sem_acesso else "")
          + ". As demais seguem pela comparação de data, parceiro, consultor e horário.")
    return om_df


def _travadas_do_experience(t, om_df, ini, fim, caminho_cu=None):
    """
    Pedido do Fragoso (14/10/2026): depois da busca no OM, cruza também os
    apontamentos TRAVADOS no Experience (lançados, mas sem OS gerada: "Pendente de
    Liberação pelo GP"). O OM não mostra essas OS, então sem isso elas viravam
    "Sem apontamento no Sankhya". Aqui elas entram na base com o mesmo formato da
    origem Experience (Núm. OS = "Pendente de Liberação pelo GP (Cód: id)") e o
    cruzamento já trata como "Aguardando aprovação do GP". Só leitura.
    """
    import re as _re
    import time
    import pandas as pd
    import experience_api as exp
    from credenciais import EXPERIENCE_USER, EXPERIENCE_PASS
    from experience_api.orders import search_orders, get_order_tasks, extrair_solucao
    from experience_api.clickup_tags import extrair_tag_clickup
    from clickup_sync.config import PARCEIRO_FAP
    from dados_conferencia import eh_pessoa_excluida_sankhya

    t.log("Travadas: buscando no Experience os apontamentos travados (sem OS) do período (só leitura)...")
    token = exp.login(EXPERIENCE_USER, EXPERIENCE_PASS)
    if not token:
        t.log("⚠ Travadas: falha no login do Experience. Seguindo só com o OM.")
        return om_df
    faps = {str(f).replace(".0", "") for f in om_df["Número Unico FAP"].dropna()}
    for v in PARCEIRO_FAP.values():
        faps.update(str(f) for f in (v if isinstance(v, list) else [v]))
    if caminho_cu:
        try:
            cu = pd.read_csv(caminho_cu)
            for col in ("List", "Parceiro (drop down)"):
                for val in cu.get(col, pd.Series(dtype=str)).dropna().unique():
                    m = _re.search(r"\b(\d{4,6})\b", str(val))
                    if m:
                        faps.add(m.group(1))
        except Exception:
            pass
    impl_fap = {}
    for fap in sorted(faps):
        try:
            impl = exp.find_implantation_by_fap(token, fap)
            if impl:
                impl_fap[impl["id"]] = fap
        except Exception:
            continue
    if not impl_fap:
        return om_df
    try:
        travadas = search_orders(token, list(impl_fap), ini.isoformat(), fim.isoformat(), integrated="") or []
    except Exception as e:
        t.log(f"⚠ Travadas: falha na busca ({e}). Seguindo só com o OM.")
        return om_df
    nums_om = set(om_df["Núm. OS"].astype(str).str.replace(".0", "", regex=False))
    linhas = []
    for o in travadas:
        if o.get("numos_sankhya") and str(o["numos_sankhya"]) in nums_om:
            continue  # já virou OS e está no OM
        if eh_pessoa_excluida_sankhya(o.get("person_name")):
            continue
        oid = o.get("id") or o.get("order_id")
        tarefas = get_order_tasks(token, oid) or []
        st = tarefas[0] if tarefas else {}
        info = st.get("additional_information")
        linhas.append({
            "Dt execução": st.get("date_done") or o.get("order_done_date") or o.get("date_done"),
            "Núm. OS": f"Pendente de Liberação pelo GP (Cód: {oid})",
            "Sub-OS": 1, "Nome (Executante)": o.get("person_name"),
            "Número Unico FAP": impl_fap.get(o.get("implantation_id")) or o.get("fap"),
            "Nome Parceiro (Parceiro)": o.get("company_name"), "Cód. Parceiro": None,
            "Tempo gasto": st.get("worked_hours") or o.get("diff_time"),
            "Hora Inicial": st.get("hour_to_start") or "00:00", "Hora Final": st.get("hour_to_finish") or "00:00",
            "Intervalo": st.get("hour_to_lunch") or "00:00", "Nro.único do pedido": o.get("application_code"),
            "Solução": extrair_solucao(info) if info else "", "Tag ClickUp": extrair_tag_clickup(info) if info else None,
        })
        time.sleep(0.1)
    t.log(f"Travadas: {len(linhas)} apontamento(s) travado(s) no Experience entram no cruzamento "
          "como \"Aguardando aprovação do GP\".")
    if not linhas:
        return om_df
    novo = pd.DataFrame(linhas)
    if "Dt execução" in om_df.columns and pd.api.types.is_datetime64_any_dtype(om_df["Dt execução"]):
        novo["Dt execução"] = pd.to_datetime(novo["Dt execução"], format="%d/%m/%Y", errors="coerce")
    return pd.concat([om_df, novo], ignore_index=True)


# ============================================================================
# WHATSAPP DOS CONSULTORES (08/10/2026, opção 1: link wa.me, envio pelo usuário)
# ============================================================================
# A Central só monta o texto e o link; quem aperta "Enviar" é o Fragoso, no
# próprio WhatsApp dele. Os celulares ficam em dados/contatos_consultores.json
# ({"GUILHERME": {"nome": "...", "celular": "5567999999999"}, ...}).
ARQ_CONTATOS = "contatos_consultores.json"


def _contatos():
    from nucleo import ler_json_dados
    return ler_json_dados(ARQ_CONTATOS, {}) or {}


def _so_digitos_celular(txt):
    d = re.sub(r"\D", "", str(txt or ""))
    if not d:
        return ""
    if len(d) in (10, 11):      # DDD + número, sem o 55
        d = "55" + d
    if not (12 <= len(d) <= 13 and d.startswith("55")):
        raise ErroUsuario(f"Celular inválido: {txt}. Use DDD + número, ex.: (67) 99999-9999.")
    return d


@rota("GET", "/api/conferencia/contatos")
def contatos(req):
    from config_conferencia import CORES, CONSULTOR_MAP
    salvos = _contatos()
    nomes = {}
    for nome, chave in CONSULTOR_MAP.items():
        if chave in CORES and nome.isupper() and len(nome) > len(nomes.get(chave, "")):
            nomes[chave] = nome.title()
    lista = [{"consultor": c, "nome": (salvos.get(c) or {}).get("nome") or nomes.get(c, c.title()),
              "celular": (salvos.get(c) or {}).get("celular", "")} for c in sorted(CORES)]
    return 200, {"contatos": lista}


@rota("POST", "/api/conferencia/contatos")
def salvar_contatos(req):
    import json
    from config_conferencia import CORES
    novos = {}
    for item in req.corpo.get("contatos") or []:
        c = str(item.get("consultor") or "").strip().upper()
        if c not in CORES:
            continue
        novos[c] = {"nome": str(item.get("nome") or "").strip()[:80], "celular": _so_digitos_celular(item.get("celular"))}
    with open(dados_arquivo(ARQ_CONTATOS), "w", encoding="utf-8") as f:
        json.dump(novos, f, ensure_ascii=False, indent=2)
    return 200, {"ok": True, "gravados": sum(1 for v in novos.values() if v["celular"])}


def _mensagens_whatsapp(mensagens, periodo_texto):
    """Um texto por consultor com as mesmas pendências do cartão do relatório."""
    salvos = _contatos()
    saida = []
    for m in mensagens:
        if not m["linhas"]:
            continue
        contato = salvos.get(m["consultor"]) or {}
        nome = contato.get("nome") or m["nome"]
        primeiro = (nome.split() or [nome])[0].title()
        pend = [l for l in m["linhas"] if not l["aguardando_gp"]]
        gp = [l for l in m["linhas"] if l["aguardando_gp"]]
        # Texto aprovado pelo Fragoso (09/10/2026). O WhatsApp não tem cor: *texto* é
        # negrito; o vermelho/verde vira 🔴/🟢 na frente.
        partes = [f"Olá, {primeiro}! Tudo bem?", "",
                  f"Na conferência no período de *{periodo_texto}, realizada em "
                  f"{datetime.now():%d/%m/%Y às %Hh%M}*, ficaram estes apontamentos pendentes. "
                  "Por gentileza, peço que verifique:"]
        if pend:
            partes += ["", "*Sem apontamento de OS no Sankhya:*"]
            for l in pend:
                atraso = f" 🔴 *⚠️ {l['dias']} dias*" if l["dias"] >= 2 else " 🔵"  # 🔵 = ainda dentro do prazo (09/10/2026)
                partes.append(f"• {l['data']} · {l['periodo']} · {l['parceiro']}{atraso}")
        if gp:
            partes += ["", "🟢 *Aguardando aprovação do GP (somente para informação):*"]
            for l in gp:
                partes.append(f"• {l['data']} · {l['periodo']} · {l['parceiro']}" + (f" ({l['os']})" if l["os"] else ""))
        total = len(m["linhas"])
        # Links das tarefas do ClickUp no fim (pedido do Fragoso, 13/10/2026).
        partes += ["", f"Total: {total} tarefa{'s' if total != 1 else ''}.", "",
                   "Se precisar de apoio, estou à disposição! 👍", "Obrigado!"]
        links = [l for l in m["linhas"] if l.get("task_id") and not l["aguardando_gp"]]  # sem link para as que aguardam o GP (13/10/2026)
        if links:
            partes += ["", "🔗 *Tarefas no ClickUp:*"]
            for l in links:
                partes.append(f"• {l['data']} · {l['parceiro']}: app.clickup.com/t/{l['task_id']}")  # sem https:// (mais curto; o WhatsApp ainda vira link)
        saida.append({"consultor": m["consultor"], "nome": nome, "celular": contato.get("celular", ""),
                      "total": len(m["linhas"]), "texto": "\n".join(partes)})
    return saida


def _oferecer_recriar_tarefas_excluidas(t, resultado):
    """
    28/10/2026 (Fragoso): OS do Sankhya cuja tarefa do ClickUp (TAG ID) foi excluída -- pergunta se
    pode criar uma tarefa nova e vincular a OS (ver conferencia_os/tarefa_excluida.py). As que forem
    vinculadas saem da seção "OS no Sankhya sem tarefa correspondente" do relatório.
    """
    from clickup_sync.config import CLICKUP_HEADERS
    import tarefa_excluida as te
    sobras = resultado.sobras
    if sobras is None or sobras.empty or "Tag ClickUp" not in sobras.columns:
        return
    headers = dict(CLICKUP_HEADERS, **{"Content-Type": "application/json"})
    vinculadas = []
    for idx in te.tarefas_excluidas(sobras, headers, t.log):
        row = sobras.loc[idx]
        num_os = str(row["Núm. OS"]).replace(".0", "")
        data = row["Dt execução"].strftime("%d/%m/%Y") if hasattr(row["Dt execução"], "strftime") else str(row["Dt execução"])
        resp = t.perguntar(
            "Tarefa excluída do ClickUp",
            f"A OS {num_os} ({row.get('Nome (Executante)')}, {row.get('Nome Parceiro (Parceiro)')}, {data}, "
            f"{row.get('Hora Inicial')}-{row.get('Hora Final')}) está vinculada à tarefa {row.get('Tag ClickUp')}, "
            "que foi EXCLUÍDA do ClickUp.\n\nPosso criar uma tarefa nova e vincular essa OS a ela "
            "(status complete, OS Sankhya, X-Observações OS e tempo apontado)?",
            [{"valor": True, "rotulo": "Sim, criar e vincular", "estilo": "primario"},
             {"valor": False, "rotulo": "Não", "estilo": "neutro"}])
        if not resp:
            t.log(f"  OS {num_os}: nova tarefa NÃO criada (você escolheu Não).")
            continue
        try:
            nova, url, lista, parceiro = te.recriar_e_vincular(row, headers, t.log)
            t.log(f"  ✔ OS {num_os}: tarefa nova {nova} criada em '{lista}' (parceiro {parceiro}) e vinculada -- {url}")
            vinculadas.append(idx)
        except Exception as e:
            t.log(f"  ❌ OS {num_os}: não consegui criar a tarefa nova ({e}).")
    if vinculadas:
        resultado.sobras = sobras.drop(index=vinculadas)


def _tirar_sobras_ja_gravadas_no_clickup(t, resultado):
    """
    28/10/2026 (Fragoso, caso CM Gestão OS 7186961 / tarefa 17twj8w1rk5): a OS pode já estar gravada no
    campo "OS Sankhya" de uma tarefa que fica FORA da visualização "Visão para IA" (ex.: Apontamento
    "Sankhya OM", X-Horas Cruzadas). Antes de listar a OS como "sem tarefa correspondente", procura o
    número no ClickUp inteiro (filtro pelo campo OS Sankhya). Só leitura.
    """
    import json as _json
    import requests
    from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS
    from config_conferencia import ID_CAMPO_OS
    sobras = resultado.sobras
    if sobras is None or sobras.empty:
        return
    team = "9013912851"
    achadas = []
    for idx, row in sobras.iterrows():
        num = str(row.get("Núm. OS") or "").replace(".0", "").strip()
        if not num.isdigit():
            continue
        try:
            r = requests.get(f"{CLICKUP_API}/team/{team}/task", headers=CLICKUP_HEADERS, timeout=60, params={
                "custom_fields": _json.dumps([{"field_id": ID_CAMPO_OS, "operator": "=", "value": num}]),
                "include_closed": "true", "subtasks": "true"})
            tarefas = r.json().get("tasks", []) if r.status_code == 200 else []
        except Exception:
            tarefas = []
        if tarefas:
            achadas.append(idx)
            t.log(f"  OS {num}: já gravada na tarefa {tarefas[0]['id']} ({tarefas[0].get('name', '')[:40]}) -- "
                  "fora da visualização da conferência; não entra como 'sem tarefa'.")
    if achadas:
        resultado.sobras = sobras.drop(index=achadas)
        t.log(f"{len(achadas)} OS já estavam vinculadas a tarefas fora da visualização (campo OS Sankhya).")


@rota("POST", "/api/conferencia/executar")
def executar(req):
    from config_conferencia import CAMINHO_DESTINO_PADRAO
    c = req.corpo
    ini, fim = periodo_br(c.get("de"), c.get("ate"))
    origem_sankhya = c.get("origem_sankhya") or ("excel" if c.get("sankhya_id") else "experience")
    if origem_sankhya not in ("om", "experience", "excel"):
        raise ErroUsuario("Origem das OS inválida.")
    sankhya_path = _caminho_upload(c.get("sankhya_id"), True, "Excel do Sankhya") if origem_sankhya == "excel" else ""
    if origem_sankhya == "om":
        from om_sessao import OM
        if OM.estado != "conectado":
            raise ErroUsuario("Conecte ao Sankhya-OM antes (botão 'Conectar ao Sankhya-OM') e faça o login na janela que abrir.")
    pela_api = _origem_api(c)
    clickup_path = None if pela_api else _caminho_upload(c.get("clickup_id"), True, "CSV do ClickUp")
    destino = (c.get("destino") or "").strip() or CAMINHO_DESTINO_PADRAO
    atualizar = bool(c.get("atualizar_clickup"))
    if atualizar:
        exigir_confirmacao(req)
    consultor = c.get("consultor") or "Todos"
    usar_tag_id = origem_sankhya == "om" and c.get("usar_tag_id", True) is not False

    def trabalho(t):
        from dados_conferencia import exportar_dados, carregar_sankhya_de_arquivo, carregar_clickup_de_arquivo
        from motor_conferencia import cruzar_bases, OperacaoCanceladaPeloUsuario
        from html_conferencia import gerar_html
        from clickup_conferencia import get_clickup_token, atualizar_clickup

        def perguntar_divergencia(consultor_, parceiro, data, tarefa_nome, periodo_cu, horario_sk):
            return t.perguntar(
                "Divergência de período",
                f"Consultor: {consultor_}\nParceiro: {parceiro}\nData: {data}\nTarefa: {tarefa_nome}\n\n"
                f"Período ClickUp: {periodo_cu}\nHorário Sankhya: {horario_sk}",
                [{"valor": True, "rotulo": "Manter vínculo", "estilo": "primario"},
                 {"valor": False, "rotulo": "Desfazer vínculo", "estilo": "neutro"},
                 {"valor": None, "rotulo": "Interromper", "estilo": "perigo"}])

        try:
            caminho_cu = _csv_da_api(t, ini, fim) if pela_api else clickup_path
            print("=== ETAPA 1: dados do Sankhya ===")
            if origem_sankhya == "om":
                import app_om
                sankhya_df, _ = app_om.buscar_os(ini, fim, t.log)
                if usar_tag_id:
                    sankhya_df = _tag_id_do_experience(t, sankhya_df, ini, fim, caminho_cu)
                sankhya_df = _travadas_do_experience(t, sankhya_df, ini, fim, caminho_cu)
                copia = os.path.join(PASTA_CLICKUP, f"OS_SankhyaOM_{ini:%Y%m%d}_a_{fim:%Y%m%d}_{datetime.now():%H%M%S}.xlsx")
                sankhya_df.to_excel(copia, index=False)
                t.adicionar_arquivo("OS do Sankhya-OM (.xlsx)", copia)
            elif sankhya_path:
                sankhya_df = carregar_sankhya_de_arquivo(sankhya_path)
            else:
                sankhya_df, xlsx = exportar_dados(ini.isoformat(), fim.isoformat(), caminho_cu)
                t.adicionar_arquivo("Planilha Sankhya (.xlsx)", xlsx)
            periodo_texto = f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}"

            print("\n=== ETAPA 2: dados do ClickUp ===")
            cu_df = carregar_clickup_de_arquivo(caminho_cu)

            print("\n=== ETAPA 3: cruzamento ===")
            resultado = cruzar_bases(sankhya_df, cu_df, callback_divergencia=perguntar_divergencia,
                                     consultor_alvo=consultor)
            # primeiro tira as OS já gravadas em alguma tarefa (ex.: Megatrucks, já recriada), depois
            # pergunta só pelas que ainda apontam para tarefa excluída
            _tirar_sobras_ja_gravadas_no_clickup(t, resultado)
            _oferecer_recriar_tarefas_excluidas(t, resultado)

            print("\n=== ETAPA 4: relatório HTML ===")
            fonte_os = {"om": "Sankhya-OM" + (" (com TAG ID do Experience)" if usar_tag_id else ""),
                        "experience": "Sankhya Experience",
                        "excel": "Excel exportado do Sankhya"}.get(origem_sankhya)
            mensagens = []
            caminho_html = gerar_html(resultado, periodo_texto, destino, fonte_os=fonte_os, mensagens=mensagens)
            whatsapp = _mensagens_whatsapp(mensagens, periodo_texto)
            t.adicionar_arquivo("Relatório da conferência (HTML)", caminho_html)

            if atualizar:
                print("\n=== ETAPA 5: atualizando ClickUp ===")
                headers = {"Authorization": get_clickup_token(), "Content-Type": "application/json"}
                qtd, erros = atualizar_clickup(resultado, resultado.sankhya_df, headers)
                if erros:
                    t.adicionar_arquivo("Erros do ClickUp (.json)", "erros_clickup.json")
                msg = f"Relatório gerado. {qtd} tarefa(s) atualizada(s) no ClickUp, {len(erros)} erro(s)."
            else:
                print("\nCaixa 'Atualizar ClickUp' desmarcada.")
                msg = "Relatório gerado (nada foi alterado no ClickUp)."
            print("\n=== CONCLUÍDO ===")
            marcar_uso("conferencia")
            return {"mensagem": msg, "resultado": {"whatsapp": whatsapp}}
        except OperacaoCanceladaPeloUsuario as e:
            raise Cancelada(str(e))

    t = GERENTE.iniciar("conferencia", "Conferência de OS", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/conferencia/borracha")
def borracha(req):
    exigir_confirmacao(req)
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    pela_api = _origem_api(req.corpo)
    clickup_path = None if pela_api else _caminho_upload(req.corpo.get("clickup_id"), True, "CSV do ClickUp")

    def trabalho(t):
        from clickup_conferencia import get_clickup_token, executar_borracha_magica
        get_clickup_token()
        caminho_cu = _csv_da_api(t, ini, fim) if pela_api else clickup_path
        qtd = executar_borracha_magica(caminho_cu, ini.isoformat(), fim.isoformat())
        marcar_uso("conferencia")
        return {"mensagem": f"Borracha concluída! {qtd} tarefa(s) foram limpas."}

    t = GERENTE.iniciar("borracha", "Borracha Mágica (ClickUp)", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/conferencia/pdf")
def gerar_pdf(req):
    """Gera o PDF do relatório HTML de uma conferência já concluída (não altera nada)."""
    from nucleo import GERENTE
    from pdf_relatorio import html_para_pdf
    t = GERENTE.obter(str(req.corpo.get("tarefa") or ""))
    if not t or t.tipo != "conferencia":
        raise ErroUsuario("Conferência não encontrada. Rode a conferência de novo.")
    if t.estado not in ("concluida", "cancelada", "erro"):
        raise ErroUsuario("Espere a conferência terminar.")
    htmls = [c for _, c in t.arquivos if c.lower().endswith((".html", ".htm"))]
    if not htmls:
        raise ErroUsuario("Esta conferência não gerou relatório HTML.")
    pdf = os.path.splitext(htmls[-1])[0] + ".pdf"
    if not any(c == pdf for _, c in t.arquivos):
        pdf = html_para_pdf(htmls[-1])
        t.adicionar_arquivo("Relatório da conferência (PDF)", pdf)
    indice = next(i for i, (_, c) in enumerate(t.arquivos) if c == pdf)
    return 200, {"indice": indice, "nome": os.path.basename(pdf), "tarefa": t.id}


# Fila de avisos no WhatsApp: a página registra quando abriu a conversa de cada
# consultor (quem aperta Enviar é o Fragoso). Fica em dados/whatsapp_avisos.jsonl.
ARQ_AVISOS = "whatsapp_avisos.jsonl"


@rota("POST", "/api/conferencia/whatsapp-avisado")
def whatsapp_avisado(req):
    import json
    tarefa = str(req.corpo.get("tarefa") or "")[:40]
    consultor = str(req.corpo.get("consultor") or "")[:40]
    if not tarefa or not consultor:
        raise ErroUsuario("Faltou a conferência ou o consultor.")
    # desfazer=True: tira a marca (ex.: o WhatsApp não abriu); a linha fica no log.
    quando = None if req.corpo.get("desfazer") else datetime.now().strftime("%d/%m/%Y %H:%M")
    with open(dados_arquivo(ARQ_AVISOS), "a", encoding="utf-8") as f:
        f.write(json.dumps({"tarefa": tarefa, "consultor": consultor, "quando": quando,
                            "celular": str(req.corpo.get("celular") or "")[:20]}, ensure_ascii=False) + "\n")
    return 200, {"quando": quando}


@rota("GET", "/api/conferencia/whatsapp-avisos")
def whatsapp_avisos(req):
    import json
    tarefa = req.query.get("tarefa") or ""
    avisos = {}
    try:
        with open(dados_arquivo(ARQ_AVISOS), encoding="utf-8") as f:
            for linha in f:
                try:
                    a = json.loads(linha)
                except ValueError:
                    continue
                if a.get("tarefa") == tarefa:
                    if a.get("quando"):
                        avisos[a["consultor"]] = a["quando"]
                    else:
                        avisos.pop(a["consultor"], None)
    except OSError:
        pass
    return 200, {"avisos": avisos}

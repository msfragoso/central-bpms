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

from nucleo import (GERENTE, PASTAS, Cancelada, ErroUsuario, dados_arquivo, exigir_confirmacao,
                    marcar_uso, periodo_br, rota)

PASTA_UPLOADS = dados_arquivo("uploads")


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


@rota("POST", "/api/conferencia/executar")
def executar(req):
    from config_conferencia import CAMINHO_DESTINO_PADRAO
    c = req.corpo
    ini, fim = periodo_br(c.get("de"), c.get("ate"))
    sankhya_path = _caminho_upload(c.get("sankhya_id"), False, "Excel do Sankhya")
    clickup_path = _caminho_upload(c.get("clickup_id"), True, "CSV do ClickUp")
    destino = (c.get("destino") or "").strip() or CAMINHO_DESTINO_PADRAO
    atualizar = bool(c.get("atualizar_clickup"))
    if atualizar:
        exigir_confirmacao(req)
    consultor = c.get("consultor") or "Todos"

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
            print("=== ETAPA 1: dados do Sankhya ===")
            if sankhya_path:
                sankhya_df = carregar_sankhya_de_arquivo(sankhya_path)
            else:
                sankhya_df, xlsx = exportar_dados(ini.isoformat(), fim.isoformat(), clickup_path)
                t.adicionar_arquivo("Planilha Sankhya (.xlsx)", xlsx)
            periodo_texto = f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}"

            print("\n=== ETAPA 2: dados do ClickUp ===")
            cu_df = carregar_clickup_de_arquivo(clickup_path)

            print("\n=== ETAPA 3: cruzamento ===")
            resultado = cruzar_bases(sankhya_df, cu_df, callback_divergencia=perguntar_divergencia,
                                     consultor_alvo=consultor)

            print("\n=== ETAPA 4: relatório HTML ===")
            caminho_html = gerar_html(resultado, periodo_texto, destino)
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
            return {"mensagem": msg}
        except OperacaoCanceladaPeloUsuario as e:
            raise Cancelada(str(e))

    t = GERENTE.iniciar("conferencia", "Conferência de OS", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/conferencia/borracha")
def borracha(req):
    exigir_confirmacao(req)
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))
    clickup_path = _caminho_upload(req.corpo.get("clickup_id"), True, "CSV do ClickUp")

    def trabalho(t):
        from clickup_conferencia import get_clickup_token, executar_borracha_magica
        get_clickup_token()
        qtd = executar_borracha_magica(clickup_path, ini.isoformat(), fim.isoformat())
        marcar_uso("conferencia")
        return {"mensagem": f"Borracha concluída! {qtd} tarefa(s) foram limpas."}

    t = GERENTE.iniciar("borracha", "Borracha Mágica (ClickUp)", trabalho, pasta=PASTAS["conferencia"])
    return 200, {"tarefa": t.id}

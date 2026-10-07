# -*- coding: utf-8 -*-
"""
Agenda semanal dos parceiros ("Confirmação da Agenda de Serviço") pela Central,
com as mesmas regras da skill agenda-semanal-parceiros:

1. Tarefas da visualização "Agrupado p/Enviar" do ClickUp (lida pela API com os
   filtros da própria visualização; só o período "próxima semana" vem da tela).
2. Regras: Agenda "Planejamento" fora; tarefas de Filipe Capulo / Elson Duarte
   fora; parceiro que fica sem tarefa sai da lista; X-Horas Cruzadas, X-Interno
   e Energe vêm desmarcados.
3. Contatos da planilha "Contatos(e-mails) dos Parceiros para Envio de Agenda"
   (1º e-mail = Para, demais = Cc), editáveis na tela antes do envio.
4. Layout aprovado (agenda_layout.py, copiado da skill).
5. Envio pelo Gmail (SMTP) com a senha de app do cofre do Windows: teste só para
   o próprio remetente; envio real só dos parceiros marcados, com confirmação.
"""
import configparser
import json
import re
import smtplib
import time
import unicodedata
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from nucleo import CONFIG, GERENTE, PASTAS, ErroUsuario, dados_arquivo, exigir_confirmacao, marcar_uso, periodo_br, rota

VIEW_AGENDA = CONFIG.get("agenda_view_id") or "8cmat8k-3873"   # "Agrupado p/Enviar"
PLANILHA_CONTATOS = CONFIG.get("agenda_planilha_contatos") or \
    r"G:\Meu Drive\PROJETOS\Contatos(e-mails) dos Parceiros para Envio de Agenda.xlsx"
SMTP_INI = r"agenda envio email\smtp_config.ini"
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 587
FIELD_PARCEIRO = "d993c20b-a9b6-4fd4-bedc-c03b77e15ae5"
FIELD_AGENDA = "af3cf86c-a293-4d1c-9916-180ad84f0a7b"
FIELD_PERIODO = "3d629467-1fc7-46d6-b925-42afba66df92"
FIELD_USUARIO = "773bc404-9cb0-4935-80e5-baadda33bf0b"
DESMARCADOS = {"X-Horas Cruzadas": "marcação interna, não é parceiro",
               "X-Interno": "marcação interna, não é parceiro",
               "Energe": "regra da agenda: nunca enviar para Energe"}
GESTORES_INTERNOS = ("capulo", "elson")   # Filipe (Paes) Capulo e Elson (Afonso) Duarte
DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
ARQ_LOG = "agenda_envios.jsonl"

ESTADO = {"parceiros": {}, "de": None, "ate": None}
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _titulo(nome):
    """'LUCAS CARVALHO' -> 'Lucas Carvalho' (o ClickUp às vezes traz caixa alta)."""
    nome = (nome or "").strip()
    if nome.isupper():
        return " ".join(p if p.lower() in ("da", "de", "do", "dos", "das", "e") else p.capitalize()
                        for p in nome.lower().split())
    return nome


def _emails(texto):
    return [e.strip() for e in re.split(r"[,;\s]+", str(texto or "")) if EMAIL_RE.match(e.strip())]


def _proxima_semana():
    hoje = date.today()
    seg = hoje + timedelta(days=7 - hoje.weekday())
    return seg, seg + timedelta(days=6)


def _contatos():
    import pandas as pd
    try:
        df = pd.read_excel(PLANILHA_CONTATOS, sheet_name="Atualizada")
    except Exception:
        df = pd.read_excel(PLANILHA_CONTATOS)
    col_p = next(c for c in df.columns if _norm(c) == "PARCEIRO")
    col_e = next(c for c in df.columns if _norm(c).startswith("EMAIL"))
    contatos = {}
    for nome, mails in zip(df[col_p], df[col_e]):
        if str(nome).strip() and str(nome).lower() != "nan":
            contatos[str(nome).strip()] = _emails(mails)
    return contatos


def _casar_contato(parceiro, contatos):
    """Nome do ClickUp x nome da planilha: igual sem acento/espaço; senão um contém o outro."""
    alvo = _norm(parceiro)
    por_norm = {_norm(k): k for k in contatos}
    if alvo in por_norm:
        return por_norm[alvo]
    candidatos = [k for n, k in por_norm.items() if alvo and n and (alvo in n or n in alvo)]
    return min(candidatos, key=len) if candidatos else None


def _smtp_config():
    import keyring
    cfg = configparser.ConfigParser()
    cfg.read(f"{PASTAS['raiz']}\\{SMTP_INI}", encoding="utf-8")
    email = cfg.get("gmail", "email", fallback="").strip()
    senha = (keyring.get_password("sankhya_experience_sync", "GMAIL_APP_PASSWORD") or "").strip()
    if not email or not senha:
        raise RuntimeError("Configuração do Gmail incompleta: confira o e-mail no smtp_config.ini e a senha "
                           "de app no cofre (Gravar_Senha_Gmail.bat).")
    return {"email": email, "senha": senha, "nome": cfg.get("gmail", "display_name", fallback=email).strip(),
            "delay": cfg.getfloat("envio", "delay_segundos", fallback=30.0)}


def _mensagem(remetente, nome, para, cc, assunto, corpo_html):
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{nome} <{remetente}>"
    msg["To"] = ", ".join(para)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = assunto
    msg.attach(MIMEText("Este e-mail requer um cliente compatível com HTML para ser exibido corretamente.",
                        "plain", "utf-8"))
    msg.attach(MIMEText(corpo_html, "html", "utf-8"))
    return msg


def _registrar(evento):
    evento["quando"] = datetime.now().isoformat(timespec="seconds")
    with open(dados_arquivo(ARQ_LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- rotas
@rota("GET", "/api/agenda/opcoes")
def opcoes(req):
    seg, dom = _proxima_semana()
    return 200, {"de": seg.strftime("%d/%m/%Y"), "ate": dom.strftime("%d/%m/%Y"), "planilha": PLANILHA_CONTATOS}


@rota("POST", "/api/agenda/montar")
def montar(req):
    ini, fim = periodo_br(req.corpo.get("de"), req.corpo.get("ate"))

    def trabalho(t):
        import agenda_layout as L
        import clickup_visao as cv
        from clickup_sync.config import CLICKUP_API, CLICKUP_HEADERS

        t.log(f"Lendo a visualização 'Agrupado p/Enviar' do ClickUp ({ini:%d/%m/%Y} a {fim:%d/%m/%Y})...")
        tarefas = cv.buscar_tarefas(CLICKUP_API, CLICKUP_HEADERS, ini, fim, t.log, view_id=VIEW_AGENDA)
        t.log("Lendo a planilha de contatos...")
        contatos = _contatos()
        t.log(f"  {len(contatos)} parceiro(s) na planilha.")

        por_parceiro, removidas = {}, []
        for tk in tarefas:
            cfs = {c.get("id"): c for c in tk.get("custom_fields", [])}
            parceiro = cv._valor_dropdown(cfs.get(FIELD_PARCEIRO, {})) or ""
            agenda = cv._valor_dropdown(cfs.get(FIELD_AGENDA, {})) or ""
            consultores = [a.get("username") or "" for a in tk.get("assignees", [])]
            if agenda in L.AGENDA_EXCLUIR:
                removidas.append(f"{parceiro}: '{tk.get('name')}' (Agenda {agenda})")
                continue
            if any(g.upper() in _norm(c) for c in consultores for g in GESTORES_INTERNOS):
                removidas.append(f"{parceiro}: '{tk.get('name')}' (responsável da gestão interna)")
                continue
            venc = cv._data_ms(tk.get("due_date"))
            por_parceiro.setdefault(parceiro, []).append({
                "Consultor": ", ".join(_titulo(c) for c in consultores),
                "Atividade": tk.get("name") or "",
                "Data": venc.strftime("%d/%m/%Y") if venc else "",
                "Dia da Semana": DIAS[venc.weekday()] if venc else "",
                "Período": cv._valor_dropdown(cfs.get(FIELD_PERIODO, {})) or "",
                "Usuário Cliente": cv._texto_cf(cfs.get(FIELD_USUARIO, {})) or "",
                "Agenda": agenda,
                "_task_id": tk.get("id"),
            })

        data_ini, data_fim = f"{ini:%d/%m/%Y}", f"{fim:%d/%m/%Y}"
        ESTADO.update({"parceiros": {}, "de": data_ini, "ate": data_fim})
        lista = []
        for parceiro in sorted(por_parceiro, key=lambda p: p.lower()):
            linhas = sorted(por_parceiro[parceiro], key=lambda r: (r["Data"][6:], r["Data"][3:5], r["Data"][:2], r["Período"]))
            nome_planilha = _casar_contato(parceiro, contatos)
            mails = contatos.get(nome_planilha, []) if nome_planilha else []
            cor = L.CLICKUP_PARTNER_COLORS.get(parceiro, "#c2410c")
            tabela = L.build_table(linhas)
            ESTADO["parceiros"][parceiro] = {
                "assunto": f"Confirmação da Agenda de Serviço - {parceiro} - Período de {data_ini} a {data_fim}",
                "card": L.CARD_ONLY_TEMPLATE.format(parceiro=parceiro, data_ini=data_ini, data_fim=data_fim,
                                                    rows=tabela, cor=cor),
                "tabela": tabela, "cor": cor,
            }
            motivo = DESMARCADOS.get(parceiro) or ("" if mails else "sem e-mail na planilha")
            lista.append({"parceiro": parceiro, "tarefas": len(linhas), "nome_planilha": nome_planilha or "",
                          "para": mails[:1], "cc": mails[1:], "enviar": not motivo, "motivo": motivo,
                          "linhas": [{k: v for k, v in r.items() if not k.startswith("_")} for r in linhas],
                          "sem_cor": parceiro not in L.CLICKUP_PARTNER_COLORS})
        for r in removidas:
            t.log("  fora do e-mail: " + r)
        marcar_uso("agenda")
        return {"mensagem": f"{sum(p['tarefas'] for p in lista)} tarefa(s) em {len(lista)} parceiro(s). "
                            f"{len(removidas)} tarefa(s) fora do e-mail pelas regras. Nada foi enviado.",
                "resultado": {"parceiros": lista, "removidas": removidas, "de": data_ini, "ate": data_fim}}

    t = GERENTE.iniciar("agenda_montar", "Agenda semanal - montagem (só leitura)", trabalho, pasta=PASTAS["raiz"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/agenda/previa")
def previa(req):
    import agenda_layout as L
    p = ESTADO["parceiros"].get(req.corpo.get("parceiro") or "")
    if not p:
        raise ErroUsuario("Monte a agenda primeiro.")
    parceiro = req.corpo["parceiro"]
    para = ", ".join(_emails(req.corpo.get("para"))) or "(sem e-mail)"
    cc = ", ".join(_emails(req.corpo.get("cc"))) or "—"
    html = L.EMAIL_TEMPLATE.format(parceiro=parceiro, data_ini=ESTADO["de"], data_fim=ESTADO["ate"], rows=p["tabela"],
                                   assunto=p["assunto"], cor=p["cor"], para=para, cc=cc)
    return 200, {"html": html, "assunto": p["assunto"]}


def _alvos(req):
    itens = []
    for item in req.corpo.get("parceiros") or []:
        nome = item.get("parceiro") or ""
        if nome not in ESTADO["parceiros"]:
            raise ErroUsuario(f"'{nome}' não está na agenda montada. Monte de novo.")
        para, cc = _emails(item.get("para")), _emails(item.get("cc"))
        itens.append((nome, para, cc))
    if not itens:
        raise ErroUsuario("Nenhum parceiro marcado.")
    return itens


@rota("POST", "/api/agenda/teste")
def teste(req):
    exigir_confirmacao(req)
    nome = (_alvos(req))[0][0]

    def trabalho(t):
        cfg = _smtp_config()
        p = ESTADO["parceiros"][nome]
        t.log(f"Enviando e-mail de TESTE (simulando '{nome}') só para você: {cfg['email']}")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(cfg["email"], cfg["senha"])
            msg = _mensagem(cfg["email"], cfg["nome"], [cfg["email"]], [], "[TESTE] " + p["assunto"], p["card"])
            smtp.sendmail(cfg["email"], [cfg["email"]], msg.as_string())
        _registrar({"tipo": "teste", "parceiro": nome, "para": [cfg["email"]], "ok": True})
        return {"mensagem": f"Teste enviado para {cfg['email']}. Confira a caixa de entrada antes de enviar aos parceiros."}

    t = GERENTE.iniciar("agenda_teste", "Agenda semanal - e-mail de teste", trabalho, pasta=PASTAS["raiz"])
    return 200, {"tarefa": t.id}


@rota("POST", "/api/agenda/enviar")
def enviar(req):
    exigir_confirmacao(req)
    itens = _alvos(req)
    sem = [n for n, para, _ in itens if not para]
    if sem:
        raise ErroUsuario("Sem e-mail (Para) para: " + ", ".join(sem))

    def trabalho(t):
        cfg = _smtp_config()
        situacao, ok = {}, 0
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(cfg["email"], cfg["senha"])
            for i, (nome, para, cc) in enumerate(itens, 1):
                p = ESTADO["parceiros"][nome]
                try:
                    msg = _mensagem(cfg["email"], cfg["nome"], para, cc, p["assunto"], p["card"])
                    smtp.sendmail(cfg["email"], para + cc, msg.as_string())
                    situacao[nome] = "ENVIADO"
                    ok += 1
                    t.log(f"  [{i}/{len(itens)}] {nome}: enviado para {', '.join(para)}" + (f" | Cc: {', '.join(cc)}" if cc else ""))
                    _registrar({"tipo": "envio", "parceiro": nome, "para": para, "cc": cc, "assunto": p["assunto"], "ok": True})
                except Exception as e:
                    situacao[nome] = "FALHOU"
                    t.log(f"  [{i}/{len(itens)}] {nome}: FALHOU ({e})")
                    _registrar({"tipo": "envio", "parceiro": nome, "para": para, "cc": cc, "ok": False, "erro": str(e)})
                if i < len(itens):
                    time.sleep(cfg["delay"])
        t.adicionar_arquivo("Registro de envios (.jsonl)", dados_arquivo(ARQ_LOG))
        marcar_uso("agenda")
        return {"mensagem": f"{ok} de {len(itens)} e-mail(s) enviado(s).", "resultado": {"situacao": situacao}}

    t = GERENTE.iniciar("agenda_enviar", f"Agenda semanal - envio de {len(itens)} e-mail(s)", trabalho,
                        pasta=PASTAS["raiz"])
    return 200, {"tarefa": t.id}

# -*- coding: utf-8 -*-
"""Serviço local da Central BP-MS.

A página (msfragoso.github.io/central-bpms) conversa com este serviço em
http://127.0.0.1:8765. Ele:
  - usa o mesmo motor do Lançador de Demandas (lancar_tarefas_clickup.py)
    para lançar tarefas no ClickUp;
  - roda os scripts locais (Conferência, Aceite, Experience) e abre as pastas.

Só aceita pedidos vindos das origens em ORIGENS_PERMITIDAS, então outros
sites não conseguem usar o serviço. Configuração em config_central.json.
"""
import datetime
import json
import os
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORTA = 8765
ORIGENS_PERMITIDAS = {
    "https://msfragoso.github.io",
    "http://localhost:8000",   # testes locais
    "http://127.0.0.1:8000",
}
RAIZ = Path(r"C:\sankhya_integracao")
BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config_central.json"
LOG = BASE / "servidor_local.log"

PADRAO = {
    "pasta_lancador": r"C:\sankhya_integracao\clickup_tasks",  # pasta do lancar_tarefas_clickup.py
    "acoes": {
        "clickup_tela": r"C:\sankhya_integracao\clickup_tasks\Rodar_Tasks.bat",
        "experience": "",
        "conferencia": r"C:\sankhya_integracao\conferencia_os\Rodar_Conferencia.bat",
        "travados": r"C:\sankhya_integracao\conferencia_os\Rodar_Fase3.vbs",
        "aceite": r"C:\sankhya_integracao\aceite_os\Rodar_Aceite.bat",
    },
}


def log(msg):
    linha = f"{datetime.datetime.now():%d/%m %H:%M:%S} {msg}"
    print(linha)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def carregar_config():
    cfg = json.loads(json.dumps(PADRAO))
    if CONFIG.exists():
        try:
            lido = json.loads(CONFIG.read_text(encoding="utf-8"))
            cfg["pasta_lancador"] = lido.get("pasta_lancador") or ""
            cfg["acoes"].update({k: v for k, v in (lido.get("acoes") or {}).items() if v})
        except (OSError, ValueError) as e:
            log(f"config inválida, usando padrão: {e}")
    return cfg


def salvar_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


CFG = carregar_config()

# ----------------------------------------------------------------------------
# Motor do lançador (mesmo arquivo usado pela tela Tkinter)
# ----------------------------------------------------------------------------
motor = None
erro_motor = None
ARQUIVO_MEMORIA = None
trava_motor = threading.Lock()


def achar_pasta_lancador():
    p = CFG.get("pasta_lancador")
    if p and (Path(p) / "lancar_tarefas_clickup.py").exists():
        return Path(p)
    if RAIZ.exists():
        for arq in RAIZ.rglob("lancar_tarefas_clickup.py"):
            CFG["pasta_lancador"] = str(arq.parent)
            salvar_config(CFG)
            return arq.parent
    return None


def carregar_motor():
    global motor, erro_motor, ARQUIVO_MEMORIA
    pasta = achar_pasta_lancador()
    if not pasta:
        erro_motor = ("Não encontrei lancar_tarefas_clickup.py em C:\\sankhya_integracao. "
                      "Informe a pasta em config_central.json (pasta_lancador).")
        log(erro_motor)
        return
    # O motor pode ler arquivos relativos (token, caches): roda com a pasta dele como diretório atual.
    os.chdir(pasta)
    sys.path.insert(0, str(pasta))
    try:
        import lancar_tarefas_clickup as m
        motor = m
        ARQUIVO_MEMORIA = pasta / "ultimo_lancamento.json"  # o mesmo arquivo da tela antiga
        log(f"motor carregado de {pasta}")
        threading.Thread(target=_precarregar, daemon=True).start()
    except Exception as e:
        erro_motor = f"Erro ao carregar o motor: {e}"
        log(erro_motor + "\n" + traceback.format_exc())


def _precarregar():
    try:
        motor.carregar_listas_avulso()
    except Exception as e:
        log(f"falha ao pré-carregar listas: {e}")


def ler_memoria():
    try:
        return json.loads(ARQUIVO_MEMORIA.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return {}


def salvar_memoria(dados):
    try:
        ARQUIVO_MEMORIA.write_text(json.dumps(dados, ensure_ascii=False, indent=4), encoding="utf-8")
    except OSError as e:
        log(f"erro ao salvar memória: {e}")


def interpretar_data(texto):
    if not texto:
        return None
    return datetime.date.fromisoformat(texto)  # a página manda AAAA-MM-DD


# ----------------------------------------------------------------------------
# Ações do ClickUp
# ----------------------------------------------------------------------------
def precisa_motor():
    if motor is None:
        raise ErroUsuario(erro_motor or "Motor do lançador não carregado.")


class ErroUsuario(Exception):
    pass


def clickup_opcoes(_q):
    precisa_motor()
    membros = motor.carregar_membros_cache() or []
    return {
        "parceiros": sorted(motor.OPCOES_PARCEIRO.keys(), key=str.lower),
        "origens": list(motor.OPCOES_ORIGEM.keys()),
        "periodos": list(motor.OPCOES_PERIODO.keys()),
        "membros": [m["nome"] for m in membros],
        "ultimo": ler_memoria(),
    }


def clickup_membros(_q):
    precisa_motor()
    membros = motor.listar_membros_workspace()
    motor.salvar_membros_cache(membros)
    return {"membros": [m["nome"] for m in membros]}


def clickup_faps(q):
    precisa_motor()
    parceiro = (q.get("parceiro") or [""])[0]
    if parceiro not in motor.OPCOES_PARCEIRO:
        raise ErroUsuario(f"O parceiro '{parceiro}' não é válido.")
    forcar = (q.get("forcar") or ["0"])[0] == "1"
    faps = motor.listar_faps_do_parceiro(parceiro, forcar)
    return {"faps": [{"id": f["id"], "nome": f["nome"]} for f in faps]}


def clickup_periodo(q):
    precisa_motor()
    texto = (q.get("texto") or [""])[0]
    return {"periodo": motor.interpretar_periodo(texto) if texto else None}


def clickup_lancar(dados):
    precisa_motor()
    parceiro = (dados.get("parceiro") or "").strip()
    origem = (dados.get("origem") or "").strip()
    titulo = (dados.get("titulo") or "").strip()
    usuario = (dados.get("usuario") or "").strip()
    detalhamento = (dados.get("detalhamento") or "").strip()
    responsavel = (dados.get("responsavel") or "").strip()
    fap_id = (dados.get("fap_id") or "").strip()
    fap_nome = (dados.get("fap_nome") or "").strip()
    texto_periodo = (dados.get("periodo") or "").strip()

    if not parceiro or not origem or not titulo or not detalhamento:
        raise ErroUsuario("Parceiro, Origem, Título e Detalhamento são obrigatórios.")
    if parceiro not in motor.OPCOES_PARCEIRO:
        raise ErroUsuario(f"O parceiro '{parceiro}' não é válido. Selecione um da lista.")
    if origem not in motor.OPCOES_ORIGEM:
        raise ErroUsuario("Selecione uma origem válida da lista.")
    if not fap_id:
        raise ErroUsuario("Selecione a FAP em que a demanda deve ser lançada.")

    responsavel_id = None
    if responsavel:
        membros = {m["nome"]: m["id"] for m in (motor.carregar_membros_cache() or [])}
        responsavel_id = membros.get(responsavel)
        if not responsavel_id:
            raise ErroUsuario(f"Responsável '{responsavel}' não encontrado. Selecione da lista ou deixe em branco.")

    try:
        data_venc = interpretar_data(dados.get("vencimento"))
    except ValueError:
        raise ErroUsuario("Data de vencimento inválida.")

    periodo = None
    if texto_periodo:
        periodo = motor.interpretar_periodo(texto_periodo)
        if not periodo:
            raise ErroUsuario(f"Período '{texto_periodo}' não existe no ClickUp. Selecione uma opção da lista (ex.: 08h-10h).")
        if not data_venc:
            raise ErroUsuario("Período preenchido sem data. Informe o vencimento (dia do atendimento) ou apague o período.")

    avisos = []
    with trava_motor:
        task_id = motor.criar_demanda_padrao(
            titulo=titulo, detalhamento=detalhamento, parceiro=parceiro,
            usuario_cliente=usuario, origem=origem,
            responsavel_id=responsavel_id, data_vencimento=data_venc, periodo=periodo,
            list_id=fap_id, avisos=avisos,
        )
    salvar_memoria({"parceiro": parceiro, "origem": origem, "titulo": titulo,
                    "usuario": usuario, "detalhamento": detalhamento})
    log(f"lançada #{task_id} | {parceiro} | {titulo}")
    return {"task_id": task_id, "fap": fap_nome, "periodo": periodo, "avisos": avisos}


# ----------------------------------------------------------------------------
# Scripts locais
# ----------------------------------------------------------------------------
def executar(acao, so_pasta=False):
    alvo = CFG["acoes"].get(acao)
    if acao not in CFG["acoes"]:
        raise ErroUsuario(f"Ação desconhecida: {acao}")
    if not alvo or not Path(alvo).exists():
        alvo = escolher_arquivo(acao)
        if not alvo:
            raise ErroUsuario(f"O programa de '{acao}' não está configurado.")
    p = Path(alvo)
    if so_pasta:
        os.startfile(str(p.parent))
    elif p.suffix.lower() in (".bat", ".cmd"):
        subprocess.Popen(["cmd", "/c", "start", "", str(p)], cwd=str(p.parent))
    else:
        os.startfile(str(p))
    log(f"{'pasta' if so_pasta else 'executou'} {acao}: {p}")
    return {"ok": True, "alvo": str(p)}


trava_dialogo = threading.Lock()


def escolher_arquivo(acao):
    """Abre a janela do Windows para escolher o programa e guarda a escolha."""
    with trava_dialogo:  # uma janela Tk por vez; criada e destruída na mesma thread
        return _escolher_arquivo(acao)


def _escolher_arquivo(acao):
    try:
        import tkinter as tk
        from tkinter import filedialog
        raiz = tk.Tk()
        raiz.withdraw()
        raiz.attributes("-topmost", True)
        caminho = filedialog.askopenfilename(
            title=f"Central BP-MS: escolha o programa de '{acao}'",
            initialdir=str(RAIZ) if RAIZ.exists() else str(BASE),
            filetypes=[("Programas", "*.bat *.cmd *.vbs *.py *.pyw *.exe *.lnk"), ("Todos", "*.*")])
        raiz.destroy()
    except Exception as e:
        log(f"não abriu o seletor de arquivo: {e}")
        return None
    if not caminho:
        return None
    CFG["acoes"][acao] = os.path.normpath(caminho)
    salvar_config(CFG)
    return CFG["acoes"][acao]


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
GET = {
    "/clickup/opcoes": clickup_opcoes,
    "/clickup/membros": clickup_membros,
    "/clickup/faps": clickup_faps,
    "/clickup/periodo": clickup_periodo,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "CentralBPMS/1.0"

    def log_message(self, fmt, *args):
        pass

    def _origem_ok(self):
        return self.headers.get("Origin") in ORIGENS_PERMITIDAS

    def _cabecalhos_cors(self):
        origem = self.headers.get("Origin")
        if origem in ORIGENS_PERMITIDAS:
            self.send_header("Access-Control-Allow-Origin", origem)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, codigo, corpo):
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self._cabecalhos_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_OPTIONS(self):
        self.send_response(204 if self._origem_ok() else 403)
        self._cabecalhos_cors()
        self.end_headers()

    def _rodar(self, func, *args):
        if not self._origem_ok():
            return self._json(403, {"erro": "Origem não permitida."})
        try:
            self._json(200, func(*args))
        except ErroUsuario as e:
            self._json(400, {"erro": str(e)})
        except Exception as e:
            log(f"erro em {self.path}: {e}\n{traceback.format_exc()}")
            self._json(500, {"erro": f"Ocorreu um problema: {e}"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/status":
            return self._rodar(lambda: {"ok": True, "motor": motor is not None, "erro_motor": erro_motor})
        func = GET.get(url.path)
        if not func:
            return self._json(404, {"erro": "Rota não encontrada."})
        self._rodar(func, parse_qs(url.query))

    def do_POST(self):
        url = urlparse(self.path)
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._json(415, {"erro": "Use application/json."})
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            dados = json.loads(self.rfile.read(tamanho) or b"{}")
        except ValueError:
            return self._json(400, {"erro": "JSON inválido."})
        partes = url.path.strip("/").split("/")
        if url.path == "/clickup/lancar":
            return self._rodar(clickup_lancar, dados)
        if len(partes) == 2 and partes[0] == "executar":
            return self._rodar(executar, partes[1])
        if len(partes) == 2 and partes[0] == "pasta":
            return self._rodar(executar, partes[1], True)
        self._json(404, {"erro": "Rota não encontrada."})


def main():
    carregar_motor()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    except OSError:
        log(f"porta {PORTA} ocupada: o serviço já deve estar rodando.")
        return
    log(f"Central BP-MS ouvindo em http://127.0.0.1:{PORTA}")
    srv.serve_forever()


if __name__ == "__main__":
    main()

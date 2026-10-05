# -*- coding: utf-8 -*-
"""
Serviço local da Central BP-MS (HTML5) -- http://127.0.0.1:8766

Serve as telas (pasta web/) e as rotas /api/... que chamam os motores de
C:\\sankhya_integracao sem alterá-los. Só aceita conexões da própria máquina.

Uso:  Iniciar_Central.vbs   (ou: python servico\\servidor.py)
"""
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nucleo  # noqa: E402
from nucleo import CONFIG, PASTA_WEB, ErroUsuario, Ocupado, Requisicao, para_json, resolver_rota  # noqa: E402

nucleo.preparar_sys_path()
nucleo.instalar_roteador()

import rotas_tarefas  # noqa: E402,F401  (registram as rotas ao importar)
import rotas_textos  # noqa: E402,F401
import app_lancar  # noqa: E402,F401
import app_fase3  # noqa: E402,F401
import app_conferencia  # noqa: E402,F401
import app_aceite  # noqa: E402,F401
import app_sync  # noqa: E402,F401

PORTA = int(CONFIG.get("porta") or 8766)
HOSTS_OK = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
# Páginas que podem chamar o serviço: as servidas por ele mesmo e o site da
# Central no GitHub Pages (que exige login antes de mostrar as telas).
ORIGENS_OK = {f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}", "https://msfragoso.github.io"}
LIMITE_CORPO = 60 * 1024 * 1024  # uploads em base64 (CSV/Excel)


class Handler(BaseHTTPRequestHandler):
    server_version = "CentralBPMS/1.0"

    def log_message(self, *args):  # silencioso (pythonw não tem console)
        pass

    # ---------------------------------------------------------------- utilitários
    def _enviar(self, status, corpo, tipo="application/json; charset=utf-8", extra=None):
        dados = corpo if isinstance(corpo, bytes) else para_json(corpo).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in {**self._cors(), **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(dados)

    def _host_ok(self):
        # Protege contra DNS rebinding: só atende quem chamou pelo endereço local.
        # Chamadas vindas de páginas de outros sites (Origin fora da lista) são recusadas.
        origem = self.headers.get("Origin")
        return (self.headers.get("Host") or "") in HOSTS_OK and (origem is None or origem in ORIGENS_OK)

    def _cors(self):
        origem = self.headers.get("Origin")
        if origem in ORIGENS_OK:
            return {"Access-Control-Allow-Origin": origem, "Vary": "Origin"}
        return {}

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        if not self._host_ok():
            return self._enviar(403, {"erro": "Acesso permitido só pelo endereço local."})
        url = urlparse(self.path)
        caminho = unquote(url.path)
        if caminho.startswith("/api/"):
            partes = caminho.strip("/").split("/")
            # /api/tarefas/<id>/arquivo/<n> -> download de um arquivo gerado pela tarefa
            if len(partes) == 5 and partes[1] == "tarefas" and partes[3] == "arquivo":
                return self._baixar(partes[2], partes[4], parse_qs(url.query).get("ver") == ["1"])
            return self._api("GET", caminho, {k: v[0] for k, v in parse_qs(url.query).items()}, {})
        return self._estatico(caminho)

    def _estatico(self, caminho):
        if caminho in ("", "/"):
            caminho = "/index.html"
        alvo = os.path.normpath(os.path.join(PASTA_WEB, caminho.lstrip("/")))
        if not alvo.startswith(os.path.normpath(PASTA_WEB) + os.sep) or not os.path.isfile(alvo):
            return self._enviar(404, b"Nao encontrado", "text/plain; charset=utf-8")
        tipo = mimetypes.guess_type(alvo)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript",):
            tipo += "; charset=utf-8"
        with open(alvo, "rb") as f:
            self._enviar(200, f.read(), tipo)

    def _baixar(self, tarefa_id, indice, ver):
        caminho = rotas_tarefas.arquivo_da_tarefa(tarefa_id, indice)
        if not caminho or not os.path.isfile(caminho):
            return self._enviar(404, {"erro": "Arquivo não encontrado."})
        nome = os.path.basename(caminho)
        tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
        if caminho.lower().endswith((".html", ".htm")) and ver:
            tipo = "text/html; charset=utf-8"
            # sandbox: o relatório abre isolado, sem acesso às rotas /api deste serviço
            extra = {"Content-Security-Policy": "sandbox allow-scripts allow-popups allow-modals"}
        else:
            extra = {"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(nome)}"}
        with open(caminho, "rb") as f:
            self._enviar(200, f.read(), tipo, extra)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        if not self._host_ok():
            return self._enviar(403, {"erro": "Acesso permitido só pelo endereço local."})
        # Cabeçalho próprio + JSON: um site de fora não consegue mandar isso sem
        # pré-verificação CORS (liberada só para ORIGENS_OK).
        if self.headers.get("X-BPMS") != "1" or "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._enviar(403, {"erro": "Requisição recusada."})
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > LIMITE_CORPO:
            return self._enviar(413, {"erro": "Arquivo grande demais."})
        try:
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
            if not isinstance(corpo, dict):
                raise ValueError
        except ValueError:
            return self._enviar(400, {"erro": "JSON inválido."})
        url = urlparse(self.path)
        self._api("POST", unquote(url.path), {}, corpo)

    def do_OPTIONS(self):
        # Pré-verificação CORS: liberada só para as origens da lista (site da Central).
        if not self._host_ok() or self.headers.get("Origin") not in ORIGENS_OK:
            return self._enviar(403, {"erro": "CORS não permitido."})
        self.send_response(204)
        for k, v in self._cors().items():
            self.send_header(k, v)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-BPMS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---------------------------------------------------------------- API
    def _api(self, metodo, caminho, query, corpo):
        f, partes = resolver_rota(metodo, caminho)
        if not f:
            return self._enviar(404, {"erro": f"Rota não encontrada: {metodo} {caminho}"})
        req = Requisicao(metodo, caminho, query, corpo)
        req.partes = partes
        try:
            status, resposta = f(req)
        except ErroUsuario as e:
            status, resposta = 400, {"erro": str(e)}
        except Ocupado as e:
            status, resposta = 409, {"erro": str(e), "tarefa": e.tarefa.id}
        except BaseException as e:  # noqa: BLE001 -- inclui RuntimeError de credenciais e SystemExit
            status, resposta = 500, {"erro": f"{e.__class__.__name__}: {e}"}
        self._enviar(status, resposta)


def _quote(nome):
    from urllib.parse import quote
    return quote(nome)


def main():
    url = f"http://127.0.0.1:{PORTA}/"
    abrir = CONFIG.get("abrir_navegador", True) and "--sem-navegador" not in sys.argv
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    except OSError:
        # Porta ocupada: normalmente é a própria Central já aberta -- só abre a página.
        if abrir:
            webbrowser.open(url)
        return
    servidor.daemon_threads = True
    print(f"Central BP-MS rodando em {url}  (Ctrl+C para parar)")
    if abrir:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

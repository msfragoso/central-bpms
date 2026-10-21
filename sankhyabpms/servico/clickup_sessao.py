# -*- coding: utf-8 -*-
"""
Sessão do ClickUp (web) por login assistido -- para liberar acesso de pastas e
listas (21/10/2026). A API oficial só faz isso no plano Enterprise; a tela do
ClickUp usa o "frontdoor" (/v3-user/access/...), autenticado pelos cookies da
sessão do navegador + cabeçalhos sessionid / x-csrf (mapeado do HAR do Fragoso).

Igual ao Sankhya-OM: a Central abre o Chrome num perfil só dela
(dados/clickup_perfil) em app.clickup.com, o usuário faz o login, e a Central lê
os cabeçalhos das chamadas que a própria tela faz para usar a mesma sessão.
Tudo do Playwright roda numa thread dedicada.
"""
import json
import os
import queue
import threading
import time
from urllib.parse import urlparse

from nucleo import dados_arquivo

URL_APP = "https://app.clickup.com/"
PERFIL = dados_arquivo("clickup_perfil")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# "authorization" (Bearer da sessão web) não aparece no HAR "sanitizado" do Chrome,
# mas a tela manda -- sem ele o frontdoor responde 401 (visto em 21/10/2026).
CABECALHOS_SESSAO = ("authorization", "sessionid", "x-csrf", "build-version", "x-build-git-sha-short")


class _ClickUpWeb:
    def __init__(self):
        self._fila = queue.Queue()
        self._thread = None
        self._pw = None
        self._ctx = None
        self.host = None          # ex.: frontdoor-prod-us-east-2-1.clickup.com
        self.cabecalhos = {}      # sessionid, x-csrf... vistos nas chamadas da tela
        self.estado = "desconectado"   # desconectado | aguardando_login | conectado
        self.mensagem = ""
        self.desde = None
        self._oculto = False
        self._minimizou = False

    # ------------------------------------------------------------ thread
    def _garantir_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._laco, daemon=True, name="clickup-playwright")
        self._thread.start()

    def _laco(self):
        while True:
            try:
                funcao, resposta = self._fila.get(timeout=0.5)
            except queue.Empty:
                self._ocioso()
                continue
            try:
                resposta.put((True, funcao()))
            except Exception as e:  # noqa: BLE001
                resposta.put((False, e))

    def _ocioso(self):
        if self._ctx is None:
            return
        try:
            if self._ctx.pages:
                self._ctx.pages[0].wait_for_timeout(300)   # deixa os eventos de requisição chegarem
            # Login feito na janela visível: minimiza a janela (ela precisa continuar aberta).
            if self.estado == "conectado" and not self._oculto and not getattr(self, "_minimizou", False):
                self._minimizou = True
                self._minimizar()
        except Exception:
            pass

    def _minimizar(self):
        try:
            pagina = self._ctx.pages[0]
            cdp = self._ctx.new_cdp_session(pagina)
            janela = cdp.send("Browser.getWindowForTarget")["windowId"]
            cdp.send("Browser.setWindowBounds", {"windowId": janela, "bounds": {"windowState": "minimized"}})
        except Exception:
            pass

    def _executar(self, funcao, timeout=120):
        self._garantir_thread()
        resposta = queue.Queue()
        self._fila.put((funcao, resposta))
        ok, valor = resposta.get(timeout=timeout)
        if not ok:
            raise valor
        return valor

    # ------------------------------------------------------------ navegador
    def _abrir(self, oculto=False):
        if self._ctx is not None:
            try:
                self._ctx.pages
                return
            except Exception:
                self._ctx = None
        try:
            import importlib
            import site
            if os.path.isdir(site.getusersitepackages()):
                site.addsitedir(site.getusersitepackages())
            importlib.invalidate_caches()
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(r"Falta instalar o Playwright neste PC: dê duplo clique em "
                               r"C:\sankhyabpms\Instalar_Playwright.bat e tente de novo.")
        if self._pw is None:
            self._pw = sync_playwright().start()
        os.makedirs(PERFIL, exist_ok=True)
        # oculto=True: Chrome sem janela (headless), usando o login já salvo no perfil.
        opcoes = dict(headless=oculto, chromium_sandbox=True)
        if oculto:
            opcoes["viewport"] = {"width": 1400, "height": 900}
        else:
            opcoes.update(no_viewport=True, args=["--start-maximized"])
        if os.path.isfile(CHROME):
            opcoes["executable_path"] = CHROME
        else:
            opcoes["channel"] = "chrome"
        self._ctx = self._pw.chromium.launch_persistent_context(PERFIL, **opcoes)
        self._oculto = oculto
        self._minimizou = False
        self._ctx.on("request", self._ver_requisicao)
        self._ctx.on("close", lambda *_: self._fechou())

    def _fechou(self):
        self._ctx = None
        self.cabecalhos = {}
        self.estado = "desconectado"
        self.mensagem = "A janela do ClickUp foi fechada."

    def _ver_requisicao(self, req):
        try:
            host = urlparse(req.url).hostname or ""
            if not (host.startswith("frontdoor-") and host.endswith(".clickup.com")):
                return
            h = req.headers
            if h.get("sessionid") and (h.get("authorization") or not self.cabecalhos.get("authorization")):
                self.host = host
                self.cabecalhos = {k: h[k] for k in CABECALHOS_SESSAO if h.get(k)}
                if self.estado != "conectado":
                    self.desde = time.time()
                self.estado = "conectado"
                self.mensagem = "Conectado ao ClickUp."
        except Exception:
            pass

    def conectar(self):
        """
        21/10/2026 (pedido do Fragoso): depois do 1º login, conecta ESCONDIDO. Tenta
        primeiro o Chrome sem janela com o login salvo no perfil; se em ~30 s a tela do
        ClickUp não fizer chamadas com a sessão (login expirou), fecha e abre a janela
        visível para o login. Com o login feito na janela visível, ela é minimizada.
        """
        def abrir():
            if self._ctx is not None and self.estado == "conectado":
                return True
            if self._ctx is None:
                self.estado, self.mensagem = "aguardando_login", "Conectando ao ClickUp em segundo plano…"
                self._abrir(oculto=True)
                pagina = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
                pagina.goto(URL_APP, wait_until="domcontentloaded", timeout=60000)
                limite = time.time() + 30
                while time.time() < limite and self.estado != "conectado":
                    pagina.wait_for_timeout(500)
                if self.estado == "conectado":
                    self.mensagem = "Conectado ao ClickUp (em segundo plano)."
                    return True
                try:  # login salvo não vale mais: troca pela janela visível
                    self._ctx.close()
                except Exception:
                    pass
                self._ctx = None
            self._abrir(oculto=False)
            pagina = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            if "app.clickup.com" not in (pagina.url or ""):
                pagina.goto(URL_APP, wait_until="domcontentloaded", timeout=60000)
            pagina.bring_to_front()
            if self.estado != "conectado":
                self.estado = "aguardando_login"
                self.mensagem = "Faça o login na janela do ClickUp que abriu (e espere a tela carregar)."
            return True
        return self._executar(abrir, timeout=150)

    # ------------------------------------------------------------ chamadas
    def chamar(self, metodo, caminho, corpo=None, workspace_id=None):
        """Chamada ao frontdoor com a sessão do navegador. Devolve o JSON."""
        if self.estado != "conectado" or not self.host:
            raise RuntimeError("ClickUp (web) não conectado. Clique em 'Conectar ao ClickUp' e faça o login.")

        def fazer():
            self._abrir()
            cab = dict(self.cabecalhos)
            cab.update({"Content-Type": "application/json", "Accept": "application/json",
                        "Origin": "https://app.clickup.com", "Referer": URL_APP})
            if workspace_id:
                cab["x-workspace-id"] = str(workspace_id)
            # A chamada sai de DENTRO da página do ClickUp (fetch com credentials), para o
            # navegador anexar os cookies da sessão como faz a própria tela; os cabeçalhos
            # lidos das chamadas da tela (Bearer, sessionid, x-csrf) vão junto.
            cab.pop("Origin", None)
            cab.pop("Referer", None)
            pagina = next((p for p in self._ctx.pages if "app.clickup.com" in (p.url or "")), None)
            if pagina is None:
                raise RuntimeError("Deixe a janela do ClickUp aberta (app.clickup.com) e tente de novo.")
            resp = pagina.evaluate("""async ([url, metodo, cab, corpo]) => {
                const r = await fetch(url, {method: metodo, headers: cab, body: corpo, credentials: 'include'});
                return {status: r.status, texto: await r.text()};
            }""", [f"https://{self.host}{caminho}", metodo, cab, json.dumps(corpo) if corpo is not None else None])

            class _R:  # mesmo formato usado abaixo
                status = resp["status"]
            r = _R()
            texto = resp["texto"]
            if r.status == 403:
                # 403 = sem permissão para mexer NESTE item (ex.: pasta de outro dono);
                # a sessão continua valendo, então segue para os próximos.
                raise RuntimeError("o ClickUp não deixou alterar este item (HTTP 403, sem permissão nele)")
            if r.status == 401:
                self.estado = "desconectado"
                self.mensagem = "A sessão do ClickUp expirou. Conecte de novo."
                raise RuntimeError(f"ClickUp recusou (HTTP {r.status}). Conecte de novo.")
            if r.status >= 400:
                raise RuntimeError(f"ClickUp HTTP {r.status}: {texto[:200]}")
            try:
                return json.loads(texto) if texto else {}
            except ValueError:
                raise RuntimeError(f"ClickUp respondeu algo inesperado (HTTP {r.status}).")
        return self._executar(fazer, timeout=90)

    def status(self):
        return {"estado": self.estado, "mensagem": self.mensagem,
                "desde": time.strftime("%d/%m %H:%M", time.localtime(self.desde)) if self.desde else None}


CLICKUP_WEB = _ClickUpWeb()

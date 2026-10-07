# -*- coding: utf-8 -*-
"""
Sessão do Sankhya-OM por login assistido.

O login do OM só é feito pela página oficial (ela gera um token de
autorização próprio, que não imitamos). Por isso a Central abre o Chrome do
PC num perfil só dela (dados/om_perfil), na página do OM, e quem faz o login
é o usuário. Com o login feito, as telas do OM chamam /mge/service.sbr com o
parâmetro mgeSession e o cabeçalho sktk; a Central lê esses dois valores das
chamadas que o próprio OM faz e usa a mesma sessão para as consultas de
leitura (DatasetSP.loadRecords), pelo contexto do navegador (mesmos cookies).

O Playwright (API síncrona) só pode ser usado pela thread que o abriu, então
tudo roda numa thread dedicada que recebe trabalhos por uma fila.
"""
import json
import os
import queue
import threading
import time
from urllib.parse import parse_qs, urlparse

from nucleo import dados_arquivo

URL_OM = "https://skw.sankhya.com.br/mge/"
SERVICO = "https://skw.sankhya.com.br/mge/service.sbr"
PERFIL = dados_arquivo("om_perfil")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class _Om:
    def __init__(self):
        self._fila = queue.Queue()
        self._thread = None
        self._pw = None
        self._ctx = None
        self.sessao = None      # {"mgeSession": ..., "sktk": ..., "quando": ...}
        self.estado = "desconectado"   # desconectado | aguardando_login | conectado | erro
        self.mensagem = ""
        self.sktk_consulta = None       # (mgeSession, sktk) vistos na tela Consulta de OS
        self._pagina_consulta = None

    # ---------------------------------------------------------------- thread
    def _garantir_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._laco, daemon=True, name="om-playwright")
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
            except Exception as e:  # noqa: BLE001 -- devolve o erro para quem pediu
                resposta.put((False, e))

    def _ocioso(self):
        """
        Na API síncrona do Playwright os eventos (como o de requisição, usado para
        pegar a sessão) só são processados durante uma chamada ao navegador. Com
        a janela aberta e nada para fazer, espera um pouco "dentro" do navegador
        para os eventos chegarem, e também procura a sessão no endereço das telas.
        """
        if self._ctx is None:
            return
        try:
            paginas = self._ctx.pages
            if not paginas:
                return
            paginas[0].wait_for_timeout(300)
            if not self.sessao and time.time() - getattr(self, "_ultima_busca", 0) > 3:
                self._ultima_busca = time.time()
                self._sessao_pelas_telas()
            # Logado e sem a Consulta de OS aberta: abre a tela uma vez por sessão.
            if self.sessao and not self._consulta_pronta() and                     getattr(self, "_abriu_consulta_em", None) != self.sessao["mgeSession"] and                     time.time() - self.sessao.get("quando", 0) > 5:
                self._abrir_tela_consulta()
        except Exception:
            pass

    def _consulta_pronta(self):
        return bool(self.sessao and self.sktk_consulta and self.sktk_consulta[0] == self.sessao["mgeSession"])

    # Endereço da tela dentro do OM: system.jsp#app/<ID da tela em base64>.
    # ID "br.com.sankhya.os.con.consultaOs" (confirmado pelo Fragoso em "Configurar
    # tela" do OM, 07/10/2026). Abrir por aqui é o mesmo que abrir pelo menu.
    URL_TELA_CONSULTA = ("https://skw.sankhya.com.br/mge/system.jsp#app/"
                         "YnIuY29tLnNhbmtoeWEub3MuY29uLmNvbnN1bHRhT3M=")

    def _abrir_tela_consulta(self):
        """Abre a Consulta de OS na janela do OM (sem filtrar nem aplicar). Thread do Playwright."""
        self._abriu_consulta_em = self.sessao["mgeSession"]
        pagina = self._ctx.pages[0]
        if "system.jsp" in (pagina.url or ""):
            pagina.evaluate("u => { location.href = u; }", self.URL_TELA_CONSULTA)
        else:
            pagina.goto(self.URL_TELA_CONSULTA, wait_until="domcontentloaded", timeout=60000)

    # Procura o mgeSession no endereço da tela, nos endereços que a página já
    # carregou (lista de recursos do navegador) e no próprio HTML/variáveis.
    _JS_SESSAO = r"""() => {
        const re = /mgeSession=([A-Za-z0-9_\-]+)/;
        const fontes = [location.href];
        try { performance.getEntriesByType('resource').forEach(e => fontes.push(e.name)); } catch (e) {}
        try { if (window.mgeSession) return String(window.mgeSession); } catch (e) {}
        for (const f of fontes) { const m = re.exec(f || ''); if (m) return m[1]; }
        try { const m = re.exec(document.documentElement.innerHTML); if (m) return m[1]; } catch (e) {}
        return '';
    }"""

    def _sessao_pelas_telas(self):
        for pagina in self._ctx.pages:
            for frame in pagina.frames:
                url = frame.url or ""
                if "skw.sankhya.com.br" not in url:
                    continue
                mge = (parse_qs(urlparse(url).query).get("mgeSession") or [""])[0]
                if not mge:
                    try:
                        mge = frame.evaluate(self._JS_SESSAO) or ""
                    except Exception:
                        mge = ""
                if mge:
                    self.sessao = {"mgeSession": mge, "sktk": "", "quando": time.time()}
                    self.estado = "conectado"
                    self.mensagem = "Conectado ao Sankhya-OM."
                    return True
        return False

    def _executar(self, funcao, timeout=120):
        self._garantir_thread()
        resposta = queue.Queue()
        self._fila.put((funcao, resposta))
        ok, valor = resposta.get(timeout=timeout)
        if not ok:
            raise valor
        return valor

    # ---------------------------------------------------------------- navegador
    def _abrir(self):
        if self._ctx is not None:
            try:
                self._ctx.pages  # ainda vivo?
                return
            except Exception:
                self._ctx = None
        from playwright.sync_api import sync_playwright
        if self._pw is None:
            self._pw = sync_playwright().start()
        os.makedirs(PERFIL, exist_ok=True)
        opcoes = dict(headless=False, no_viewport=True, chromium_sandbox=True, args=["--start-maximized"])
        if os.path.isfile(CHROME):
            opcoes["executable_path"] = CHROME
        else:
            opcoes["channel"] = "chrome"
        self._ctx = self._pw.chromium.launch_persistent_context(PERFIL, **opcoes)
        self._ctx.on("request", self._ver_requisicao)
        self._ctx.on("close", lambda *_: self._fechou())

    def _fechou(self):
        self._ctx = None
        self.sessao = None
        self.estado = "desconectado"
        self.mensagem = "A janela do Sankhya-OM foi fechada."

    def _ver_requisicao(self, req):
        """Guarda mgeSession/sktk das chamadas que o próprio OM faz depois do login."""
        try:
            if "/mge/service.sbr" not in req.url:
                return
            q = parse_qs(urlparse(req.url).query)
            mge = (q.get("mgeSession") or [""])[0]
            sktk = req.headers.get("sktk") or ""
            if mge and "consultaOs" in ((q.get("resourceID") or [""])[0]) and sktk:
                self.sktk_consulta = (mge, sktk)   # token da licença da tela Consulta de OS
            if mge:
                antigo = self.sessao or {}
                self.sessao = {"mgeSession": mge, "sktk": antigo.get("sktk", "") if antigo.get("mgeSession") == mge else "",
                               "quando": antigo.get("quando") or time.time()}
                self.estado = "conectado"
                self.mensagem = "Conectado ao Sankhya-OM."
        except Exception:
            pass

    def conectar(self):
        """Abre (ou traz para frente) a janela do OM. O login é feito pelo usuário."""
        def abrir():
            self._abrir()
            pagina = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            if "skw.sankhya.com.br" not in (pagina.url or ""):
                pagina.goto(URL_OM, wait_until="domcontentloaded", timeout=60000)
            pagina.bring_to_front()
            if self.estado != "conectado":
                self.estado = "aguardando_login"
                self.mensagem = "Faça o login na janela do Sankhya-OM que abriu."
            return True
        return self._executar(abrir)

    # ---------------------------------------------------------------- tela Consulta de OS
    URL_CONSULTA = ("https://skw.sankhya.com.br/mgeos/ConsultaOS.xhtml5?mgeSession={s}"
                    "&resourceID=br.com.sankhya.os.con.consultaOs")

    def _token_consulta(self, forcar=False):
        """
        O OM só aceita a consulta de OS com a licença da tela aberta (token sktk
        que a tela recebe ao abrir). Abrir o arquivo interno da tela
        (ConsultaOS.xhtml5) fora do OM não funciona (testado em 06/10/2026), então a
        Central abre a tela pelo endereço system.jsp#app/<ID> (igual ao menu) e usa
        o token que ela recebe. Roda na thread do Playwright.
        """
        mge = self.sessao["mgeSession"]
        if forcar:
            self.sktk_consulta = None
        espera = 5
        if not self._consulta_pronta():
            self._abrir_tela_consulta()   # abre pelo endereço da tela e espera ela carregar
            espera = 40
        limite = time.time() + espera
        while time.time() < limite and not (self.sktk_consulta and self.sktk_consulta[0] == mge):
            paginas = self._ctx.pages if self._ctx else []
            if not paginas:
                break
            paginas[0].wait_for_timeout(500)
        if not (self.sktk_consulta and self.sktk_consulta[0] == mge):
            raise RuntimeError("Abra a tela 'Consulta de OS' pelo menu do Sankhya-OM, na janela da Central "
                               "(não precisa filtrar nem aplicar), e tente de novo.")
        return self.sktk_consulta[1]

    # ---------------------------------------------------------------- consultas
    def chamar(self, servico, corpo, extra_query=None):
        """POST em /mge/service.sbr com a sessão do usuário. Devolve o JSON da resposta."""
        if not self.sessao:
            raise RuntimeError("Sankhya-OM não conectado. Clique em 'Conectar ao Sankhya-OM' e faça o login.")
        sessao = dict(self.sessao)

        def fazer(tentativa=1):
            self._abrir()
            if (extra_query or {}).get("resourceID", "").endswith("consultaOs"):
                sessao["sktk"] = self._token_consulta(forcar=tentativa > 1)
            params = {"serviceName": servico, "outputType": "json", "preventTransform": "false",
                      "mgeSession": sessao["mgeSession"], "vss": "1"}
            params.update(extra_query or {})
            cab = {"Content-Type": "application/json; charset=UTF-8", "Origin": "https://skw.sankhya.com.br",
                   "Referer": URL_OM}
            if sessao.get("sktk"):
                cab["sktk"] = sessao["sktk"]
            r = self._ctx.request.post(SERVICO, params=params, headers=cab,
                                       data=json.dumps({"serviceName": servico, "requestBody": corpo}),
                                       timeout=120000)
            texto = r.text()
            try:
                j = json.loads(texto)
            except ValueError:
                raise RuntimeError(f"O OM respondeu algo inesperado (HTTP {r.status}). A sessão pode ter expirado.")
            if str(j.get("status")) != "1":
                msg = j.get("statusMessage") or j.get("statusMessageID") or str(j)[:300]
                if "licen" in str(msg).lower():
                    self.sktk_consulta = None
                    raise RuntimeError("A licença da tela Consulta de OS expirou no Sankhya-OM. Abra a tela "
                                       "'Consulta de OS' de novo pelo menu do OM, na janela da Central, e tente outra vez.")
                if "sess" in str(msg).lower() or str(j.get("status")) == "3":
                    self.sessao = None
                    self.estado = "desconectado"
                    self.mensagem = "A sessão do Sankhya-OM expirou. Conecte de novo."
                raise RuntimeError(f"OM: {msg}")
            return j
        return self._executar(fazer, timeout=180)

    def status(self):
        pronta = bool(self.sessao and self.sktk_consulta and self.sktk_consulta[0] == self.sessao["mgeSession"])
        return {"estado": self.estado, "mensagem": self.mensagem, "consulta_pronta": pronta,
                "desde": time.strftime("%d/%m %H:%M", time.localtime(self.sessao["quando"])) if self.sessao else None}


OM = _Om()


def _diagnostico_js():
    return r"""() => {
        const re = /mgeSession=([A-Za-z0-9_\-]+)/g, achados = [];
        const add = (fonte, txt) => { let m; re.lastIndex = 0; while ((m = re.exec(txt || ''))) achados.push([fonte, m[1]]); };
        add('location', location.href);
        try { performance.getEntriesByType('resource').forEach(e => add('recurso:' + e.name.split('?')[0].slice(-60), e.name)); } catch (e) {}
        try { add('html', document.documentElement.innerHTML); } catch (e) {}
        const vars = {};
        for (const k of ['mgeSession', 'MGE_SESSION', 'sessionId', 'SESSIONID']) { try { if (window[k]) vars[k] = String(window[k]); } catch (e) {} }
        return {achados, vars, cookies: document.cookie.split(';').map(c => c.split('=')[0].trim())};
    }"""


def diagnostico():
    """Onde aparece mgeSession na janela do OM (valores mascarados). Só leitura."""
    def fazer():
        out = []
        mascara = lambda v: (v[:4] + "…" + v[-3:]) if v and len(v) > 8 else v
        for pi, pagina in enumerate(OM._ctx.pages if OM._ctx else []):
            for frame in pagina.frames:
                try:
                    d = frame.evaluate(_diagnostico_js())
                except Exception as e:
                    d = {"erro": str(e)[:100]}
                out.append({"pagina": pi, "frame": (frame.url or "").split("?")[0][-80:],
                            "achados": [[f, mascara(v)] for f, v in (d.get("achados") or [])][:15],
                            "vars": {k: mascara(v) for k, v in (d.get("vars") or {}).items()},
                            "cookies": d.get("cookies"), "erro": d.get("erro")})
        return {"sessao_atual": mascara((OM.sessao or {}).get("mgeSession", "")), "frames": out}
    return OM._executar(fazer)

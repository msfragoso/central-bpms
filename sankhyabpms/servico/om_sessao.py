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
import html as html_mod
import json
import os
import queue
import re
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

from nucleo import dados_arquivo, gravar_json_dados, ler_json_dados

URL_OM = "https://skw.sankhya.com.br/mge/"
SERVICO = "https://skw.sankhya.com.br/mge/service.sbr"
PERFIL = dados_arquivo("om_perfil")
ARQ_LOGIN_PARADO = "om_login_parado.json"
ESPERA_TELA_LOGIN_MS = 30000
# 05/11/2026: a página pede ao Chrome uma credencial salva, e o popup "Fazer login como" prende o login
# (é janela do navegador, a automação não alcança). Aqui o Chrome responde "nenhuma" e a página segue.
SEM_POPUP_DE_LOGIN = """
if (navigator.credentials) {
  navigator.credentials.get = () => Promise.resolve(null);
  navigator.credentials.store = (c) => Promise.resolve(c);
}
"""
COFRE = "sankhya_experience_sync"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _user32():
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    return u


def _janelas_visiveis(pid):
    """Janelas de navegador visíveis do processo do Chrome informado."""
    import ctypes
    from ctypes import wintypes
    u = _user32()
    achadas = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def ver(hwnd, _):
        dono = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if dono.value == pid and u.IsWindowVisible(hwnd):
            classe = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(hwnd, classe, 64)
            if classe.value == "Chrome_WidgetWin_1":
                achadas.append(hwnd)
        return True

    u.EnumWindows(ver, 0)
    return achadas


def _pid_chrome_do_perfil(perfil):
    filtro = os.path.basename(perfil).replace("'", "")
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { "
           f"$_.CommandLine -like '*{filtro}*' -and $_.CommandLine -notlike '*--type=*' }} | "
           "Select-Object -First 1 -ExpandProperty ProcessId")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                       text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    return int(r.stdout.strip())


def credenciais_om():
    """(usuário, senha) do OM no cofre. O login é único (Fragoso, 05/11/2026): sem dados próprios, usa os do Experience."""
    import keyring
    usuario = (keyring.get_password(COFRE, "OM_USER") or keyring.get_password(COFRE, "EXPERIENCE_USER") or "").strip()
    if not usuario:
        return None
    senha = keyring.get_password(COFRE, "OM_PASS") or keyring.get_password(COFRE, "EXPERIENCE_PASS") or ""
    return (usuario, senha) if senha else None


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
        self.janela_oculta = False
        self._pid_chrome = None
        self._janelas_ocultas = []

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
            self._responder_aviso_restaurar()
            # Logado e sem a Consulta de OS aberta: abre a tela uma vez por sessão.
            if self.sessao and not self._consulta_pronta() and                     getattr(self, "_abriu_consulta_em", None) != self.sessao["mgeSession"] and                     time.time() - self.sessao.get("quando", 0) > 5:
                self._abrir_tela_consulta()
            # 29/10/2026 (Fragoso): com o login feito e a Consulta de OS pronta, a janela do OM
            # sai da frente; só volta quando precisar de login de novo.
            # 04/11/2026 (Fragoso): além de minimizar, some também da barra de tarefas.
            if self._consulta_pronta() and getattr(self, "_minimizada_em", None) != self.sessao["mgeSession"]:
                self._minimizada_em = self.sessao["mgeSession"]
                self._ocultar_janela()
        except Exception:
            pass

    def _janela(self, estado):
        """Minimiza ("minimized") ou traz de volta ("normal") a janela do OM. Thread do Playwright."""
        try:
            if estado == "normal":
                self._mostrar_janelas_ocultas()
            pagina = self._ctx.pages[0]
            cdp = self._ctx.new_cdp_session(pagina)
            wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": estado}})
            cdp.detach()
            if estado == "normal":
                pagina.bring_to_front()
        except Exception:
            pass

    def _ocultar_janela(self):
        """Minimiza e tira a janela da tela e da barra de tarefas; o Chrome e a tela seguem abertos.
        Se não conseguir ocultar, a janela só fica minimizada. Thread do Playwright."""
        self._janela("minimized")
        try:
            hwnds = _janelas_visiveis(self._pid_do_chrome())
            for hwnd in hwnds:
                _user32().ShowWindow(hwnd, 0)   # SW_HIDE
            self._janelas_ocultas = hwnds
            self.janela_oculta = bool(hwnds)
            print(f"[OM] janela oculta automaticamente ou pelo botão: {len(hwnds)} janela(s)", flush=True)
        except Exception as e:
            print(f"[OM] não consegui ocultar a janela, ela fica só minimizada: {e}", flush=True)

    def _mostrar_janelas_ocultas(self):
        for hwnd in self._janelas_ocultas:
            _user32().ShowWindow(hwnd, 5)   # SW_SHOW
        self._janelas_ocultas = []
        self.janela_oculta = False

    def _pid_do_chrome(self):
        """PID do processo principal do Chrome que usa o perfil do OM."""
        if not self._pid_chrome:
            self._pid_chrome = _pid_chrome_do_perfil(PERFIL)
        return self._pid_chrome

    # 04/11/2026 (Fragoso): o Reiniciar_Servico encerra o Chrome à força e o OM pergunta se quer
    # "Restaurar telas". A Central abre a Consulta de OS sozinha, então responde "Não" a esse aviso.
    _JS_AVISO_RESTAURAR = r"""() => {
        const todos = (raiz, saida = []) => {
            if (raiz.shadowRoot) todos(raiz.shadowRoot, saida);
            for (const el of raiz.querySelectorAll('*')) {
                saida.push(el);
                if (el.shadowRoot) todos(el.shadowRoot, saida);
            }
            return saida;
        };
        const texto = (el) => (el.innerText ?? el.textContent ?? '').trim();
        const pai = (el) => el.parentElement || (el.getRootNode() && el.getRootNode().host) || null;
        const elementos = todos(document).filter((el) => !['SCRIPT', 'STYLE', 'TEMPLATE'].includes(el.tagName));
        const aviso = elementos.filter((el) => /sua última saída do sistema aconteceu inesperadamente/i.test(el.textContent || ''));
        const mensagem = aviso[aviso.length - 1];
        if (!mensagem) return false;
        const botoes = elementos.filter((el) => texto(el) === 'Não' && !Array.from(el.children).some((f) => texto(f) === 'Não'));
        // Sobe só até a caixa do aviso: nunca clica em um "Não" de fora dela (filtros da tela, por exemplo).
        for (let caixa = mensagem; caixa && caixa !== document.body && caixa !== document.documentElement; caixa = pai(caixa)) {
            const dentro = todos(caixa);
            const botao = botoes.find((b) => dentro.includes(b));
            if (botao) { botao.click(); return true; }
        }
        return false;
    }"""

    def _responder_aviso_restaurar(self):
        """Procura o aviso nos primeiros 2 minutos de cada sessão e responde uma vez. Thread do Playwright."""
        if not self.sessao or getattr(self, "_aviso_respondido_em", None) == self.sessao["mgeSession"]:
            return
        agora = time.time()
        if agora - self.sessao.get("quando", 0) > 120 or agora - getattr(self, "_ultimo_aviso", 0) < 2:
            return
        self._ultimo_aviso = agora
        for pagina in self._ctx.pages:
            for frame in pagina.frames:
                try:
                    if frame.evaluate(self._JS_AVISO_RESTAURAR):
                        self._aviso_respondido_em = self.sessao["mgeSession"]
                        print("[OM] aviso 'Restaurar telas' respondido com Não.", flush=True)
                        return
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
        try:
            # A pasta de bibliotecas do usuário só entra no sys.path se já existia
            # quando o serviço subiu; um pip install --user feito depois não seria visto.
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
        opcoes = dict(headless=False, no_viewport=True, chromium_sandbox=True, args=["--start-maximized"])
        if os.path.isfile(CHROME):
            opcoes["executable_path"] = CHROME
        else:
            opcoes["channel"] = "chrome"
        self._pid_chrome = None
        self._ctx = self._pw.chromium.launch_persistent_context(PERFIL, **opcoes)
        self._ctx.add_init_script(SEM_POPUP_DE_LOGIN)
        self._ctx.on("request", self._ver_requisicao)
        self._ctx.on("close", lambda *_: self._fechou())

    def _fechou(self):
        self._ctx = None
        self.sessao = None
        self.estado = "desconectado"
        self.mensagem = "A janela do Sankhya-OM foi fechada."
        self.janela_oculta = False
        self._janelas_ocultas = []
        self._pid_chrome = None

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
            if mge and "CentralNotas" in ((q.get("resourceID") or [""])[0]) and sktk:
                self.sktk_central = (mge, sktk)    # token da licença da Central de Vendas
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
            if self.estado != "conectado":
                self._janela("normal")   # precisa do login: a janela volta para a frente
                self.estado = "aguardando_login"
                self.mensagem = "Faça o login na janela do Sankhya-OM que abriu."
                self._login_automatico(pagina)
            else:
                self._janela("normal")   # já logado: o botão mostra a janela oculta
            return True
        return self._executar(abrir, timeout=200)   # 09/11/2026: abertura + até 60s da tela de login + 30s do login

    def _log_login(self, texto):
        """Rastro do login automático em dados/om_login.log (nunca usuário nem senha)."""
        try:
            with open(dados_arquivo("om_login.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%d/%m/%Y %H:%M:%S") + " " + texto + "\n")
        except OSError:
            pass

    def _parar_login(self, motivo):
        """Uma tentativa só: repetir login recusado pode bloquear a conta. Volta a tentar depois de gravar de novo."""
        self._log_login(f"parado: {motivo}")
        gravar_json_dados(ARQ_LOGIN_PARADO, {"motivo": motivo, "quando": time.strftime("%d/%m/%Y %H:%M")})
        self.mensagem = f"Login automático parado: {motivo} Continue na janela do Sankhya-OM."

    def _login_automatico(self, pagina):
        """
        05/11/2026 (Fragoso): preenche usuário e senha do cofre na página oficial do OM. Só segue pelo
        caminho esperado. Qualquer outro pedido (código, troca de senha, aviso, senha recusada) para
        na hora, com a janela aberta, sem tentar de novo. Nunca registra a senha.
        """
        if ler_json_dados(ARQ_LOGIN_PARADO):
            self._log_login("não tentou: login automático parado desde a última recusa")
            return
        try:
            cred = credenciais_om()
        except Exception:
            cred = None
        if not cred:
            return
        try:
            campo_usuario = pagina.locator("input#user:visible")
            campo_senha = pagina.locator("input[type=password]:visible").first
            # Só o botão "Prosseguir" do formulário: nunca o "Entrar com Sankhya Pass" nem os das telas de código,
            # que têm outra estrutura (account-button) e continuam sendo com o usuário.
            botao_prosseguir = pagina.locator("button[type=submit]:visible", has_text="Prosseguir").first
            try:
                # 09/11/2026 (Fragoso, "Prosseguir" sem clique): na tela de senha existe um input#user ESCONDIDO (para o
                # gerenciador de senhas); sem o :visible, a espera travava nele e o login nunca seguia.
                campo_usuario.or_(campo_senha).first.wait_for(state="visible", timeout=ESPERA_TELA_LOGIN_MS)
            except Exception:
                self._log_login(f"tela de login não apareceu em {ESPERA_TELA_LOGIN_MS // 1000}s (url: {(pagina.url or '')[:80]})")
                return   # sem tela de login: já está logado ou a página mudou; segue pelo fluxo normal
            self.mensagem = "Entrando no Sankhya-OM com o usuário do cofre..."
            if campo_usuario.is_visible():
                campo_usuario.fill(cred[0])
                botao_prosseguir.click()
                try:
                    campo_senha.wait_for(state="visible", timeout=15000)
                except Exception:
                    return self._parar_login("o OM não pediu a senha depois do usuário.")
            elif pagina.get_by_text(cred[0]).count() == 0:
                # O OM lembra o último usuário e já abre na senha: só segue se for o mesmo do cofre.
                return self._parar_login("a tela de senha é de outro usuário.")
            outros = [c for c in pagina.locator("input:visible").all()
                      if (c.get_attribute("type") or "text").lower() not in ("password", "hidden", "checkbox")
                      and c.get_attribute("id") != "user"]
            if outros:
                return self._parar_login("o OM pediu mais um dado junto com a senha.")
            campo_senha.fill(cred[1])
            botao_prosseguir.click()
            self._log_login("senha preenchida e Prosseguir clicado")
            limite = time.time() + 30
            while time.time() < limite and not self.sessao:
                pagina.wait_for_timeout(500)
                if not self.sessao:
                    self._sessao_pelas_telas()
            if not self.sessao:
                return self._parar_login("o login não terminou. Pode ser senha recusada, código ou troca de senha.")
            self.mensagem = "Conectado ao Sankhya-OM."
        except Exception as e:
            self._log_login(f"erro no login automático: {e.__class__.__name__}")
            self._parar_login("a página do OM não seguiu o caminho esperado.")

    def ocultar(self):
        """Oculta de novo a janela que o usuário pediu para ver."""
        def fazer():
            if self._ctx is not None:
                self._ocultar_janela()
            return True
        return self._executar(fazer)

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
            self._janela("normal")   # o usuário precisa da janela para abrir a tela
            self._minimizada_em = None
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
                    self._janela("normal")   # a mensagem pede para usar a janela: ela não pode estar oculta
                    self._minimizada_em = None
                    raise RuntimeError("A licença da tela Consulta de OS expirou no Sankhya-OM. Abra a tela "
                                       "'Consulta de OS' de novo pelo menu do OM, na janela da Central, e tente outra vez.")
                if "sess" in str(msg).lower() or str(j.get("status")) == "3":
                    self.sessao = None
                    self.estado = "desconectado"
                    self.mensagem = "A sessão do Sankhya-OM expirou. Conecte de novo."
                raise RuntimeError(f"OM: {msg}")
            return j
        return self._executar(fazer, timeout=180)

    # ---------------------------------------------------------------- Central de Vendas
    # 05/11/2026: ajuste de horas de pedido (ver om_ajuste_pedido.py). A tela abre numa aba própria
    # da janela do OM, para não tirar a Consulta de OS do lugar.
    URL_TELA_CENTRAL = ("https://skw.sankhya.com.br/mge/system.jsp#app/"
                        "YnIuY29tLnNhbmtoeWEuY29tLm1vdi5DZW50cmFsTm90YXM=")
    RESOURCE_CENTRAL = "br.com.sankhya.com.mov.CentralNotas"

    def _token_central(self):
        mge = self.sessao["mgeSession"]
        pronto = lambda: getattr(self, "sktk_central", None) and self.sktk_central[0] == mge
        if not pronto():
            pagina = getattr(self, "_pagina_central", None)
            if pagina is None or pagina.is_closed():
                pagina = self._ctx.new_page()
                self._pagina_central = pagina
            pagina.goto(self.URL_TELA_CENTRAL, wait_until="domcontentloaded", timeout=60000)
            limite = time.time() + 45
            while time.time() < limite and not pronto():
                pagina.wait_for_timeout(500)
        if not pronto():
            raise RuntimeError("A Central de Vendas não abriu na janela do Sankhya-OM. Nada foi alterado. "
                               "Clique em 'Mostrar janela do OM' para ver o que aconteceu e tente de novo.")
        return self.sktk_central[1]

    def chamar_central(self, modulo, servico, corpo):
        """POST com a licença da Central de Vendas. Só status "1" é sucesso: qualquer aviso do OM vira erro."""
        if not self.sessao:
            raise RuntimeError("Sankhya-OM não conectado. Conecte e faça o login.")

        def fazer():
            self._abrir()
            sktk = self._token_central()
            r = self._ctx.request.post(
                f"https://skw.sankhya.com.br/{modulo}/service.sbr",
                params={"serviceName": servico, "application": "CentralNotasStack", "outputType": "json",
                        "preventTransform": "false", "mgeSession": self.sessao["mgeSession"],
                        "resourceID": self.RESOURCE_CENTRAL, "vss": "1"},
                headers={"Content-Type": "application/json; charset=UTF-8", "Origin": "https://skw.sankhya.com.br",
                         "Referer": "https://skw.sankhya.com.br/mgecom/CentralNotasStack.xhtml5", "sktk": sktk},
                data=json.dumps({"serviceName": servico, "requestBody": corpo}), timeout=120000)
            try:
                j = json.loads(r.text())
            except ValueError:
                raise RuntimeError(f"O OM respondeu algo inesperado (HTTP {r.status}). A sessão pode ter expirado.")
            if str(j.get("status")) != "1":
                raise RuntimeError(f"O OM não confirmou ({servico}): {j.get('statusMessage') or j.get('statusMessageID') or str(j)[:300]}")
            return j
        return self._executar(fazer, timeout=180)

    # 06/11/2026 (Fragoso): portal de chamados (ajuda.sankhya.com.br, Zendesk) com o mesmo login Sankhya ID.
    PORTAL_CHAMADOS = "https://ajuda.sankhya.com.br"

    def ler_chamado(self, numero):
        """
        Só leitura: status e últimas respostas de um chamado do portal, pela sessão do navegador da Central.
        Se o portal pedir login, abre a página do chamado (o login Sankhya ID costuma entrar sozinho) e tenta de
        novo uma vez. Devolve {"request": {...}, "comments": [...], "users": [...]} ou levanta RuntimeError.
        """
        numero = int(numero)

        def api():
            r1 = self._ctx.request.get(f"{self.PORTAL_CHAMADOS}/api/v2/requests/{numero}.json",
                                       params={"include": "users"}, timeout=60000)
            if r1.status != 200:
                return None, r1.status
            r2 = self._ctx.request.get(f"{self.PORTAL_CHAMADOS}/api/v2/requests/{numero}/comments.json",
                                       params={"sort_order": "desc", "per_page": "5", "include": "users"}, timeout=60000)
            comentarios = json.loads(r2.text()) if r2.status == 200 else {}
            corpo1 = json.loads(r1.text())
            req = corpo1.get("request") or {}
            req["status_label"] = rotulo_status(req)
            # 06/11/2026 (Fragoso): quem é quem no chamado (solicitante, atribuído, você) para distinguir quem respondeu
            usuarios = {u.get("id"): u for u in (corpo1.get("users") or []) + (comentarios.get("users") or []) if u.get("id")}
            return {"request": req, "comments": comentarios.get("comments") or [], "users": list(usuarios.values()),
                    "eu": eu_no_portal()}, 200

        def eu_no_portal():
            if getattr(self, "_eu_portal", None) is None:
                try:
                    r = self._ctx.request.get(f"{self.PORTAL_CHAMADOS}/api/v2/users/me.json", timeout=30000)
                    self._eu_portal = (json.loads(r.text()).get("user") or {}).get("id") if r.status == 200 else None
                except Exception:
                    self._eu_portal = None
            return self._eu_portal

        def rotulo_status(req):
            """06/11/2026 (Fragoso): o rótulo que o portal mostra (status personalizado, ex.: "resolvido - aguardando
            validação do cliente"). Pela API de status personalizados; se não der, pela própria tela do chamado."""
            cid = req.get("custom_status_id")
            if cid:
                try:
                    r = self._ctx.request.get(f"{self.PORTAL_CHAMADOS}/api/v2/custom_statuses/{cid}.json", timeout=30000)
                    if r.status == 200:
                        cs = json.loads(r.text()).get("custom_status") or {}
                        rot = cs.get("end_user_label") or cs.get("agent_label")
                        if rot:
                            return rot
                except Exception:
                    pass
            # 06/11/2026 (Fragoso: "fica abrindo várias telas"): lê o HTML da tela do chamado sem abrir aba,
            # pela mesma sessão (cookies) do navegador da Central. O rótulo vem pronto no HTML do portal.
            try:
                r = self._ctx.request.get(f"{self.PORTAL_CHAMADOS}/hc/pt-br/requests/{numero}", timeout=60000)
                if r.status == 200:
                    m = re.search(r'class="[^"]*status-label[^"]*"[^>]*>\s*([^<]+?)\s*<', r.text())
                    if m:
                        return html_mod.unescape(m.group(1)).strip()
            except Exception:
                pass
            return ""

        def fazer():
            self._abrir()
            dados, status = api()
            if dados is not None:
                return dados
            if status == 404:
                raise RuntimeError("Chamado não encontrado no portal (ou sem acesso para este login).")
            pagina = self._ctx.new_page()
            try:
                pagina.goto(f"{self.PORTAL_CHAMADOS}/hc/pt-br/requests/{numero}", wait_until="load", timeout=60000)
                try:
                    pagina.wait_for_url(f"{self.PORTAL_CHAMADOS}/hc/**", timeout=30000)
                except Exception:
                    pass
                dados, status = api()
                if dados is not None:
                    pagina.close()
                    return dados
                # 06/11/2026 (Fragoso): o andamento se lê na própria tela do chamado depois do login no ID.
                if "/hc/" in (pagina.url or "") and f"/requests/{numero}" in (pagina.url or ""):
                    dados = self._ler_tela_chamado(pagina, numero)
                    if dados:
                        pagina.close()
                        return dados
            except Exception:
                pass
            raise RuntimeError("O portal de chamados pediu login. Entre com o Sankhya ID na janela do navegador da "
                               "Central e clique em Atualizar de novo.")
        return self._executar(fazer, timeout=180)

    _JS_TELA_CHAMADO = r"""() => {
        const t = (el) => (el ? (el.innerText || el.textContent || '').trim() : '');
        const titulo = t(document.querySelector('h1'));
        let status = '';
        const rotulo = document.querySelector('[class*="status-label"], .request-status, [data-status]');
        if (rotulo) status = t(rotulo);
        if (!status) {
          for (const dt of document.querySelectorAll('dt')) {
            if (/status/i.test(t(dt))) { status = t(dt.nextElementSibling); break; }
          }
        }
        const comentarios = [...document.querySelectorAll('.comment, li[id^="request_comment"], article.comment')].map((c) => ({
          autor: t(c.querySelector('.comment-author, [class*="author"]')).split('\n')[0],
          quando: (c.querySelector('time[datetime]') || {}).getAttribute ? c.querySelector('time[datetime]').getAttribute('datetime') : '',
          texto: t(c.querySelector('.comment-body, [class*="comment-body"], .zd-comment')) || t(c),
        })).filter((c) => c.texto);
        return { titulo, status, comentarios };
    }"""
    _STATUS_TELA = {"novo": "new", "aberto": "open", "aguardando": "pending", "pendente": "pending", "em espera": "hold",
                    "resolvido": "solved", "solucionado": "solved", "fechado": "closed", "encerrado": "closed"}

    def _ler_tela_chamado(self, pagina, numero):
        """Lê título, status e a última resposta da tela do chamado (quando a API do portal não responde)."""
        try:
            pagina.wait_for_selector("h1", timeout=20000)
        except Exception:
            return None
        d = pagina.evaluate(self._JS_TELA_CHAMADO)
        if not d or not d.get("titulo"):
            return None
        rotulo = (d.get("status") or "").strip().lower()
        status = next((v for k, v in self._STATUS_TELA.items() if k in rotulo), rotulo)
        comentarios = d.get("comentarios") or []
        ult = max(comentarios, key=lambda c: c.get("quando") or "") if comentarios else None
        return {"request": {"id": numero, "status": status, "subject": d["titulo"], "status_label": d.get("status") or "",
                            "updated_at": (ult or {}).get("quando") or ""},
                "comments": [{"author_id": 0, "created_at": ult.get("quando"), "plain_body": ult.get("texto")}] if ult else [],
                "users": [{"id": 0, "name": (ult or {}).get("autor") or ""}]}

    def status(self):
        pronta = bool(self.sessao and self.sktk_consulta and self.sktk_consulta[0] == self.sessao["mgeSession"])
        return {"estado": self.estado, "mensagem": self.mensagem, "consulta_pronta": pronta,
                "janela_oculta": self.janela_oculta,
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

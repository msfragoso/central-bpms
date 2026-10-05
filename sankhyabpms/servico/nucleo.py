# -*- coding: utf-8 -*-
"""
Núcleo do serviço local da Central BP-MS (HTML5).

- Lê config.json (pasta dos motores, porta).
- Põe as pastas dos motores no sys.path (os motores continuam em
  C:\\sankhya_integracao até a mudança para sankhyabpms -- basta trocar
  "pasta_motores" no config.json).
- Gerente de tarefas: roda UM processo longo por vez (conferência, Fase 3,
  aceite, sync), com log ao vivo, perguntas Sim/Não para a página e
  arquivos de saída para baixar. Um por vez de propósito: vários motores
  gravam arquivos na pasta atual (os.chdir) e o sync nunca pode rodar em
  paralelo consigo mesmo.
"""
import json
import os
import sys
import threading
import time
import traceback
import uuid
from datetime import date, datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_WEB = os.path.join(RAIZ, "web")
PASTA_DADOS = os.path.join(RAIZ, "dados")

CONFIG_PADRAO = {"pasta_motores": r"C:\sankhya_integracao", "porta": 8766, "abrir_navegador": True}


def ler_config():
    cfg = dict(CONFIG_PADRAO)
    try:
        with open(os.path.join(RAIZ, "config.json"), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


CONFIG = ler_config()
MOTORES = os.path.normpath(CONFIG["pasta_motores"])
PASTAS = {
    "raiz": MOTORES,
    "conferencia": os.path.join(MOTORES, "conferencia_os"),
    "aceite": os.path.join(MOTORES, "aceite_os"),
    "clickup_tasks": os.path.join(MOTORES, "clickup_tasks"),
}


def preparar_sys_path():
    for p in (PASTAS["raiz"], PASTAS["conferencia"], PASTAS["aceite"], PASTAS["clickup_tasks"]):
        if p not in sys.path:
            sys.path.append(p)


def para_json(obj):
    """json.dumps que aceita date/datetime/set/DataFrame (vira texto)."""
    def padrao(o):
        if isinstance(o, (date, datetime)):
            return o.strftime("%d/%m/%Y")
        if isinstance(o, set):
            return sorted(o)
        return str(o)
    return json.dumps(obj, ensure_ascii=False, default=padrao)


def dados_arquivo(nome):
    os.makedirs(PASTA_DADOS, exist_ok=True)
    return os.path.join(PASTA_DADOS, nome)


def ler_json_dados(nome, padrao=None):
    try:
        with open(dados_arquivo(nome), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def gravar_json_dados(nome, valor):
    with open(dados_arquivo(nome), "w", encoding="utf-8") as f:
        json.dump(valor, f, ensure_ascii=False, indent=2)


def marcar_uso(chave):
    usos = ler_json_dados("ultimo_uso.json", {}) or {}
    usos[chave] = datetime.now().strftime("%d/%m %H:%M")
    gravar_json_dados("ultimo_uso.json", usos)


# ============================================================================
# TAREFAS (processos longos)
# ============================================================================

class Cancelada(Exception):
    pass


class Tarefa:
    def __init__(self, tipo, titulo):
        self.id = uuid.uuid4().hex[:12]
        self.tipo = tipo
        self.titulo = titulo
        self.estado = "rodando"          # rodando | aguardando | concluida | erro | cancelada
        self.inicio = datetime.now()
        self.fim = None
        self.mensagem = ""
        self.resultado = None
        self.arquivos = []               # [(rotulo, caminho)]
        self._linhas = []
        self._parcial = ""
        self._lock = threading.Lock()
        self._pergunta = None
        self._evento = threading.Event()
        self._resposta = None

    # ---- log
    def escrever(self, texto):
        if not texto:
            return
        with self._lock:
            texto = self._parcial + str(texto)
            partes = texto.split("\n")
            self._parcial = partes.pop()
            self._linhas.extend(partes)

    def log(self, msg):
        self.escrever(str(msg) + "\n")

    def linhas_desde(self, n):
        with self._lock:
            linhas = self._linhas[n:]
            total = len(self._linhas)
            if self._parcial and self.estado not in ("rodando", "aguardando"):
                linhas = linhas + [self._parcial]
        return linhas, total

    # ---- perguntas para a página (bloqueiam o motor até a resposta)
    def perguntar(self, titulo, texto, opcoes):
        """opcoes = [{"valor": ..., "rotulo": ..., "estilo": "primario|perigo|neutro"}]"""
        with self._lock:
            self._pergunta = {"id": uuid.uuid4().hex[:8], "titulo": titulo, "texto": texto, "opcoes": opcoes}
            self._evento.clear()
            self.estado = "aguardando"
        self._evento.wait()
        with self._lock:
            self._pergunta = None
            self.estado = "rodando"
            return self._resposta

    def responder(self, pergunta_id, valor):
        with self._lock:
            if not self._pergunta or self._pergunta["id"] != pergunta_id:
                return False
            self._resposta = valor
        self._evento.set()
        return True

    def adicionar_arquivo(self, rotulo, caminho):
        if caminho:
            caminho = os.path.abspath(caminho)
            if os.path.isfile(caminho):
                self.arquivos.append((rotulo, caminho))

    def estado_json(self, desde=0):
        linhas, total = self.linhas_desde(desde)
        return {
            "id": self.id, "tipo": self.tipo, "titulo": self.titulo, "estado": self.estado,
            "inicio": self.inicio.strftime("%d/%m/%Y %H:%M:%S"),
            "fim": self.fim.strftime("%d/%m/%Y %H:%M:%S") if self.fim else None,
            "mensagem": self.mensagem, "resultado": self.resultado,
            "linhas": linhas, "total_linhas": total,
            "pergunta": self._pergunta,
            "arquivos": [{"indice": i, "rotulo": r, "nome": os.path.basename(c)}
                         for i, (r, c) in enumerate(self.arquivos)],
        }


class Ocupado(Exception):
    def __init__(self, tarefa):
        super().__init__(f"Já existe um processo rodando: {tarefa.titulo}")
        self.tarefa = tarefa


class Gerente:
    def __init__(self):
        self.tarefas = {}
        self.ativa = None
        self._lock = threading.Lock()

    def iniciar(self, tipo, titulo, funcao, pasta=None):
        """
        funcao(tarefa) roda numa thread; o que ela imprimir vai para o log da
        tarefa. Retorno: dict com "mensagem" (texto final) e opcional
        "resultado" (dados para a página).
        """
        with self._lock:
            if self.ativa and self.ativa.estado in ("rodando", "aguardando"):
                raise Ocupado(self.ativa)
            t = Tarefa(tipo, titulo)
            self.tarefas[t.id] = t
            self.ativa = t
            # guarda só as 30 últimas
            for antigo in list(self.tarefas)[:-30]:
                self.tarefas.pop(antigo, None)

        def rodar():
            cwd_antes = os.getcwd()
            try:
                if pasta:
                    os.chdir(pasta)
                retorno = funcao(t) or {}
                t.mensagem = retorno.get("mensagem", "Concluído.")
                t.resultado = retorno.get("resultado")
                t.estado = retorno.get("estado", "concluida")
            except Cancelada as e:
                t.log(f"\n⏹ CANCELADO: {e}")
                t.mensagem = str(e) or "Cancelado pelo usuário."
                t.estado = "cancelada"
            except BaseException as e:  # noqa: BLE001 -- SystemExit dos motores também conta
                t.log(f"\n❌ ERRO: {e}")
                t.log(traceback.format_exc())
                t.mensagem = str(e) or e.__class__.__name__
                t.estado = "erro"
            finally:
                t.fim = datetime.now()
                try:
                    os.chdir(cwd_antes)
                except OSError:
                    pass

        threading.Thread(target=rodar, daemon=True, name=f"tarefa-{t.id}").start()
        return t

    def obter(self, tarefa_id):
        return self.tarefas.get(tarefa_id)


GERENTE = Gerente()


class RoteadorSaida:
    """
    Substitui sys.stdout/sys.stderr: enquanto há tarefa rodando, tudo que os
    motores imprimem vai para o log dela (como a ScrolledText das telas Tk).
    Sem tarefa, vai para o console original (se existir -- no pythonw é None).
    """
    def __init__(self, original):
        self.original = original
        self.encoding = "utf-8"

    def write(self, texto):
        t = GERENTE.ativa
        if t is not None and t.estado in ("rodando", "aguardando"):
            t.escrever(texto)
        if self.original is not None:
            try:
                self.original.write(texto)
            except Exception:
                pass
        return len(texto) if texto else 0

    def flush(self):
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def instalar_roteador():
    if not isinstance(sys.stdout, RoteadorSaida):
        sys.stdout = RoteadorSaida(sys.stdout)
    if not isinstance(sys.stderr, RoteadorSaida):
        sys.stderr = RoteadorSaida(sys.stderr)


# ============================================================================
# ROTAS
# ============================================================================

ROTAS = {}   # (metodo, caminho) -> funcao(req) -> (status, corpo)


class Requisicao:
    def __init__(self, metodo, caminho, query, corpo):
        self.metodo = metodo
        self.caminho = caminho
        self.query = query      # dict str -> str
        self.corpo = corpo      # dict (JSON) ou {}
        self.partes = []        # pedaços variáveis do caminho (ex.: id da tarefa)


class ErroUsuario(Exception):
    """Erro de validação: vira HTTP 400 com a mensagem para mostrar na tela."""


def rota(metodo, caminho):
    def registrar(f):
        ROTAS[(metodo, caminho)] = f
        return f
    return registrar


def resolver_rota(metodo, caminho):
    f = ROTAS.get((metodo, caminho))
    if f:
        return f, []
    # rotas com parâmetro: /api/tarefas/<id>, /api/tarefas/<id>/responder ...
    pedacos = caminho.strip("/").split("/")
    for (m, modelo), f in ROTAS.items():
        if m != metodo:
            continue
        mp = modelo.strip("/").split("/")
        if len(mp) != len(pedacos):
            continue
        vars_ = []
        for a, b in zip(mp, pedacos):
            if a == "*":
                vars_.append(b)
            elif a != b:
                break
        else:
            return f, vars_
    return None, []


def data_br(texto, campo="Data"):
    """'DD/MM/AAAA' -> date. ErroUsuario se inválida."""
    try:
        return datetime.strptime((texto or "").strip().replace("-", "/"), "%d/%m/%Y").date()
    except ValueError:
        raise ErroUsuario(f"{campo} inválida. Use DD/MM/AAAA.")


def periodo_br(de, ate):
    a, b = data_br(de, "Data inicial"), data_br(ate, "Data final")
    if a > b:
        raise ErroUsuario("A data inicial é maior que a final.")
    return a, b


def exigir_confirmacao(req):
    """Ações que enviam ou alteram dados só rodam com confirmar=true (vem do modal da página)."""
    if req.corpo.get("confirmar") is not True:
        raise ErroUsuario("Ação não confirmada.")


def agora_txt():
    return time.strftime("%d/%m/%Y %H:%M:%S")

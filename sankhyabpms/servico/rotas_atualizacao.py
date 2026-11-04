# -*- coding: utf-8 -*-
"""
Atualização online (04/11/2026, pedido do Fragoso), da Central e do pacote Lançar ClickUp.

Ao abrir uma tela, a página pergunta se há versão nova no GitHub. Se houver, aparece
"Atualizar agora": só com a confirmação da pessoa o serviço baixa a versão, confere o
pacote, guarda cópia do que vai trocar em dados/atualizacoes e reinicia.

- Central: baixa a etiqueta vX.Y.Z do repositório. Não troca config.json, dados/ e dist/.
  Os motores de C:\\sankhya_integracao ficam fora do repositório e não são atualizados.
- Pacote Lançar (config.json com "atualizacao": "lancar"): baixa o .zip anexado à versão
  (Release) no GitHub, que já traz os motores sem nomes e e-mails (ver criar_pacote_lancar.py).
  Não troca central/config.json e central/dados/; o token fica no cofre do Windows.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

from atualizador import HISTORICO, MANIFESTO, registrar, restaurar
from nucleo import CONFIG, GERENTE, PASTA_DADOS, RAIZ, ErroUsuario, exigir_confirmacao, rota

REPO = "msfragoso/central-bpms"
URL_RAW = f"https://raw.githubusercontent.com/{REPO}/main/sankhyabpms/"
URL_ZIP = f"https://github.com/{REPO}/archive/refs/tags/v{{versao}}.zip"
URL_VERSAO_PACOTE = f"https://github.com/{REPO}/releases/latest/download/versao.json"
URL_PACOTE = f"https://github.com/{REPO}/releases/download/v{{versao}}/Lancar_ClickUp_BP-MS.zip"
PASTA_PACOTE = "Lancar_ClickUp_BP-MS"
ARQ_VERSAO = "web/assets/comum.js"
LIMITE_ZIP = 50 * 1024 * 1024
RE_VERSAO = re.compile(r'const VERSAO = "(\d+\.\d+\.\d+)"')
VALIDADE_CONSULTA = 600

OBRIGATORIOS_SERVICO = ("servico/servidor.py", "servico/nucleo.py", "servico/atualizador.py", ARQ_VERSAO)
# Só o que o instalador copia para a pasta do programa (instalar.ps1).
ITENS_PACOTE = {"central", "motores", "configurar_token.py", "configurar_token.vbs", "Abrir_Lancar_ClickUp.vbs",
                "Configurar_Token_ClickUp.bat", "Desinstalar.bat", "desinstalar.ps1", "LEIA-ME.txt"}

_cache = {"quando": 0, "dados": None}
_trava = threading.Lock()
_em_andamento = threading.Event()


def modo():
    """"central", "lancar" ou None (outro pacote limitado, que não se atualiza por aqui)."""
    if not CONFIG.get("modulos"):
        return "central"
    return "lancar" if CONFIG.get("atualizacao") == "lancar" else None


def raiz_arquivos(m):
    return os.path.dirname(RAIZ) if m == "lancar" else RAIZ


def _relativo(partes, m):
    """Caminho dentro da instalação, ou None se o arquivo do .zip não faz parte dela."""
    if m == "lancar":
        return "/".join(partes[1:]) if len(partes) >= 2 and partes[0] == PASTA_PACOTE else None
    return "/".join(partes[2:]) if len(partes) >= 3 and partes[1] == "sankhyabpms" else None


def _pode_trocar(relativo, m):
    if m == "lancar":
        return (relativo.split("/")[0] in ITENS_PACOTE and relativo != "central/config.json"
                and not relativo.startswith("central/dados/"))
    return relativo not in {"config.json", ".gitignore"} and not relativo.startswith(("dados/", "dist/", "pacote-lancar/"))


def _prefixo(m):
    return "central/" if m == "lancar" else ""


def pasta_atualizacoes():
    return os.path.join(PASTA_DADOS, "atualizacoes")


def _numeros(versao):
    return tuple(int(n) for n in versao.split("."))


def versao_local():
    with open(os.path.join(RAIZ, *ARQ_VERSAO.split("/")), encoding="utf-8") as f:
        achou = RE_VERSAO.search(f.read())
    if not achou:
        raise RuntimeError("Não encontrei a versão instalada.")
    return achou.group(1)


def _baixar(url, limite=LIMITE_ZIP, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "CentralBPMS"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dados = r.read(limite + 1)
    if len(dados) > limite:
        raise ErroUsuario("O pacote da atualização é maior do que o esperado.")
    return dados


def novidades(changelog, local, nova):
    """Trechos do CHANGELOG das versões depois da instalada, até a nova."""
    partes = re.split(r"(?m)^## (?=\d+\.\d+\.\d+)", changelog)[1:]
    saida = []
    for parte in partes:
        v = parte.split()[0]
        if _numeros(local) < _numeros(v) <= _numeros(nova):
            saida.append("## " + parte.strip())
    return "\n\n".join(saida)[:4000]


def _consultar_github(m, local):
    if m == "lancar":
        info = json.loads(_baixar(URL_VERSAO_PACOTE).decode("utf-8"))
        return {"versao_nova": info["versao"], "sha256": info["sha256"], "novidades": info.get("novidades", "")}
    achou = RE_VERSAO.search(_baixar(URL_RAW + ARQ_VERSAO).decode("utf-8"))
    if not achou:
        raise RuntimeError("versão não encontrada")
    nova = achou.group(1)
    texto = ""
    if _numeros(nova) > _numeros(local):
        texto = novidades(_baixar(URL_RAW + "CHANGELOG.md").decode("utf-8"), local, nova)
    return {"versao_nova": nova, "sha256": None, "novidades": texto}


def consultar(forcar=False):
    """Compara a versão instalada com a do GitHub. Sem internet, só não oferece atualização."""
    local = versao_local()
    base = {"versao_local": local, "versao_nova": None, "disponivel": False, "novidades": "", "sha256": None}
    m = modo()
    if not m:
        return {**base, "motivo": "Este pacote não se atualiza por aqui."}
    agora = time.time()
    with _trava:
        if forcar or not _cache["dados"] or agora - _cache["quando"] >= VALIDADE_CONSULTA:
            try:
                dados = _consultar_github(m, local)
                if not re.fullmatch(r"\d+\.\d+\.\d+", dados["versao_nova"]):
                    raise ValueError("versão inválida")
            except Exception as e:  # noqa: BLE001 -- sem internet a tela segue normal
                return {**base, "motivo": f"Não consegui consultar o GitHub: {e.__class__.__name__}"}
            _cache.update(quando=agora, dados=dados)
        dados = _cache["dados"]
    return {**base, **dados, "disponivel": _numeros(dados["versao_nova"]) > _numeros(local)}


def conferir_pacote(conteudo, versao, m="central"):
    """Devolve {caminho relativo: bytes} do pacote, ou recusa se algo estiver errado."""
    try:
        pacote = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile:
        raise ErroUsuario("O pacote baixado está corrompido. Nada foi alterado.")
    arquivos = {}
    for info in pacote.infolist():
        if info.is_dir():
            continue
        partes = info.filename.replace("\\", "/").split("/")
        relativo = _relativo(partes, m)
        if relativo is None:
            continue
        if ".." in partes or ":" in relativo or relativo.startswith("/"):
            raise ErroUsuario(f"Pacote recusado: caminho inválido ({info.filename}). Nada foi alterado.")
        if not _pode_trocar(relativo, m) or "__pycache__" in partes:
            continue
        dados = pacote.read(info)
        if relativo.lower().endswith((".bat", ".vbs")):
            # O pacote do GitHub vem com fim de linha LF; .bat e .vbs precisam de CRLF no Windows.
            dados = dados.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        arquivos[relativo] = dados
    arq_versao = _prefixo(m) + ARQ_VERSAO
    faltando = [o for o in (_prefixo(m) + p for p in OBRIGATORIOS_SERVICO) if o not in arquivos]
    if faltando:
        raise ErroUsuario(f"Pacote recusado: faltam {', '.join(faltando)}. Nada foi alterado.")
    achou = RE_VERSAO.search(arquivos[arq_versao].decode("utf-8"))
    if not achou or achou.group(1) != versao:
        raise ErroUsuario(f"Pacote recusado: não é a versão {versao}. Nada foi alterado.")
    for relativo, dados in arquivos.items():
        if relativo.endswith(".py"):
            try:
                compile(dados, relativo, "exec")
            except (SyntaxError, ValueError) as e:
                raise ErroUsuario(f"Pacote recusado: erro em {relativo} ({e}). Nada foi alterado.")
    return arquivos


def instalar(arquivos, de, para, raiz=None, pasta=None):
    """Guarda a cópia do que muda e troca os arquivos. Se falhar no meio, desfaz. Devolve a pasta da cópia."""
    raiz = raiz or RAIZ
    pasta = pasta or pasta_atualizacoes()
    backup = os.path.join(pasta, f"antes_de_v{para}_era_v{de}")
    shutil.rmtree(backup, ignore_errors=True)
    os.makedirs(backup)
    alterados, novos = [], []
    for relativo, dados in arquivos.items():
        atual = os.path.join(raiz, *relativo.split("/"))
        if not os.path.isfile(atual):
            novos.append(relativo)
            continue
        with open(atual, "rb") as f:
            if f.read() == dados:
                continue
        copia = os.path.join(backup, *relativo.split("/"))
        os.makedirs(os.path.dirname(copia), exist_ok=True)
        shutil.copy2(atual, copia)
        alterados.append(relativo)
    with open(os.path.join(backup, MANIFESTO), "w", encoding="utf-8") as f:
        json.dump({"de": de, "para": para, "alterados": alterados, "novos": novos}, f, ensure_ascii=False, indent=1)
    try:
        for relativo in alterados + novos:
            destino = os.path.join(raiz, *relativo.split("/"))
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            temporario = destino + ".novo"
            with open(temporario, "wb") as f:
                f.write(arquivos[relativo])
            os.replace(temporario, destino)
    except Exception as e:
        restaurar(raiz, backup)
        raise ErroUsuario(f"Não consegui trocar os arquivos ({e}). A versão atual foi mantida.")
    return backup


def _reiniciar(raiz_dos_arquivos, backup, ajudante):
    """Espera os processos em andamento, passa para o atualizador e encerra este serviço."""
    limite = time.time() + 600
    while GERENTE.ativas and time.time() < limite:
        time.sleep(1)
    time.sleep(1)   # deixa a resposta chegar à página
    subprocess.Popen([sys.executable, ajudante, str(os.getpid()), RAIZ, raiz_dos_arquivos, backup,
                      str(CONFIG.get("porta") or 8766)],
                     cwd=RAIZ, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    os._exit(0)


@rota("GET", "/api/atualizacao/status")
def status(req):
    info = consultar()
    info.pop("sha256", None)
    return 200, {**info, "em_andamento": _em_andamento.is_set()}


@rota("GET", "/api/atualizacao/historico")
def historico(req):
    arq = os.path.join(pasta_atualizacoes(), HISTORICO)
    if not os.path.isfile(arq):
        return 200, {"eventos": []}
    with open(arq, encoding="utf-8") as f:
        return 200, {"eventos": [json.loads(l) for l in f if l.strip()][-20:]}


@rota("POST", "/api/atualizacao/aplicar")
def aplicar(req):
    exigir_confirmacao(req)
    m = modo()
    if not m:
        raise ErroUsuario("Este pacote não se atualiza por aqui.")
    if _em_andamento.is_set():
        raise ErroUsuario("A atualização já está em andamento.")
    ativas = GERENTE.ativas
    if ativas:
        raise ErroUsuario(f"Espere terminar antes de atualizar: {ativas[0].titulo}.")
    info = consultar(forcar=True)
    if not info["disponivel"]:
        raise ErroUsuario(info.get("motivo") or "Já está na versão mais recente.")
    _em_andamento.set()
    try:
        de, para = info["versao_local"], info["versao_nova"]
        url = URL_PACOTE if m == "lancar" else URL_ZIP
        conteudo = _baixar(url.format(versao=para), timeout=60)
        if m == "lancar" and hashlib.sha256(conteudo).hexdigest() != info["sha256"]:
            raise ErroUsuario("O pacote baixado não confere com o publicado. Nada foi alterado.")
        arquivos = conferir_pacote(conteudo, para, m)
        pasta = pasta_atualizacoes()
        os.makedirs(pasta, exist_ok=True)
        # O atualizador roda desta cópia: a versão atual, já testada, é quem confere a nova.
        ajudante = os.path.join(pasta, "atualizador.py")
        shutil.copy2(os.path.join(RAIZ, "servico", "atualizador.py"), ajudante)
        raiz = raiz_arquivos(m)
        backup = instalar(arquivos, de, para, raiz=raiz, pasta=pasta)
        registrar(pasta, evento="arquivos trocados", de=de, para=para)
    except BaseException:
        _em_andamento.clear()
        raise
    threading.Thread(target=_reiniciar, args=(raiz, backup, ajudante), daemon=True, name="atualizacao").start()
    return 200, {"versao_nova": para, "mensagem": f"Atualizando para a versão {para}."}

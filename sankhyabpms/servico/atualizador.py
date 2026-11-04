# -*- coding: utf-8 -*-
"""
Finaliza a atualização online, fora do serviço (ver rotas_atualizacao.py).

Espera o serviço antigo encerrar, sobe o novo e confere se ele responde. Se não
responder, devolve os arquivos da cópia de segurança e sobe a versão anterior.
Só usa a biblioteca padrão, porque roda enquanto os arquivos do serviço são trocados.

Uso: atualizador.py <pid do serviço> <pasta do serviço> <pasta dos arquivos> <cópia de segurança> <porta>
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

MANIFESTO = "_manifesto.json"
HISTORICO = "historico.jsonl"
ESPERA_SUBIR = 45


def registrar(pasta_atualizacoes, **campos):
    os.makedirs(pasta_atualizacoes, exist_ok=True)
    campos = {"quando": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), **campos}
    with open(os.path.join(pasta_atualizacoes, HISTORICO), "a", encoding="utf-8") as f:
        f.write(json.dumps(campos, ensure_ascii=False) + "\n")


def restaurar(raiz, backup):
    """Devolve os arquivos da cópia de segurança e apaga os que a atualização criou."""
    with open(os.path.join(backup, MANIFESTO), encoding="utf-8") as f:
        manifesto = json.load(f)
    for relativo in manifesto.get("alterados", []):
        destino = os.path.join(raiz, relativo)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        shutil.copy2(os.path.join(backup, relativo), destino)
    for relativo in manifesto.get("novos", []):
        try:
            os.remove(os.path.join(raiz, relativo))
        except FileNotFoundError:
            pass
    return manifesto


def _processo_vivo(pid):
    import ctypes
    k = ctypes.WinDLL("kernel32")
    k.OpenProcess.restype = ctypes.c_void_p
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
    if not h:
        return False
    try:
        return k.WaitForSingleObject(h, 0) == 258   # WAIT_TIMEOUT: ainda rodando
    finally:
        k.CloseHandle(h)


def _subir_servico(raiz_servico):
    subprocess.Popen([sys.executable, os.path.join("servico", "servidor.py"), "--sem-navegador"], cwd=raiz_servico,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)


def _respondendo(porta, segundos=ESPERA_SUBIR):
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/", timeout=3) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    return False


def main(pid, raiz_servico, raiz_arquivos, backup, porta):
    pasta = os.path.dirname(backup)
    limite = time.time() + 60
    while _processo_vivo(pid) and time.time() < limite:
        time.sleep(0.5)
    time.sleep(1)   # a porta precisa ser liberada
    _subir_servico(raiz_servico)
    if _respondendo(porta):
        registrar(pasta, evento="serviço novo respondeu", backup=os.path.basename(backup))
        return
    manifesto = restaurar(raiz_arquivos, backup)
    registrar(pasta, evento="serviço novo não respondeu: versão anterior restaurada",
              de=manifesto.get("de"), para=manifesto.get("para"))
    _subir_servico(raiz_servico)


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))

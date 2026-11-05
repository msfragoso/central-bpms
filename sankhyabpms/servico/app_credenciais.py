# -*- coding: utf-8 -*-
"""
Tela Credenciais: senha do Experience guardada no cofre do Windows (05/11/2026, pedido do Fragoso).

Depois de trocar a senha no Experience, a pessoa grava a nova por esta tela: testa o login uma
vez e só grava no cofre se o Experience aceitar. A senha nunca vai para log, arquivo ou resposta.
Esta rota só atende a página servida pelo próprio serviço (ver servidor.py), não o site do GitHub.

Aviso de senha expirada: qualquer processo que tente entrar passa por _login_com_aviso, que guarda o
motivo da recusa em dados/ e limpa o aviso quando um login dá certo. O Experience não informa a
validade com antecedência: o aviso aparece na primeira recusa.
"""
from datetime import datetime
import sys
import threading
import time

import experience_api as _exp
from experience_api import auth as _auth
from nucleo import ErroUsuario, exigir_confirmacao, gravar_json_dados, ler_json_dados, marcar_uso, rota

SERVICO = "sankhya_experience_sync"
ESPERA_ENTRE_TENTATIVAS = 60   # repetir login recusado pode bloquear a conta
_trava = threading.Lock()
_ultima_recusa = {"quando": 0}
ARQ_AVISO = "credenciais_aviso.json"
_login_original = _exp.login


def _login_com_aviso(usuario, senha):
    token = _login_original(usuario, senha)
    if token:
        if ler_json_dados(ARQ_AVISO):
            gravar_json_dados(ARQ_AVISO, {})
        return token
    motivo = _auth.ULTIMA_RECUSA.get("mensagem")
    if motivo:   # sem motivo é falha de rede: não diz nada sobre a senha
        gravar_json_dados(ARQ_AVISO, {"motivo": motivo, "expirada": "expirad" in motivo.lower(),
                                      "quando": datetime.now().strftime("%d/%m/%Y %H:%M")})
    return token


_exp.login = _login_com_aviso


def _atualizar_em_memoria(usuario, senha):
    """Os motores guardam a senha ao importar. Atualiza quem já carregou, sem precisar reiniciar."""
    for modulo in list(sys.modules.values()):
        try:
            if hasattr(modulo, "EXPERIENCE_PASS"):
                modulo.EXPERIENCE_PASS = senha
                modulo.EXPERIENCE_USER = usuario
        except Exception:
            pass


@rota("GET", "/api/credenciais/experience")
def ver(req):
    import keyring
    return 200, {"usuario": keyring.get_password(SERVICO, "EXPERIENCE_USER") or "", "aviso": ler_json_dados(ARQ_AVISO) or None}


@rota("GET", "/api/credenciais/aviso")
def aviso(req):
    return 200, {"aviso": ler_json_dados(ARQ_AVISO) or None}


@rota("POST", "/api/credenciais/experience")
def gravar(req):
    exigir_confirmacao(req)
    import keyring
    senha = req.corpo.get("senha")
    if not isinstance(senha, str) or not senha.strip():
        raise ErroUsuario("Digite a senha nova.")
    senha = senha.strip()
    usuario = keyring.get_password(SERVICO, "EXPERIENCE_USER") or ""
    if "@" not in usuario:
        raise ErroUsuario("Usuário do Experience não encontrado no cofre.")
    if not _trava.acquire(blocking=False):
        raise ErroUsuario("Já há um teste de login em andamento.")
    try:
        resta = ESPERA_ENTRE_TENTATIVAS - (time.time() - _ultima_recusa["quando"])
        if resta > 0:
            raise ErroUsuario(f"Espere {int(resta) + 1}s antes de tentar de novo, para não bloquear a conta.")
        # Sem passar pelo aviso: uma senha digitada errada aqui não diz nada sobre a que está no cofre.
        if not _login_original(usuario, senha):
            _ultima_recusa["quando"] = time.time()
            motivo = _auth.ULTIMA_RECUSA.get("mensagem") or "sem resposta do Experience"
            raise ErroUsuario(f"O Experience recusou o teste ({motivo}). Nada foi gravado. Confira se a senha já foi trocada no Experience.")
        keyring.set_password(SERVICO, "EXPERIENCE_PASS", senha)
        _atualizar_em_memoria(usuario, senha)
        gravar_json_dados(ARQ_AVISO, {})
        marcar_uso("credenciais")
    finally:
        _trava.release()
    return 200, {"ok": True, "usuario": usuario, "quando": time.strftime("%d/%m/%Y %H:%M")}

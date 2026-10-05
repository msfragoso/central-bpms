/* Central BP-MS — login (só no site do GitHub). Aberta pelo serviço do PC
   (127.0.0.1) a tela entra direto, porque só o próprio PC chega nela. */
"use strict";
(function () {
  if (["127.0.0.1", "localhost"].includes(location.hostname)) return;
  document.documentElement.classList.add("trava-login");

  const FB = "https://www.gstatic.com/firebasejs/10.12.2/";
  const base = document.currentScript.src.replace(/login\.js(\?.*)?$/, "");
  const carregar = (src) => new Promise((ok, falha) => {
    const s = document.createElement("script");
    s.src = src; s.onload = ok; s.onerror = falha;
    document.head.append(s);
  });
  const MSG = {
    "auth/invalid-credential": "E-mail ou senha incorretos.",
    "auth/wrong-password": "E-mail ou senha incorretos.",
    "auth/user-not-found": "E-mail ou senha incorretos.",
    "auth/invalid-email": "Digite um e-mail válido.",
    "auth/too-many-requests": "Muitas tentativas. Espere alguns minutos e tente de novo.",
    "auth/network-request-failed": "Sem conexão com o servidor de login. Confira a internet.",
    "auth/user-disabled": "Este acesso foi desativado. Fale com o administrador.",
  };

  function telaLogin(auth) {
    let caixa = document.getElementById("login");
    if (caixa) { caixa.hidden = false; return; }
    caixa = document.createElement("div");
    caixa.id = "login"; caixa.className = "login";
    caixa.innerHTML = `<form class="card" novalidate>
      <h1>Central BP-MS</h1>
      <p class="suave">Entre com seu e-mail e senha.</p>
      <div class="campo"><label for="login-email">E-mail</label><input id="login-email" type="email" autocomplete="username" required></div>
      <div class="campo"><label for="login-senha">Senha</label><input id="login-senha" type="password" autocomplete="current-password" required></div>
      <button class="btn" type="submit">Entrar</button>
      <button class="link" type="button" data-esqueci>Esqueci a senha</button>
      <p class="erro" role="alert"></p>
    </form>`;
    document.body.append(caixa);
    const form = caixa.querySelector("form");
    const erro = (m) => { caixa.querySelector(".erro").textContent = m || ""; };
    const btn = form.querySelector("[type=submit]");
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); erro("");
      const email = form.querySelector("#login-email").value.trim();
      const senha = form.querySelector("#login-senha").value;
      if (!email || !senha) return erro("Preencha e-mail e senha.");
      btn.disabled = true; btn.textContent = "Entrando…";
      try { await auth.signInWithEmailAndPassword(email, senha); }
      catch (err) { erro(MSG[err.code] || `Não foi possível entrar (${err.code}).`); }
      finally { btn.disabled = false; btn.textContent = "Entrar"; }
    });
    form.querySelector("[data-esqueci]").addEventListener("click", async () => {
      const email = form.querySelector("#login-email").value.trim();
      if (!email) return erro("Digite seu e-mail acima e clique de novo em Esqueci a senha.");
      try { await auth.sendPasswordResetEmail(email); erro("Se o e-mail estiver cadastrado, o link para nova senha chega em instantes."); }
      catch (err) { erro(MSG[err.code] || `Não foi possível enviar o e-mail (${err.code}).`); }
    });
    form.querySelector("#login-email").focus();
  }

  function botaoSair(auth, user) {
    const topo = document.querySelector(".topo-dentro");
    if (!topo || document.getElementById("botao-sair")) return;
    const b = document.createElement("button");
    b.id = "botao-sair"; b.className = "botao-tema"; b.textContent = "Sair";
    b.title = `Sair (${user.email})`;
    b.onclick = () => auth.signOut();
    topo.append(b);
  }

  const pronto = new Promise((ok) => (document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", ok) : ok()));
  Promise.all([carregar(FB + "firebase-app-compat.js"), carregar(base + "firebase-config.js")])
    .then(() => carregar(FB + "firebase-auth-compat.js"))
    .then(() => pronto)
    .then(() => {
      firebase.initializeApp(window.FIREBASE_CONFIG);
      const auth = firebase.auth();
      auth.setPersistence(firebase.auth.Auth.Persistence.LOCAL).catch(() => {});
      auth.onAuthStateChanged((user) => {
        if (user) {
          document.getElementById("login")?.remove();
          document.documentElement.classList.remove("trava-login");
          botaoSair(auth, user);
        } else {
          document.documentElement.classList.add("trava-login");
          telaLogin(auth);
        }
      });
    })
    .catch(() => pronto.then(() => {
      document.body.insertAdjacentHTML("beforeend",
        '<div id="login" class="login"><div class="card"><h1>Central BP-MS</h1><p class="erro">Não consegui carregar o login. Confira a internet e recarregue a página.</p></div></div>');
    }));
})();

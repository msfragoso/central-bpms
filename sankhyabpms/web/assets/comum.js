/* Central BP-MS — componentes comuns de todas as telas HTML5 */
"use strict";

const BPMS = (() => {
  const TELAS = [
    { id: "inicio", href: "index.html", rotulo: "Início" },
    { id: "lancar", href: "lancar.html", rotulo: "Lançar ClickUp" },
    { id: "sync", href: "sync.html", rotulo: "Sync tarefa ClickUp ⇄ Experience" },
    { id: "conferencia", href: "conferencia.html", rotulo: "Conferência de OS" },
    { id: "fase3", href: "fase3.html", rotulo: "Apontamentos travados" },
    { id: "aceite", href: "aceite.html", rotulo: "Aceite de OS" },
  ];

  // ------------------------------------------------------------ util
  const $ = (sel, raiz = document) => raiz.querySelector(sel);
  const $$ = (sel, raiz = document) => Array.from(raiz.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const normalizar = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  const hojeBR = (dias = 0) => { const d = new Date(); d.setDate(d.getDate() + dias); return d.toLocaleDateString("pt-BR"); };

  function lerTema() { try { return localStorage.getItem("bpms-tema"); } catch (e) { return null; } }
  function gravarTema(t) { try { localStorage.setItem("bpms-tema", t); } catch (e) { /* sem storage */ } }
  const temaSalvo = lerTema();
  if (temaSalvo) document.documentElement.dataset.theme = temaSalvo;

  // ------------------------------------------------------------ API
  async function api(metodo, caminho, corpo) {
    const op = { method: metodo, headers: {} };
    if (corpo !== undefined) {
      op.headers["Content-Type"] = "application/json";
      op.headers["X-BPMS"] = "1";
      op.body = JSON.stringify(corpo);
    }
    let resp;
    try {
      resp = await fetch(caminho, op);
    } catch (e) {
      throw new Error("Serviço local fora do ar. Abra a Central pelo atalho Iniciar_Central.");
    }
    let dados = {};
    try { dados = await resp.json(); } catch (e) { /* sem corpo */ }
    if (!resp.ok) {
      const erro = new Error(dados.erro || `Erro ${resp.status}`);
      erro.status = resp.status; erro.dados = dados;
      throw erro;
    }
    return dados;
  }
  const get = (c) => api("GET", c);
  const post = (c, corpo = {}) => api("POST", c, corpo);

  // ------------------------------------------------------------ cabeçalho
  function montarTopo(ativo) {
    const topo = document.createElement("header");
    topo.className = "topo";
    topo.innerHTML = `<div class="topo-dentro">
      <a class="marca" href="index.html"><span class="selo">BP</span>Central BP-MS</a>
      <nav class="nav">${TELAS.map((t) => `<a href="${t.href}" class="${t.id === ativo ? "ativo" : ""}" data-texto="nav.${t.id}">${t.rotulo}</a>`).join("")}</nav>
      <span class="pilula" id="pilula-servico">verificando…</span>
      <button class="botao-tema" id="botao-editar" title="Editar os textos desta tela">✎</button>
      <button class="botao-tema" id="botao-tema" title="Tema claro/escuro">◐</button>
    </div>`;
    document.body.prepend(topo);
    $("#botao-editar").onclick = () => (document.body.classList.contains("editando") ? null : editarTextos());
    aplicarTextos();
    $("#botao-tema").onclick = () => {
      const escuro = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      const novo = escuro ? "light" : "dark";
      document.documentElement.dataset.theme = novo;
      gravarTema(novo);
    };
    const toasts = document.createElement("div");
    toasts.className = "toasts"; toasts.id = "toasts";
    document.body.append(toasts);
    atualizarPilula();
    setInterval(atualizarPilula, 5000);
  }

  let ultimoStatus = null;
  async function atualizarPilula() {
    const p = $("#pilula-servico");
    try {
      const s = await get("/api/status");
      ultimoStatus = s;
      if (s.ativa) { p.className = "pilula rodando"; p.textContent = `rodando: ${s.ativa.titulo}`; }
      else if (!s.motores_encontrados) { p.className = "pilula erro"; p.textContent = "pasta dos motores não encontrada"; }
      else { p.className = "pilula ok"; p.textContent = "serviço local ok"; }
      $$("[data-ultimo-uso]").forEach((el) => {
        const v = s.ultimo_uso[el.dataset.ultimoUso];
        el.textContent = v ? `último uso ${v}` : "";
      });
      return s;
    } catch (e) {
      p.className = "pilula erro"; p.textContent = "serviço fora do ar";
      return null;
    }
  }

  // ------------------------------------------------------------ textos editáveis
  // Elementos com data-texto="chave" (títulos, descrições, menu) podem ser
  // reescritos pelo botão ✎ do topo; o serviço guarda em dados/textos.json.
  let textosSalvos = {};
  function guardarPadroes() {
    $$("[data-texto]").forEach((el) => { if (el.dataset.padrao === undefined) el.dataset.padrao = el.textContent.trim(); });
  }
  async function aplicarTextos() {
    guardarPadroes();
    try { textosSalvos = (await get("/api/textos")).textos || {}; } catch (e) { return; }
    $$("[data-texto]").forEach((el) => {
      const v = textosSalvos[el.dataset.texto];
      el.textContent = v !== undefined ? v : el.dataset.padrao;
    });
  }

  function editarTextos() {
    guardarPadroes();
    const els = $$("[data-texto]");
    const antes = new Map(els.map((el) => [el, el.textContent]));
    document.body.classList.add("editando");
    els.forEach((el) => {
      el.contentEditable = "plaintext-only";
      if (el.contentEditable !== "plaintext-only") el.contentEditable = "true";
      el.spellcheck = true;
    });
    const evitarEnter = (e) => { if (e.key === "Enter" && e.target.closest?.("[data-texto]")) { e.preventDefault(); e.target.blur(); } };
    const evitarLink = (e) => { if (e.target.closest("[data-texto]")) e.preventDefault(); };
    document.addEventListener("keydown", evitarEnter, true);
    document.addEventListener("click", evitarLink, true);

    const barra = document.createElement("div");
    barra.className = "barra-edicao";
    barra.innerHTML = `<span>✎ Clique em qualquer título ou descrição marcado e escreva.</span>
      <button class="btn secundario pequeno" data-a="padrao">Restaurar padrão</button>
      <button class="btn secundario pequeno" data-a="cancelar">Cancelar</button>
      <button class="btn pequeno" data-a="salvar">Salvar textos</button>`;
    document.body.append(barra);

    function sair() {
      els.forEach((el) => el.removeAttribute("contenteditable"));
      document.body.classList.remove("editando");
      document.removeEventListener("keydown", evitarEnter, true);
      document.removeEventListener("click", evitarLink, true);
      barra.remove();
    }
    barra.onclick = async (e) => {
      const a = e.target.dataset.a;
      if (a === "cancelar") { antes.forEach((t, el) => { el.textContent = t; }); sair(); }
      else if (a === "padrao") {
        if (await confirmar("Restaurar textos padrão?", "Todos os textos editáveis desta tela voltam ao original.", { botao: "Restaurar" })) {
          els.forEach((el) => { el.textContent = el.dataset.padrao; });
        }
      } else if (a === "salvar") {
        const textos = {};
        els.forEach((el) => {
          const v = el.textContent.replace(/\s+/g, " ").trim();
          const chave = el.dataset.texto;
          if (!v || v === el.dataset.padrao) { if (chave in textosSalvos) textos[chave] = null; }
          else if (v !== textosSalvos[chave]) textos[chave] = v;
        });
        try {
          if (Object.keys(textos).length) textosSalvos = (await post("/api/textos", { textos })).textos;
          sair(); aplicarTextos();
          toast("Textos salvos.", "ok");
        } catch (err) { toast(err.message, "erro"); }
      }
    };
  }

  // ------------------------------------------------------------ toast / modal
  function toast(msg, tipo = "") {
    const t = document.createElement("div");
    t.className = `toast ${tipo}`; t.textContent = msg;
    $("#toasts").append(t);
    setTimeout(() => t.remove(), tipo === "erro" ? 9000 : 5000);
  }

  /** opcoes: [{valor, rotulo, estilo: primario|perigo|neutro}] -> Promise(valor) */
  function modal({ titulo, texto = "", html = "", opcoes, perigo = false }) {
    return new Promise((resolver) => {
      const fundo = document.createElement("div");
      fundo.className = "fundo-modal";
      fundo.innerHTML = `<div class="modal ${perigo ? "perigo" : ""}" role="dialog" aria-modal="true">
        <h3>${esc(titulo)}</h3><div class="corpo">${html || esc(texto)}</div><div class="rodape"></div></div>`;
      const rodape = $(".rodape", fundo);
      opcoes.forEach((o, i) => {
        const b = document.createElement("button");
        b.className = "btn " + ({ perigo: "perigo", neutro: "secundario" }[o.estilo] || "");
        b.textContent = o.rotulo;
        b.onclick = () => { fundo.remove(); resolver(o.valor); };
        rodape.append(b);
        if (i === opcoes.length - 1) setTimeout(() => b.focus(), 30);
      });
      document.body.append(fundo);
    });
  }
  const confirmar = (titulo, html, { botao = "Confirmar", perigo = false } = {}) =>
    modal({ titulo, html, perigo, opcoes: [
      { valor: false, rotulo: "Cancelar", estilo: "neutro" },
      { valor: true, rotulo: botao, estilo: perigo ? "perigo" : "primario" },
    ] });
  const informar = (titulo, html) => modal({ titulo, html, opcoes: [{ valor: true, rotulo: "OK" }] });

  // ------------------------------------------------------------ tarefa (processo longo)
  /**
   * Acompanha uma tarefa do serviço: log ao vivo, perguntas, arquivos.
   * el: {log, status, statusTexto, arquivos}; aoTerminar(estadoFinal)
   */
  function acompanhar(tarefaId, el, aoTerminar) {
    let desde = 0, perguntaAberta = null, parado = false;
    if (el.log) el.log.textContent = "";
    el.status?.classList.add("ativo");
    if (el.arquivos) el.arquivos.innerHTML = "";
    async function ciclo() {
      if (parado) return;
      let t;
      try {
        t = await get(`/api/tarefas/${tarefaId}?desde=${desde}`);
      } catch (e) {
        if (el.statusTexto) el.statusTexto.textContent = e.message;
        setTimeout(ciclo, 2000);
        return;
      }
      if (t.linhas.length && el.log) {
        const perto = el.log.scrollHeight - el.log.scrollTop - el.log.clientHeight < 40;
        el.log.textContent += t.linhas.join("\n") + "\n";
        if (perto) el.log.scrollTop = el.log.scrollHeight;
      }
      desde = t.total_linhas;
      if (el.statusTexto) {
        el.statusTexto.textContent = { rodando: `${t.titulo} — rodando…`, aguardando: `${t.titulo} — aguardando sua resposta` }[t.estado] || t.mensagem;
      }
      if (t.pergunta && perguntaAberta !== t.pergunta.id) {
        perguntaAberta = t.pergunta.id;
        modal({ titulo: t.pergunta.titulo, texto: t.pergunta.texto, opcoes: t.pergunta.opcoes })
          .then((valor) => post(`/api/tarefas/${tarefaId}/responder`, { pergunta_id: t.pergunta.id, valor }))
          .catch((e) => toast(e.message, "erro"));
      }
      if (t.estado === "rodando" || t.estado === "aguardando") {
        setTimeout(ciclo, 700);
        return;
      }
      parado = true;
      el.status?.classList.remove("ativo");
      if (el.arquivos) mostrarArquivos(el.arquivos, t);
      atualizarPilula();
      toast(t.mensagem, t.estado === "concluida" ? "ok" : t.estado === "erro" ? "erro" : "");
      aoTerminar && aoTerminar(t);
    }
    ciclo();
    return { parar: () => { parado = true; } };
  }

  function mostrarArquivos(caixa, t) {
    caixa.innerHTML = t.arquivos.map((a) => {
      const base = `/api/tarefas/${t.id}/arquivo/${a.indice}`;
      const html = /\.html?$/i.test(a.nome);
      return `<a class="btn secundario pequeno" href="${base}${html ? "?ver=1" : ""}" ${html ? 'target="_blank" rel="noopener"' : ""}>⬇ ${esc(a.rotulo)}</a>`;
    }).join("");
  }

  /** Se há tarefa destes tipos rodando (ex.: página recarregada), volta a acompanhá-la. */
  async function retomar(tipos, el, aoTerminar, aoRetomar) {
    const s = ultimoStatus || (await atualizarPilula());
    if (s && s.ativa && tipos.includes(s.ativa.tipo)) {
      aoRetomar && aoRetomar(s.ativa);
      return acompanhar(s.ativa.id, el, aoTerminar);
    }
    return null;
  }

  /** Inicia uma tarefa (POST) e acompanha; trata "já tem processo rodando". */
  async function iniciar(caminho, corpo, el, aoTerminar) {
    try {
      const r = await post(caminho, corpo);
      return acompanhar(r.tarefa, el, aoTerminar);
    } catch (e) {
      if (e.status === 409) {
        await informar("Processo em andamento", `${esc(e.message)}<br><br>Aguarde ele terminar (veja a pílula no topo).`);
      } else {
        toast(e.message, "erro");
      }
      aoTerminar && aoTerminar(null);
      return null;
    }
  }

  // ------------------------------------------------------------ campos
  function mascaraData(input) {
    input.placeholder = input.placeholder || "dd/mm/aaaa";
    input.inputMode = "numeric";
    input.maxLength = 10;
    input.addEventListener("input", () => {
      const d = input.value.replace(/\D/g, "").slice(0, 8);
      input.value = d.length > 4 ? `${d.slice(0, 2)}/${d.slice(2, 4)}/${d.slice(4)}` : d.length > 2 ? `${d.slice(0, 2)}/${d.slice(2)}` : d;
    });
  }
  function dataValida(txt) {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec((txt || "").trim());
    if (!m) return null;
    const d = new Date(+m[3], +m[2] - 1, +m[1]);
    return d.getDate() === +m[1] && d.getMonth() === +m[2] - 1 ? d : null;
  }

  /**
   * Busca com autocompletar, sem acento e sem maiúscula (como o CampoBusca da tela Tk).
   * Enter/Tab confirma o item marcado. onEscolher(valor).
   */
  function busca(input, opcoes, { onEscolher, livre = false } = {}) {
    const caixa = document.createElement("div");
    caixa.className = "busca";
    input.parentNode.insertBefore(caixa, input);
    caixa.append(input);
    input.autocomplete = "off";
    const lista = document.createElement("ul");
    lista.className = "busca-lista oculto";
    caixa.append(lista);
    let itens = opcoes.slice(), filtrados = [], marcado = 0;

    function desenhar() {
      const q = normalizar(input.value);
      filtrados = q ? itens.filter((o) => normalizar(o).includes(q)) : itens.slice();
      filtrados.sort((a, b) => (normalizar(b).startsWith(q) - normalizar(a).startsWith(q)));
      marcado = Math.min(marcado, Math.max(filtrados.length - 1, 0));
      lista.innerHTML = filtrados.length
        ? filtrados.slice(0, 80).map((o, i) => `<li data-i="${i}" class="${i === marcado ? "marcado" : ""}">${esc(o)}</li>`).join("")
        : `<li class="vazio">nenhuma opção</li>`;
      lista.classList.remove("oculto");
      lista.querySelector(".marcado")?.scrollIntoView({ block: "nearest" });
    }
    function fechar() { lista.classList.add("oculto"); }
    function escolher(v) {
      input.value = v; fechar();
      input.dispatchEvent(new Event("change"));
      onEscolher && onEscolher(v);
    }
    input.addEventListener("focus", desenhar);
    input.addEventListener("input", () => { marcado = 0; desenhar(); });
    input.addEventListener("blur", () => setTimeout(fechar, 150));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (lista.classList.contains("oculto")) return desenhar();
        marcado = (marcado + (e.key === "ArrowDown" ? 1 : -1) + filtrados.length) % Math.max(filtrados.length, 1);
        desenhar();
      } else if ((e.key === "Enter" || e.key === "Tab") && !lista.classList.contains("oculto") && filtrados.length && input.value) {
        if (e.key === "Enter") e.preventDefault();
        escolher(filtrados[marcado]);
      } else if (e.key === "Escape") fechar();
    });
    lista.addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); escolher(filtrados[+li.dataset.i]); }
    });
    return {
      valido: () => livre || itens.includes(input.value),
      definirOpcoes: (novas) => { itens = novas.slice(); },
    };
  }

  /** Tabela ordenável por clique no cabeçalho (th[data-ordem="chave"]). */
  function ordenavel(tabela, aoOrdenar) {
    let estado = { chave: null, desc: false };
    $$("th[data-ordem]", tabela).forEach((th) => {
      th.onclick = () => {
        const chave = th.dataset.ordem;
        estado = { chave, desc: estado.chave === chave ? !estado.desc : false };
        $$("th[data-ordem]", tabela).forEach((x) => x.classList.remove("asc", "desc"));
        th.classList.add(estado.desc ? "desc" : "asc");
        aoOrdenar(estado);
      };
    });
    return () => estado;
  }
  function comparar(a, b) {
    const na = typeof a === "number" ? a : normalizar(a), nb = typeof b === "number" ? b : normalizar(b);
    return na < nb ? -1 : na > nb ? 1 : 0;
  }

  function arquivoBase64(arquivo) {
    return new Promise((ok, falha) => {
      const r = new FileReader();
      r.onload = () => ok(String(r.result).split(",")[1] || "");
      r.onerror = () => falha(new Error("Não consegui ler o arquivo."));
      r.readAsDataURL(arquivo);
    });
  }

  return { $, $$, esc, normalizar, hojeBR, api, get, post, montarTopo, atualizarPilula, toast, modal, confirmar, informar,
           acompanhar, retomar, iniciar, mascaraData, dataValida, busca, ordenavel, comparar, arquivoBase64 };
})();

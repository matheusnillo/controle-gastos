const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const brl = (v) => (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const monthLabel = (m) => {
  const [y, mo] = m.split("-").map(Number);
  if (window.innerWidth < 560) {  // celular: "Set/26"
    const short = new Date(y, mo - 1, 1).toLocaleDateString("pt-BR", { month: "short" }).replace(".", "");
    return short[0].toUpperCase() + short.slice(1) + "/" + String(y).slice(2);
  }
  const s = new Date(y, mo - 1, 1).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
  return s[0].toUpperCase() + s.slice(1);
};
const shortMonth = (m) => {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1, 1).toLocaleDateString("pt-BR", { month: "short" }).replace(".", "");
};

const PALETTE = ["#0f766e", "#2563eb", "#d97706", "#db2777", "#7c3aed", "#16a34a", "#dc2626", "#0891b2", "#65a30d", "#9333ea", "#ea580c", "#475569"];
const GROUP_LABEL = { essencial: "Essenciais", desejo: "Desejos", perda: "Tarifas e juros (perda)", indefinido: "Sem categoria clara" };
const SEVERITY_LABEL = { alta: "Urgente", media: "Atenção", baixa: "Dica", info: "Info" };

const state = { status: null, month: null, summary: null, categories: [], charts: {}, mode: "fatura" };
try { state.mode = localStorage.getItem("modo") || "fatura"; } catch {}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json();
  if (res.status === 401 && data.login) {
    location.href = "login.html";  // acesso pelo celular sem sessão: pede o PIN
    throw new Error(data.erro);
  }
  if (!res.ok) throw new Error(data.erro || `Erro ${res.status}`);
  return data;
}

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

async function busy(btn, fn) {
  const label = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = "Aguarde…"; }
  try { return await fn(); }
  catch (e) { toast(e.message, 6000); }
  finally { if (btn) { btn.disabled = false; btn.textContent = label; } }
}

// ------------------------------------------------------------------- navegação
function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== `tab-${name}`));
  try { localStorage.setItem("tab", name); } catch {}
  if (name === "transacoes") loadTransactions();
  if (name === "orcamentos") renderBudgets();
  if (name === "conexoes") renderConnections();
  if (name === "alertas") loadConfig().catch((e) => toast(e.message));
}

// ------------------------------------------------------------------- carregamento
async function refresh() {
  state.status = await api(`/api/status?modo=${state.mode}`);
  const s = state.status;
  const hasData = s.temDados;
  $("#empty").classList.toggle("hidden", hasData);
  $$(".tab-panel, .tabs").forEach((el) => el.classList.toggle("hidden", !hasData));
  $("#month").classList.toggle("hidden", !hasData);
  $("#mode").classList.toggle("hidden", !hasData);
  $("#btn-sync").classList.toggle("hidden", !s.conexoes.length);
  $("#source-label").textContent = s.modoDemo ? "Dados de demonstração" :
    s.conexoes.length ? `Open Finance · ${s.conexoes.length} conexão(ões)` : hasData ? "Extratos importados" : "Open Finance";
  $("#empty-hint").textContent = s.pluggyConfigurado ? "" :
    "Para conectar bancos reais, preencha PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET no arquivo .env (veja o README).";
  if (!hasData) {
    // Sem dados: mostra as instruções de conexão junto com a tela inicial.
    $("#tab-conexoes").classList.remove("hidden");
    renderConnections();
    return;
  }

  const sel = $("#month");
  if (!s.meses.includes(state.month)) state.month = s.meses[0];
  sel.innerHTML = s.meses.map((m) => `<option value="${m}">${monthLabel(m)}</option>`).join("");
  sel.value = state.month;

  let tab = "painel";
  try { tab = localStorage.getItem("tab") || "painel"; } catch {}
  showTab(tab);
  await loadSummary();
}

async function loadSummary() {
  state.summary = await api(`/api/summary?month=${state.month}&modo=${state.mode}`);
  renderDashboard();
  renderInsights();
  if (!$("#tab-orcamentos").classList.contains("hidden")) renderBudgets();
}

// ------------------------------------------------------------------- painel
function renderDashboard() {
  const { resumo: r, insights, economia_potencial } = state.summary;
  $("#demo-banner").classList.toggle("hidden", !state.status.modoDemo);
  $("#k-income").textContent = brl(r.income);
  $("#k-expenses").textContent = brl(r.expenses);
  $("#k-projection").textContent = r.projection ? `projeção do mês: ${brl(r.projection)}` : "";
  const bal = $("#k-balance");
  bal.textContent = brl(r.balance);
  bal.className = r.balance >= 0 ? "pos" : "neg";
  $("#k-rate").textContent = r.savings_rate != null ? `${r.savings_rate.toLocaleString("pt-BR")}% da renda guardada` : "";
  $("#k-saving").textContent = brl(economia_potencial);

  // Rosca de categorias (top 8 + outros)
  const cats = r.categories.filter((c) => c.total > 0);
  const top = cats.slice(0, 8);
  const rest = cats.slice(8).reduce((a, c) => a + c.total, 0);
  const labels = top.map((c) => c.category).concat(rest ? ["Demais"] : []);
  const values = top.map((c) => c.total).concat(rest ? [rest] : []);
  drawChart("categories", {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: PALETTE, borderWidth: 0 }] },
    options: {
      maintainAspectRatio: false, cutout: "60%",
      plugins: {
        legend: { position: window.innerWidth < 560 ? "bottom" : "right", labels: { color: css("--text"), boxWidth: 12 } },
        tooltip: { callbacks: { label: (c) => `${c.label}: ${brl(c.parsed)} (${(c.parsed / r.expenses * 100).toFixed(0)}%)` } },
      },
    },
  });

  drawChart("trend", {
    type: "bar",
    data: {
      labels: r.trend.map((t) => shortMonth(t.month)),
      datasets: [
        { label: "Entradas", data: r.trend.map((t) => t.income), backgroundColor: css("--good"), borderRadius: 4 },
        { label: "Gastos", data: r.trend.map((t) => t.expenses), backgroundColor: css("--bad"), borderRadius: 4 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: css("--muted") }, grid: { display: false } },
        y: { ticks: { color: css("--muted"), callback: (v) => brl(v).replace(",00", "") }, grid: { color: css("--border") } },
      },
      plugins: {
        legend: { labels: { color: css("--text"), boxWidth: 12 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${brl(c.parsed.y)}` } },
      },
    },
  });

  // Grupos 50/30/20
  const ref = { essencial: 50, desejo: 30 };
  $("#groups").innerHTML = Object.entries(GROUP_LABEL).map(([g, label]) => {
    const v = r.groups[g] || 0;
    if (!v && !ref[g]) return "";
    const pctIncome = r.income ? (v / r.income) * 100 : 0;
    const over = ref[g] && pctIncome > ref[g];
    return `<div class="group-row">
      <div class="row"><span>${label}</span><span>${brl(v)} <span class="muted small">· ${pctIncome.toFixed(0)}% da renda${ref[g] ? ` (ideal ≤ ${ref[g]}%)` : ""}</span></span></div>
      <div class="bar ${over ? "over" : ""}"><span style="width:${Math.min(pctIncome, 100)}%"></span></div>
    </div>`;
  }).join("") + (r.income ? `<div class="group-row"><div class="row"><span>Sobrou / investiu</span>
      <span class="${r.balance >= 0 ? "pos" : "neg"}">${brl(r.balance)} <span class="muted small">· ${(r.balance / r.income * 100).toFixed(0)}% (ideal ≥ 20%)</span></span></div></div>` : "");

  $("#top-insights").innerHTML = insights.filter((i) => i.severidade !== "info").slice(0, 4).map((i) => `
    <div class="mini-insight">
      <span><span class="tag ${i.severidade}">${SEVERITY_LABEL[i.severidade]}</span> ${esc(i.titulo)}</span>
      ${i.economia_mensal ? `<span class="saving">−${brl(i.economia_mensal)}</span>` : ""}
    </div>`).join("") || `<p class="muted">Nenhum alerta neste mês. 👏</p>`;

  // Tabela de categorias
  $("#cat-table tbody").innerHTML = r.categories.map((c, idx) => {
    const trend = c.prev_avg ? ((c.total / c.prev_avg - 1) * 100) : null;
    const budget = c.budget ? (() => {
      const p = (c.total / c.budget) * 100;
      return `<div class="small">${brl(c.total)} / ${brl(c.budget)}</div>
        <div class="bar ${p > 100 ? "over" : p >= 85 ? "near" : ""}"><span style="width:${Math.min(p, 100)}%"></span></div>`;
    })() : `<span class="muted small">—</span>`;
    return `<tr>
      <td><span class="dot" style="background:${PALETTE[idx % PALETTE.length]}"></span>${esc(c.category)}</td>
      <td class="num">${brl(c.total)}${trend != null && Math.abs(trend) >= 10 ? ` <span class="small ${trend > 0 ? "neg" : "pos"}">${trend > 0 ? "▲" : "▼"}${Math.abs(trend).toFixed(0)}%</span>` : ""}</td>
      <td class="num muted">${c.prev_avg != null ? brl(c.prev_avg) : "—"}</td>
      <td class="num">${c.pct.toLocaleString("pt-BR")}%</td>
      <td>${budget}</td>
    </tr>`;
  }).join("");
}

function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

function drawChart(key, config) {
  if (!window.Chart) return;
  state.charts[key]?.destroy();
  state.charts[key] = new Chart($(`#chart-${key}`), config);
}

// ------------------------------------------------------------------- onde cortar
function renderInsights() {
  const { insights, economia_potencial } = state.summary;
  $("#saving-month").textContent = `${brl(economia_potencial)}/mês`;
  $("#saving-year").textContent = `≈ ${brl(economia_potencial * 12)} por ano`;
  $("#insights-list").innerHTML = insights.map((i) => `
    <div class="card insight ${i.severidade}">
      <div class="head">
        <div>
          <span class="tag ${i.severidade}">${SEVERITY_LABEL[i.severidade]}</span>
          <h4 style="margin-top:6px">${esc(i.titulo)}</h4>
        </div>
        ${i.economia_mensal ? `<div class="saving">economize ${brl(i.economia_mensal)}/mês${i.conta_no_total ? "" : " <span class='muted small'>(não somado)</span>"}</div>` : ""}
      </div>
      <p>${esc(i.detalhe)}</p>
      ${i.itens.length ? `<ul class="small">${i.itens.map(renderItem).join("")}</ul>` : ""}
      <div class="acao small"><strong>O que fazer:</strong> ${esc(i.acao)}</div>
    </div>`).join("") || `<div class="card"><p>Nada a cortar por aqui neste mês. Continue assim!</p></div>`;
}

function renderItem(it) {
  if (it.anual != null) {
    return `<li>${esc(it.nome)} — ${brl(it.valor)}/mês <span class="muted">(${brl(it.anual)}/ano)</span>${it.aumentou ? ` <span class="neg">▲ aumentou</span>` : ""}</li>`;
  }
  if (it.vezes != null) return `<li>${esc(it.nome)} — ${brl(it.valor)} em ${it.vezes}×</li>`;
  return `<li>${esc(it.nome)} — ${brl(it.valor)}${it.data ? ` <span class="muted">(${it.data.split("-").reverse().join("/")})</span>` : ""}</li>`;
}

// ------------------------------------------------------------------- transações
async function loadCategories() {
  state.categories = (await api("/api/categories")).categorias;
  $("#tx-category").innerHTML = `<option value="">Todas as categorias</option>` +
    state.categories.map((c) => `<option>${esc(c.nome)}</option>`).join("");
}

async function loadTransactions() {
  const q = new URLSearchParams({ modo: state.mode, month: state.month || "", category: $("#tx-category").value, q: $("#tx-search").value });
  const { transacoes } = await api(`/api/transactions?${q}`);
  const opts = (dir, cur) => state.categories
    .filter((c) => (dir === "in" ? ["receita", "neutro"] : ["essencial", "desejo", "perda", "indefinido", "neutro"]).includes(c.grupo))
    .map((c) => `<option ${c.nome === cur ? "selected" : ""}>${esc(c.nome)}</option>`).join("");
  $("#tx-table tbody").innerHTML = transacoes.map((t) => `
    <tr>
      <td class="small">${t.date.split("-").reverse().join("/")}</td>
      <td>${esc(t.description)}<div class="muted small">${esc(t.account_name)}</div></td>
      <td><select data-tx="${esc(t.id)}">${opts(t.direction, t.category)}</select></td>
      <td class="num ${t.direction === "in" ? "pos" : ""}">${t.direction === "in" ? "+" : "−"}${brl(t.amount)}</td>
    </tr>`).join("");
  const out = transacoes.filter((t) => t.direction === "out" && !["neutro"].includes(t.grupo)).reduce((a, t) => a + t.amount, 0);
  $("#tx-count").textContent = `${transacoes.length} transações · ${brl(out)} em gastos`;
}

async function changeCategory(sel) {
  const r = await api(`/api/transactions/${encodeURIComponent(sel.dataset.tx)}/category`, {
    method: "POST", body: { category: sel.value, applyToSimilar: $("#tx-similar").checked },
  });
  toast(r.chave
    ? `${r.atualizadas} transação(ões) atualizada(s). Regra criada para "${r.chave}".`
    : `${r.atualizadas} transação(ões) atualizada(s)`, 6000);
  await loadSummary();
  if (r.atualizadas > 1) loadTransactions();
}

async function exportCsv() {
  const q = new URLSearchParams({ modo: state.mode, month: state.month || "", category: $("#tx-category").value, q: $("#tx-search").value });
  const { csv } = await api(`/api/export?${q}`);
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `gastos-${state.month}.csv` });
  a.click();
  URL.revokeObjectURL(a.href);
}

// ------------------------------------------------------------------- orçamentos
function renderBudgets() {
  if (!state.summary) return;
  const r = state.summary.resumo;
  const spent = Object.fromEntries(r.categories.map((c) => [c.category, c]));
  const expenseCats = state.categories.filter((c) => ["essencial", "desejo", "perda", "indefinido"].includes(c.grupo));
  $("#budget-form tbody").innerHTML = expenseCats.map(({ nome }) => {
    const c = spent[nome] || {};
    const suggestion = c.prev_avg ? Math.round(c.prev_avg * 0.9 / 10) * 10 : null;
    return `<tr>
      <td>${esc(nome)}</td>
      <td class="num">${brl(c.total || 0)}</td>
      <td class="num muted">${suggestion ? brl(suggestion) : "—"}</td>
      <td class="num"><input type="number" min="0" step="10" name="${esc(nome)}" value="${c.budget ?? ""}" placeholder="${suggestion ?? ""}"></td>
    </tr>`;
  }).join("");
}

async function saveBudgets(e) {
  e.preventDefault();
  const body = Object.fromEntries($$("#budget-form input").map((i) => [i.name, i.value]));
  await api("/api/budgets", { method: "PUT", body });
  $("#budget-msg").textContent = "Salvo!";
  setTimeout(() => ($("#budget-msg").textContent = ""), 2000);
  await loadSummary();
}

// ------------------------------------------------------------------- conexões
function renderConnections() {
  const items = state.status?.conexoes || [];
  $("#connections").innerHTML = items.length ? items.map((i) => `
    <div class="conn">
      <div><strong>${esc(i.connector || "Banco")}</strong><div class="muted small">item ${esc(i.id)}</div></div>
      <div class="muted small">última sincronização: ${i.last_sync ? new Date(i.last_sync.replace(" ", "T") + "Z").toLocaleString("pt-BR") : "—"}</div>
    </div>`).join("") : `<p class="muted">Nenhum banco conectado ainda.</p>`;
}

async function connectBank(btn) {
  if (!state.status.pluggyConfigurado) {
    toast("Configure as credenciais da Pluggy no .env e reinicie o app — ou use \"Importar extrato\", que não precisa de cadastro.", 8000);
    return;
  }
  if (!window.PluggyConnect) {
    toast("Não foi possível carregar o widget da Pluggy. Verifique sua internet.", 6000);
    return;
  }
  await busy(btn, async () => {
    const { accessToken } = await api("/api/connect-token", { method: "POST", body: {} });
    const meuPluggy = state.status.meuPluggyConnectorId;
    const widget = new PluggyConnect({
      connectToken: accessToken,
      includeSandbox: state.status.incluirSandbox,
      // Meu Pluggy: conector gratuito para uso pessoal (outros bancos diretos exigem plano pago)
      ...(meuPluggy ? { connectorIds: [meuPluggy], selectedConnectorId: meuPluggy } : {}),
      onSuccess: ({ item }) => addItem(item.id),
      onError: (err) => toast(`Erro na conexão: ${err?.message || "desconhecido"}`, 10000),
    });
    widget.init();
  });
}

async function addItem(itemId) {
  console.info("Conexão Pluggy (itemId):", itemId);
  toast("Banco conectado! Aguardando o Meu Pluggy enviar as transações (pode levar até 2 minutos)…", 120000);
  try {
    const r = await api("/api/items", { method: "POST", body: { itemId } });
    toast(r.transacoes
      ? `${r.banco || "Banco"}: ${r.transacoes} transações importadas.`
      : `${r.banco || "Banco"} conectado, mas ainda sem transações. Tente "Sincronizar" em alguns minutos.`, 10000);
    state.month = null;
    await refresh();
  } catch (e) { toast(e.message, 10000); }
}

// ------------------------------------------------------------------- importação
const toBase64 = (buf) => {
  let bin = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
};

async function importFiles(files) {
  const arquivos = [];
  let cartao = null;
  for (const f of files) {
    const buf = await f.arrayBuffer();
    if (/\.(csv|txt)$/i.test(f.name) && cartao === null) {
      const header = new TextDecoder().decode(buf.slice(0, 200)).split(/\r?\n/)[0].trim().toLowerCase();
      if (header !== "date,title,amount") {
        cartao = confirm(`"${f.name}" é FATURA DE CARTÃO (compras aparecem com valor positivo)?\n\nOK = fatura de cartão\nCancelar = extrato de conta (saídas negativas)`);
      }
    }
    arquivos.push({ nome: f.name, conteudo: toBase64(buf) });
  }
  const { resultados } = await api("/api/import", { method: "POST", body: { arquivos, cartao } });
  const ok = resultados.filter((r) => !r.erro);
  const erros = resultados.filter((r) => r.erro);
  toast([
    ok.length ? `${ok.reduce((a, r) => a + r.transacoes, 0)} transações importadas de ${ok.length} arquivo(s).` : "",
    ...erros.map((r) => `${r.arquivo}: ${r.erro}`),
  ].filter(Boolean).join(" "), 7000);
  state.month = null;
  await refresh();
}

$("#item-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("#item-id").value.trim();
  if (id) { await addItem(id); $("#item-id").value = ""; }
});

$("#file-input").addEventListener("change", async (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  if (files.length) await importFiles(files).catch((err) => toast(err.message, 7000));
});

// ------------------------------------------------------------------- eventos
document.addEventListener("click", async (e) => {
  const el = e.target.closest("button");
  if (!el) return;
  if (el.dataset.tab) showTab(el.dataset.tab);
  if (el.dataset.goto) showTab(el.dataset.goto);
  if (el.dataset.action === "connect" || el.id === "btn-connect") connectBank(el);
  if (el.dataset.action === "import") $("#file-input").click();
  if (el.dataset.action === "demo") {
    await busy(el, async () => { await api("/api/demo", { method: "POST" }); state.month = null; await refresh(); toast("Dados de demonstração carregados."); });
  }
  if (el.id === "btn-sync") {
    await busy(el, async () => {
      toast("Sincronizando… pode levar até 2 minutos por banco.", 120000);
      const { resultados } = await api("/api/sync", { method: "POST" });
      const erros = resultados.filter((r) => r.erro).map((r) => `${r.banco || r.itemId}: ${r.erro}`);
      toast([`Sincronizado: ${resultados.reduce((a, r) => a + r.transacoes, 0)} transações verificadas.`, ...erros].join(" "), erros.length ? 12000 : 4000);
      await refresh();
    });
  }
  if (el.id === "btn-export") busy(el, exportCsv);
  if (el.id === "btn-clear" && confirm("Apagar todas as transações e conexões salvas neste computador?")) {
    await busy(el, async () => { await api("/api/data", { method: "DELETE" }); state.month = null; await refresh(); });
  }
});

$("#mode").value = state.mode;
$("#mode").addEventListener("change", async (e) => {
  state.mode = e.target.value;
  try { localStorage.setItem("modo", state.mode); } catch {}
  await refresh();
  if (!$("#tab-transacoes").classList.contains("hidden")) loadTransactions();
});
$("#month").addEventListener("change", async (e) => {
  state.month = e.target.value;
  await loadSummary();
  if (!$("#tab-transacoes").classList.contains("hidden")) loadTransactions();
});
let searchTimer;
$("#tx-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadTransactions, 250); });
$("#tx-category").addEventListener("change", loadTransactions);
$("#tx-table").addEventListener("change", (e) => { if (e.target.dataset.tx) changeCategory(e.target).catch((err) => toast(err.message)); });
$("#budget-form").addEventListener("submit", (e) => saveBudgets(e).catch((err) => toast(err.message)));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => state.summary && renderDashboard());

// ------------------------------------------------------------------- alertas e celular
const CHECKS = ["alertas_ativos", "alerta_tarifas", "alerta_orcamento", "alerta_assinaturas", "resumo_diario"];

async function loadConfig() {
  const c = await api("/api/config");
  const form = $("#wa-form");
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") el.checked = c[el.name] === "1";
    else el.value = c[el.name] ?? "";
  }
  $("#sync-hours").textContent = c.syncHoras;
  $("#wa-howto").open = !c.whatsappPronto;
  $("#wa-status").innerHTML = c.whatsappPronto
    ? (c.ultimoErro ? `<span class="neg">Último envio falhou: ${esc(c.ultimoErro)}</span>`
      : `<span class="pos">WhatsApp configurado.</span>${c.ultimoEnvio ? ` Última mensagem: ${esc(c.ultimoEnvio.replace("T", " "))}` : ""}`)
    : "Ainda não configurado.";
  $("#pin-msg").textContent = c.pinDefinido ? "PIN já definido — digite outro para trocar." : "";
  $("#pin-btn").textContent = c.pinDefinido ? "Trocar PIN" : "Salvar PIN";
  renderNuvem(await api("/api/nuvem"));
}

function renderNuvem(n) {
  const link = $("#nuvem-link");
  link.hidden = !n.site;
  if (n.site) link.href = n.site;
  $("#btn-nuvem-enviar").hidden = !n.ativa;
  $("#nuvem-status").innerHTML = !n.ativa
    ? "Desligado. Preencha GITHUB_TOKEN, GITHUB_REPO e NUVEM_SENHA no arquivo .env e reinicie o app."
    : n.ultimoErro
      ? `<span class="neg">Último envio falhou: ${esc(n.ultimoErro)}</span>`
      : `<span class="pos">Ligado</span> · repositório ${esc(n.repo)}${n.ultimoEnvio ? ` · ajustes enviados em ${esc(n.ultimoEnvio.replace("T", " "))}` : " · nenhum envio ainda"}`;
}

$("#btn-nuvem-enviar").addEventListener("click", (e) => busy(e.currentTarget, async () => {
  renderNuvem(await api("/api/nuvem/enviar", { method: "POST" }));
  toast("Ajustes enviados. O painel da nuvem atualiza em 1–2 minutos.");
}));

$("#wa-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {};
  for (const el of e.target.elements) {
    if (el.name) body[el.name] = el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value;
  }
  try {
    await api("/api/config", { method: "PUT", body });
    toast("Configurações salvas.");
    await loadConfig();
  } catch (err) { toast(err.message, 7000); }
});

$("#btn-wa-test").addEventListener("click", (e) => busy(e.currentTarget, async () => {
  await api("/api/whatsapp/teste", { method: "POST" });
  toast("Mensagem enviada! Confira o WhatsApp.");
  await loadConfig();
}));

$("#btn-wa-summary").addEventListener("click", (e) => busy(e.currentTarget, async () => {
  await api("/api/whatsapp/resumo", { method: "POST" });
  toast("Resumo enviado para o WhatsApp.");
}));

$("#pin-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/pin", { method: "POST", body: { pin: $("#pin-new").value } });
    $("#pin-new").value = "";
    toast("PIN salvo. Use-o para entrar pelo celular.");
    await loadConfig();
  } catch (err) { toast(err.message, 7000); }
});

// App instalável no celular (só funciona em HTTPS, ex.: pelo tailscale serve, ou no próprio PC).
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

(async () => {
  try {
    await loadCategories();
    await refresh();
  } catch (e) {
    toast(`Não foi possível falar com o servidor: ${e.message}`, 8000);
  }
})();

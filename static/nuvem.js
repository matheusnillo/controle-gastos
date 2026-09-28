// Modo nuvem (GitHub Pages): o painel funciona sem o computador ligado.
// Os dados chegam criptografados (dados.enc) e são decifrados AQUI, no aparelho, com a sua senha.
// A senha nunca sai do aparelho; opcionalmente guardamos a CHAVE derivada (não exportável) no IndexedDB.
(() => {
  const DB = "controle-gastos", STORE = "chave";
  let data = null;
  let ready;
  const dataReady = new Promise((r) => (ready = r));
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

  // ---------------------------------------------------------------- IndexedDB (chave lembrada)
  function idb(mode, fn) {
    return new Promise((resolve, reject) => {
      const open = indexedDB.open(DB, 1);
      open.onupgradeneeded = () => open.result.createObjectStore(STORE);
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const tx = open.result.transaction(STORE, mode);
        const req = fn(tx.objectStore(STORE));
        tx.oncomplete = () => resolve(req && req.result);
        tx.onerror = () => reject(tx.error);
      };
    });
  }
  const loadKey = () => idb("readonly", (s) => s.get("k")).catch(() => null);
  const saveKey = (v) => idb("readwrite", (s) => s.put(v, "k")).catch(() => {});
  const forgetKey = () => idb("readwrite", (s) => s.delete("k")).catch(() => {});

  // ---------------------------------------------------------------- cripto
  async function deriveKey(password, salt, iterations) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt, iterations },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  }

  async function decrypt(env, key) {
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(env.iv) }, key, b64(env.ct));
    const stream = new Blob([plain]).stream().pipeThrough(new DecompressionStream("gzip"));
    return JSON.parse(await new Response(stream).text());
  }

  // ---------------------------------------------------------------- tela de desbloqueio
  function askPassword(env, message) {
    return new Promise((resolve) => {
      const box = document.createElement("div");
      box.className = "unlock";
      box.innerHTML = `
        <form>
          <div class="logo">R$</div>
          <h2>Controle de Gastos</h2>
          <p class="muted">Digite a senha da nuvem para abrir seus dados.</p>
          <input type="password" autocomplete="current-password" required aria-label="Senha">
          <label class="small check"><input type="checkbox" checked> Lembrar neste aparelho</label>
          <button class="btn primary" type="submit">Abrir</button>
          <p class="erro small" role="alert"></p>
        </form>`;
      document.body.appendChild(box);
      const form = box.querySelector("form");
      const [pwd, remember] = form.querySelectorAll("input");
      const err = box.querySelector(".erro");
      err.textContent = message || "";
      pwd.focus();
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const btn = form.querySelector("button");
        btn.disabled = true; btn.textContent = "Abrindo…"; err.textContent = "";
        try {
          const key = await deriveKey(pwd.value, b64(env.salt), env.iter);
          const result = await decrypt(env, key);
          if (remember.checked) await saveKey({ key, salt: env.salt });
          box.remove();
          resolve(result);
        } catch {
          err.textContent = "Senha incorreta.";
          btn.disabled = false; btn.textContent = "Abrir";
        }
      });
    });
  }

  async function unlock() {
    let env;
    try {
      const res = await fetch("dados.enc", { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      env = await res.json();
    } catch {
      document.body.insertAdjacentHTML("afterbegin",
        `<div class="banner" style="margin:16px">Ainda não há dados publicados. Rode o robô no GitHub (Actions → "Run workflow").</div>`);
      return;
    }
    const saved = await loadKey();
    if (saved && saved.salt === env.salt) {
      try { return await decrypt(env, saved.key); } catch { await forgetKey(); }
    }
    return askPassword(env, saved ? "A senha mudou. Digite a nova senha." : "");
  }

  // ---------------------------------------------------------------- "API" local, só leitura
  const json = (obj, status = 200) =>
    new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });

  function refMonth(t, mode) {
    return mode === "fatura" && t.is_card && t.bill_month ? t.bill_month : t.date.slice(0, 7);
  }

  function filterTx(q) {
    const mode = q.get("modo") || "fatura", month = q.get("month"), cat = q.get("category");
    const text = (q.get("q") || "").toLowerCase();
    return data.transacoes.filter((t) =>
      (!month || refMonth(t, mode) === month) && (!cat || t.category === cat) &&
      (!text || t.description.toLowerCase().includes(text)));
  }

  function route(method, url) {
    const q = url.searchParams, mode = q.get("modo") || "fatura", path = url.pathname.replace(/^.*\/api\//, "");
    if (method !== "GET") {
      return json({ erro: "No celular é só para ver. Faça essa alteração no computador; ela chega aqui na próxima atualização." }, 403);
    }
    switch (path) {
      case "status":
        return json({ pluggyConfigurado: true, conexoes: data.conexoes, temDados: data.transacoes.length > 0,
          modoDemo: false, meses: data.meses[mode] || [], acessoLocal: false, nuvem: true });
      case "summary": {
        const month = q.get("month") || (data.meses[mode] || [])[0];
        const s = data.resumos[mode] && data.resumos[mode][month];
        return s ? json(s) : json({ erro: "Esse mês não está disponível no celular (só o último ano)." }, 404);
      }
      case "transactions":
        return json({ transacoes: filterTx(q) });
      case "categories":
        return json({ categorias: data.categorias });
      case "budgets":
        return json({ orcamentos: data.orcamentos });
      case "export": {
        const lines = ["data;descricao;categoria;tipo;valor;conta", ...filterTx(q).map((t) =>
          [t.date, t.description.replace(/;/g, ","), t.category, t.direction === "in" ? "entrada" : "saida",
            t.amount.toFixed(2).replace(".", ","), t.account_name].join(";"))];
        return json({ csv: lines.join("\n") });
      }
      default:
        return json({ erro: "Indisponível no celular." }, 404);
    }
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!url.pathname.includes("/api/")) return realFetch(input, init);
    await dataReady;
    if (!data) return json({ erro: "Dados indisponíveis." }, 503);
    return route((init.method || "GET").toUpperCase(), url);
  };

  // ---------------------------------------------------------------- início
  document.addEventListener("DOMContentLoaded", async () => {
    document.body.classList.add("somente-leitura");
    data = await unlock();
    if (data) {
      const when = new Date(data.geradoEm).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
      document.querySelector(".tabs").insertAdjacentHTML("afterend",
        `<div class="nuvem-info muted small"><span>Atualizado em ${when} · só leitura</span>
         <button type="button" id="nuvem-sair">Bloquear</button></div>`);
      document.getElementById("nuvem-sair").addEventListener("click", async () => {
        await forgetKey();
        location.reload();
      });
    }
    ready();
  });
})();

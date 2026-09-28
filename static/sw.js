// Service worker do app no celular: guarda só a "casca" (HTML/CSS/JS/ícones) para abrir rápido.
// Dados financeiros abertos (/api/) NUNCA são guardados no aparelho. No modo nuvem, o arquivo
// dados.enc fica em cache (é criptografado) para o painel abrir mesmo sem internet.
const CACHE = "gastos-v2";
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest", "icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/api/")) return;
  // Rede primeiro (versão sempre atual); cache só se estiver sem conexão.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok && !res.redirected) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("./")))
  );
});

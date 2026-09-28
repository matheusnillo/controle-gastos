"""Controle de Gastos com Open Finance — servidor local (somente biblioteca padrão do Python).

Uso:  python app.py   →  abre http://127.0.0.1:8765
"""
import base64
import json
import os
import re
import sys
import threading
import time
import webbrowser
from datetime import date, datetime
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from financas import alerts, demo, importer, insights, nuvem, whatsapp
from financas.auth import SESSION_DAYS, Auth
from financas.categorize import CATEGORIES, categorize, merchant_key
from financas.pluggy import PluggyClient, PluggyError
from financas.store import Store

ROOT = Path(__file__).parent
HOST, PORT = "127.0.0.1", int(os.environ.get("PORT", "8765"))


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(ROOT / ".env")
DATA = Path(os.environ.get("DATA_DIR") or ROOT / "data")
store = Store(DATA / "financas.db")
auth = Auth(DATA / "secret.key", store)
pluggy = PluggyClient(os.environ.get("PLUGGY_CLIENT_ID"), os.environ.get("PLUGGY_CLIENT_SECRET"))
INCLUDE_SANDBOX = os.environ.get("PLUGGY_INCLUDE_SANDBOX", "false").lower() == "true"
# Meu Pluggy (conector 200) é o caminho gratuito para uso pessoal.
MEU_PLUGGY = os.environ.get("PLUGGY_MEU_PLUGGY", "true").lower() == "true"
MEU_PLUGGY_CONNECTOR_ID = 200
# De quantas em quantas horas buscar transações novas automaticamente (o Meu Pluggy atualiza 1x/dia).
SYNC_HOURS = float(os.environ.get("SYNC_HORAS", "4"))

# Modo nuvem: o GitHub roda o app com o PC desligado (veja README). Aqui o PC só envia os ajustes.
NUVEM = nuvem.env_config()
# (dentro do robô do GitHub, NUVEM_JOB=1: ali é ele quem manda os alertas)
NUVEM_ATIVA = bool(NUVEM["token"] and NUVEM["repo"] and NUVEM["senha"]) and not os.environ.get("NUVEM_JOB")

# Arquivos que o celular pode abrir antes de digitar o PIN.
PUBLIC_PATHS = {"/login.html", "/api/login", "/manifest.webmanifest", "/sw.js", "/styles.css"}


def save_raw(raw_txs):
    rules = store.rules()
    for t in raw_txs:
        t["category"] = categorize(t["description"], t["direction"], t.get("pluggy_category"), rules,
                                   is_card=bool(t.get("is_card")))
        t.setdefault("pluggy_category", None)
        t["is_card"] = 1 if t.get("is_card") else 0
        t.setdefault("bill_month", None)
    store.upsert_transactions(raw_txs)
    store.reconcile_card_payments()
    return len(raw_txs)


UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def sync_item(item_id, refresh=False):
    if refresh:
        pluggy.refresh_item(item_id)
    connector, txs, bills = pluggy.fetch_item_transactions(item_id)
    store.add_item(item_id, connector)
    store.save_bills(bills)  # antes de save_raw, que reconcilia o pagamento das faturas
    count = save_raw(txs)
    store.mark_synced(item_id)
    print(f"[sync] {connector or item_id}: {count} transações")
    return {"itemId": item_id, "banco": connector, "transacoes": count}


def sync_everything(refresh=True):
    results = []
    for i in store.items():
        try:
            # Itens do Meu Pluggy não aceitam atualização pela API (o Meu Pluggy atualiza 1x por dia).
            results.append(sync_item(i["id"], refresh and i.get("connector") != "MeuPluggy"))
        except PluggyError as e:
            print(f"[sync] ERRO {i['id']}: {e}", file=sys.stderr)
            results.append({"itemId": i["id"], "banco": i.get("connector"), "transacoes": 0, "erro": str(e)})
    return results


def default_month(txs):
    months = insights.available_months(txs)
    return months[0] if months else None


def load_txs(q):
    """Transações com o mês de referência conforme o modo de visualização.

    modo=fatura (padrão): compras no cartão contam no mês de vencimento da fatura, como no PDF do banco.
    modo=compra: tudo pela data da compra.
    """
    txs = store.all_transactions()
    if q.get("modo", "fatura") == "fatura":
        for t in txs:
            if t.get("is_card") and t.get("bill_month"):
                t["ref_month"] = t["bill_month"]
    return txs


# ------------------------------------------------------------------ WhatsApp
_alert_lock = threading.Lock()


def _whatsapp_ready(cfg):
    return cfg.get("whatsapp_phone") and cfg.get("callmebot_apikey")


def _send(cfg, text):
    try:
        whatsapp.send(cfg["whatsapp_phone"], cfg["callmebot_apikey"], text)
        store.set_settings({"whatsapp_ultimo_erro": None, "whatsapp_ultimo_envio": datetime.now().isoformat(timespec="minutes")})
    except whatsapp.WhatsAppError as e:
        store.set_settings({"whatsapp_ultimo_erro": str(e)})
        raise


def run_alerts():
    """Manda num único WhatsApp os alertas novos (gastos altos, tarifas, orçamento, assinaturas)."""
    if NUVEM_ATIVA:
        return 0  # o robô da nuvem manda os alertas (evita mensagens duplicadas)
    with _alert_lock:
        cfg = alerts.config(store.settings())
        if not alerts._on(cfg, "alertas_ativos") or not _whatsapp_ready(cfg):
            return 0
        found = alerts.pending_alerts(load_txs({"modo": "fatura"}), store.budgets(), cfg)
        sent = store.alerts_already_sent([k for k, _ in found])
        new = [(k, line) for k, line in found if k not in sent]
        if not new:
            return 0
        lines = [line for _, line in new[:12]]
        if len(new) > 12:
            lines.append(f"…e mais {len(new) - 12} alerta(s). Veja no app.")
        try:
            _send(cfg, "🔔 *Controle de Gastos*\n" + "\n".join(lines))
        except whatsapp.WhatsAppError as e:
            print(f"[whatsapp] ERRO: {e}", file=sys.stderr)
            return 0
        store.mark_alerts_sent([k for k, _ in new])
        print(f"[whatsapp] {len(new)} alerta(s) enviados")
        return len(new)


def send_daily_summary(force=False):
    if NUVEM_ATIVA and not force:
        return False  # o robô da nuvem manda o resumo diário
    cfg = alerts.config(store.settings())
    key = f"resumo:{date.today().isoformat()}"
    if not force and (not alerts._on(cfg, "resumo_diario") or store.alerts_already_sent([key])):
        return False
    if not _whatsapp_ready(cfg):
        return False
    txs = load_txs({"modo": "fatura"})
    if not txs:
        return False
    _send(cfg, alerts.daily_summary(txs, store.budgets()))
    store.mark_alerts_sent([key])
    return True


def scheduler():
    """Roda em segundo plano enquanto o app estiver aberto: sincroniza, alerta e manda o resumo diário."""
    last_sync = 0.0
    while True:
        try:
            if pluggy.configured and store.items() and time.time() - last_sync >= SYNC_HOURS * 3600:
                last_sync = time.time()
                sync_everything()
                run_alerts()
            cfg = alerts.config(store.settings())
            if datetime.now().hour >= int(cfg.get("resumo_hora") or 20):
                send_daily_summary()
        except whatsapp.WhatsAppError as e:
            print(f"[whatsapp] ERRO: {e}", file=sys.stderr)
        except Exception as e:  # o agendador nunca pode morrer
            print(f"[agendador] ERRO: {e!r}", file=sys.stderr)
        time.sleep(60)


def in_background(fn):
    threading.Thread(target=fn, daemon=True).start()


# ------------------------------------------------------- envio dos ajustes à nuvem
_push_timer = None
_push_lock = threading.Lock()


def push_ajustes_now():
    if not NUVEM_ATIVA:
        raise nuvem.NuvemError("Modo nuvem não configurado: preencha GITHUB_TOKEN, GITHUB_REPO e NUVEM_SENHA no .env.")
    nuvem.check_password(NUVEM["senha"])
    with _push_lock:
        payload = json.dumps(nuvem.export_ajustes(store), ensure_ascii=False).encode()
        try:
            nuvem.github_put_file(NUVEM["token"], NUVEM["repo"], "nuvem/ajustes.enc",
                                  nuvem.encrypt(payload, NUVEM["senha"]), "ajustes do computador")
        except nuvem.NuvemError as e:
            store.set_settings({"nuvem_ultimo_erro": str(e)})
            raise
        store.set_settings({"nuvem_ultimo_erro": None,
                            "nuvem_ultimo_envio": datetime.now().isoformat(timespec="minutes")})
        print("[nuvem] ajustes enviados ao GitHub")


def schedule_push(delay=20):
    """Envia os ajustes alguns segundos depois da última mudança (junta várias edições num envio só)."""
    global _push_timer
    if not NUVEM_ATIVA:
        return

    def run():
        try:
            push_ajustes_now()
        except nuvem.NuvemError as e:
            print(f"[nuvem] ERRO: {e}", file=sys.stderr)

    if _push_timer:
        _push_timer.cancel()
    _push_timer = threading.Timer(delay, run)
    _push_timer.daemon = True
    _push_timer.start()


# ---------------------------------------------------------------- HTTP
class Server(ThreadingHTTPServer):
    # No Windows, SO_REUSEADDR deixa DOIS processos escutarem a mesma porta sem erro;
    # desligado, uma segunda cópia do app percebe que já existe uma aberta.
    allow_reuse_address = False
    daemon_threads = True


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "static"), **kwargs)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    # ------------------------------------------------------------------ utils
    def _json(self, data, status=200, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    # ---------------------------------------------------------------- acesso
    def is_direct_local(self):
        """Acesso no próprio PC (não passa por proxy como o `tailscale serve`)."""
        host = (self.headers.get("Host") or "").lower()
        proxied = any(self.headers.get(h) for h in
                      ("X-Forwarded-For", "X-Forwarded-Host", "Forwarded", "Tailscale-User-Login"))
        return (self.client_address[0] in ("127.0.0.1", "::1") and not proxied
                and host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"))

    def is_https(self):
        return (self.headers.get("X-Forwarded-Proto") == "https"
                or (self.headers.get("Host") or "").endswith(".ts.net"))

    def session_ok(self):
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        return "sessao" in cookie and auth.valid_session(cookie["sessao"].value)

    def allowed(self, path):
        return self.is_direct_local() or path in PUBLIC_PATHS or path.startswith("/icons/") or self.session_ok()

    def session_cookie(self, token, max_age):
        secure = "; Secure" if self.is_https() else ""
        return f"sessao={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"

    def _route(self, method):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return False
        # Bloqueia requisições de outros sites (CSRF): a origem tem de ser o próprio app.
        origin = self.headers.get("Origin")
        if method != "GET" and origin and urlparse(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
            self._json({"erro": "origem não permitida"}, 403)
            return True
        if not self.allowed(url.path):
            self._json({"erro": "Digite o PIN para acessar.", "login": True}, 401)
            return True
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/login":
                self._login()
                return True
            if url.path == "/api/logout":
                self._json({"ok": True}, cookie=self.session_cookie("", 0))
                return True
            handler = ROUTES.get((method, url.path))
            if handler:
                self._json(handler(self, q))
                return True
            m = re.fullmatch(r"/api/transactions/([^/]+)/category", url.path)
            if method == "POST" and m:
                self._json(set_category(self, m.group(1)))
                return True
            self._json({"erro": "rota não encontrada"}, 404)
        except PluggyError as e:
            self._json({"erro": str(e)}, 502)
        except (whatsapp.WhatsAppError, nuvem.NuvemError) as e:
            self._json({"erro": str(e)}, 502)
        except PermissionError as e:
            self._json({"erro": str(e)}, 429)
        except (ValueError, KeyError) as e:
            self._json({"erro": f"requisição inválida: {e}"}, 400)
        return True

    def _login(self):
        if not auth.pin_set:
            self._json({"erro": "Defina um PIN no computador primeiro (aba Alertas e celular)."}, 400)
            return
        client = self.headers.get("Tailscale-User-Login") or self.headers.get("X-Forwarded-For") or self.client_address[0]
        if not auth.check_pin(str(self._body().get("pin", "")), client):
            self._json({"erro": "PIN incorreto."}, 401)
            return
        self._json({"ok": True}, cookie=self.session_cookie(auth.new_session(), SESSION_DAYS * 86400))

    def do_GET(self):
        if self._route("GET"):
            return
        path = urlparse(self.path).path
        if not self.allowed(path):
            self.send_response(302)
            self.send_header("Location", "/login.html")
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")


# ---------------------------------------------------------------------- rotas
def status(h, q):
    txs = load_txs(q)
    sources = {t["source"] for t in txs}
    return {
        "pluggyConfigurado": pluggy.configured,
        "incluirSandbox": INCLUDE_SANDBOX,
        "meuPluggyConnectorId": MEU_PLUGGY_CONNECTOR_ID if MEU_PLUGGY else None,
        "conexoes": store.items(),
        "temDados": bool(txs),
        "modoDemo": sources == {"demo"},
        "meses": insights.available_months(txs),
        "acessoLocal": h.is_direct_local(),
    }


def connect_token(h, q):
    body = h._body()
    return {"accessToken": pluggy.create_connect_token(body.get("itemId"))}


def add_item(h, q):
    item_id = str(h._body()["itemId"]).strip()
    if not UUID_RE.match(item_id):
        raise ValueError("o ID da conexão (itemId) deve ser um UUID, ex.: 3f1c2a9e-....")
    # Ao conectar um banco real, remove os dados de demonstração.
    store.execute("DELETE FROM transactions WHERE source = 'demo'")
    result = sync_item(item_id)
    in_background(run_alerts)
    schedule_push()
    return result


def import_files(h, q):
    body = h._body()
    card = body.get("cartao")  # None = detectar automaticamente
    store.execute("DELETE FROM transactions WHERE source = 'demo'")
    results = []
    for f in body["arquivos"]:
        try:
            txs = importer.parse_file(f["nome"], base64.b64decode(f["conteudo"]), card)
            results.append({"arquivo": f["nome"], "transacoes": save_raw(txs)})
        except ValueError as e:
            results.append({"arquivo": f["nome"], "erro": str(e)})
    in_background(run_alerts)
    schedule_push()
    return {"resultados": results}


def sync_all(h, q):
    results = sync_everything()
    in_background(run_alerts)
    return {"resultados": results}


def load_demo(h, q):
    store.clear_transactions()
    return {"transacoes": save_raw(demo.generate())}


def clear_data(h, q):
    store.clear_transactions()
    return {"ok": True}


def summary(h, q):
    txs = load_txs(q)
    month = q.get("month") or default_month(txs)
    if not month:
        return {"vazio": True}
    budgets = store.budgets()
    return {
        "resumo": insights.summarize(txs, month, budgets),
        **insights.build_insights(txs, month, budgets),
    }


def transactions(h, q):
    txs = load_txs(q)
    month, cat, text = q.get("month"), q.get("category"), (q.get("q") or "").lower()
    out = [
        t for t in txs
        if (not month or insights.month_of(t) == month)
        and (not cat or t["category"] == cat)
        and (not text or text in t["description"].lower())
    ]
    for t in out:
        t["grupo"] = insights.group_of(t["category"])
    return {"transacoes": out}


def set_category(h, tx_id):
    body = h._body()
    category = body["category"]
    if category not in CATEGORIES:
        raise ValueError("categoria desconhecida")
    rows = store.query("SELECT * FROM transactions WHERE id = ?", (tx_id,))
    if not rows:
        raise KeyError(tx_id)
    tx = rows[0]
    key = merchant_key(tx["description"])
    if body.get("applyToSimilar"):
        store.set_rule(key, category)
        similar = [t["id"] for t in store.all_transactions()
                   if merchant_key(t["description"]) == key and t["direction"] == tx["direction"]]
    else:
        similar = [tx_id]
    store.executemany("UPDATE transactions SET category = ?, manual_category = 1 WHERE id = ?",
                      [(category, i) for i in similar])
    schedule_push()
    return {"atualizadas": len(similar), "chave": key if body.get("applyToSimilar") else None}


def categories(h, q):
    return {"categorias": [{"nome": c, "grupo": g} for c, g in CATEGORIES.items()]}


def get_budgets(h, q):
    return {"orcamentos": store.budgets()}


def put_budgets(h, q):
    for category, limit in h._body().items():
        if category not in CATEGORIES:
            raise ValueError(f"categoria desconhecida: {category}")
        store.set_budget(category, float(limit) if limit not in (None, "") else None)
    in_background(run_alerts)
    schedule_push()
    return {"orcamentos": store.budgets()}


def export_csv(h, q):
    txs = transactions(h, q)["transacoes"]
    lines = ["data;descricao;categoria;tipo;valor;conta"]
    for t in txs:
        valor = f"{t['amount']:.2f}".replace(".", ",")
        desc = t["description"].replace(";", ",")
        lines.append(f"{t['date']};{desc};{t['category']};{'entrada' if t['direction'] == 'in' else 'saida'};{valor};{t['account_name']}")
    return {"csv": "\n".join(lines)}


# ------------------------------------------------------- alertas e celular
EDITABLE = {"whatsapp_phone", "callmebot_apikey", *alerts.DEFAULTS}


def get_config(h, q):
    cfg = alerts.config(store.settings())
    key = cfg.get("callmebot_apikey") or ""
    return {
        **{k: cfg.get(k) for k in EDITABLE if k != "callmebot_apikey"},
        "callmebot_apikey": ("•••" + key[-3:]) if key else "",
        "whatsappPronto": bool(_whatsapp_ready(cfg)),
        "ultimoErro": cfg.get("whatsapp_ultimo_erro"),
        "ultimoEnvio": cfg.get("whatsapp_ultimo_envio"),
        "pinDefinido": auth.pin_set,
        "acessoLocal": h.is_direct_local(),
        "syncHoras": SYNC_HOURS,
    }


def put_config(h, q):
    body = h._body()
    values = {}
    for k, v in body.items():
        if k not in EDITABLE:
            continue
        v = "" if v is None else str(v).strip()
        if k == "callmebot_apikey" and (not v or v.startswith("•")):
            continue  # campo mascarado: mantém a chave salva
        if k == "whatsapp_phone" and v:
            v = whatsapp.normalize_phone(v)
            if len(v) < 12:
                raise ValueError("número inválido; use DDD + número, ex.: 34 99999-9999")
        if k in ("alerta_valor_minimo", "resumo_hora") and v:
            n = float(v)
            if k == "resumo_hora" and not 0 <= n <= 23:
                raise ValueError("hora do resumo deve ser de 0 a 23")
            v = str(int(n)) if k == "resumo_hora" else str(n)
        values[k] = v
    store.set_settings(values)
    schedule_push()
    return get_config(h, q)


def set_pin(h, q):
    # Só dá para definir/trocar o PIN no próprio computador (ou já logado com o PIN atual).
    auth.set_pin(str(h._body().get("pin", "")))
    return {"ok": True}


def whatsapp_test(h, q):
    cfg = alerts.config(store.settings())
    if not _whatsapp_ready(cfg):
        raise whatsapp.WhatsAppError("Salve primeiro o número e a apikey do CallMeBot.")
    _send(cfg, "✅ Controle de Gastos conectado! Você vai receber os alertas de gastos por aqui.")
    return {"ok": True}


def whatsapp_summary(h, q):
    if not send_daily_summary(force=True):
        raise whatsapp.WhatsAppError("Não foi possível montar o resumo: confira o WhatsApp e se há transações.")
    return {"ok": True}


def nuvem_status(h, q):
    s = store.settings()
    return {
        "ativa": NUVEM_ATIVA,
        "repo": NUVEM["repo"] or None,
        "site": nuvem.site_url(NUVEM["repo"]) if NUVEM["repo"] else None,
        "ultimoEnvio": s.get("nuvem_ultimo_envio"),
        "ultimoErro": s.get("nuvem_ultimo_erro"),
    }


def nuvem_push(h, q):
    push_ajustes_now()
    return nuvem_status(h, q)


ROUTES = {
    ("GET", "/api/status"): status,
    ("POST", "/api/connect-token"): connect_token,
    ("POST", "/api/items"): add_item,
    ("POST", "/api/sync"): sync_all,
    ("POST", "/api/import"): import_files,
    ("POST", "/api/demo"): load_demo,
    ("DELETE", "/api/data"): clear_data,
    ("GET", "/api/summary"): summary,
    ("GET", "/api/transactions"): transactions,
    ("GET", "/api/categories"): categories,
    ("GET", "/api/budgets"): get_budgets,
    ("PUT", "/api/budgets"): put_budgets,
    ("GET", "/api/export"): export_csv,
    ("GET", "/api/config"): get_config,
    ("PUT", "/api/config"): put_config,
    ("POST", "/api/pin"): set_pin,
    ("POST", "/api/whatsapp/teste"): whatsapp_test,
    ("POST", "/api/whatsapp/resumo"): whatsapp_summary,
    ("GET", "/api/nuvem"): nuvem_status,
    ("POST", "/api/nuvem/enviar"): nuvem_push,
}


def main():
    url = f"http://{HOST}:{PORT}"
    if sys.stdout is None or sys.stderr is None:
        # Rodando sem janela (pythonw, início automático): registra tudo em data/app.log.
        log = open(DATA / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    try:
        server = Server((HOST, PORT), Handler)
    except OSError:
        print(f"O app já está aberto (porta {PORT} em uso). Abrindo {url}")
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        return
    print(f"Controle de Gastos rodando em {url}  (Ctrl+C para parar)")
    print("Pluggy:", "configurada" if pluggy.configured else "NÃO configurada — use o modo demonstração ou preencha o .env")
    if pluggy.configured and store.items():
        print(f"Sincronizando {len(store.items())} conexão(ões) agora e a cada {SYNC_HOURS:g} h…")
    if NUVEM_ATIVA:
        print(f"Modo nuvem ativo ({NUVEM['repo']}): alertas saem pelo GitHub; ajustes são enviados automaticamente.")
    in_background(scheduler)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

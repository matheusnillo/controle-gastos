"""Modo nuvem: o GitHub roda o app sem o computador ligado.

Tudo que vai para o GitHub (repositório público) é criptografado com AES-256-GCM e uma chave
derivada da SUA senha (PBKDF2-SHA256, 600 mil iterações). O formato é o mesmo que o navegador
decifra com a Web Crypto API, então só quem sabe a senha vê os dados no celular.

Arquivos:
  nuvem/ajustes.enc   (branch main)   regras, orçamentos, categorias manuais, alertas, conexões,
                                      extratos importados — enviados pelo computador
  financas.db.enc     (branch dados)  estado do robô (alertas já enviados, faturas…)
  dados.enc           (GitHub Pages)  painel pronto para o celular
"""
import base64
import gzip
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime

from . import insights
from .categorize import CATEGORIES

ITERATIONS = 600_000
MIN_PASSWORD = 12


class NuvemError(Exception):
    pass


# ------------------------------------------------------------------ cripto
def check_password(password):
    if not password or len(password) < MIN_PASSWORD:
        raise NuvemError(f"A senha da nuvem precisa ter pelo menos {MIN_PASSWORD} caracteres "
                         "(ela protege dados que ficam num site público).")
    if password.isdigit() or password.isalpha():
        raise NuvemError("Use letras E números (ou símbolos) na senha da nuvem.")


def derive_key(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, dklen=32)


def encrypt(data: bytes, password, salt=None, key=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = salt or secrets.token_bytes(16)
    key = key or derive_key(password, salt)
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, gzip.compress(data), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return json.dumps({"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS,
                       "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}).encode()


def decrypt(envelope: bytes, password) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    env = json.loads(envelope)
    key = derive_key(password, base64.b64decode(env["salt"]))
    try:
        plain = AESGCM(key).decrypt(base64.b64decode(env["iv"]), base64.b64decode(env["ct"]), None)
    except InvalidTag:
        raise NuvemError("Senha da nuvem incorreta (ou arquivo corrompido).") from None
    return gzip.decompress(plain)


# ------------------------------------------------------- ajustes (PC → nuvem)
def export_ajustes(store):
    """Tudo que você configura no computador e o robô precisa saber."""
    local_only = ("pin_hash", "session_epoch", "whatsapp_ultimo_erro", "whatsapp_ultimo_envio",
                  "nuvem_salt", "nuvem_ultimo_envio", "nuvem_ultimo_erro")
    settings = {k: v for k, v in store.settings().items() if k not in local_only}
    return {
        "versao": 1,
        "geradoEm": datetime.now().isoformat(timespec="seconds"),
        "conexoes": [i["id"] for i in store.items()],
        "regras": store.rules(),
        "orcamentos": store.budgets(),
        "configuracoes": settings,
        "categoriasManuais": {t["id"]: t["category"] for t in
                              store.query("SELECT id, category FROM transactions WHERE manual_category = 1")},
        # Extratos importados (OFX/CSV) só existem no PC: vão junto para a nuvem.
        "transacoesImportadas": store.query(
            "SELECT id, account_id, account_name, date, description, amount, direction, category, "
            "pluggy_category, source, is_card, bill_month FROM transactions WHERE source = 'arquivo'"),
    }


def apply_ajustes(store, aj):
    for item_id in aj.get("conexoes", []):
        store.add_item(item_id)
    known = {i["id"] for i in store.items()}
    for gone in known - set(aj.get("conexoes", [])):
        store.execute("DELETE FROM items WHERE id = ?", (gone,))
    store.execute("DELETE FROM rules")
    for key, cat in aj.get("regras", {}).items():
        store.set_rule(key, cat)
    store.execute("DELETE FROM budgets")
    for cat, limit in aj.get("orcamentos", {}).items():
        store.set_budget(cat, limit)
    store.set_settings(aj.get("configuracoes", {}))
    if aj.get("transacoesImportadas"):
        store.upsert_transactions(aj["transacoesImportadas"])


def apply_manual_categories(store, aj):
    manual = aj.get("categoriasManuais", {})
    store.executemany("UPDATE transactions SET category = ?, manual_category = 1 WHERE id = ?",
                      [(cat, tx_id) for tx_id, cat in manual.items() if cat in CATEGORIES])


# -------------------------------------------------- painel para o celular
TX_FIELDS = ("id", "date", "description", "amount", "direction", "category", "account_name", "is_card", "bill_month")


def _with_mode(txs, mode):
    out = []
    for t in txs:
        t = dict(t)
        if mode == "fatura" and t.get("is_card") and t.get("bill_month"):
            t["ref_month"] = t["bill_month"]
        out.append(t)
    return out


def build_site_data(store):
    """Tudo que o painel do celular precisa, já calculado (o celular só lê)."""
    base = store.all_transactions()
    budgets = store.budgets()
    data = {
        "geradoEm": datetime.now().isoformat(timespec="minutes"),
        "categorias": [{"nome": c, "grupo": g} for c, g in CATEGORIES.items()],
        "orcamentos": budgets,
        "conexoes": store.items(),
        "meses": {},
        "resumos": {},
        "transacoes": [{**{k: t.get(k) for k in TX_FIELDS}, "grupo": insights.group_of(t["category"])}
                       for t in base],
    }
    for mode in ("fatura", "compra"):
        txs = _with_mode(base, mode)
        months = insights.available_months(txs)
        data["meses"][mode] = months
        data["resumos"][mode] = {
            m: {"resumo": insights.summarize(txs, m, budgets), **insights.build_insights(txs, m, budgets)}
            for m in months[:13]  # último ano
        }
    return data


# ------------------------------------------------------- GitHub (PC → nuvem)
def github_put_file(token, repo, path, content: bytes, message):
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "controle-de-gastos"}

    def call(method, body=None):
        req = urllib.request.Request(api, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body else None)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if method == "GET" and e.code == 404:
                return None
            detail = e.read().decode(errors="replace")[:200]
            if e.code in (401, 403):
                raise NuvemError("O GitHub recusou o token. Confira GITHUB_TOKEN (permissão Contents: "
                                 f"Read and write no repositório {repo}).") from None
            raise NuvemError(f"GitHub respondeu HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise NuvemError(f"Sem conexão com o GitHub: {e.reason}") from None

    current = call("GET")
    body = {"message": message, "content": base64.b64encode(content).decode()}
    if current and current.get("sha"):
        body["sha"] = current["sha"]
    call("PUT", body)


def env_config():
    return {
        "token": os.environ.get("GITHUB_TOKEN", "").strip(),
        "repo": os.environ.get("GITHUB_REPO", "").strip().strip("/"),
        "senha": os.environ.get("NUVEM_SENHA", ""),
    }


def site_url(repo):
    if "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"

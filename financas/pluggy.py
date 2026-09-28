"""Cliente mínimo da API da Pluggy (agregador autorizado do Open Finance Brasil).

Documentação: https://docs.pluggy.ai
O CLIENT_SECRET nunca sai deste servidor: o navegador só recebe um connect token
de curta duração para abrir o widget de consentimento do banco.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

API = "https://api.pluggy.ai"


class PluggyError(Exception):
    pass


class PluggyClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self._api_key = None
        self._api_key_expires = 0.0

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret)

    def _request(self, method, path, body=None, auth=True):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth:
            headers["X-API-KEY"] = self._get_api_key()
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise PluggyError(f"Pluggy {method} {path} -> HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise PluggyError(f"Não foi possível acessar a Pluggy: {e.reason}") from None

    def _get_api_key(self):
        # A API key vale 2h; renovamos com folga.
        if not self._api_key or time.time() > self._api_key_expires:
            if not self.configured:
                raise PluggyError("Configure PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET no arquivo .env")
            res = self._request("POST", "/auth",
                                {"clientId": self.client_id, "clientSecret": self.client_secret}, auth=False)
            self._api_key = res["apiKey"]
            self._api_key_expires = time.time() + 100 * 60
        return self._api_key

    def create_connect_token(self, item_id=None):
        body = {"itemId": item_id} if item_id else {}
        return self._request("POST", "/connect_token", body)["accessToken"]

    def get_item(self, item_id):
        return self._request("GET", f"/items/{urllib.parse.quote(item_id)}")

    def refresh_item(self, item_id):
        """Pede à Pluggy para atualizar o item (buscar transações novas no banco)."""
        try:
            self._request("PATCH", f"/items/{urllib.parse.quote(item_id)}", {})
        except PluggyError:
            pass  # alguns conectores (ex.: Meu Pluggy) atualizam sozinhos; seguimos com o que houver

    def wait_until_ready(self, item_id, timeout=120):
        """Espera o item sair de UPDATING/CREATED. Retorna o item."""
        deadline = time.time() + timeout
        while True:
            item = self.get_item(item_id)
            if item.get("status") not in ("UPDATING", "CREATED") or time.time() > deadline:
                return item
            time.sleep(3)

    def list_accounts(self, item_id):
        return self._request("GET", "/accounts?" + urllib.parse.urlencode({"itemId": item_id}))["results"]

    def list_transactions(self, account_id, since):
        """GET /v2/transactions (paginação por cursor; o /transactions antigo foi descontinuado)."""
        base = "/v2/transactions?" + urllib.parse.urlencode({"accountId": account_id})
        path, results, seen = base, [], set()
        while True:
            res = self._request("GET", path)
            results.extend(res.get("results", []))
            cursor = res.get("next")
            if not cursor or cursor in seen:
                break
            seen.add(cursor)
            if cursor.startswith("http"):
                path = cursor[len(API):] if cursor.startswith(API) else urllib.parse.urlparse(cursor).path + "?" + urllib.parse.urlparse(cursor).query
            elif cursor.startswith("/"):
                path = cursor
            else:
                path = base + "&" + urllib.parse.urlencode({"cursor": cursor})
        since_s = since.isoformat()
        # Transações pendentes mudam de id quando são efetivadas; importamos só as já lançadas.
        return [t for t in results
                if (t.get("date") or "")[:10] >= since_s and t.get("status") != "PENDING"]

    def list_bills(self, account_id):
        try:
            res = self._request("GET", "/bills?" + urllib.parse.urlencode({"accountId": account_id}))
        except PluggyError:
            return []  # nem todo conector informa faturas
        return [{"id": b["id"], "account_id": account_id, "due_date": (b.get("dueDate") or "")[:10],
                 "total": float(b.get("totalAmount") or 0)}
                for b in res.get("results", []) if b.get("dueDate")]

    def fetch_item_transactions(self, item_id, months=12):
        """Retorna (conector, transações normalizadas, faturas dos cartões) do item."""
        item = self.wait_until_ready(item_id)
        if item.get("status") in ("LOGIN_ERROR", "WAITING_USER_INPUT"):
            raise PluggyError(f"A conexão {item_id} precisa ser autorizada de novo (status {item['status']}). "
                              "Clique em Conectar banco e refaça a autorização.")
        connector = (item.get("connector") or {}).get("name")
        since = date.today() - timedelta(days=31 * months)
        out, bills = [], []
        for acc in self.list_accounts(item_id):
            name = f"{connector or 'Banco'} · {acc.get('marketingName') or acc.get('name') or acc.get('type')}"
            is_credit_card = acc.get("type") == "CREDIT"
            if is_credit_card:
                bills.extend(self.list_bills(acc["id"]))
            for t in self.list_transactions(acc["id"], since):
                amount = float(t.get("amount") or 0)
                # Compra internacional: "amount" vem na moeda original (ex.: US$ 11,99);
                # o valor cobrado em reais está em amountInAccountCurrency.
                if t.get("currencyCode") not in (None, "BRL") and t.get("amountInAccountCurrency") is not None:
                    converted = abs(float(t["amountInAccountCurrency"]))
                    amount = converted if amount >= 0 else -converted
                card_meta = t.get("creditCardMetadata") or {}
                tx_type = t.get("type")
                if tx_type in ("DEBIT", "CREDIT"):
                    direction = "out" if tx_type == "DEBIT" else "in"
                elif is_credit_card:
                    direction = "out" if amount > 0 else "in"
                else:
                    direction = "out" if amount < 0 else "in"
                out.append({
                    "id": t["id"],
                    "account_id": acc["id"],
                    "account_name": name,
                    "date": (t.get("date") or "")[:10],
                    "description": t.get("description") or t.get("descriptionRaw") or "(sem descrição)",
                    "amount": abs(amount),
                    "direction": direction,
                    "pluggy_category": t.get("category"),
                    "source": "pluggy",
                    "is_card": is_credit_card,
                    # Mês de vencimento da fatura em que a compra/parcela é cobrada (ex.: "2026-09").
                    "bill_month": (card_meta.get("billForecastDate") or "")[:7] or None,
                })
        return connector, out, bills

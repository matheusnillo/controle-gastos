"""Persistência local em SQLite (arquivo data/financas.db)."""
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id               TEXT PRIMARY KEY,
    account_id       TEXT,
    account_name     TEXT,
    date             TEXT NOT NULL,          -- YYYY-MM-DD
    description      TEXT NOT NULL,
    amount           REAL NOT NULL,          -- sempre positivo
    direction        TEXT NOT NULL,          -- 'in' | 'out'
    category         TEXT NOT NULL,
    pluggy_category  TEXT,
    manual_category  INTEGER NOT NULL DEFAULT 0,
    source           TEXT NOT NULL           -- 'pluggy' | 'demo'
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);

CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    connector   TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    last_sync   TEXT
);

CREATE TABLE IF NOT EXISTS budgets (
    category    TEXT PRIMARY KEY,
    monthly_limit REAL NOT NULL
);

-- Faturas do cartão (para reconhecer o pagamento feito pela conta corrente)
CREATE TABLE IF NOT EXISTS bills (
    id          TEXT PRIMARY KEY,
    account_id  TEXT,
    due_date    TEXT NOT NULL,           -- YYYY-MM-DD
    total       REAL NOT NULL
);

-- Configurações editáveis pela tela (WhatsApp, limites de alerta, PIN)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Alertas já enviados (evita mandar o mesmo aviso duas vezes)
CREATE TABLE IF NOT EXISTS alerts_sent (
    key     TEXT PRIMARY KEY,
    sent_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Regras criadas quando o usuário recategoriza "todas parecidas"
CREATE TABLE IF NOT EXISTS rules (
    merchant_key TEXT PRIMARY KEY,
    category     TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(transactions)")}
            if "bill_month" not in cols:  # mês (YYYY-MM) do vencimento da fatura do cartão
                self._conn.execute("ALTER TABLE transactions ADD COLUMN bill_month TEXT")
                self._conn.commit()
            if "is_card" not in cols:  # migração de bancos criados por versões anteriores
                self._conn.execute("ALTER TABLE transactions ADD COLUMN is_card INTEGER NOT NULL DEFAULT 0")
                self._conn.execute("UPDATE transactions SET is_card = 1 WHERE account_name LIKE '%Cartão%' "
                                   "OR account_name LIKE '%OUROCARD%' OR account_name LIKE '%CARD%'")
                self._conn.commit()

    def query(self, sql, params=()):
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def executemany(self, sql, rows):
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    # ---- transações -------------------------------------------------------
    def upsert_transactions(self, txs):
        """Insere/atualiza sem sobrescrever categorias escolhidas manualmente."""
        self.executemany(
            """
            INSERT INTO transactions
              (id, account_id, account_name, date, description, amount, direction,
               category, pluggy_category, manual_category, source, is_card, bill_month)
            VALUES (:id, :account_id, :account_name, :date, :description, :amount,
                    :direction, :category, :pluggy_category, 0, :source, :is_card, :bill_month)
            ON CONFLICT(id) DO UPDATE SET
              account_name = excluded.account_name,
              is_card = excluded.is_card,
              bill_month = excluded.bill_month,
              date = excluded.date,
              description = excluded.description,
              amount = excluded.amount,
              direction = excluded.direction,
              pluggy_category = excluded.pluggy_category,
              category = CASE WHEN transactions.manual_category = 1
                              THEN transactions.category ELSE excluded.category END
            """,
            txs,
        )

    def reconcile_card_payments(self, days=3):
        """Marca como "Pagamento de fatura" a saída da conta que paga o cartão.

        Ex.: "Pagamento de Pix QR Code BANCO DO BRASIL" na conta corrente com o mesmo valor
        de um "PGTO. QR CODE PIX" que entrou no cartão até 3 dias depois/antes.
        Sem isso a fatura seria contada duas vezes (compras no cartão + pagamento na conta).
        """
        with self._lock:
            cur = self._conn.execute(
                """
                UPDATE transactions SET category = 'Pagamento de fatura'
                WHERE is_card = 0 AND direction = 'out' AND manual_category = 0
                  AND category <> 'Pagamento de fatura'
                  AND EXISTS (
                    SELECT 1 FROM transactions c
                    WHERE c.is_card = 1 AND c.direction = 'in' AND c.category = 'Pagamento de fatura'
                      AND ABS(c.amount - transactions.amount) < 0.01
                      AND ABS(julianday(c.date) - julianday(transactions.date)) <= ?)
                """,
                (days,),
            )
            # Também casa com o total da fatura perto do vencimento (o crédito no cartão
            # às vezes só aparece dias depois, ou nem aparece).
            cur2 = self._conn.execute(
                """
                UPDATE transactions SET category = 'Pagamento de fatura'
                WHERE is_card = 0 AND direction = 'out' AND manual_category = 0
                  AND category <> 'Pagamento de fatura'
                  AND EXISTS (
                    SELECT 1 FROM bills b
                    WHERE b.total > 0 AND ABS(b.total - transactions.amount) < 0.01
                      AND julianday(transactions.date) - julianday(b.due_date) BETWEEN -10 AND 5)
                """
            )
            self._conn.commit()
            return cur.rowcount + cur2.rowcount

    def save_bills(self, bills):
        self.executemany(
            "INSERT INTO bills (id, account_id, due_date, total) VALUES (:id, :account_id, :due_date, :total) "
            "ON CONFLICT(id) DO UPDATE SET due_date = excluded.due_date, total = excluded.total",
            bills,
        )

    def all_transactions(self):
        return self.query("SELECT * FROM transactions ORDER BY date DESC, id")

    def clear_transactions(self):
        with self._lock:
            self._conn.executescript("DELETE FROM transactions; DELETE FROM items; DELETE FROM rules; DELETE FROM bills;")

    # ---- itens (conexões Open Finance) -------------------------------------
    def add_item(self, item_id, connector=None):
        self.execute(
            "INSERT OR IGNORE INTO items (id, connector) VALUES (?, ?)", (item_id, connector)
        )

    def items(self):
        return self.query("SELECT * FROM items ORDER BY created_at")

    def mark_synced(self, item_id):
        self.execute("UPDATE items SET last_sync = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))

    # ---- orçamentos e regras -----------------------------------------------
    def budgets(self):
        return {r["category"]: r["monthly_limit"] for r in self.query("SELECT * FROM budgets")}

    def set_budget(self, category, limit):
        if limit is None or limit <= 0:
            self.execute("DELETE FROM budgets WHERE category = ?", (category,))
        else:
            self.execute(
                "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?) "
                "ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit",
                (category, limit),
            )

    def settings(self):
        return {r["key"]: r["value"] for r in self.query("SELECT * FROM settings")}

    def set_settings(self, values: dict):
        self.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, None if v is None else str(v)) for k, v in values.items()],
        )

    def alerts_already_sent(self, keys):
        if not keys:
            return set()
        marks = ",".join("?" * len(keys))
        return {r["key"] for r in self.query(f"SELECT key FROM alerts_sent WHERE key IN ({marks})", list(keys))}

    def mark_alerts_sent(self, keys):
        self.executemany("INSERT OR IGNORE INTO alerts_sent (key) VALUES (?)", [(k,) for k in keys])

    def rules(self):
        return {r["merchant_key"]: r["category"] for r in self.query("SELECT * FROM rules")}

    def set_rule(self, merchant_key, category):
        self.execute(
            "INSERT INTO rules (merchant_key, category) VALUES (?, ?) "
            "ON CONFLICT(merchant_key) DO UPDATE SET category = excluded.category",
            (merchant_key, category),
        )

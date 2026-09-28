"""Importação de extratos exportados do app/internet banking (OFX ou CSV).

Alternativa 100% gratuita e sem cadastro: praticamente todo banco brasileiro
exporta o extrato em OFX (Itaú, Bradesco, BB, Santander, Caixa, Inter, C6...)
e o Nubank exporta CSV da conta e da fatura.
"""
import csv
import hashlib
import io
import re
from datetime import datetime


class ImportError_(ValueError):
    pass


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _id(*parts):
    return "arq-" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


def _tx(tx_id, account, d, desc, signed_amount, is_card=False):
    return {
        "id": tx_id, "account_id": f"arquivo-{account}", "account_name": account,
        "date": d, "description": (desc or "(sem descrição)").strip()[:200],
        "amount": round(abs(signed_amount), 2), "direction": "out" if signed_amount < 0 else "in",
        "pluggy_category": None, "source": "arquivo", "is_card": is_card,
    }


# ------------------------------------------------------------------------- OFX
def _ofx_tag(block, tag):
    m = re.search(rf"<{tag}>\s*([^<\r\n]*)", block, re.I)
    return m.group(1).strip() if m else None


def parse_ofx(text, filename):
    bank = _ofx_tag(text, "ORG") or _ofx_tag(text, "BANKID") or "Banco"
    acct = _ofx_tag(text, "ACCTID") or filename
    is_card = bool(re.search(r"<CCSTMTRS>", text, re.I))
    account = f"{bank} · {'Cartão' if is_card else 'Conta'} {acct[-4:]}"
    out = []
    for block in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", text, re.S | re.I):
        amount_s = _ofx_tag(block, "TRNAMT")
        date_s = _ofx_tag(block, "DTPOSTED")
        if not amount_s or not date_s:
            continue
        amount = float(amount_s.replace(",", "."))
        d = f"{date_s[0:4]}-{date_s[4:6]}-{date_s[6:8]}"
        memo = _ofx_tag(block, "MEMO")
        name = _ofx_tag(block, "NAME")
        desc = memo if memo and (not name or len(memo) > len(name)) else name
        fitid = _ofx_tag(block, "FITID") or f"{d}{amount}{desc}"
        out.append(_tx(_id(acct, fitid, d, amount), account, d, desc, amount, is_card))
    if not out:
        raise ImportError_("Nenhuma transação encontrada no OFX.")
    return out


# ------------------------------------------------------------------------- CSV
DATE_COLS = ("data", "date", "data lancamento", "data lançamento", "dt")
DESC_COLS = ("descricao", "descrição", "title", "historico", "histórico", "lancamento", "lançamento",
             "estabelecimento", "description", "memo")
VALUE_COLS = ("valor", "amount", "value", "valor (r$)", "valor r$", "quantia")


def _parse_date(s):
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_amount(s):
    s = s.strip().replace("R$", "").replace(" ", "").replace(" ", "")
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negative else v


def _find(headers, names):
    for i, h in enumerate(headers):
        if h in names:
            return i
    for i, h in enumerate(headers):
        if any(h.startswith(n) for n in names):
            return i
    return None


def parse_csv(text, filename, card=None):
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    # Alguns bancos colocam linhas de cabeçalho do relatório antes da tabela.
    header_idx = next((i for i, r in enumerate(rows[:15])
                       if _find([c.strip().lower() for c in r], DATE_COLS) is not None
                       and _find([c.strip().lower() for c in r], VALUE_COLS) is not None), None)
    if header_idx is None:
        raise ImportError_("CSV sem colunas reconhecíveis. Precisa ter colunas de data, descrição e valor.")
    headers = [c.strip().lower() for c in rows[header_idx]]
    di, vi = _find(headers, DATE_COLS), _find(headers, VALUE_COLS)
    si = _find(headers, DESC_COLS)
    idi = _find(headers, ("identificador", "id"))

    # Fatura de cartão (ex.: Nubank "date,title,amount"): valor positivo = gasto.
    if card is None:
        card = headers[:3] == ["date", "title", "amount"] or "fatura" in filename.lower() or "cartao" in filename.lower()
    account = f"{'Cartão' if card else 'Conta'} · {re.sub(r'\.csv$', '', filename, flags=re.I)[:40]}"

    out, seen = [], {}
    for r in rows[header_idx + 1:]:
        if len(r) <= max(di, vi):
            continue
        d, amount = _parse_date(r[di]), _parse_amount(r[vi])
        if not d or amount is None or amount == 0:
            continue
        desc = r[si] if si is not None and si < len(r) else ""
        signed = -amount if card else amount
        if idi is not None and idi < len(r) and r[idi].strip():
            key = r[idi].strip()
        else:
            base = (d, desc, amount)
            seen[base] = seen.get(base, 0) + 1  # mesma compra 2x no mesmo dia continua sendo 2 transações
            key = f"{base}#{seen[base]}"
        out.append(_tx(_id(account, key), account, d, desc, signed, card))
    if not out:
        raise ImportError_("Nenhuma transação válida encontrada no CSV.")
    return out


def parse_file(filename, raw: bytes, card=None):
    text = decode(raw)
    if filename.lower().endswith((".ofx", ".qfx")) or "<OFX>" in text.upper()[:2000]:
        return parse_ofx(text, filename)
    if filename.lower().endswith((".csv", ".txt")):
        return parse_csv(text, filename, card)
    raise ImportError_("Formato não suportado. Use .ofx ou .csv.")

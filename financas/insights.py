"""Análises: resumo do mês, tendência e recomendações de onde cortar."""
import calendar
from collections import defaultdict
from datetime import date
from statistics import median

from .categorize import CATEGORIES, merchant_key

EXPENSE_GROUPS = ("essencial", "desejo", "perda", "indefinido")


def group_of(category):
    return CATEGORIES.get(category, "indefinido")


def is_expense(tx):
    return tx["direction"] == "out" and group_of(tx["category"]) in EXPENSE_GROUPS


def is_income(tx):
    return tx["direction"] == "in" and group_of(tx["category"]) == "receita"


def month_of(tx):
    """Mês de referência: o da fatura (quando o app está em "ver por fatura") ou o da compra."""
    return tx.get("ref_month") or tx["date"][:7]


def shift_month(month, delta):
    y, m = map(int, month.split("-"))
    m += delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return f"{y:04d}-{m:02d}"


def available_months(txs):
    return sorted({month_of(t) for t in txs}, reverse=True)


def _by_month(txs):
    out = defaultdict(list)
    for t in txs:
        out[month_of(t)].append(t)
    return out


def _category_totals(txs):
    totals = defaultdict(float)
    for t in txs:
        if is_expense(t):
            totals[t["category"]] += t["amount"]
    return totals


def brl(value):
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


# --------------------------------------------------------------------------- resumo
def summarize(txs, month, budgets=None, today=None):
    budgets = budgets or {}
    today = today or date.today()
    by_month = _by_month(txs)
    cur = by_month.get(month, [])

    income = sum(t["amount"] for t in cur if is_income(t))
    expenses = sum(t["amount"] for t in cur if is_expense(t))
    invested = sum(t["amount"] for t in cur if t["category"] == "Investimentos" and t["direction"] == "out") - sum(
        t["amount"] for t in cur if t["category"] == "Investimentos" and t["direction"] == "in"
    )

    totals = _category_totals(cur)
    prev_months = [shift_month(month, -i) for i in (1, 2, 3)]
    prev_totals = [_category_totals(by_month[m]) for m in prev_months if m in by_month]

    categories = []
    for cat in sorted(set(totals) | set(budgets), key=lambda c: -totals.get(c, 0)):
        total = totals.get(cat, 0.0)
        prev_avg = sum(p.get(cat, 0.0) for p in prev_totals) / len(prev_totals) if prev_totals else None
        categories.append({
            "category": cat,
            "group": group_of(cat),
            "total": round(total, 2),
            "count": sum(1 for t in cur if is_expense(t) and t["category"] == cat),
            "pct": round(total / expenses * 100, 1) if expenses else 0,
            "budget": budgets.get(cat),
            "prev_avg": round(prev_avg, 2) if prev_avg is not None else None,
        })

    groups = defaultdict(float)
    for cat, total in totals.items():
        groups[group_of(cat)] += total

    projection = None
    if month == today.strftime("%Y-%m") and today.day < 28:
        days = calendar.monthrange(today.year, today.month)[1]
        projection = round(expenses / today.day * days, 2)

    trend = []
    for i in range(5, -1, -1):
        m = shift_month(month, -i)
        mt = by_month.get(m, [])
        trend.append({
            "month": m,
            "income": round(sum(t["amount"] for t in mt if is_income(t)), 2),
            "expenses": round(sum(t["amount"] for t in mt if is_expense(t)), 2),
        })

    return {
        "month": month,
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "balance": round(income - expenses, 2),
        "invested": round(invested, 2),
        "savings_rate": round((income - expenses) / income * 100, 1) if income else None,
        "projection": projection,
        "groups": {k: round(v, 2) for k, v in groups.items()},
        "categories": categories,
        "trend": trend,
    }


# ------------------------------------------------------------------------ insights
def _recurring(txs, month):
    """Detecta cobranças recorrentes (assinaturas) nos últimos 3 meses."""
    window = {shift_month(month, -i) for i in range(3)}
    groups = defaultdict(list)
    for t in txs:
        if month_of(t) in window and is_expense(t) and group_of(t["category"]) != "essencial":
            groups[merchant_key(t["description"])].append(t)

    found = []
    for key, items in groups.items():
        months = defaultdict(list)
        for t in items:
            months[month_of(t)].append(t["amount"])
        if len(months) < 2 or any(len(v) > 2 for v in months.values()):
            continue
        if month not in months and shift_month(month, -1) not in months:
            continue
        amounts = [a for v in months.values() for a in v]
        med = median(amounts)
        if med < 5 or any(abs(a - med) / med > 0.15 for a in amounts):
            if not all(t["category"] == "Assinaturas" for t in items):
                continue
        latest = max(items, key=lambda t: t["date"])
        ordered = sorted(items, key=lambda t: t["date"])
        raised = len(ordered) >= 2 and ordered[-1]["amount"] > ordered[-2]["amount"] * 1.05
        found.append({
            "nome": latest["description"],
            "categoria": latest["category"],
            "valor": round(latest["amount"], 2),
            "anual": round(latest["amount"] * 12, 2),
            "aumentou": raised,
        })
    return sorted(found, key=lambda r: -r["valor"])


def build_insights(txs, month, budgets=None):
    budgets = budgets or {}
    by_month = _by_month(txs)
    cur = by_month.get(month, [])
    s = summarize(txs, month, budgets)
    totals = {c["category"]: c for c in s["categories"]}
    income, expenses = s["income"], s["expenses"]
    out = []

    def add(id_, severity, title, detail, action, saving=0.0, in_total=True, items=None):
        out.append({
            "id": id_, "severidade": severity, "titulo": title, "detalhe": detail, "acao": action,
            "economia_mensal": round(saving, 2), "conta_no_total": in_total and saving > 0,
            "itens": items or [],
        })

    # 1. Gastando mais do que ganha
    if income and expenses > income:
        add("deficit", "alta", "Você gastou mais do que recebeu",
            f"Saídas de {brl(expenses)} contra entradas de {brl(income)}: déficit de {brl(expenses - income)}.",
            "Priorize os cortes abaixo até o saldo voltar a ficar positivo; evite cobrir o buraco com cheque especial ou rotativo.",
            in_total=False)

    # 2. Tarifas e juros = dinheiro perdido
    fees = [t for t in cur if is_expense(t) and t["category"] == "Tarifas e juros"]
    if fees:
        total = sum(t["amount"] for t in fees)
        add("tarifas", "alta", f"{brl(total)} em tarifas, juros e IOF",
            "É dinheiro que não compra nada. Juros de rotativo e cheque especial são os mais caros do mercado.",
            "Pague a fatura integral, migre para conta/cartão sem tarifa e evite compras internacionais com IOF alto.",
            saving=total,
            items=[{"nome": t["description"], "valor": t["amount"], "data": t["date"]} for t in fees])

    # 3. Assinaturas e cobranças recorrentes
    rec = _recurring(txs, month)
    if rec:
        total = sum(r["valor"] for r in rec)
        raised = [r["nome"] for r in rec if r["aumentou"]]
        detail = f"{len(rec)} cobranças recorrentes somam {brl(total)}/mês ({brl(total * 12)}/ano)."
        if raised:
            detail += f" Aumentaram de preço: {', '.join(raised)}."
        add("assinaturas", "media", "Assinaturas e cobranças recorrentes", detail,
            "Cancele o que não usou nas últimas 2 semanas e faça rodízio de streamings (1 por vez). Estimativa: cortar metade.",
            saving=total / 2, items=rec)

    # 4. Delivery vs mercado
    delivery = totals.get("Delivery", {}).get("total", 0)
    market = totals.get("Mercado", {}).get("total", 0)
    if delivery > 150 and delivery > 0.25 * (delivery + market):
        n = totals["Delivery"]["count"]
        add("delivery", "media", f"Delivery: {brl(delivery)} em {n} pedidos",
            f"Representa {delivery / (delivery + market) * 100:.0f}% do que você gasta com comida (mercado + delivery). "
            f"Ticket médio de {brl(delivery / n)}.",
            "Cozinhar em casa custa em média 1/3 do delivery. Trocar metade dos pedidos por mercado economiza cerca de 1/3 desse valor.",
            saving=delivery / 3)

    # 5. Gastos formiga
    small = [t for t in cur if is_expense(t) and t["amount"] < 40
             and group_of(t["category"]) in ("desejo", "indefinido") and t["category"] != "Delivery"]
    if len(small) >= 8:
        total = sum(t["amount"] for t in small)
        add("formiga", "media", f"Gastos formiga: {len(small)} compras pequenas somam {brl(total)}",
            "Compras abaixo de R$ 40 passam despercebidas, mas juntas pesam no mês.",
            "Defina uma mesada semanal para pequenos gastos. Meta: cortar metade.",
            saving=total / 2)

    # 6. Categorias que dispararam em relação à média
    covered = {"Delivery", "Tarifas e juros"}
    for cat, c in totals.items():
        if cat in covered or c["prev_avg"] is None or (c["group"] == "essencial" and cat not in ("Combustível", "Transporte")):
            continue
        delta = c["total"] - c["prev_avg"]
        if c["prev_avg"] > 0 and c["total"] > 1.3 * c["prev_avg"] and delta > 100:
            add(f"alta-{cat}", "media", f"{cat} subiu {(c['total'] / c['prev_avg'] - 1) * 100:.0f}%",
                f"{brl(c['total'])} este mês contra média de {brl(c['prev_avg'])} nos 3 meses anteriores.",
                f"Volte para a sua média em {cat.lower()}: defina um orçamento de {brl(c['prev_avg'])} para a categoria.",
                saving=delta)

    # 7. Orçamentos estourados
    for cat, limit in budgets.items():
        spent = totals.get(cat, {}).get("total", 0)
        if spent > limit:
            add(f"orcamento-{cat}", "alta", f"Orçamento de {cat} estourado",
                f"Gasto de {brl(spent)} para um limite de {brl(limit)} (+{brl(spent - limit)}).",
                "Congele gastos nessa categoria pelo resto do mês ou ajuste o orçamento se ele não for realista.",
                saving=spent - limit, in_total=False)
        elif spent >= 0.85 * limit:
            add(f"orcamento-{cat}", "baixa", f"{cat} perto do limite",
                f"{brl(spent)} de {brl(limit)} ({spent / limit * 100:.0f}%).",
                "Segure os próximos gastos dessa categoria.", in_total=False)

    # 8. Regra 50/30/20
    if income:
        needs = s["groups"].get("essencial", 0)
        wants = sum(s["groups"].get(g, 0) for g in ("desejo", "perda", "indefinido"))
        if wants > 0.30 * income:
            add("503020-desejos", "media", f"Gastos não essenciais em {wants / income * 100:.0f}% da renda",
                "A regra 50/30/20 sugere até 30% da renda para desejos (lazer, delivery, compras, assinaturas).",
                f"Reduzir para 30% libera {brl(wants - 0.30 * income)} por mês.",
                saving=wants - 0.30 * income, in_total=False)
        if needs > 0.50 * income:
            add("503020-essenciais", "baixa", f"Custos essenciais em {needs / income * 100:.0f}% da renda",
                "O ideal é que moradia, contas, mercado, transporte e saúde fiquem perto de 50% da renda.",
                "Revise contratos fixos: plano de celular/internet, seguro, plano de saúde, aluguel.", in_total=False)
        saved_rate = (income - expenses) / income
        if 0 <= saved_rate < 0.20:
            add("503020-poupanca", "baixa", f"Você guardou {saved_rate * 100:.0f}% da renda",
                "A meta recomendada é poupar ou investir pelo menos 20% do que entra.",
                "Programe uma transferência automática para investimento no dia do salário.", in_total=False)

    # 9. Muito gasto sem categoria clara
    undefined = s["groups"].get("indefinido", 0)
    if expenses and undefined > 0.15 * expenses:
        add("indefinido", "baixa", f"{brl(undefined)} em gastos sem categoria clara",
            "Pix enviados e transações genéricas escondem para onde o dinheiro está indo.",
            "Recategorize na aba Transações. Use \"aplicar a todas parecidas\" para o app aprender.", in_total=False)

    # 10. Maiores estabelecimentos
    merchants = defaultdict(lambda: {"valor": 0.0, "vezes": 0, "nome": ""})
    for t in cur:
        if is_expense(t) and group_of(t["category"]) != "essencial":
            m = merchants[merchant_key(t["description"])]
            m["valor"] += t["amount"]
            m["vezes"] += 1
            m["nome"] = t["description"]
    top = sorted(merchants.values(), key=lambda m: -m["valor"])[:5]
    if top:
        add("top", "info", "Onde mais foi dinheiro (fora os essenciais)",
            "Os 5 estabelecimentos com mais gasto no mês.",
            "Veja se algum deles pode ser trocado por uma opção mais barata ou usado com menos frequência.",
            in_total=False, items=[{**m, "valor": round(m["valor"], 2)} for m in top])

    order = {"alta": 0, "media": 1, "baixa": 2, "info": 3}
    out.sort(key=lambda i: (order[i["severidade"]], i["id"] != "deficit", -i["economia_mensal"]))
    return {
        "insights": out,
        "economia_potencial": round(sum(i["economia_mensal"] for i in out if i["conta_no_total"]), 2),
    }

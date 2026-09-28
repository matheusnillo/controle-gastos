"""Monta os alertas de WhatsApp a partir das transações.

Cada alerta tem uma chave única; o app guarda as chaves enviadas para nunca repetir o aviso.
"""
from datetime import date, timedelta

from . import insights
from .insights import brl

DEFAULTS = {
    "alertas_ativos": "1",
    "alerta_valor_minimo": "200",
    "alerta_tarifas": "1",
    "alerta_orcamento": "1",
    "alerta_assinaturas": "1",
    "resumo_diario": "1",
    "resumo_hora": "20",
}

# Só avisa de lançamentos recentes: evita uma enxurrada de mensagens na primeira sincronização.
RECENT_DAYS = 3


def config(settings):
    return {**DEFAULTS, **{k: v for k, v in settings.items() if v is not None}}


def _on(cfg, key):
    return str(cfg.get(key, "0")) in ("1", "true", "True", "on")


def _fmt_date(d):
    return f"{d[8:10]}/{d[5:7]}"


def pending_alerts(txs, budgets, cfg, today=None):
    """Lista de (chave, linha de texto) de alertas. `txs` já com ref_month (modo fatura)."""
    today = today or date.today()
    since = (today - timedelta(days=RECENT_DAYS)).isoformat()
    month = today.strftime("%Y-%m")
    out = []

    minimum = float(cfg.get("alerta_valor_minimo") or 0)
    for t in txs:
        if t["date"] < since or not insights.is_expense(t):
            continue
        if _on(cfg, "alerta_tarifas") and t["category"] == "Tarifas e juros":
            out.append((f"tarifa:{t['id']}",
                        f"⚠️ Tarifa/juros de *{brl(t['amount'])}* — {t['description'].strip()[:40]} ({_fmt_date(t['date'])}). "
                        "É dinheiro perdido: veja se dá para evitar."))
        elif minimum and t["amount"] >= minimum:
            out.append((f"gasto:{t['id']}",
                        f"💸 Gasto de *{brl(t['amount'])}* em {t['description'].strip()[:40]} "
                        f"({t['category']}, {_fmt_date(t['date'])})."))

    if _on(cfg, "alerta_orcamento") and budgets:
        totals = {c["category"]: c["total"] for c in insights.summarize(txs, month, budgets, today)["categories"]}
        for cat, limit in budgets.items():
            spent = totals.get(cat, 0)
            if spent > limit:
                out.append((f"orc100:{cat}:{month}",
                            f"🚨 Orçamento de *{cat}* estourado: {brl(spent)} de {brl(limit)} (+{brl(spent - limit)})."))
            elif spent >= 0.85 * limit:
                out.append((f"orc85:{cat}:{month}",
                            f"🟡 {cat} já usou {spent / limit * 100:.0f}% do orçamento ({brl(spent)} de {brl(limit)})."))

    if _on(cfg, "alerta_assinaturas"):
        for r in insights._recurring(txs, month):
            if r["aumentou"]:
                out.append((f"assin:{r['nome'][:30]}:{month}",
                            f"📈 A assinatura {r['nome'].strip()[:35]} aumentou para {brl(r['valor'])}/mês."))
    return out


def daily_summary(txs, budgets, today=None):
    today = today or date.today()
    month = today.strftime("%Y-%m")
    s = insights.summarize(txs, month, budgets, today)
    extra = insights.build_insights(txs, month, budgets)

    recent_from = (today - timedelta(days=1)).isoformat()
    recent = [t for t in txs if t["date"] >= recent_from and insights.is_expense(t)]
    lines = [f"📊 *Resumo {today.strftime('%d/%m')}*"]
    if recent:
        lines.append(f"Ontem e hoje: {brl(sum(t['amount'] for t in recent))} em {len(recent)} lançamento(s)")
    else:
        lines.append("Nenhum gasto novo lançado ontem/hoje (o banco pode levar 1 dia para enviar).")
    lines.append(f"No mês: gastos {brl(s['expenses'])} · entradas {brl(s['income'])} · saldo *{brl(s['balance'])}*")
    if s["projection"]:
        lines.append(f"Projeção de gastos até o fim do mês: {brl(s['projection'])}")
    top = [c for c in s["categories"] if c["total"] > 0][:3]
    if top:
        lines.append("Top: " + ", ".join(f"{c['category']} {brl(c['total'])}" for c in top))
    over = [c for c in s["categories"] if c["budget"] and c["total"] > c["budget"]]
    if over:
        lines.append("Estourados: " + ", ".join(c["category"] for c in over))
    if extra["economia_potencial"] > 0:
        best = next((i for i in extra["insights"] if i["conta_no_total"]), None)
        lines.append(f"💡 Dá para economizar ~{brl(extra['economia_potencial'])}/mês."
                     + (f" Comece por: {best['titulo']}." if best else ""))
    return "\n".join(lines)

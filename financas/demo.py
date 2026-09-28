"""Gera 6 meses de extrato fictício, realista, para testar o app sem conectar um banco."""
import calendar
import random
from datetime import date


def _day(y, m, d):
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def generate(today=None, months=6, seed=42):
    today = today or date.today()
    rnd = random.Random(seed)
    txs = []
    n = 0

    def add(d, desc, amount, direction="out", account="Conta corrente", pluggy_category=None):
        nonlocal n
        if d > today:
            return
        n += 1
        txs.append({
            "id": f"demo-{n}", "account_id": f"demo-{account}", "account_name": f"Banco Demo · {account}",
            "date": d.isoformat(), "description": desc, "amount": round(amount, 2), "direction": direction,
            "pluggy_category": pluggy_category, "source": "demo",
        })

    y, m = today.year, today.month
    month_list = []
    for _ in range(months):
        month_list.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    month_list.reverse()

    for idx, (y, m) in enumerate(month_list):
        last = idx == len(month_list) - 1
        # Entradas
        add(_day(y, m, 5), "PAGTO SALARIO EMPRESA XYZ LTDA", 6500, "in")
        if idx % 2 == 1:
            add(_day(y, m, 18), "PIX RECEBIDO FREELA DESIGN", rnd.choice([600, 850, 1200]), "in")

        # Fixos essenciais
        add(_day(y, m, 6), "ALUGUEL QUINTOANDAR", 1800)
        add(_day(y, m, 10), "CONDOMINIO RESIDENCIAL", 420)
        add(_day(y, m, 12), "ENEL DISTRIBUICAO ENERGIA", rnd.uniform(160, 240))
        add(_day(y, m, 15), "VIVO FIBRA INTERNET", 119.90)
        add(_day(y, m, 15), "CLARO MOVEL", 69.90)
        add(_day(y, m, 20), "SABESP AGUA", rnd.uniform(70, 95))

        # Assinaturas (cartão)
        card = "Cartão de crédito"
        add(_day(y, m, 3), "NETFLIX.COM", 44.90 if idx < 3 else 59.90, account=card)
        add(_day(y, m, 8), "SPOTIFY", 21.90, account=card)
        add(_day(y, m, 9), "DISNEY PLUS", 43.90, account=card)
        add(_day(y, m, 11), "HBO MAX", 34.90, account=card)
        add(_day(y, m, 14), "SMART FIT MENSALIDADE", 129.90, account=card)
        add(_day(y, m, 17), "APPLE.COM/BILL ICLOUD", 14.90, account=card)
        add(_day(y, m, 22), "OPENAI CHATGPT SUBSCR", 104.00, account=card)
        add(_day(y, m, 25), "GLOBOPLAY", 26.90, account=card)

        # Mercado semanal
        for d in (2, 9, 16, 23, 30):
            add(_day(y, m, d), rnd.choice(["SUPERMERCADO PAO DE ACUCAR", "ASSAI ATACADISTA", "CARREFOUR HIPER"]),
                rnd.uniform(140, 320), account=card)

        # Delivery crescendo ao longo dos meses
        for _ in range(8 + idx * 2 + (4 if last else 0)):
            add(_day(y, m, rnd.randint(1, 28)), rnd.choice(["IFD*IFOOD", "IFD*IFOOD CLUB", "RAPPI BRASIL", "ZE DELIVERY"]),
                rnd.uniform(35, 95), account=card)

        # Transporte
        for _ in range(rnd.randint(8, 14)):
            add(_day(y, m, rnd.randint(1, 28)), rnd.choice(["UBER *TRIP", "99APP *CORRIDA"]), rnd.uniform(12, 45), account=card)
        for d in (7, 21):
            add(_day(y, m, d), "AUTO POSTO SHELL", rnd.uniform(180, 260), account=card)

        # Gastos formiga
        for _ in range(rnd.randint(12, 20)):
            add(_day(y, m, rnd.randint(1, 28)),
                rnd.choice(["PADARIA SAO JOSE", "STARBUCKS", "LANCHONETE DO ZE", "CAFE DO PONTO", "LOJAS AMERICANAS"]),
                rnd.uniform(8, 38), account=card)

        # Restaurantes / lazer / compras
        for _ in range(rnd.randint(2, 4)):
            add(_day(y, m, rnd.randint(1, 28)), rnd.choice(["OUTBACK STEAKHOUSE", "RESTAURANTE SABOR", "PIZZARIA BELLA"]),
                rnd.uniform(90, 220), account=card)
        add(_day(y, m, rnd.randint(1, 28)), "CINEMARK", rnd.uniform(50, 90), account=card)
        for _ in range(rnd.randint(1, 3) + (3 if last else 0)):
            add(_day(y, m, rnd.randint(1, 28)), rnd.choice(["MERCADOLIVRE*LOJA", "AMAZON MARKETPLACE", "SHOPEE", "SHEIN"]),
                rnd.uniform(60, 280), account=card)

        # Saúde
        add(_day(y, m, rnd.randint(1, 28)), "DROGASIL", rnd.uniform(40, 140), account=card)

        # Pix genéricos
        for _ in range(rnd.randint(1, 3)):
            add(_day(y, m, rnd.randint(1, 28)), "PIX ENVIADO JOAO SILVA", rnd.uniform(30, 150))

        # Tarifas e juros (pior nos meses mais recentes)
        add(_day(y, m, 1), "TARIFA PACOTE DE SERVICOS", 39.90)
        if idx >= 3:
            add(_day(y, m, 4), "JUROS ROTATIVO CARTAO", rnd.uniform(90, 180), account=card)
            add(_day(y, m, 4), "IOF ROTATIVO", rnd.uniform(8, 20), account=card)

        # Investimento e pagamento de fatura (neutros)
        add(_day(y, m, 6), "APLICACAO CDB LIQUIDEZ DIARIA", 300 if idx < 3 else 100)
        add(_day(y, m, 10), "PAGAMENTO DE FATURA CARTAO", rnd.uniform(2500, 3200))

    return txs

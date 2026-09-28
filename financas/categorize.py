"""Categorização de transações em categorias em português.

Ordem de prioridade:
  1. regra criada pelo usuário (recategorizar "todas parecidas")
  2. palavras-chave no nome do estabelecimento (mais confiável para comércio brasileiro)
  3. categoria enviada pela Pluggy / Open Finance
  4. "Outros" (saída) ou "Outras receitas" (entrada)
"""
import re
import unicodedata

# grupo: essencial | desejo | perda | indefinido (conta como gasto, mas precisa ser revisado)
#        | neutro (não conta como gasto nem receita) | receita
CATEGORIES = {
    "Moradia": "essencial",
    "Contas da casa": "essencial",
    "Mercado": "essencial",
    "Transporte": "essencial",
    "Combustível": "essencial",
    "Saúde": "essencial",
    "Pets": "essencial",
    "Educação": "essencial",
    "Impostos": "essencial",
    "Delivery": "desejo",
    "Restaurantes": "desejo",
    "Assinaturas": "desejo",
    "Compras": "desejo",
    "Lazer": "desejo",
    "Viagem": "desejo",
    "Pix e transferências enviadas": "indefinido",
    "Outros": "indefinido",
    "Tarifas e juros": "perda",
    "Investimentos": "neutro",
    "Aplicação/resgate automático": "neutro",
    "Transferência entre contas": "neutro",
    "Pagamento de fatura": "neutro",
    "Estornos e créditos no cartão": "neutro",
    "Salário": "receita",
    "Outras receitas": "receita",
}

INCOME_CATEGORIES = [c for c, g in CATEGORIES.items() if g == "receita"]
# Categorias que não contam como gasto (evita contar em dobro fatura/transferências)
NEUTRAL_CATEGORIES = [c for c, g in CATEGORIES.items() if g == "neutro"]

# A ordem importa: termos mais específicos antes dos genéricos.
KEYWORD_RULES = [
    # BB Rende Fácil / "APLIC AUT MAIS", Itaú "APLIC AUT", etc.: o banco aplica e resgata o saldo sozinho.
    ("Aplicação/resgate automático", ["RES APLIC", "APLIC AUT", "RESG AUT", "RESGATE AUT", "APLICACAO AUT",
                                      "REND PAGO APLIC AUT", "BB RENDE FACIL", "RENDE FACIL", "APLIC AUTOMATICA",
                                      "RESGATE AUTOMATICO", "APLICACAO AUTOMATICA"]),
    ("Pagamento de fatura", ["PAGAMENTO DE FATURA", "PAGAMENTO FATURA", "PAGTO FATURA", "PAG FATURA", "PGTO FATURA"]),
    ("Tarifas e juros", ["TARIFA", "JUROS", "IOF", "MULTA", "ANUIDADE", "ENCARGO", "MORA", "CESTA DE SERVICOS", "ROTATIVO", "SAQUE 24H"]),
    ("Investimentos", ["APLICACAO", "CDB", "TESOURO", "CORRETORA", "POUPANCA", "RESGATE", "LCI", "LCA", "XP INVEST", "RICO INVEST", "NUINVEST"]),
    ("Salário", ["SALARIO", "PROVENTOS", "FOLHA DE PAGAMENTO", "PAGTO SALARIO", "13 SALARIO", "FERIAS"]),
    ("Delivery", ["IFOOD", "IFD", "RAPPI", "ZE DELIVERY", "AIQFOME", "UBER EATS", "JAMES DELIVERY"]),
    ("Assinaturas", ["NETFLIX", "SPOTIFY", "DISNEY", "HBO", "HBOMAX", "MAX COM", "PRIME VIDEO", "AMAZON PRIME", "AMAZONPRIME",
                     "YOUTUBE", "DEEZER", "GLOBOPLAY", "APPLE COM", "ICLOUD", "GOOGLE ONE", "CHATGPT", "OPENAI", "ANTHROPIC",
                     "CLAUDE AI", "PARAMOUNT", "CRUNCHYROLL", "GYMPASS", "WELLHUB", "SMART FIT", "SMARTFIT", "BLUEFIT",
                     "TOTALPASS", "MICROSOFT", "XBOX GAME PASS", "PLAYSTATION PLUS", "CANVA", "ADOBE", "KINDLE UNLIMITED"]),
    ("Transporte", ["UBER", "99APP", "99 APP", "99 POP", "99TAXI", "CABIFY", "METRO", "BILHETE UNICO", "SPTRANS", "CPTM",
                    "ESTACIONAMENTO", "ESTAPAR", "SEM PARAR", "CONECTCAR", "VELOE", "PEDAGIO", "ONIBUS"]),
    ("Combustível", ["POSTO", "SHELL", "IPIRANGA", "PETROBRAS", "BR MANIA", "COMBUSTIVEL", "AUTO POSTO"]),
    ("Compras", ["MERCADO LIVRE", "MERCADOLIVRE", "AMAZON", "SHOPEE", "SHEIN", "ALIEXPRESS", "MAGALU",
                 "MAGAZINE LUIZA", "AMERICANAS", "RENNER", "RIACHUELO", "C A MODAS", "CENTAURO", "NETSHOES", "KABUM",
                 "CASAS BAHIA", "ZARA", "DECATHLON", "LEROY MERLIN", "TEMU"]),
    ("Mercado", ["SUPERMERCADO", "MERCADO", "ASSAI", "ATACADAO", "CARREFOUR", "PAO DE ACUCAR", "EXTRA", "HORTIFRUTI",
                 "SACOLAO", "ATACAREJO", "SAMS CLUB", "OXXO", "MINUTO PA", "DIA BRASIL", "GUANABARA", "ZAFFARI"]),
    ("Saúde", ["FARMACIA", "DROGARIA", "DROGAO", "DROGASIL", "RAIA", "PAGUE MENOS", "PANVEL", "HOSPITAL", "CLINICA", "LABORATORIO",
               "UNIMED", "AMIL", "HAPVIDA", "SULAMERICA", "BRADESCO SAUDE", "ODONTO", "DENTISTA", "PSICOLOGO", "PSICOLOGA", "PSICOLOGIA"]),
    ("Educação", ["ESCOLA", "FACULDADE", "UNIVERSIDADE", "CURSO", "UDEMY", "ALURA", "LIVRARIA", "COLEGIO", "DUOLINGO"]),
    ("Restaurantes", ["RESTAURANTE", "LANCHONETE", "PIZZARIA", "HAMBURGUER", "HAMBURGUERIA", "BURGER", "MC DONALDS", "MCDONALDS", "OUTBACK",
                      "STARBUCKS", "CAFE", "PADARIA", "BAR ", "CHURRASCARIA", "SUSHI", "BOTECO", "SUBWAY", "HABIBS"]),
    ("Lazer", ["CINEMA", "CINEMARK", "INGRESSO", "SYMPLA", "EVENTIM", "STEAM", "NUUVEM", "PLAYSTATION", "NINTENDO",
               "TEATRO", "PARQUE", "BALADA"]),
    ("Viagem", ["HOTEL", "AIRBNB", "BOOKING", "LATAM", "GOL LINHAS", "AZUL LINHAS", "DECOLAR", "123MILHAS", "POUSADA",
                "HURB", "RODOVIARIA"]),
    ("Moradia", ["ALUGUEL", "CONDOMINIO", "QUINTOANDAR", "QUINTO ANDAR", "IMOBILIARIA"]),
    ("Contas da casa", ["ENEL", "SABESP", "CEMIG", "COPEL", "LIGHT S A", "CPFL", "ENERGISA", "EQUATORIAL", "COMGAS",
                        "NATURGY", "VIVO", "CLARO", "TIM ", "OI FIBRA", "NET SERVICOS", "INTERNET", "SANEPAR", "CEDAE",
                        "EMBASA", "COMPESA", "ENERGIA", "GAS "]),
    ("Impostos", ["IPVA", "IPTU", "DARF", "DAS SIMPLES", "IMPOSTO", "LICENCIAMENTO", "DETRAN", "GRU"]),
    ("Transferência entre contas", ["MESMA TITULARIDADE", "ENTRE CONTAS", "TRANSF PROPRIA", "MESMO TITULAR"]),
    ("Pix e transferências enviadas", ["PIX ENVIADO", "PIX TRANSF", "TRANSFERENCIA ENVIADA", "TED ENVIADA", "DOC ENVIADO"]),
]

# Mapeamento da taxonomia (em inglês) da Pluggy -> nossas categorias.
PLUGGY_MAP = [
    ("credit card payment", "Pagamento de fatura"),
    ("same person transfer", "Transferência entre contas"),
    ("same ownership", "Transferência entre contas"),
    ("salary", "Salário"),
    ("retirement", "Outras receitas"),
    ("investment", "Investimentos"),
    ("fee", "Tarifas e juros"),
    ("interest", "Tarifas e juros"),
    ("late payment", "Tarifas e juros"),
    ("taxi", "Transporte"),
    ("ride", "Transporte"),
    ("tax on financial", "Tarifas e juros"),
    ("tax", "Impostos"),
    ("food delivery", "Delivery"),
    ("delivery", "Delivery"),
    ("groceries", "Mercado"),
    ("supermarket", "Mercado"),
    ("eating out", "Restaurantes"),
    ("restaurant", "Restaurantes"),
    ("public transport", "Transporte"),
    ("parking", "Transporte"),
    ("toll", "Transporte"),
    ("gas station", "Combustível"),
    ("fuel", "Combustível"),
    ("pharmacy", "Saúde"),
    ("health", "Saúde"),
    ("hospital", "Saúde"),
    ("dentist", "Saúde"),
    ("education", "Educação"),
    ("school", "Educação"),
    ("university", "Educação"),
    ("streaming", "Assinaturas"),
    ("digital services", "Assinaturas"),
    ("gym", "Assinaturas"),
    ("subscription", "Assinaturas"),
    ("rent", "Moradia"),
    ("housing", "Moradia"),
    ("electricity", "Contas da casa"),
    ("water", "Contas da casa"),
    ("telecom", "Contas da casa"),
    ("internet", "Contas da casa"),
    ("mobile", "Contas da casa"),
    ("utilities", "Contas da casa"),
    ("travel", "Viagem"),
    ("accommodation", "Viagem"),
    ("accomodation", "Viagem"),
    ("airline", "Viagem"),
    ("airport", "Viagem"),
    ("leisure", "Lazer"),
    ("entertainment", "Lazer"),
    ("gaming", "Lazer"),
    ("optometry", "Saúde"),
    ("pet ", "Pets"),
    ("veterin", "Pets"),
    ("automotive", "Transporte"),
    ("houseware", "Compras"),
    ("office supplies", "Compras"),
    ("shopping", "Compras"),
    ("clothing", "Compras"),
    ("electronics", "Compras"),
    ("pix", "Pix e transferências enviadas"),
    ("transfer", "Pix e transferências enviadas"),
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text.upper())
    return " " + re.sub(r"\s+", " ", text).strip() + " "


NOISE_WORDS = {
    "PARC", "PARCELA", "PIX", "QR", "CODE", "COMPRA", "COMPRAS", "DEBITO", "CREDITO", "CARTAO", "PAG", "PAGTO", "PGTO",
    "PAGAMENTO", "ENVIADO", "ENVIADA", "RECEBIDO", "RECEBIDA", "TRANSFERENCIA", "TRANSF", "TED", "DOC", "BOLETO",
    "DE", "DA", "DO", "DAS", "DOS", "E", "EM", "COM", "NO", "NA", "A", "O", "BR", "LTDA", "SA", "ME", "EIRELI",
}


def merchant_key(description: str) -> str:
    """Chave estável do estabelecimento/pessoa, sem prefixos genéricos do banco.

    "Pagamento de Pix QR Code UBERTRANS 123" -> "UBERTRANS"; "Pix enviado JOAO DA SILVA" -> "JOAO SILVA".
    """
    text = re.sub(r"\d+", " ", normalize(description))
    words = [w for w in text.split() if len(w) > 1 and w not in NOISE_WORDS]
    return " ".join(words[:3]) or normalize(description).strip()


def _match_keywords(description: str):
    text = normalize(description)
    for category, words in KEYWORD_RULES:
        for w in words:
            # Casa por palavra inteira (evita "EXTRA" dentro de "EXTRATO").
            if re.search(r"(?<![A-Z0-9])" + re.escape(w.strip()) + r"(?![A-Z0-9])", text):
                return category
    return None


def _match_pluggy(pluggy_category):
    if not pluggy_category:
        return None
    lower = pluggy_category.lower()
    for needle, category in PLUGGY_MAP:
        if re.search(r"\b" + re.escape(needle), lower):
            return category
    return None


CARD_PAYMENT_WORDS = ("PGTO", "PAGTO", "PAGAMENTO", "PAG ", "PG ", "FAT", "PIX", "DEBITO AUTOMATICO", "DEB AUT")


def categorize(description, direction, pluggy_category=None, rules=None, is_card=False):
    if rules:
        rule = rules.get(merchant_key(description))
        if rule:
            return rule

    # Sinais fortes da Pluggy (vêm do próprio banco) valem mais que palavras-chave.
    strong = (pluggy_category or "").lower()
    if "same person transfer" in strong or "same ownership" in strong:
        return "Transferência entre contas"
    if "automatic investment" in strong:
        return "Aplicação/resgate automático"

    category = _match_keywords(description) or _match_pluggy(pluggy_category)

    if is_card and direction == "in":
        # Entrada no cartão nunca é receita: ou é pagamento da fatura ou estorno/ajuste.
        text = normalize(description)
        if category == "Pagamento de fatura" or any(w in text for w in (" " + w for w in CARD_PAYMENT_WORDS)):
            return "Pagamento de fatura"
        return "Estornos e créditos no cartão"

    if direction == "in":
        # Entradas só podem ser receita ou neutras (resgate, transferência própria, estorno de fatura).
        if category in INCOME_CATEGORIES or category in NEUTRAL_CATEGORIES:
            return category
        return "Outras receitas"

    if category is None or category in INCOME_CATEGORIES:
        return "Outros"
    return category

import unittest
from datetime import date

from financas import demo, importer, insights
from financas.categorize import categorize, merchant_key


def tx(d, desc, amount, direction="out", category=None):
    return {"id": f"{d}-{desc}-{amount}", "date": d, "description": desc, "amount": amount,
            "direction": direction, "category": category or categorize(desc, direction)}


class CategorizeTest(unittest.TestCase):
    def test_keywords(self):
        cases = {
            "IFD*IFOOD": "Delivery",
            "UBER *TRIP": "Transporte",
            "UBER EATS": "Delivery",
            "MERCADOLIVRE*LOJA": "Compras",
            "SUPERMERCADO PAO DE ACUCAR": "Mercado",
            "NETFLIX.COM": "Assinaturas",
            "AMAZON PRIME": "Assinaturas",
            "AMAZON MARKETPLACE": "Compras",
            "JUROS ROTATIVO CARTAO": "Tarifas e juros",
            "PAGAMENTO DE FATURA CARTAO": "Pagamento de fatura",
            "IMPOSTO DE RENDA DARF": "Impostos",
            "PIX ENVIADO MARIA": "Pix e transferências enviadas",
            "Drogaria São Paulo": "Saúde",
        }
        for desc, expected in cases.items():
            self.assertEqual(categorize(desc, "out"), expected, desc)

    def test_word_boundary(self):
        # "EXTRATO" não pode casar com o mercado "EXTRA"; "IMPOSTO" não pode casar com "POSTO"
        self.assertNotEqual(categorize("EXTRATO CONSOLIDADO", "out"), "Mercado")
        self.assertEqual(categorize("IMPOSTO SINDICAL", "out"), "Impostos")

    def test_pluggy_fallback_and_income(self):
        self.assertEqual(categorize("LOJA XPTO", "out", "Food delivery"), "Delivery")
        self.assertEqual(categorize("EMPRESA ABC", "in", "Salary"), "Salário")
        self.assertEqual(categorize("ESTORNO LOJA", "in"), "Outras receitas")
        self.assertEqual(categorize("LOJA DESCONHECIDA", "out"), "Outros")

    def test_pluggy_taxi_is_not_tax(self):
        self.assertEqual(categorize("LOJA X", "out", "Taxi and ride-hailing"), "Transporte")
        self.assertEqual(categorize("LOJA X", "out", "Tax on financial operations"), "Tarifas e juros")
        self.assertEqual(categorize("LOJA X", "out", "Taxes"), "Impostos")

    def test_card_inflows_are_never_income(self):
        self.assertEqual(categorize("PGTO. QR CODE PIX 4700", "in", "Third party transfer - PIX", is_card=True),
                         "Pagamento de fatura")
        self.assertEqual(categorize("PG PARCELADO AUTOMAT FAT", "in", "Transfers", is_card=True), "Pagamento de fatura")
        self.assertEqual(categorize("AJUSTE A CREDITO DE JUROS", "in", "Interests charged", is_card=True),
                         "Estornos e créditos no cartão")
        # na conta corrente, Pix recebido continua sendo receita
        self.assertEqual(categorize("PIX RECEBIDO", "in", "Third party transfer - PIX"), "Outras receitas")

    def test_user_rules_win(self):
        rules = {merchant_key("PIX ENVIADO JOAO SILVA"): "Moradia"}
        self.assertEqual(categorize("PIX ENVIADO JOAO SILVA", "out", rules=rules), "Moradia")

    def test_merchant_key_skips_bank_prefixes(self):
        # Antes todas viravam "DE QR CODE" e uma regra pegava todas as compras por Pix QR.
        self.assertEqual(merchant_key("Pagamento de Pix QR Code UBERTRANS"), "UBERTRANS")
        self.assertEqual(merchant_key("Pagamento de Pix QR Code LEROY MERLIN COMPANHIA"), "LEROY MERLIN COMPANHIA")
        self.assertNotEqual(merchant_key("Pagamento de Pix QR Code UBERTRANS"),
                            merchant_key("Pagamento de Pix QR Code BANCO DO BRASIL SA"))
        self.assertEqual(merchant_key("Pix enviado JOAO CARLOS PEREIRA SOUZA"), "JOAO CARLOS PEREIRA")

    def test_automatic_investment_and_own_transfers_are_neutral(self):
        self.assertEqual(categorize("Resgate RES APLIC AUT MAIS", "in", "Automatic investment"),
                         "Aplicação/resgate automático")
        self.assertEqual(categorize("Resgate RES APLIC AUT MAIS", "in"), "Aplicação/resgate automático")
        self.assertEqual(categorize("Aplicação APL APLIC AUT MAIS", "out"), "Aplicação/resgate automático")
        self.assertEqual(categorize("Pix enviado FULANO DE TAL", "out", "Same person transfer"),
                         "Transferência entre contas")

    def test_merchant_key_ignores_numbers(self):
        self.assertEqual(merchant_key("NETFLIX.COM 123456"), merchant_key("NETFLIX.COM 987"))


class InsightsTest(unittest.TestCase):
    def test_summary_excludes_neutral(self):
        txs = [
            tx("2026-09-05", "SALARIO", 5000, "in"),
            tx("2026-09-06", "IFD*IFOOD", 100),
            tx("2026-09-10", "PAGAMENTO DE FATURA", 3000),
            tx("2026-09-11", "APLICACAO CDB", 500),
        ]
        s = insights.summarize(txs, "2026-09", today=date(2026, 10, 1))
        self.assertEqual(s["income"], 5000)
        self.assertEqual(s["expenses"], 100)
        self.assertEqual(s["invested"], 500)

    def test_detects_subscription_and_fees(self):
        txs = []
        for m in ("07", "08", "09"):
            txs.append(tx(f"2026-{m}-03", "NETFLIX.COM", 55.90))
            txs.append(tx(f"2026-{m}-05", "SALARIO", 5000, "in"))
        txs.append(tx("2026-09-04", "JUROS ROTATIVO", 120))
        result = insights.build_insights(txs, "2026-09")
        ids = {i["id"] for i in result["insights"]}
        self.assertIn("assinaturas", ids)
        self.assertIn("tarifas", ids)
        fees = next(i for i in result["insights"] if i["id"] == "tarifas")
        self.assertEqual(fees["economia_mensal"], 120)

    def test_weekly_market_is_not_subscription(self):
        txs = [tx(f"2026-{m}-{d:02d}", "SUPERMERCADO BOM", 200)
               for m in ("07", "08", "09") for d in (2, 9, 16, 23)]
        rec = insights._recurring(txs, "2026-09")
        self.assertEqual(rec, [])

    def test_budget_overrun(self):
        txs = [tx("2026-09-06", "IFD*IFOOD", 400)]
        result = insights.build_insights(txs, "2026-09", {"Delivery": 300})
        over = next(i for i in result["insights"] if i["id"] == "orcamento-Delivery")
        self.assertEqual(over["severidade"], "alta")
        self.assertEqual(over["economia_mensal"], 100)

    def test_demo_end_to_end(self):
        raw = demo.generate(today=date(2026, 9, 27))
        for t in raw:
            t["category"] = categorize(t["description"], t["direction"])
        result = insights.build_insights(raw, "2026-09")
        self.assertGreater(result["economia_potencial"], 0)
        self.assertEqual(result["insights"][0]["id"], "deficit")

    def test_card_purchase_counts_in_bill_month(self):
        # Fatura com vencimento em setembro tem compras de agosto (ex.: TryHackMe em 17/08).
        t = tx("2026-08-17", "TRYHACKME.COM LONDON", 65.14)
        self.assertEqual(insights.month_of(t), "2026-08")
        t["ref_month"] = "2026-09"
        s = insights.summarize([t], "2026-09", today=date(2026, 10, 1))
        self.assertEqual(s["expenses"], 65.14)

    def test_shift_month(self):
        self.assertEqual(insights.shift_month("2026-01", -1), "2025-12")
        self.assertEqual(insights.shift_month("2026-12", 1), "2027-01")


OFX = b"""OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKACCTFROM><BANKID>0341<ACCTID>12345-6</BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260905120000[-3:BRT]<TRNAMT>-45.90<FITID>A1<MEMO>IFD*IFOOD
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260905<TRNAMT>6500.00<FITID>A2<MEMO>PAGTO SALARIO
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""


class ImporterTest(unittest.TestCase):
    def test_ofx_sgml_without_closing_tags(self):
        txs = importer.parse_file("extrato.ofx", OFX)
        self.assertEqual([(t["date"], t["amount"], t["direction"]) for t in txs],
                         [("2026-09-05", 45.9, "out"), ("2026-09-05", 6500.0, "in")])
        # reimportar gera os mesmos ids (sem duplicar)
        self.assertEqual([t["id"] for t in txs], [t["id"] for t in importer.parse_file("extrato.ofx", OFX)])

    def test_nubank_account_csv(self):
        raw = ("Data,Valor,Identificador,Descrição\n"
               "01/09/2026,-32.50,abc,Compra no débito - Padaria\n"
               "05/09/2026,5000.00,def,Transferência recebida\n").encode()
        txs = importer.parse_file("NU_2026.csv", raw)
        self.assertEqual([(t["amount"], t["direction"]) for t in txs], [(32.5, "out"), (5000.0, "in")])

    def test_nubank_card_csv_positive_is_expense(self):
        raw = b"date,title,amount\n2026-09-02,Uber *Trip,23.40\n2026-09-10,Pagamento recebido,-900.00\n"
        txs = importer.parse_file("Nubank_2026-09.csv", raw)
        self.assertEqual([(t["amount"], t["direction"]) for t in txs], [(23.4, "out"), (900.0, "in")])

    def test_semicolon_brazilian_numbers_and_preamble(self):
        raw = ("Extrato conta corrente\nAgência 1234\nData;Lançamento;Valor (R$)\n"
               "03/09/2026;NETFLIX;-1.059,90\n03/09/2026;NETFLIX;-1.059,90\n").encode("cp1252")
        txs = importer.parse_file("extrato.csv", raw, card=False)
        self.assertEqual(len(txs), 2)  # duas compras iguais no mesmo dia continuam sendo duas
        self.assertNotEqual(txs[0]["id"], txs[1]["id"])
        self.assertEqual(txs[0]["amount"], 1059.9)

    def test_reconcile_card_payment_from_checking(self):
        import tempfile
        from pathlib import Path
        from financas.store import Store
        with tempfile.TemporaryDirectory() as d:
            st = Store(Path(d) / "t.db")
            base = {"account_id": "a", "account_name": "x", "pluggy_category": None, "source": "pluggy",
                    "bill_month": None}
            st.upsert_transactions([
                {**base, "id": "1", "date": "2026-09-10", "description": "Pagamento de Pix QR Code BANCO DO BRASIL",
                 "amount": 850.0, "direction": "out", "category": "Pix e transferências enviadas", "is_card": 0},
                {**base, "id": "2", "date": "2026-09-11", "description": "PGTO. QR CODE PIX",
                 "amount": 850.0, "direction": "in", "category": "Pagamento de fatura", "is_card": 1},
                {**base, "id": "3", "date": "2026-09-10", "description": "Pagamento de Pix QR Code UBERTRANS",
                 "amount": 23.0, "direction": "out", "category": "Transporte", "is_card": 0},
            ])
            self.assertEqual(st.reconcile_card_payments(), 1)
            cats = {t["id"]: t["category"] for t in st.all_transactions()}
            self.assertEqual(cats["1"], "Pagamento de fatura")
            self.assertEqual(cats["3"], "Transporte")

            # Pagamento da fatura ainda sem o crédito correspondente no cartão: casa pelo total da fatura.
            st.save_bills([{"id": "b1", "account_id": "c", "due_date": "2026-09-02", "total": 1117.0}])
            st.upsert_transactions([
                {**base, "id": "4", "date": "2026-09-02", "description": "Pagamento de Pix QR Code BANCO DO BRASIL",
                 "amount": 1117.0, "direction": "out", "category": "Pix e transferências enviadas", "is_card": 0},
            ])
            st.reconcile_card_payments()
            self.assertEqual({t["id"]: t["category"] for t in st.all_transactions()}["4"], "Pagamento de fatura")
            st._conn.close()

    def test_rejects_unknown(self):
        with self.assertRaises(ValueError):
            importer.parse_file("x.pdf", b"%PDF")


class AlertsTest(unittest.TestCase):
    def setUp(self):
        from financas import alerts
        self.alerts = alerts
        self.cfg = alerts.config({})
        self.today = date(2026, 9, 28)

    def test_big_expense_and_fee_only_when_recent(self):
        txs = [
            tx("2026-09-27", "LOJA GRANDE", 450),
            tx("2026-09-27", "TARIFA PACOTE", 39.9),
            tx("2026-09-27", "PADARIA", 12),          # abaixo do mínimo
            tx("2026-09-01", "LOJA ANTIGA", 900),      # antigo: não alerta
        ]
        keys = [k for k, _ in self.alerts.pending_alerts(txs, {}, self.cfg, self.today)]
        self.assertEqual(sorted(k.split(":")[0] for k in keys), ["gasto", "tarifa"])

    def test_budget_levels(self):
        txs = [tx("2026-09-10", "IFD*IFOOD", 90), tx("2026-09-11", "RESTAURANTE X", 300)]
        keys = {k for k, _ in self.alerts.pending_alerts(txs, {"Delivery": 100, "Restaurantes": 200},
                                                            {**self.cfg, "alerta_valor_minimo": "0"}, self.today)}
        self.assertIn("orc85:Delivery:2026-09", keys)
        self.assertIn("orc100:Restaurantes:2026-09", keys)

    def test_daily_summary_text(self):
        txs = [tx("2026-09-05", "SALARIO", 3000, "in"), tx("2026-09-27", "IFD*IFOOD", 50)]
        text = self.alerts.daily_summary(txs, {}, self.today)
        self.assertIn("Resumo 28/09", text)
        self.assertIn("R$ 50,00", text)


class AuthTest(unittest.TestCase):
    def test_pin_and_session(self):
        import tempfile
        from pathlib import Path
        from financas.auth import Auth
        from financas.store import Store
        with tempfile.TemporaryDirectory() as d:
            st = Store(Path(d) / "t.db")
            a = Auth(Path(d) / "secret.key", st)
            self.assertFalse(a.pin_set)
            with self.assertRaises(ValueError):
                a.set_pin("123")
            a.set_pin("482913")
            self.assertTrue(a.check_pin("482913", "x"))
            self.assertFalse(a.check_pin("000000", "x"))
            token = a.new_session()
            self.assertTrue(a.valid_session(token))
            self.assertFalse(a.valid_session(token[:-1] + ("0" if token[-1] != "0" else "1")))
            for _ in range(5):
                a.check_pin("111111", "atacante")
            with self.assertRaises(PermissionError):
                a.check_pin("482913", "atacante")
            st._conn.close()

    def test_phone_normalization(self):
        from financas.whatsapp import normalize_phone
        self.assertEqual(normalize_phone("(34) 99999-1234"), "+5534999991234")
        self.assertEqual(normalize_phone("+55 34 99999-1234"), "+5534999991234")


class NuvemTest(unittest.TestCase):
    def test_encrypt_roundtrip_and_wrong_password(self):
        from financas import nuvem
        env = nuvem.encrypt(b'{"ok": 1}', "minha-Senha-123")
        self.assertEqual(nuvem.decrypt(env, "minha-Senha-123"), b'{"ok": 1}')
        self.assertNotIn(b"ok", __import__("base64").b64decode(__import__("json").loads(env)["ct"]))
        with self.assertRaises(nuvem.NuvemError):
            nuvem.decrypt(env, "outra-Senha-456")

    def test_password_rules(self):
        from financas import nuvem
        for bad in ("curta1", "123456789012345", "somenteletrasaqui"):
            with self.assertRaises(nuvem.NuvemError):
                nuvem.check_password(bad)
        nuvem.check_password("gastos-2026-seguro")

    def test_ajustes_roundtrip_between_pc_and_cloud(self):
        import tempfile
        from pathlib import Path
        from financas import nuvem
        from financas.store import Store
        with tempfile.TemporaryDirectory() as d:
            pc, cloud = Store(Path(d) / "pc.db"), Store(Path(d) / "cloud.db")
            pc.add_item("item-1")
            pc.set_rule("UBERTRANS", "Transporte")
            pc.set_budget("Delivery", 300)
            pc.set_settings({"alerta_valor_minimo": "150", "pin_hash": "segredo-local"})
            base = {"account_id": "a", "account_name": "x", "pluggy_category": None, "is_card": 0, "bill_month": None}
            pc.upsert_transactions([
                {**base, "id": "t1", "date": "2026-09-01", "description": "LOJA", "amount": 10.0,
                 "direction": "out", "category": "Outros", "source": "pluggy"},
                {**base, "id": "t2", "date": "2026-09-02", "description": "EXTRATO OFX", "amount": 20.0,
                 "direction": "out", "category": "Compras", "source": "arquivo"},
            ])
            pc.execute("UPDATE transactions SET category = 'Lazer', manual_category = 1 WHERE id = 't1'")
            aj = nuvem.export_ajustes(pc)
            self.assertNotIn("pin_hash", aj["configuracoes"])  # PIN local nunca vai para a nuvem

            nuvem.apply_ajustes(cloud, aj)
            cloud.upsert_transactions([{**base, "id": "t1", "date": "2026-09-01", "description": "LOJA",
                                        "amount": 10.0, "direction": "out", "category": "Outros", "source": "pluggy"}])
            nuvem.apply_manual_categories(cloud, aj)
            cats = {t["id"]: t["category"] for t in cloud.all_transactions()}
            self.assertEqual(cats, {"t1": "Lazer", "t2": "Compras"})
            self.assertEqual(cloud.budgets(), {"Delivery": 300.0})
            self.assertEqual(cloud.rules(), {"UBERTRANS": "Transporte"})
            self.assertEqual([i["id"] for i in cloud.items()], ["item-1"])

            site = nuvem.build_site_data(cloud)
            self.assertEqual(site["meses"]["fatura"], ["2026-09"])
            self.assertEqual(site["resumos"]["compra"]["2026-09"]["resumo"]["expenses"], 30.0)
            pc._conn.close(); cloud._conn.close()

    def test_job_log_masks_long_numbers(self):
        import io
        from nuvem_job import MaskedOutput
        buf = io.StringIO()
        MaskedOutput(buf).write("fone +55 34 99999-1234, conta 00002269-1, data 2026-09-28")
        self.assertEqual(buf.getvalue(), "fone [oculto], conta [oculto], data 2026-09-28")


if __name__ == "__main__":
    unittest.main()

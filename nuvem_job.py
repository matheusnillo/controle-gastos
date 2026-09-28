"""Robô da nuvem (roda no GitHub Actions a cada 4 h, sem o seu computador).

1. Decifra o estado anterior e os ajustes enviados pelo PC.
2. Baixa as transações novas da Pluggy/Meu Pluggy.
3. Manda os alertas e o resumo diário no WhatsApp.
4. Gera o painel criptografado do celular (site/) e o novo estado (estado/).

Os logs do GitHub Actions de um repositório público são públicos: nada de dados pessoais no print.
"""
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
ESTADO = Path(os.environ.get("ESTADO_DIR", ROOT / "estado"))
SITE = Path(os.environ.get("SITE_DIR", ROOT / "site"))
AJUSTES = ROOT / "nuvem" / "ajustes.enc"


class MaskedOutput:
    """Mascara sequências longas de dígitos (telefone, conta, cartão) em tudo que for impresso."""

    def __init__(self, stream):
        self.stream = stream

    def write(self, text):
        # 9+ dígitos (telefone, conta, cartão) viram [oculto]; datas (8 dígitos) continuam legíveis.
        mask = lambda m: "[oculto]" if sum(c.isdigit() for c in m.group()) >= 9 else m.group()
        return self.stream.write(re.sub(r"\+?\d[\d .-]{6,}\d", mask, text))

    def flush(self):
        self.stream.flush()


def main():
    sys.stdout, sys.stderr = MaskedOutput(sys.stdout), MaskedOutput(sys.stderr)
    password = os.environ.get("NUVEM_SENHA") or ""
    work = Path(tempfile.mkdtemp(prefix="gastos-"))
    os.environ["DATA_DIR"] = str(work)
    os.environ["NUVEM_JOB"] = "1"

    from financas import nuvem
    nuvem.check_password(password)

    state_file = ESTADO / "financas.db.enc"
    if state_file.exists():
        (work / "financas.db").write_bytes(nuvem.decrypt(state_file.read_bytes(), password))
        print("Estado anterior restaurado.")
    else:
        print("Primeira execução: estado novo.")

    import app  # usa DATA_DIR acima
    from financas import alerts

    ajustes = {}
    if AJUSTES.exists():
        ajustes = __import__("json").loads(nuvem.decrypt(AJUSTES.read_bytes(), password))
        nuvem.apply_ajustes(app.store, ajustes)
        print(f"Ajustes do computador aplicados (enviados em {ajustes.get('geradoEm', '?')}).")
    else:
        print("Nenhum ajuste enviado pelo computador ainda (nuvem/ajustes.enc).")

    if not app.pluggy.configured:
        print("AVISO: segredos PLUGGY_CLIENT_ID/PLUGGY_CLIENT_SECRET não configurados no GitHub.")
    elif app.store.items():
        results = app.sync_everything()
        erros = [r for r in results if r.get("erro")]
        print(f"Sincronização: {len(results) - len(erros)} conexão(ões) ok, {len(erros)} com erro.")
    nuvem.apply_manual_categories(app.store, ajustes)
    app.store.reconcile_card_payments()

    enviados = app.run_alerts()
    print(f"Alertas enviados: {enviados}")
    cfg = alerts.config(app.store.settings())
    if datetime.now().hour >= int(cfg.get("resumo_hora") or 20):
        try:
            print("Resumo diário enviado." if app.send_daily_summary() else "Resumo diário: nada a enviar agora.")
        except Exception as e:
            print(f"Resumo diário falhou: {type(e).__name__}")

    # Sal fixo entre execuções: o celular pode guardar a chave e não pedir a senha toda vez.
    salt_hex = app.store.settings().get("nuvem_salt")
    if not salt_hex:
        salt_hex = os.urandom(16).hex()
        app.store.set_settings({"nuvem_salt": salt_hex})
    salt = bytes.fromhex(salt_hex)
    key = nuvem.derive_key(password, salt)

    # ---- site do celular
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(ROOT / "static", SITE, ignore=shutil.ignore_patterns("login.html"))
    index = (SITE / "index.html").read_text(encoding="utf-8")
    index = index.replace('<script src="app.js"></script>',
                          '<script src="nuvem.js"></script>\n  <script src="app.js"></script>')
    (SITE / "index.html").write_text(index, encoding="utf-8")
    data = nuvem.build_site_data(app.store)
    (SITE / "dados.enc").write_bytes(
        nuvem.encrypt(__import__("json").dumps(data, ensure_ascii=False).encode(), password, salt, key))
    (SITE / ".nojekyll").write_text("")
    print(f"Painel gerado: {len(data['transacoes'])} transações, {len(data['meses']['fatura'])} meses.")

    # ---- estado para a próxima execução
    app.store._conn.execute("PRAGMA wal_checkpoint(FULL)")
    app.store._conn.commit()
    ESTADO.mkdir(parents=True, exist_ok=True)
    state_file.write_bytes(nuvem.encrypt((work / "financas.db").read_bytes(), password, salt, key))
    print("Estado salvo.")


if __name__ == "__main__":
    main()

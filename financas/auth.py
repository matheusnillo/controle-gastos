"""PIN e sessão para acessar o painel pelo celular.

No próprio computador (http://127.0.0.1) o acesso é livre. Qualquer acesso que venha
por outro endereço (ex.: pelo Tailscale no celular) precisa do PIN.
"""
import hashlib
import hmac
import secrets
import threading
import time
from pathlib import Path

SESSION_DAYS = 30
MAX_FAILS, LOCK_SECONDS = 5, 300


class Auth:
    def __init__(self, secret_path: Path, store):
        self.store = store
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        if not secret_path.exists():
            secret_path.write_bytes(secrets.token_bytes(32))
        self._secret = secret_path.read_bytes()
        self._fails = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- PIN
    @property
    def pin_set(self):
        return bool(self.store.settings().get("pin_hash"))

    def set_pin(self, pin: str):
        if not pin.isdigit() or not 6 <= len(pin) <= 12:
            raise ValueError("o PIN deve ter de 6 a 12 números")
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()
        self.store.set_settings({"pin_hash": f"{salt}${digest}"})
        # Trocar o PIN derruba as sessões antigas.
        self.store.set_settings({"session_epoch": str(int(time.time()))})

    def check_pin(self, pin: str, client: str):
        with self._lock:
            fails, until = self._fails.get(client, (0, 0))
            if until > time.time():
                raise PermissionError(f"Muitas tentativas. Tente de novo em {int(until - time.time())} s.")
        stored = self.store.settings().get("pin_hash") or ""
        ok = False
        if "$" in stored:
            salt, digest = stored.split("$", 1)
            test = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()
            ok = hmac.compare_digest(test, digest)
        with self._lock:
            if ok:
                self._fails.pop(client, None)
            else:
                fails += 1
                self._fails[client] = (fails, time.time() + LOCK_SECONDS if fails >= MAX_FAILS else 0)
        return ok

    # ------------------------------------------------------------- sessão
    def _sign(self, payload: str):
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def new_session(self):
        payload = f"{int(time.time()) + SESSION_DAYS * 86400}.{secrets.token_hex(8)}"
        return f"{payload}.{self._sign(payload)}"

    def valid_session(self, token: str):
        try:
            expiry, nonce, sig = (token or "").split(".")
        except ValueError:
            return False
        payload = f"{expiry}.{nonce}"
        if not hmac.compare_digest(sig, self._sign(payload)):
            return False
        issued = int(expiry) - SESSION_DAYS * 86400
        epoch = int(self.store.settings().get("session_epoch") or 0)
        return int(expiry) > time.time() and issued >= epoch

"""Envio de mensagens para o SEU WhatsApp via CallMeBot (gratuito, uso pessoal).

Ativação (uma vez): salve o contato +34 644 95 42 75 e mande para ele no WhatsApp
"I allow callmebot to send me messages". Em alguns minutos chega a sua apikey.
Doc: https://www.callmebot.com/blog/free-api-whatsapp-messages/

Observação de privacidade: o texto das mensagens passa pelos servidores do CallMeBot.
"""
import re
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.callmebot.com/whatsapp.php"
MAX_CHARS = 1500  # a mensagem vai na URL; mantemos curta


class WhatsAppError(Exception):
    pass


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) in (10, 11):  # número brasileiro sem DDI
        digits = "55" + digits
    return "+" + digits if digits else ""


def send(phone: str, apikey: str, text: str) -> None:
    phone = normalize_phone(phone)
    if not phone or not apikey:
        raise WhatsAppError("Configure o seu número e a apikey do CallMeBot na aba Alertas.")
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 20].rstrip() + "\n…(mensagem cortada)"
    url = API + "?" + urllib.parse.urlencode({"phone": phone, "text": text, "apikey": apikey})
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        raise WhatsAppError(f"CallMeBot respondeu HTTP {e.code}. Confira número e apikey.") from None
    except urllib.error.URLError as e:
        raise WhatsAppError(f"Sem conexão com o CallMeBot: {e.reason}") from None
    low = body.lower()
    # O CallMeBot responde 200 com texto/HTML; erros vêm descritos no corpo.
    if "apikey is invalid" in low or "invalid apikey" in low or ("error" in low and "queued" not in low):
        clean = re.sub(r"<[^>]+>", " ", body)
        raise WhatsAppError("CallMeBot recusou a mensagem: " + re.sub(r"\s+", " ", clean).strip()[:200])

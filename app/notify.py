"""Notification channel adapters (Telegram / WhatsApp / Email).

All channels run in DEMO mode unless outbound networking actually works.
Nothing here ever claims a message was delivered to an external service
without a real API response."""
import urllib.request, urllib.parse, json

def send_telegram(token, chat_id, text, timeout=4):
    """Try a REAL Telegram Bot API call. Returns (ok, mode, detail)."""
    if not token or not chat_id:
        return False, "DEMO", "Bot token / chat ID belum diisi — pesan hanya dicatat sebagai draft demo."
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
        if body.get("ok"):
            return True, "REAL", "Terkirim via Telegram Bot API."
        return False, "REAL", body.get("description", "Ditolak API")
    except Exception as e:
        return False, "DEMO", f"Tidak dapat menghubungi api.telegram.org ({type(e).__name__}) — pesan TIDAK terkirim keluar, dicatat sebagai demo."

def send_whatsapp(number, text):
    return False, "DEMO", "Integrasi WhatsApp Business API tidak tersedia di lingkungan ini — pesan dicatat sebagai demo, TIDAK terkirim."

def send_email(smtp_host, to, subject, body):
    if not smtp_host:
        return False, "DEMO", "SMTP host belum dikonfigurasi — email dicatat sebagai demo, TIDAK terkirim."
    return False, "DEMO", "Kirim SMTP belum diimplementasi pada build ini — dicatat sebagai demo."

CHANNELS = {"telegram": send_telegram, "whatsapp": send_whatsapp, "email": send_email}

def dispatch(channel, settings, to, subject, body):
    """Returns (ok, mode, detail). Logs are handled by caller."""
    if channel == "telegram":
        return send_telegram(settings.get("tg_token",""), settings.get("tg_chat","") or to, body)
    if channel == "whatsapp":
        return send_whatsapp(to, body)
    if channel == "email":
        return send_email(settings.get("smtp_host",""), to, subject, body)
    return False, "DEMO", "Kanal tidak dikenal"

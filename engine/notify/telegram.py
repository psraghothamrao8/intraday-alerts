"""
Telegram notification sender.
Implements spec 04 §6.
"""
import logging
import requests
from engine.config import get_settings

logger = logging.getLogger(__name__)


def send_telegram(title: str, body: str) -> bool:
    """
    Send notification message to Telegram bot.
    POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage
    """
    settings = get_settings()
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        logger.debug("Telegram token or chat_id not set; skipping Telegram notification.")
        return False

    text = f"{title}\n{body}" if body else title
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        logger.warning(f"Telegram API error {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False

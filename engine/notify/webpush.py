"""
Web Push sender via pywebpush.
Implements spec 04 §5.4.
"""
import json
import logging
from typing import Any, Dict
from pywebpush import webpush, WebPushException
from engine.config import get_settings

logger = logging.getLogger(__name__)


def send_webpush(sub: Dict[str, Any], payload: Dict[str, Any], ttl: int = 180) -> int:
    """
    Send Web Push notification to a single subscribed device.
    Returns HTTP status code (201 on success, 410 on expired, etc.).
    """
    settings = get_settings()
    vapid_key_path = settings.VAPID_PRIVATE_KEY_PATH
    vapid_sub = settings.VAPID_SUBJECT

    try:
        # build a NEW dict every call: pywebpush mutates it
        resp = webpush(
            subscription_info=sub,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid_key_path,
            vapid_claims={"sub": vapid_sub},
            ttl=ttl,
            headers={"Urgency": "high"},
            timeout=10,
        )
        return resp.status_code
    except WebPushException as e:
        status = e.response.status_code if e.response is not None else 0
        logger.warning(f"WebPushException sending push: status={status}, err={e}")
        return status
    except Exception as e:
        logger.error(f"Unexpected error sending web push: {e}")
        return 0

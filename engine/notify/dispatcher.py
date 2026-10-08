"""
Notification dispatcher with exactly-once delivery semantics.
Implements spec 04 §4.
"""
import json
import logging
import sqlite3
import time
from typing import Any, Dict, Optional
from engine.config import get_settings
from engine.core.clock import get_clock
from engine.core.state import (
    get_connection,
    get_active_devices,
    mark_device_inactive,
    insert_notification_if_new,
    update_notification_status,
)
from engine.notify.formatter import format_entry, format_exit, build_push_payload
from engine.notify.webpush import send_webpush
from engine.notify.telegram import send_telegram

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Dispatches notifications exactly once across active Web Push devices and Telegram."""

    def __init__(self, conn: Optional[sqlite3.Connection] = None, notify_file: Optional[str] = None):
        self.conn = conn
        self.notify_file = notify_file

    def dispatch_trade_entry(self, trade: Dict[str, Any]) -> bool:
        """
        Send ENTRY notification for a trade.
        Returns True if sent, False if already sent or skipped.
        """
        settings = get_settings()
        trade_id = trade["id"]
        notif_id = f"{trade_id}:ENTRY"

        title, body = format_entry(trade)
        payload = build_push_payload("ENTRY", trade_id, title, body)
        ttl = settings.notify.webpush.ttl_entry_sec

        return self._dispatch(notif_id, trade_id, "ENTRY", title, body, payload, ttl)

    def dispatch_trade_exit(self, trade: Dict[str, Any]) -> bool:
        """
        Send EXIT notification for a trade.
        Returns True if sent, False if already sent or skipped.
        """
        settings = get_settings()
        trade_id = trade["id"]
        notif_id = f"{trade_id}:EXIT"

        title, body = format_exit(trade)
        payload = build_push_payload("EXIT", trade_id, title, body)
        ttl = settings.notify.webpush.ttl_exit_sec

        return self._dispatch(notif_id, trade_id, "EXIT", title, body, payload, ttl)

    def dispatch_alert(self, key: str, message: str, body: str = "") -> bool:
        """
        Send ALERT notification.
        ALERTs with the same key are sent at most once per day (id = f"alert:{key}:{date}").
        """
        settings = get_settings()
        today_str = get_clock().today().isoformat()
        notif_id = f"alert:{key}:{today_str}"

        title = message
        payload = build_push_payload("ALERT", notif_id, title, body, url="./")
        ttl = settings.notify.webpush.ttl_alert_sec

        return self._dispatch(notif_id, None, "ALERT", title, body, payload, ttl)

    def _dispatch(
        self,
        notif_id: str,
        trade_id: Optional[str],
        kind: str,
        title: str,
        body: str,
        payload: Dict[str, Any],
        ttl: int
    ) -> bool:
        conn = self.conn or get_connection()
        payload_json = json.dumps(payload, ensure_ascii=False)

        # 1. Exactly-once check via INSERT OR IGNORE
        inserted = insert_notification_if_new(notif_id, trade_id, kind, payload_json, conn)
        if not inserted:
            logger.info(f"Notification {notif_id} was already handled; skipping duplicate delivery.")
            return False

        # If file output is configured, write to file and skip network delivery
        if self.notify_file:
            with open(self.notify_file, "a", encoding="utf-8") as f_out:
                f_out.write(json.dumps({
                    "notif_id": notif_id,
                    "trade_id": trade_id,
                    "kind": kind,
                    "title": title,
                    "body": body,
                    "payload": payload,
                    "timestamp": get_clock().now().isoformat(),
                }, ensure_ascii=False) + "\n")
            update_notification_status(notif_id, webpush_status="file_logged", telegram_status="file_logged", conn=conn)
            return True

        settings = get_settings()
        devices = get_active_devices(conn)
        webpush_success_count = 0
        webpush_failure_count = 0

        # 2. Web Push delivery to all active devices
        if settings.notify.webpush.enabled:
            for dev in devices:
                sub = dev["subscription"]
                endpoint = sub.get("endpoint", "")
                delivered = False

                for attempt in range(3):
                    status = send_webpush(sub, payload, ttl=ttl)
                    if 200 <= status < 300:
                        delivered = True
                        break
                    elif status in (404, 410):
                        # Subscription expired or unregistered
                        logger.warning(f"Device {dev.get('name')} endpoint expired (HTTP {status}). Marking inactive.")
                        mark_device_inactive(endpoint, conn)
                        # Notify user via Telegram about expired phone subscription
                        self._notify_subscription_expired()
                        break
                    else:
                        time.sleep(0.5)

                if delivered:
                    webpush_success_count += 1
                else:
                    webpush_failure_count += 1

        webpush_status = f"DELIVERED({webpush_success_count})" if webpush_success_count > 0 else (
            "FAILED" if devices else "NO_DEVICES"
        )

        # 3. Telegram delivery (if enabled)
        telegram_status = "SKIPPED"
        if settings.notify.telegram.enabled:
            tg_success = send_telegram(title, body)
            telegram_status = "DELIVERED" if tg_success else "FAILED"

        # 4. Update status in database
        update_notification_status(notif_id, webpush_status=webpush_status, telegram_status=telegram_status, conn=conn)
        return True

    def _notify_subscription_expired(self) -> None:
        """Send Telegram alert when a web push subscription expires."""
        send_telegram(
            title="⚠️ Phone notifications expired",
            body="Open the dashboard and re-enable notifications."
        )


_DISPATCHER_INSTANCE: Optional[NotificationDispatcher] = None


def get_dispatcher() -> NotificationDispatcher:
    global _DISPATCHER_INSTANCE
    if _DISPATCHER_INSTANCE is None:
        _DISPATCHER_INSTANCE = NotificationDispatcher()
    return _DISPATCHER_INSTANCE

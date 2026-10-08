#!/usr/bin/env python3
"""
GitHub Actions Watchdog Script.
Runs every 15 min during market hours.
Checks heartbeat and alerts via Web Push / Telegram if engine is offline.
Implements spec 04 §9.
"""
from datetime import datetime, time, timezone
import json
import os
import sys
import tempfile
import zoneinfo
import requests

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def main() -> None:
    repo = os.environ.get("GITHUB_REPOSITORY", "psraghothamrao8/intraday-alerts")
    raw_url = f"https://raw.githubusercontent.com/{repo}/data/state.enc.json"

    try:
        res = requests.get(raw_url, timeout=15)
        if res.status_code != 200:
            print(f"Could not fetch envelope (HTTP {res.status_code}); exiting.")
            return
        envelope = res.json()
    except Exception as e:
        print(f"Error fetching state envelope: {e}")
        return

    now_ist = datetime.now(IST)
    today_str = now_ist.date().isoformat()

    engine_status = envelope.get("engine_status", "running")
    next_trading_day = envelope.get("next_trading_day")

    # 1. If IST today != next_trading_day and engine_status == "stopped_eod", it's a holiday or weekend: exit.
    if engine_status == "stopped_eod" and next_trading_day != today_str:
        print("Market closed / holiday / weekend; exiting.")
        return

    # 2. If the time is outside 09:05–15:35 IST: exit.
    market_open = time(9, 5)
    market_close = time(15, 35)
    cur_time = now_ist.time()
    if cur_time < market_open or cur_time > market_close:
        print(f"Current time {cur_time} is outside 09:05–15:35 IST; exiting.")
        return

    # 3. If heartbeat_at is 12–40 minutes old: send alert
    heartbeat_str = envelope.get("heartbeat_at") or envelope.get("updated_at")
    if not heartbeat_str:
        print("No heartbeat_at found in envelope; exiting.")
        return

    try:
        heartbeat_dt = datetime.fromisoformat(heartbeat_str)
        if heartbeat_dt.tzinfo is None:
            heartbeat_dt = heartbeat_dt.replace(tzinfo=IST)
    except Exception as e:
        print(f"Could not parse heartbeat timestamp {heartbeat_str}: {e}")
        return

    diff_seconds = (now_ist - heartbeat_dt).total_seconds()
    diff_minutes = diff_seconds / 60.0

    print(f"Heartbeat timestamp: {heartbeat_str}, diff: {diff_minutes:.1f} minutes")

    if 12.0 <= diff_minutes <= 40.0:
        time_display = heartbeat_dt.strftime("%H:%M")
        alert_title = f"⚠️ Engine offline since {time_display}"
        alert_body = f"No heartbeat received for {int(diff_minutes)} minutes."
        print(f"Triggering watchdog alert: {alert_title}")
        send_watchdog_alerts(alert_title, alert_body)
    else:
        print("Heartbeat is within healthy threshold or outside alert window.")


def send_watchdog_alerts(title: str, body: str) -> None:
    # 1. Telegram
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        try:
            tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            requests.post(tg_url, json={"chat_id": tg_chat, "text": f"{title}\n{body}"}, timeout=10)
            print("Telegram alert sent.")
        except Exception as e:
            print(f"Failed to send Telegram alert: {e}")

    # 2. Web Push
    vapid_key_pem = os.environ.get("VAPID_PRIVATE_KEY")
    vapid_sub = os.environ.get("VAPID_SUBJECT", "mailto:watchdog@example.com")
    subs_json = os.environ.get("PUSH_SUBSCRIPTIONS")

    if vapid_key_pem and subs_json:
        try:
            from pywebpush import webpush
            subs = json.loads(subs_json)
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem") as f:
                f.write(vapid_key_pem)
                key_path = f.name

            payload = {
                "v": 1,
                "kind": "ALERT",
                "id": f"alert:watchdog:{datetime.now(IST).date().isoformat()}",
                "title": title,
                "body": body,
                "tag": "alert:watchdog",
                "url": "./",
                "sticky": True,
                "ts": datetime.now(IST).isoformat(),
            }

            for sub in subs:
                try:
                    webpush(
                        subscription_info=sub,
                        data=json.dumps(payload),
                        vapid_private_key=key_path,
                        vapid_claims={"sub": vapid_sub},
                        ttl=3600,
                        headers={"Urgency": "high"},
                        timeout=10,
                    )
                    print(f"Web push sent to device {sub.get('endpoint', '')[:30]}...")
                except Exception as ex:
                    print(f"Failed web push to device: {ex}")

            try:
                os.remove(key_path)
            except OSError:
                pass

        except Exception as e:
            print(f"Failed to process web push in watchdog: {e}")


if __name__ == "__main__":
    main()

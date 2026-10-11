"""
Telegram Bot Linker & Verifier.
Connects @daytrading_ragi_googly_101_bot to the trading alert engine.
Fetches the user's chat_id, stores it in .env, and sends a test message.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import requests
from engine.config import get_settings
from engine.notify.telegram import send_telegram

def link_telegram(timeout_sec=30):
    settings = get_settings()
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set in .env")
        return False

    url_me = f"https://api.telegram.org/bot{token}/getMe"
    try:
        r_me = requests.get(url_me, timeout=10).json()
        if not r_me.get("ok"):
            print(f"ERROR: Invalid Telegram Bot Token: {r_me}")
            return False
        bot_username = r_me.get("result", {}).get("username")
        print(f"Bot verified: @{bot_username}")
    except Exception as e:
        print(f"ERROR: Could not connect to Telegram API: {e}")
        return False

    url_updates = f"https://api.telegram.org/bot{token}/getUpdates"
    print(f"\nChecking for messages from you on @{bot_username}...")
    
    start_t = time.time()
    chat_id = None
    first_name = None

    while time.time() - start_t < timeout_sec:
        try:
            r = requests.get(url_updates, timeout=10).json()
            updates = r.get("result", [])
            if updates:
                last_msg = updates[-1].get("message", {})
                chat_id = last_msg.get("chat", {}).get("id")
                first_name = last_msg.get("from", {}).get("first_name", "Trader")
                if chat_id:
                    break
        except Exception as e:
            pass
        time.sleep(2)

    if not chat_id:
        print("\n" + "=" * 70)
        print("ACTION REQUIRED:")
        print(f"1. Open Telegram on your phone or PC.")
        print(f"2. Search for @{bot_username} or open: https://t.me/{bot_username}")
        print("3. Tap 'START' (or send any message like 'hi').")
        print("4. Rerun: python scripts/setup_telegram.py")
        print("=" * 70)
        return False

    # Store TELEGRAM_CHAT_ID in .env safely
    env_path = Path(".env")
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    new_lines = []
    found = False
    for l in lines:
        if l.startswith("TELEGRAM_CHAT_ID="):
            new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
            found = True
        else:
            new_lines.append(l)
    if not found:
        new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    print(f"\nFound message from {first_name} (chat_id: {chat_id})!")
    print("Saved TELEGRAM_CHAT_ID to .env")

    # Send verification message
    test_title = "🚀 Daytrading Alpha Bot Connected!"
    test_body = (
        "Hello! Your intraday alert engine is now linked.\n"
        "• Strategies: B5 Concordant S2 ORB + S1 Results + S3 Filing Flash\n"
        "• Hard Stop Loss Cap: 1.25%\n"
        "• Minimum Conviction Strength: 8/10\n"
        "All real-time trade signals will now be sent directly to you here!"
    )
    
    # Reload settings in memory
    from engine.config import load_config
    load_config()
    
    success = send_telegram(test_title, test_body)
    if success:
        print("Verification message sent successfully to your Telegram!")
        return True
    else:
        print("Warning: Could not deliver test message.")
        return False

if __name__ == "__main__":
    link_telegram(timeout_sec=5)

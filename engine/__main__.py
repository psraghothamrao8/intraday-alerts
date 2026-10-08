"""
CLI entry point for the Intraday Alert Bot engine.
Supports: vapid-gen, add-device, notify-test, publish-test, doctor, run, replay, universe, collect-eod, filings.
"""
import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Optional
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid

from engine.config import get_settings
from engine.core.state import init_db, add_device as db_add_device, get_active_devices
from engine.notify.dispatcher import get_dispatcher
from engine.publish.github_data import upload_envelope
from engine.publish.snapshot import build_snapshot


def cli_vapid_gen() -> None:
    """Generate VAPID EC P-256 keys and save private key to secrets/vapid_private.pem."""
    settings = get_settings()
    key_path = Path(settings.VAPID_PRIVATE_KEY_PATH)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    vapid = Vapid()
    vapid.generate_keys()
    vapid.save_key(str(key_path))

    # Export uncompressed point in base64url
    pub_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    b64_pub = base64.urlsafe_b64encode(pub_bytes).decode("ascii").rstrip("=")

    print(f"\n[SUCCESS] VAPID private key saved to: {key_path}")
    print(f"Public Key (base64url):\n{b64_pub}\n")
    print("Put this public key in docs/config.js as vapidPublicKey.")


def cli_add_device(name: str = "Device") -> None:
    """Add a push subscription JSON to secrets/subscriptions.json and state database."""
    print("Paste push subscription JSON (or press Enter if copied to clipboard):")
    sub_json = ""

    # Try clipboard if available
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        clipboard_content = root.clipboard_get().strip()
        root.destroy()
        if clipboard_content.startswith("{") and "endpoint" in clipboard_content:
            sub_json = clipboard_content
            print("Read subscription from clipboard.")
    except Exception:
        pass

    if not sub_json:
        sub_json = input().strip()

    try:
        sub_data = json.loads(sub_json)
        assert "endpoint" in sub_data
        assert "keys" in sub_data
        assert "p256dh" in sub_data["keys"]
        assert "auth" in sub_data["keys"]
    except Exception as e:
        print(f"[ERROR] Invalid subscription JSON: {e}")
        sys.exit(1)

    # Save to secrets/subscriptions.json
    subs_path = Path("secrets/subscriptions.json")
    subs_path.parent.mkdir(parents=True, exist_ok=True)
    subs = []
    if subs_path.exists():
        try:
            subs = json.loads(subs_path.read_text(encoding="utf-8"))
        except Exception:
            subs = []

    # Replace if same endpoint exists, otherwise append
    subs = [s for s in subs if s.get("endpoint") != sub_data["endpoint"]]
    sub_entry = dict(sub_data)
    sub_entry["name"] = name
    subs.append(sub_entry)
    subs_path.write_text(json.dumps(subs, indent=2), encoding="utf-8")

    # Add to SQLite devices table
    init_db()
    db_add_device(name, json.dumps(sub_data))
    print(f"[SUCCESS] Added device '{name}' successfully.")


def cli_notify_test() -> None:
    """Send test notification via Web Push and Telegram."""
    init_db()
    dispatcher = get_dispatcher()

    sample_trade = {
        "id": "TEST-NOTIFY-001",
        "strategy": "S1",
        "symbol": "KPITTECH",
        "side": "LONG",
        "product": "MIS",
        "strength": 8,
        "max_entry": 1452.00,
        "valid_till": "11:45",
        "exit_by": "15:07",
        "thesis": {"tf": "5m", "dir": "below", "level": 1428.50},
        "safety_stop": 1404.00,
        "qty": 41,
        "risk_inr": 1968,
        "why": "Q2 results: Rev +28% · PAT +61% · margin +310bps (consol.)",
        "status": "OPEN",
    }

    print("Sending test ENTRY notification...")
    sent = dispatcher.dispatch_trade_entry(sample_trade)
    print(f"Result: {'Sent successfully' if sent else 'Duplicate or skipped'}")


def cli_publish_test() -> None:
    """Publish a sample state envelope to GitHub data branch."""
    init_db()
    settings = get_settings()
    print(f"Building state snapshot for {settings.publish.owner}/{settings.publish.repo}...")
    envelope, _ = build_snapshot(engine_status="running")
    print("Uploading to GitHub Git Data API...")
    success = upload_envelope(envelope)
    if success:
        print("[SUCCESS] State published successfully to GitHub 'data' branch!")
    else:
        print("[ERROR] State publication failed. Check GITHUB_TOKEN and repo permissions.")


def cli_universe(date_str: Optional[str] = None) -> None:
    from datetime import date
    from engine.data.universe import build_universe
    target_d = date.fromisoformat(date_str) if date_str else None
    print(f"Building universe for {target_d or 'today'}...")
    df = build_universe(target_d)
    print(f"[SUCCESS] Universe built with {len(df)} rows.")


def cli_collect_eod(backfill: int = 0) -> None:
    from engine.data.collect_eod import collect_eod
    print(f"Collecting EOD candles (backfill={backfill})...")
    files = collect_eod(backfill_days=backfill)
    print(f"[SUCCESS] Collected {len(files)} daily Parquet candle files.")


def cli_filings(replay_date_str: Optional[str] = None) -> None:
    from datetime import date
    from engine.data.filings_replay import replay_filings_for_date
    target_d = date.fromisoformat(replay_date_str) if replay_date_str else date.today()
    print(f"Replaying filings for {target_d}...")
    res = replay_filings_for_date(target_d)
    print(f"\n[SUCCESS] Replayed {len(res)} filings for {target_d}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Intraday Alert Bot Engine CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("vapid-gen", help="Generate VAPID keys for Web Push")

    add_dev_parser = subparsers.add_parser("add-device", help="Register a Web Push device subscription")
    add_dev_parser.add_argument("--name", default="Phone", help="Friendly name for the device")

    subparsers.add_parser("notify-test", help="Send test notification to subscribed devices")
    subparsers.add_parser("publish-test", help="Publish test state to GitHub Pages data branch")
    subparsers.add_parser("doctor", help="Check system health, credentials, and API reachability")

    # Placeholders for future tasks
    subparsers.add_parser("run", help="Run the live intraday trading engine")
    replay_parser = subparsers.add_parser("replay", help="Replay past trading sessions")
    replay_parser.add_argument("--date", help="Date to replay (YYYY-MM-DD)")
    replay_parser.add_argument("--notify", default="webpush", help="Notification channel: webpush or file")

    universe_parser = subparsers.add_parser("universe", help="Build universe reference data")
    universe_parser.add_argument("--date", help="Date for universe")

    collect_parser = subparsers.add_parser("collect-eod", help="Collect end-of-day candles and S4 data")
    collect_parser.add_argument("--backfill", type=int, default=0, help="Days to backfill")

    filings_parser = subparsers.add_parser("filings", help="Run filings watcher")
    filings_parser.add_argument("--replay", help="Date to replay filings for")

    args = parser.parse_args()

    if args.command == "vapid-gen":
        cli_vapid_gen()
    elif args.command == "add-device":
        cli_add_device(args.name)
    elif args.command == "notify-test":
        cli_notify_test()
    elif args.command == "publish-test":
        cli_publish_test()
    elif args.command == "universe":
        cli_universe(args.date)
    elif args.command == "collect-eod":
        cli_collect_eod(args.backfill)
    elif args.command == "filings":
        cli_filings(args.replay)
    elif args.command in ("run", "replay", "doctor"):
        print(f"Command '{args.command}' is part of subsequent build tasks.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

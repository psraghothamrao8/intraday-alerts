# 04: Notifications and the GitHub Pages dashboard

## 1. Channels

| Channel | Role | Needs |
|---|---|---|
| **Web Push** via the GitHub Pages site | Primary: every trade notification | One-time "Enable notifications" on each device, then paste its subscription into the engine |
| **Telegram bot** | Optional backup for every notification, and the fallback when a web-push subscription expires | A bot token and chat id in `.env` |
| **Dashboard** (the same Pages site) | See today's trades, open positions, per-strategy scoreboard, S4 research, engine health | The passphrase, typed once per device |

How Web Push works without a server: the Pages site registers a **service worker** and asks the browser for a push subscription (an endpoint URL plus keys). You paste that subscription into the engine once. The engine then sends encrypted messages to the browser vendor's push service (Google for Chrome/Android, Apple for iOS/Safari, Mozilla for Firefox), which wakes your phone. The only sender is the engine on your PC.

## 2. What gets notified

Exactly these, nothing else:

| Kind | When | Count |
|---|---|---|
| `ENTRY` | A signal with `strength ≥ notify.min_strength` passed every filter and risk check | **One per trade** |
| `EXIT` | The first exit condition fires (03 §7). **Always** sent for every ENTRY that was sent | **One per trade** |
| `ALERT` | Engine or feed problem, daily loss limit hit, subscription expired, broker login needed, or the watchdog finds the engine offline | Rare |

No daily summaries by default (`notify.daily_summary: false`); the dashboard shows them.

## 3. Exact notification texts

Formatter: `notify/formatter.py`. Prices use the ₹ symbol with Indian digit grouping (₹1,23,456.50) and 24-hour IST time. Leave a line out entirely when its value is null.

**ENTRY, long, intraday (MIS)**
```
Title: 🟢 BUY KPITTECH · 8/10
Buy ≤ ₹1,452.00 now · valid till 11:45
Sell: by 15:07
Stop: only if a 5-min candle closes below ₹1,428.50
Safety SL order ₹1,404.00 · Qty 41 (risk ₹1,968)
Q2 results: Rev +28% · PAT +61% · margin +310bps (consol.)
```

**ENTRY, short, intraday (MIS)**
```
Title: 🔻 SHORT HDFCLIFE · 6/10
Sell (intraday) ≥ ₹702.10 now · valid till 09:41
Buy back: by 15:07
Stop: only if a 5-min candle closes above ₹709.40
Safety SL-buy order ₹713.00 · Qty 180 (risk ₹1,962)
Stock in play: volume 4.2× normal in first 5 min · gap −1.8%
```

**ENTRY, long, delivery (S4)**
```
Title: 🟢 BUY ABCLTD (delivery) · 7/10
Buy as CNC, full cash, ≤ ₹318.40 now · valid 1 min
Sell: 15:25 (you'll get a SELL alert)
Safety SL order ₹315.20 · Qty 300
Square-off dip: −0.7% in the 15:20 minute · day −3.4% · low delivery
```

**EXIT, long**
```
Title: 🔴 SELL KPITTECH now
Idea broken: 5-min close ₹1,426.80 below ₹1,428.50
Paper result: −1.6% (−₹950)
Cancel your safety SL order.
```

**EXIT, short**
```
Title: 🟢 BUY BACK HDFCLIFE now
Time exit (15:07)
Paper result: +1.9% (+₹2,410)
Cancel your safety SL-buy order.
```

**Exit reason strings**: `Time exit ({exit_by})` · `Idea broken: 5-min close ₹{c} below ₹{level}` (or "above" for a short) · `Profit lock: 5-min close below VWAP ₹{v}` · `Safety stop ₹{s} hit: your SL order should have filled. Check it.` · `Target ₹{t} reached`. Prefix `(engine was offline) ` when it applies.

**ALERT examples**: `⚠️ Data feed down since 10:42` · `⚠️ Daily loss limit hit: no new trades today` · `⚠️ Engine offline since 10:05` (from the watchdog) · `⚠️ Phone notifications expired: open the dashboard and re-enable` (sent by Telegram) · `🔑 Broker login needed: open {link}` (manual-login mode only).

**Push payload** (JSON, under 3 KB):
```json
{"v":1,"kind":"ENTRY","id":"S1-20261008-KPITTECH","title":"🟢 BUY KPITTECH · 8/10",
 "body":"Buy ≤ ₹1,452.00 now · valid till 11:45\n...","tag":"S1-20261008-KPITTECH:ENTRY",
 "url":"./#t=S1-20261008-KPITTECH","sticky":true,"ts":"2026-10-08T11:42:07+05:30"}
```
Push options: `TTL` 180 s for ENTRY (a stale entry is useless), 3600 s for EXIT and ALERT. Header `Urgency: high` on all.

## 4. Exactly-once delivery (`notify/dispatcher.py`)

```
table notifications(
  id TEXT PRIMARY KEY,          -- f"{trade_id}:{kind}" or f"alert:{key}:{date}"
  trade_id TEXT, kind TEXT, payload TEXT,
  created_at TEXT, webpush_status TEXT, telegram_status TEXT)
```
1. `INSERT OR IGNORE` the row **before** sending. If no row was inserted, it was already handled: return.
2. Send to every active device, plus Telegram if enabled. Retry failures up to 3 times within 30 s. Never insert again.
3. A `404` or `410` from the push service means that device's subscription is dead. Mark the device inactive and send the "notifications expired" ALERT through Telegram.
4. ALERTs with the same key are sent at most once per day (`alert:{key}:{date}`).

## 5. Web Push implementation

### 5.1 Keys (once)
`python -m engine vapid-gen` creates `secrets/vapid_private.pem` and prints the **public key** (base64url, uncompressed P-256 point). Put the public key in `docs/config.js`. It's public by design.

### 5.2 Device subscription (on the site)
`docs/app.js`:
```js
async function enablePush() {
  const reg = await navigator.serviceWorker.register('sw.js', { scope: './' });
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') return showError('Notifications were blocked for this site.');
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: b64urlToUint8(APP_CONFIG.vapidPublicKey),
  });
  showSubscription(JSON.stringify(sub));   // textarea + Copy button + instructions
}
```
Then on the PC: `python -m engine add-device --name "Pixel 8"`. It reads the JSON from the clipboard (fallback: stdin), checks it has `endpoint`, `keys.p256dh` and `keys.auth`, and appends it to `secrets/subscriptions.json`. Run `python -m engine notify-test` to confirm.

### 5.3 Service worker `docs/sw.js` (complete; keep it this small)
```js
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let p;
  try { p = event.data.json(); } catch { p = { title: 'Alert', body: event.data ? event.data.text() : '' }; }
  event.waitUntil(self.registration.showNotification(p.title, {
    body: p.body, tag: p.tag, renotify: true, requireInteraction: !!p.sticky,
    icon: 'icons/icon-192.png', badge: 'icons/badge-72.png',
    vibrate: [200, 100, 200, 100, 400], data: { url: p.url || './' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.registration.scope).href;
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    for (const c of list) if (c.url.startsWith(self.registration.scope)) { c.navigate(url); return c.focus(); }
    return clients.openWindow(url);
  }));
});
```

### 5.4 Sending (`notify/webpush.py`)
```python
from pywebpush import webpush, WebPushException

def send(sub: dict, payload: dict, ttl: int) -> int:
    try:
        resp = webpush(
            subscription_info=sub,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.VAPID_PRIVATE_KEY_PATH,
            vapid_claims={"sub": settings.VAPID_SUBJECT},   # build a NEW dict every call: pywebpush mutates it
            ttl=ttl,
            headers={"Urgency": "high"},
            timeout=10,
        )
        return resp.status_code
    except WebPushException as e:
        return e.response.status_code if e.response is not None else 0
```

### 5.5 Phone setup (put this in the site's help panel)
- **Android (Chrome):** open the site → Enable notifications → Allow. Then Settings → Apps → Chrome → Battery → **Unrestricted**, so pushes aren't delayed.
- **iPhone (iOS 16.4+):** Safari → Share → **Add to Home Screen** → open it **from the home-screen icon** → Enable notifications. Web push doesn't work in a normal Safari tab on iOS.
- **PC (Chrome/Edge):** allow notifications for the site. They only arrive while the browser is running.

## 6. Telegram backup (`notify/telegram.py`, optional)
`POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage` with `chat_id`, `text = title + "\n" + body`, `disable_web_page_preview=true`. Enable with `notify.telegram.enabled: true`.

## 7. Encrypted state publishing (`publish/`)

### 7.1 What's published
One file, `state.enc.json`, on branch **`data`**, overwritten each time as a **single orphan commit**, so there's no history bloat.

**Envelope (the top-level fields are public, the payload is encrypted):**
```json
{"v":1,
 "updated_at":"2026-10-08T11:32:05+05:30",
 "heartbeat_at":"2026-10-08T11:32:05+05:30",
 "engine_status":"running",            // running | stopped_eod | error
 "next_trading_day":"2026-10-09",
 "salt":"<b64 16 bytes>", "iv":"<b64 12 bytes>", "ct":"<b64 ciphertext+tag>"}
```

### 7.2 Crypto (identical on both sides)
- Key = PBKDF2-HMAC-SHA256(passphrase, salt, **310,000** iterations, 32 bytes). The salt is generated once into `secrets/state_salt.bin` and reused.
- AES-256-GCM, a random 12-byte IV per publish, associated data = `"intraday-state-v1"`.
- Python: `cryptography`'s `AESGCM(key).encrypt(iv, plaintext, aad)` returns ciphertext‖tag, which is exactly what WebCrypto's `decrypt` expects.
- JS (`docs/crypto.js`):
```js
const enc = new TextEncoder();
async function decryptState(env, pass) {
  const salt = b64ToBytes(env.salt), iv = b64ToBytes(env.iv), ct = b64ToBytes(env.ct);
  const base = await crypto.subtle.importKey('raw', enc.encode(pass), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: 310000, hash: 'SHA-256' },
                base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv, additionalData: enc.encode('intraday-state-v1') }, key, ct);
  return JSON.parse(new TextDecoder().decode(pt));
}
```
- Cache the derived key in memory after the first decrypt (derivation takes about 0.3 s).

### 7.3 Upload (GitHub Git Data API, fine-grained token with Contents: read/write)
```
POST  /repos/{owner}/{repo}/git/trees    {"tree":[{"path":"state.enc.json","mode":"100644","type":"blob","content":"<envelope json>"}]}
POST  /repos/{owner}/{repo}/git/commits  {"message":"state 11:32","tree":"<tree sha>","parents":[]}
PATCH /repos/{owner}/{repo}/git/refs/heads/data   {"sha":"<commit sha>","force":true}
      (on 422/404 the first time: POST /repos/{owner}/{repo}/git/refs {"ref":"refs/heads/data","sha":"<commit sha>"})
Headers: Authorization: Bearer $GITHUB_TOKEN · Accept: application/vnd.github+json · X-GitHub-Api-Version: 2022-11-28
```
**Throttle:** publish when state changes, at most once per `publish.min_interval_sec` (60). Publish a heartbeat every `publish.heartbeat_sec` (300) even without changes. Publish `engine_status: "stopped_eod"` at shutdown. Upload failures are logged and retried at the next interval; they never block trading logic.

### 7.4 Decrypted state schema
```json
{
 "generated_at": "2026-10-08T11:32:05+05:30", "mode": "paper", "engine_version": "0.3.0",
 "health": {"feed": "ok", "bse_last_poll": "11:32:01", "nse_last_poll": "11:31:40",
            "llm_errors_today": 0, "last_error": null},
 "today": {"date": "2026-10-08", "paper_pnl_pct": 0.42, "entries": 3,
           "trades": [ <Trade>, ... ]},
 "history": [ <Trade compact>, ... ],            // last 30 trading days, closed trades only
 "scoreboard": [{"strategy": "S1", "name": "Results-Hour Reader", "mode": "paper",
                 "n_30d": 14, "win_rate_30d": 0.57, "avg_net_pct_30d": 0.61, "sum_net_pct_30d": 8.5,
                 "n_all": 31, "avg_net_pct_all": 0.48, "last10": "WWLWLWWWLW"}],
 "research": {"S4": {"sessions": 23, "promoted": false, "top_groups": [ {...} ]}}
}
```
`Trade` (also the SQLite `trades` row):
```json
{"id":"S1-20261008-KPITTECH","strategy":"S1","symbol":"KPITTECH","side":"LONG","product":"MIS",
 "strength":8,"raw_score":7,"why":"Q2 results: Rev +28% · PAT +61% · margin +310bps (consol.)",
 "source_url":"https://www.bseindia.com/xml-data/corpfiling/AttachLive/....pdf",
 "signal_time":"2026-10-08T11:42:07+05:30","ref_price":1446.2,"max_entry":1452.0,"valid_till":"11:45",
 "qty":41,"risk_inr":1968,"thesis":{"tf":"5m","dir":"below","level":1428.5},"safety_stop":1404.0,
 "target":null,"exit_by":"15:07","profit_lock":{"active":false,"rule":"avwap_after_2pct"},
 "status":"OPEN","paper_entry":1449.6,"exit_time":null,"exit_price":null,"exit_reason":null,
 "paper_net_pct":null,"notified":true}
```
`status` ∈ `PENDING` (not notified: low strength or risk limits), `OPEN`, `MISSED` (paper couldn't fill, but ENTRY was sent), `EXITED`.

## 8. Dashboard (`docs/`)

**Files:** `index.html`, `app.js`, `crypto.js`, `sw.js`, `style.css`, `config.js` (owner, repo, data branch, path, VAPID public key; no secrets), `manifest.webmanifest` (name "Intraday Alerts", `display: standalone`, icons 192 and 512), `icons/`.

**Rules:** plain HTML/CSS/JS, no frameworks, no build step, no external CDNs. Mobile-first. Light and dark mode through `prefers-color-scheme`.

**Data fetch:**
- `GET https://api.github.com/repos/{owner}/{repo}/contents/state.enc.json?ref=data` with `Accept: application/vnd.github.raw+json` and `If-None-Match: <last ETag>`. A 304 doesn't count against GitHub's 60/hour unauthenticated limit.
- Poll every 60 s while the tab is visible, and immediately on `visibilitychange` → visible.
- On a 403/429 rate limit, fall back to `https://raw.githubusercontent.com/{owner}/{repo}/data/state.enc.json` (may be about 5 min stale) and show "delayed".

**Sections, top to bottom:**
1. **Status bar:** 🟢 Live · updated 11:32 / 🟡 Delayed (>10 min) / 🔴 Engine offline / ⚪ Market closed (next: Fri 9 Oct) · a PAPER or LIVE badge.
2. **Open trades:** a card each with symbol, side, strategy, strength, entry, thesis stop, safety stop, exit-by, paper P&L as of the last publish, and a source link.
3. **Today:** every notified trade with status and result.
4. **Scoreboard:** one row per strategy (mode, trades, win %, average net %, total net %, last 10 as ●○).
5. **Research (S4):** sessions collected, promotion status, and the top groups table.
6. **Health:** feed, last poll times, LLM errors, version.
7. **Settings** (collapsed after first use): passphrase field (stored in `localStorage` under `ia_pass`), Enable notifications, subscription box with Copy, a local test-notification button, and the phone-setup help from §5.5.

A deep link `#t=<trade id>` scrolls to and highlights that trade's card; notification taps use it.

## 9. Watchdog (`.github/workflows/watchdog.yml` + `.github/scripts/watchdog.py`)

```yaml
name: watchdog
on:
  schedule:
    - cron: "*/15 3-10 * * 1-5"   # 08:30–16:15 IST, Mon–Fri (cron is UTC; runs may start late, which is fine here)
  workflow_dispatch:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install pywebpush requests
      - run: python .github/scripts/watchdog.py
        env:
          VAPID_PRIVATE_KEY: ${{ secrets.VAPID_PRIVATE_KEY }}      # PEM contents
          VAPID_SUBJECT: ${{ secrets.VAPID_SUBJECT }}
          PUSH_SUBSCRIPTIONS: ${{ secrets.PUSH_SUBSCRIPTIONS }}    # JSON array, the same as secrets/subscriptions.json
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```
Logic of `watchdog.py`:
1. Fetch the envelope from the `data` branch (public, no decryption needed).
2. If IST today ≠ `next_trading_day` and `engine_status == "stopped_eod"`, it's a holiday or weekend: exit.
3. If the time is outside 09:05–15:35 IST: exit.
4. If `heartbeat_at` is 12–40 minutes old: send `⚠️ Engine offline since {heartbeat_at}`. The window limits this to one or two alerts per outage without needing stored state.

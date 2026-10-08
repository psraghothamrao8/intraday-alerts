# 01: Decisions and architecture

## 1. Key decisions (and changes to the original plan)

| # | Original idea | Decision | Why |
|---|---|---|---|
| D1 | "Create GitHub Pages" to run everything | **GitHub Pages = dashboard + notification subscription only.** The engine runs on the home PC. | Pages is static hosting and can't run code. GitHub Actions can't run the engine either (see §3). |
| D2 | Machine on 24/7 with an LLM running | **The PC runs only on trading days, about 08:40–15:45 IST, plus about 20 min in the evening.** No local LLM. | Nothing happens outside market hours. PDF reading goes to the Claude API, which is more accurate on messy tables and scanned pages than a local model and costs a few dollars a month (§5). |
| D3 | GPU ("3090") for the LLM | **GPU not needed.** | See D2. (An RTX 3090 has 24 GB. If yours really has 4 GB, that's another reason not to run models locally.) |
| D4 | Telegram alerts (playbook) | **Web Push from the GitHub Pages site** as primary (what you asked for), with Telegram as an optional backup | A missed "SELL now" costs money. Phones sometimes delay web pushes under battery saving, so a second channel is cheap insurance. |
| D5 | Fixed or tight stop-losses | **Three-layer exits:** a thesis stop on 5-minute closes, a wide safety SL at the broker, and a time exit. Position size comes from the stop distance. | See [03_exits_and_stops.md](03_exits_and_stops.md). The playbook's own S1 stop ("1.5% or the 15-minute low, whichever is closer") is the kind of stop that gets hit by noise. |
| D6 | (implicit) the bot trades | **Alerts only; you place orders by hand** | Automated orders need a static IP, the broker's algo setup and a daily 2FA under SEBI's retail-algo framework (live since April 2026). Alerts avoid all of that. |
| D7 | Public GitHub repo/site | **The site is public, the data is encrypted** (AES-GCM, passphrase you type once on each device) | Pages sites are public even from private repos on free plans. Encryption keeps your positions private, and a public page posting buy/sell calls could also look like unregistered research advice under SEBI rules. |
| D8 | Token pasted in chat | **Revoke that token.** Create a fine-grained token for this one repo only (Contents: read/write), stored in `.env` on the PC | A classic `ghp_` token usually has access to *all* your repos, and it's now in a chat log. Never give tokens to the coding model. |

## 2. What runs where

```
 ┌────────────────────────── Your Windows PC (trading days 08:40–15:45 IST) ──────────────────────────┐
 │                                                                                                     │
 │  BSE announcements API ──┐                                                                          │
 │  NSE announcements API ──┼─► filings_watcher ─► pdf_fetch ─► llm_reader ──► S1 / S3 scorers ──┐     │
 │                          │        (dedupe)                    (Claude API)                    │     │
 │                          │                                                                    ▼     │
 │  Broker WebSocket/REST ──┴─► market_data (ticks → 1m/5m candles, VWAP, quotes) ─► S2 ORB ─► signal  │
 │                                     │                                             S4      engine   │
 │                                     └──────────────► exit_engine (all open trades) ◄──────┘        │
 │                                                                                    │               │
 │                       risk (size, daily limits) ◄─────────────────────────────────┤               │
 │                       state.db (SQLite: signals, trades, notifications) ◄──────────┤               │
 │                                                                                    ▼               │
 │                                          notifier ──► Web Push service ──► your phone / PC browser │
 │                                             └──────► Telegram (optional backup)                     │
 │                                          publisher ─► GitHub `data` branch: state.enc.json          │
 │  Evening job (18:30): universe refresh, bhavcopy, 1-min data download, S4 stats, backups            │
 └─────────────────────────────────────────────────────────────────────────────────────────────────────┘

 GitHub repo (public)
   main branch  /docs  ──► GitHub Pages: PWA dashboard + service worker (sw.js) + manifest
                /engine, /backtest, /spec, /.github/workflows
   data branch  state.enc.json (single orphan commit, overwritten each publish)
   Actions      watchdog.yml every 15 min in market hours: heartbeat stale → push "Engine offline"
```

## 3. Why GitHub alone can't run the engine

You asked whether GitHub Pages alone would be enough. It isn't. These were checked or are well known:

1. **Pages only serves files.** It has no server-side code, so it can't poll exchanges or send pushes.
2. **GitHub Actions cron is unreliable for intraday timing.** Scheduled runs often start 5–30+ minutes late and are sometimes dropped under load. A 09:20 ORB signal can't wait for that.
3. **Job time limit.** A hosted job runs at most 6 hours; the session from 09:00 to 15:30 is 6.5 hours.
4. **Exchange sites block bots.** On 2026-10-08, a plain `curl` to the BSE API from your PC got **HTTP 403** (Akamai). A browser-fingerprinted client (`curl_cffi` with Chrome impersonation) got 200 for both BSE and NSE. Data-centre IPs such as GitHub runners are blocked more often still.
5. **Minutes.** In a private repo, 6.5 h × 22 days ≈ 8,600 min/month, against 2,000 free.

So the engine runs on the home PC (a verified working IP), and GitHub does the cheap jobs: hosting the dashboard and running a watchdog that tolerates delay.

**Alternative host (optional, later):** a small Indian-region cloud VM (Mumbai/Hyderabad). Test first that BSE/NSE don't block its IP. The home PC is the default because it's free and verified.

## 4. Machine requirements

| Item | Requirement |
|---|---|
| OS | Windows 10/11, the existing PC |
| Python | 3.12 (installed: 3.12.0) |
| CPU/RAM | Any modern CPU; 8 GB RAM is plenty |
| GPU | Not used |
| Disk | About 5 GB/year (1-minute data in Parquet, PDFs, SQLite) |
| Network | Home broadband; a phone hotspot as fallback. A UPS for the PC and router is strongly recommended |
| Schedule | Task Scheduler: start `run_engine.bat` at 08:40 Mon–Fri with "Wake the computer to run this task"; the engine exits by itself at 15:45. Evening task at 18:30. It skips exchange holidays itself. |
| Sleep | Allow sleep outside those windows; the PC doesn't need to be on 24/7 |

## 5. LLM choice

The LLM is used only to **read filings** (results PDFs, order and buyback announcements) and return strict JSON. All scoring, filtering and trading logic is ordinary Python, so it's deterministic and testable.

| Option | Model ID | Price (input / output per 1M tokens) | Notes |
|---|---|---|---|
| **Default** | `claude-opus-5-5` | $4 / $20 | Most accurate on dense Indian results tables and scanned pages. Use `effort: "low"` for speed. |
| Cheaper | `claude-haiku-5-5` | $0.10 / $0.50 | About 40× cheaper and faster. **Your call**: switch in `config.yaml` after Task 3.6 measures its accuracy against Opus on about 50 real filings. |

**Rough monthly cost with the default:** a results PDF is about 6–15k input tokens and about 1–2k output tokens, so roughly **$0.05–0.10 per filing**. In-session results are a few hundred per season (only 4 on Oct 8, early season; far more at the peak), and in-session order/buyback filings are about 5–20 a day (7 order filings on Oct 8). Expect **about $20–60 a month in season** with Opus and about $1–2 with Haiku. Backtests use the **Batch API (50% cheaper)**.

**Why not a local model on the GPU:** a wrong number becomes a wrong trade. About 1 in 4 sampled PDFs on Oct 8 had **scanned pages with no text layer**. Lotus Chocolate's results PDF had text on page 1 and images on pages 2–6. Reading those needs a vision model. Running and maintaining a local vision model costs more effort than the API costs in money. You can revisit this later.

**SDK pattern** (Python `anthropic` SDK, structured outputs):

```python
import anthropic
client = anthropic.AsyncAnthropic()   # reads ANTHROPIC_API_KEY from env

resp = await client.beta.messages.parse(
    model=cfg.llm.model,                          # "claude-opus-5-5"
    max_tokens=16000,
    output_config={"effort": cfg.llm.effort},     # "low"
    betas=["server-side-fallback-2026-07-01"],    # Opus/Sonnet only; omit for Haiku
    fallbacks="default",                          # Opus/Sonnet only; omit for Haiku
    system=RESULTS_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": content_blocks}],
    output_format=ResultsExtraction,              # a Pydantic model (see 02_strategies.md)
)
if resp.stop_reason == "refusal":
    ...  # log it, no signal
data: ResultsExtraction = resp.parsed_output
```

Notes for the implementer:
- `content_blocks` is either text (`{"type": "text", "text": ...}`) or the PDF itself (`{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}` placed **before** the text instruction). See §S1.3 in 02.
- Pass `fallbacks` only when the model is Opus or Sonnet. Haiku has no server-side fallback, so leave out both `betas` and `fallbacks`. If the installed SDK doesn't accept `fallbacks=` as a keyword, pass it through `extra_body={"fallbacks": "default"}`.
- **Don't** set `temperature`; current models reject sampling parameters. **Don't** use assistant prefill.
- Timeout: 60 s with 2 retries. If the LLM fails, **no signal**; never guess.

## 6. Process model (inside the engine)

- One Python process, `asyncio`. Each component is a long-running task that catches and logs its own exceptions and never kills the process.
- Broker WebSocket callbacks run on the SDK's thread and push ticks into an `asyncio.Queue` through `loop.call_soon_threadsafe`.
- **Clock abstraction** (`core/clock.py`): all code calls `clock.now()`. In replay mode a fake clock drives recorded data, so the whole engine can be tested on a weekend. This is mandatory; see Task 1.3.
- **State** in SQLite (`data/state.db`), so a restart resumes open trades and never sends a notification twice.

## 7. Repository layout

```
trading_coding/
├─ AGENTS.md / CLAUDE.md        rules for the coding model
├─ intraday.md                  the playbook (reference only)
├─ spec/                        this design
├─ docs/                        GitHub Pages site (the name is required by Pages "deploy from /docs")
│   ├─ index.html  app.js  crypto.js  sw.js  style.css  config.js  manifest.webmanifest  icons/
├─ engine/
│   ├─ __main__.py              CLI: run | replay | universe | collect-eod | filings | vapid-gen
│   │                                add-device | notify-test | publish-test | doctor
│   ├─ config.py                load config.yaml + .env (pydantic-settings)
│   ├─ core/   clock.py  calendar.py  models.py  state.py  risk.py  exits.py  strength.py  costs.py
│   ├─ data/   broker_base.py  broker_<name>.py  fake_broker.py  candles.py  universe.py
│   │          filings_bse.py  filings_nse.py  pdf_fetch.py  bhavcopy.py  http.py
│   ├─ llm/    reader.py  schemas.py  prompts/results.md  prompts/order.md  prompts/buyback.md
│   ├─ strategies/  base.py  s1_results.py  s2_orb.py  s3_filing_flash.py  s4_squareoff.py
│   ├─ notify/ webpush.py  telegram.py  formatter.py  dispatcher.py
│   └─ publish/ github_data.py  crypto.py  snapshot.py
├─ backtest/   fetch_history.py  extract_batch.py  simulate.py  report.py  calibrate.py
├─ tests/      unit + replay tests, fixtures/ (saved PDFs, JSON, candles)
├─ config.yaml                  all tunables (committed, no secrets)
├─ .env                         secrets (never committed)
├─ secrets/                     vapid_private.pem, subscriptions.json (never committed)
├─ data/                        state.db, parquet, pdf cache, logs (never committed)
└─ .github/workflows/watchdog.yml
```

## 8. Security rules (non-negotiable)

1. `.gitignore` must contain: `.env`, `secrets/`, `data/`, `*.pem`, `*.db`, `__pycache__/`, `.venv/`.
2. Add a pre-commit hook that refuses commits containing `ghp_`, `github_pat_`, `sk-ant-`, or `-----BEGIN` (private keys).
3. GitHub token: fine-grained, **only this repository**, permission **Contents: Read and write**, expiry 90 days. Never a classic token.
4. Broker credentials stay in `.env` on the PC. If you automate the daily broker login with a TOTP secret, that secret is as sensitive as your password. Decide whether you're comfortable storing it; the manual alternative is in 05 §3.
5. The dashboard passphrase is never committed. The site stores it in the browser's `localStorage` on your own devices only.
6. Logs must not print secrets, tokens or full push subscriptions.

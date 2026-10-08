# 07: Build plan (task list for the coding model)

Work **one task at a time**, in order. Each task lists the files it touches and **acceptance tests**. A task is done only when its tests pass. Read [AGENTS.md](../AGENTS.md) first.

Rough effort for a capable coding model: Tasks 1–4 in about 1 week (needed during this results season), Tasks 5–7 in week 2, Task 8 onwards in weeks 3–4.

---

## Task 0: Setup (the USER does this, not the model, ~30 min)

1. **Revoke the token you pasted in chat:** GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → delete it.
2. Create a **public** repo (for example `intraday-alerts`) and push this folder to it (it's not a git repo yet: `git init`, commit, push).
3. Repo → Settings → Pages → *Deploy from a branch* → `main` / `/docs`.
4. Create a **fine-grained token**: Settings → Developer settings → Fine-grained tokens → *Only select repositories* → this repo → Repository permissions → **Contents: Read and write** → 90 days.
5. Get an **Anthropic API key** (console.anthropic.com) and set a monthly spend limit there.
6. Set up your **broker's API app** (API key/secret; redirect URL `http://127.0.0.1:8765/callback`).
7. Optional: a Telegram bot (BotFather) and your chat id.
8. Create `.env` from `.env.example` (08 §2) and fill it in. **Never paste these values into a chat.**
9. Tell the model which broker you use (Task 2.1 needs it).

---

## Task 1: Skeleton, notifications, dashboard (gets a test push to the phone)

| # | Work | Files |
|---|---|---|
| 1.1 | Project setup: `pyproject.toml` (Python 3.12; deps: `anthropic`, `pydantic>=2`, `pydantic-settings`, `pyyaml`, `curl_cffi`, `pypdf`, `pandas`, `pyarrow`, `pywebpush`, `cryptography`, `requests`, `pyotp`, `pytest`, `pytest-asyncio`), `.gitignore` (01 §8), pre-commit secret check, `.env.example`, `config.yaml` (from 08) | root |
| 1.2 | `engine/config.py`: load and validate `config.yaml` + `.env` into typed settings; fail fast with clear messages | engine/config.py |
| 1.3 | `core/clock.py` (`RealClock`, `FakeClock` with `advance()`), `core/calendar.py` (holidays, `is_trading_day`, `last_exit_time(sym)`, `entry_cutoff(sym)`) | engine/core |
| 1.4 | `core/state.py`: SQLite schema (05 §10), WAL mode, simple DAO functions | engine/core |
| 1.5 | `notify/`: formatter (04 §3), webpush (04 §5.4), telegram, dispatcher with exactly-once (04 §4); CLI `vapid-gen`, `add-device`, `notify-test` | engine/notify, engine/__main__.py |
| 1.6 | `publish/`: crypto (04 §7.2), snapshot builder (04 §7.4), GitHub Git Data uploader (04 §7.3) with throttle and heartbeat | engine/publish |
| 1.7 | `docs/`: the site (04 §8), `sw.js` (04 §5.3), manifest, icons (simple generated PNGs) | docs/ |
| 1.8 | `.github/workflows/watchdog.yml` + `.github/scripts/watchdog.py` (04 §9) | .github |

**Acceptance tests**
- `pytest tests/test_formatter.py`: the exact texts in 04 §3 are reproduced from sample Trade objects (₹ formatting with Indian grouping, missing lines omitted).
- `pytest tests/test_dispatcher.py`: sending the same ENTRY twice delivers once; a 410 marks the device inactive and triggers the Telegram ALERT (mocked HTTP).
- `pytest tests/test_crypto.py`: Python encrypt → decrypt round trip; plus a fixed test vector (key, iv, plaintext → ct) **also checked in the browser** by a test page `docs/test-crypto.html` that prints PASS.
- Manual: `python -m engine notify-test` → a notification appears on the user's phone within 10 s; tapping it opens the dashboard.
- Manual: `python -m engine publish-test` → the dashboard (after you enter the passphrase) shows the sample state, and the status bar says "Live".
- Manual: stop publishing for 15 min during market hours (or set a test override) → the watchdog sends "Engine offline".

## Task 2: Market data and universe

| # | Work |
|---|---|
| 2.1 | `data/broker_<name>.py` for the user's broker, implementing the `Broker` protocol (05 §5), including login modes. Plus `data/fake_broker.py` (replays Parquet). |
| 2.2 | `data/http.py`: the curl_cffi session factory and backoff (05 §1) |
| 2.3 | `data/universe.py`: reference tables (05 §6) → `universe_YYYY-MM-DD.parquet`. Confirm every 🔎 endpoint in DevTools first; if one doesn't work, write down the replacement in `spec/05_data_sources.md` (edit the spec) |
| 2.4 | `data/candles.py`: tick → 1m/5m, VWAP, anchored VWAP, seeding from intraday candles (05 §7) |
| 2.5 | `data/bhavcopy.py`: delivery % |
| 2.6 | **`collect-eod` command** (05 §8) with `--backfill N` days. **Schedule it daily at 18:30 as soon as it works**, because S2 and S4 need the history. |

**Acceptance tests**
- `pytest tests/test_candles.py`: synthetic ticks → the expected 1m/5m OHLCV and VWAP; a missing minute is handled; 5-minute alignment starts at 09:15.
- `python -m engine universe --date <today>`: the Parquet has ≥ 1,500 rows; for 3 hand-picked symbols (one F&O large cap, one small cap, one BE-series), every column matches what you can see on the NSE website.
- `python -m engine collect-eod --backfill 20`: 20 daily Parquet files; spot-check one symbol's 09:15 candle against a chart.

## Task 3: Filings watcher and LLM reader

| # | Work |
|---|---|
| 3.1 | `data/filings_bse.py`, `data/filings_nse.py`: pollers (05 §2–3), normalised into `filings` rows, dedupe (05 §4) |
| 3.2 | `data/pdf_fetch.py`: download, sha256, cache, AttachLive → AttachHis fallback, page-text extraction and the results-page detector (02 §S1.3) |
| 3.3 | `llm/schemas.py` (Pydantic models from 02), `llm/prompts/*.md`, `llm/reader.py` (01 §5 pattern, text and PDF modes, retry rules) |
| 3.4 | `strategies/s1_results.py`: validation, derived numbers, score (02 §S1.5–S1.7), save fundamentals |
| 3.5 | `strategies/s3_filing_flash.py`: extraction rules and materiality (02 §S3.4) |
| 3.6 | **Extraction accuracy check:** `python -m backtest.extraction_check --n 50`: picks 50 recent results PDFs (mixed text and scanned), extracts with `claude-opus-5-5` **and** `claude-haiku-5-5`, and writes `data/reports/extraction_check.csv` (PDF link + both models' numbers). **The user** hand-checks revenue and PAT for 20 of them; the report shows each model's accuracy. The user then chooses `llm.model`. |

**Acceptance tests**
- `tests/fixtures/pdf/`: save 10 real PDFs (at least 3 scanned) with hand-entered expected values in `expected.json`. `pytest tests/test_results_extraction.py -m live_llm` gets revenue_ops and net_profit (current and year-ago) within 0.5% for at least 9 of 10.
- `pytest tests/test_s1_score.py`: about 15 hand-made extraction objects covering every rubric row, including loss → profit, profit → loss, null EBITDA, and other income > 30% of PBT.
- `python -m engine filings --replay 2026-10-08`: re-processes that day's saved filings and prints one status line per filing (`signal` / `skipped:<reason>` / …).

## Task 4: Signal engine, exits, risk (S1 + S3 live in paper mode)

| # | Work |
|---|---|
| 4.1 | `core/models.py` (Trade etc.), `strategies/base.py` (interface: `on_start`, `on_filing`, `on_candle_1m`, `on_candle_5m`, `on_tick`, `on_clock`) |
| 4.2 | `core/risk.py` (03 §2, §6), `core/exits.py` (03 §4, §7), `core/strength.py` (provisional + calibrated, 06 §8) |
| 4.3 | `engine/__main__.py run`: the asyncio orchestration (01 §6): login → universe → subscribe → pollers → strategies → exits → publisher → shutdown at 15:45 |
| 4.4 | `engine replay --date D`: the whole engine on `FakeBroker` + `FakeClock` + recorded filings, at up to 60× speed, with notifications going to a file instead of the phone (`--notify file`) |
| 4.5 | Windows Task Scheduler setup script (`scripts/install_tasks.ps1`): 08:40 run (wake the computer), 18:30 collect-eod |

**Acceptance tests**
- `pytest tests/test_exits.py`: synthetic candles covering each exit reason; the first condition wins; a 5-minute wick below the thesis level doesn't exit, a close does; time exit at `last_exit_time`.
- `pytest tests/test_risk.py`: qty formula; the daily loss stop blocks new entries; max open trades.
- `pytest tests/test_exactly_once.py`: kill and restart the engine mid-trade in replay → no duplicate notifications, and the EXIT still arrives.
- `python -m engine replay --date <a day with saved data>` produces a notifications file with an ENTRY and EXIT pair for every notified trade, and nothing else.
- **Run live in paper mode for 3 trading days** with no crashes. The health panel stays green.

## Task 5: S2 opening-range breakout
Implement 02 §S2 on the same engine.
**Acceptance:** `pytest tests/test_s2.py` (RVOL ranking, setup direction, the extended-candle skip, the 3-per-day cap). In a replay of 5 recorded days, every S2 notification can be checked by hand against the 1-minute data.

## Task 6: Backtester and calibration
`backtest/fetch_history.py`, `extract_batch.py`, `simulate.py`, `report.py`, `calibrate.py` per 06.
**Acceptance:** reports for S1, S2 and S3 exist with every section in 06 §6. The edge-decay table exists for S1. Calibration JSON files load in `core/strength.py`. Running the same backtest twice gives identical numbers.

## Task 7: Stop calibration and config update
Run the MAE and stop grids (03 §5). Write the chosen parameters into `config.yaml` with a comment pointing to the report file.
**Acceptance:** `data/reports/stops_S1.md`, `stops_S2.md`, `stops_S3.md` exist, and `config.yaml` references them.

## Task 8: S4 research report and (optional) live rule
The S4 report in the evening job (02 §S4.2), published to the dashboard research panel. The live rule (02 §S4.4) stays behind `s4.alerts_enabled: false`.
**Acceptance:** after ≥ 10 collected sessions, the research panel shows grouped stats; `pytest tests/test_s4_events.py` checks the event math on synthetic data.

## Task 9: Hardening
- Feed-down detection (no ticks for 60 s during market hours → ALERT, auto-reconnect).
- A daily log file under `data/logs/`, rotating, kept 30 days.
- A `doctor` command: checks `.env`, broker login, BSE/NSE reachability, the LLM key, GitHub publish, and the push test, and prints a green/red table.

---

## Definition of done (v1)
- The user gets exactly one ENTRY and one EXIT push per trade, with a strength score. The dashboard shows today, open trades and the scoreboard.
- S1 and S3 run in paper mode during results season; S2 runs in paper mode daily; S4 collects data daily.
- Backtest reports and calibration exist; stops are chosen by data.
- The PC starts and stops the engine on its own, and the watchdog reports if it's down.

# Intraday Alert Bot (Indian Cash Equities)

[![CI Tests](https://img.shields.io/badge/pytest-58%20passed-brightgreen.svg)](tests/)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Dashboard](https://img.shields.io/badge/dashboard-GitHub%20Pages-blueviolet.svg)](https://psraghothamrao8.github.io/intraday-alerts/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

An intelligent, event-driven intraday alert system for Indian cash market equities (NSE/BSE). The engine runs locally on your Windows PC during trading hours, monitors exchange corporate filings and live price feeds, scores high-probability setups, and sends encrypted **Web Push notifications to your mobile phone** with calibrated strength scores (1–10).

> **Important Safety Guarantee:** This bot **never places automated broker orders**. It generates strictly one ENTRY and one EXIT notification per trade. All orders are reviewed and executed manually by the trader.

---

## Live Mobile Dashboard & PWA

- **Dashboard URL:** [https://psraghothamrao8.github.io/intraday-alerts](https://psraghothamrao8.github.io/intraday-alerts)
- **Features:** Plain HTML/CSS/JS (no build step, no framework, zero tracking), client-side AES-256-GCM decryption with your passphrase, Web Push subscription manager, and live Health Watchdog monitor.

---

## Strategy Overview

| Strategy | Name | Focus | Active Hours | Side | Exit Template |
|---|---|---|---|---|---|
| **S1** | **Results-Hour Reader** | Real-time LLM extraction of quarterly financial results PDFs filed during market hours | In-session (results season) | Long & Short | News Template (AVWAP + 5m close) |
| **S2** | **Opening-Range Breakout** | Relative volume (RVOL $\ge 1.0$) top 20 stocks-in-play breakout | 09:20–11:00 daily | Long & Short | ORB Template (OR far-side 5m close) |
| **S3** | **Filing Flash** | Real-time extraction of high-materiality orders ($\ge 10\%$ of revenue) and tender buybacks ($\ge 15\%$ premium) | In-session daily | Long | News Template |
| **S4** | **Square-Off Crush Reversal** | Research & measurement of broker auto-square-off selling waves in stocks down $\le -3\%$ | 15:00–15:25 daily | Long (CNC cash) | 5-min Hold Time Exit |

---

## Architecture & Directory Structure

```
trading_coding_implementation/
├── config.yaml               # All numbers, thresholds, risk limits, and broker square-offs
├── .env.example              # Secrets template (copy to .env)
├── docs/                     # Static dashboard hosted on GitHub Pages
│   ├── index.html            # Dashboard layout (Open Trades, Today, Scoreboard, Health)
│   ├── app.js                # AES-256-GCM decryption & PWA push subscription
│   ├── sw.js                 # Service Worker displaying Web Push notifications
│   └── style.css             # Dark-themed responsive stylesheet
├── engine/                   # Core Python engine
│   ├── core/                 # Models, clock abstraction, risk sizing, 3-layer exit engine
│   ├── data/                 # BSE/NSE HTTP scrapers, Upstox adapter, Bhavcopy, candles
│   ├── llm/                  # Claude extraction schemas and prompt templates
│   ├── notify/               # Web Push dispatcher, Telegram backup, formatting
│   ├── publish/              # GitHub Pages encrypted state snapshot publisher
│   ├── strategies/           # S1, S2, S3, and S4 strategy implementations
│   ├── doctor.py             # System diagnostic battery (`python -m engine doctor`)
│   └── logging_config.py     # 30-day rotating midnight log setup
├── backtest/                 # Simulation engine, batch extractor, reports & calibration
├── scripts/
│   ├── push.py               # Safe non-interactive git push helper using GITHUB_TOKEN
│   └── install_tasks.ps1     # Windows Task Scheduler setup (08:40 start, 18:30 EOD)
├── spec/                     # Complete architecture and strategy design specifications
└── tests/                    # Comprehensive unit and acceptance test suite
```

---

## Installation & Setup

### 1. Prerequisites
- **OS:** Windows 10/11
- **Python:** 3.12+ (64-bit)
- **PowerShell:** Default shell

### 2. Clone and Install Dependencies
```powershell
git clone https://github.com/psraghothamrao8/intraday-alerts.git
cd intraday-alerts

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install required packages
pip install -r requirements.txt
```

### 3. Configure `.env`
Copy the template and populate your credentials:
```powershell
Copy-Item .env.example .env
```
Edit `.env` with your values:
```env
# Anthropic Claude API Key (for real-time PDF extraction)
ANTHROPIC_API_KEY=sk-ant-...

# GitHub Personal Access Token (with 'repo' scope for dashboard publishing)
GITHUB_TOKEN=ghp_...

# Client-Side Dashboard Passphrase (used by app.js to decrypt state.enc.json)
DATA_PASSPHRASE=ChooseAStrongSecretPassphrase

# Broker API credentials (Upstox / Zerodha)
BROKER_CLIENT_ID=...
BROKER_API_KEY=...
BROKER_API_SECRET=...
```

### 4. Generate Web Push (VAPID) Cryptographic Keys
Generate EC P-256 keys for Web Push:
```powershell
python -m engine vapid-gen
```
This saves `secrets/vapid_private.pem` and displays your VAPID public key.

### 5. Run the System Doctor
Verify system health, API reachability, and configuration readiness:
```powershell
python -m engine doctor
```
Expected output:
```
======================================================================
 INTRADAY ALERT BOT SYSTEM HEALTH DIAGNOSTICS
======================================================================
 [PASS]   | .env Environment File      | Found .env with 12 keys configured
 [PASS]   | Broker Configuration       | Broker credentials present (upstox)
 [PASS]   | BSE API Reachability       | HTTP 200 OK (14287 bytes)
 [PASS]   | NSE API Reachability       | HTTP 200 OK (13370 bytes)
 [PASS]   | Anthropic LLM API Key      | Configured model: claude-opus-5-5
 [PASS]   | GitHub Pages Publish       | Token present, target: psraghothamrao8/intraday-alerts:data
 [PASS]   | Web Push VAPID Keys        | VAPID private key present at secrets\vapid_private.pem
======================================================================
 RESULT: All systems healthy and operational.
```

---

## How to Use

### 1. Registering Your Phone for Web Push Notifications
1. Open [https://psraghothamrao8.github.io/intraday-alerts](https://psraghothamrao8.github.io/intraday-alerts) in your mobile browser (Safari on iOS 16.4+ or Chrome on Android).
2. Tap **"Share" $\to$ "Add to Home Screen"** to install as a standalone PWA.
3. Enter your `DATA_PASSPHRASE` and tap **Unlock**.
4. Tap **"Subscribe this device"** and grant notification permissions.
5. In your PC shell, test notification delivery:
   ```powershell
   python -m engine notify-test
   ```
   Your phone will immediately receive a test notification!

---

### 2. Daily Trading Session Workflow

#### Morning Automatic Startup (Recommended)
Install the automated Windows Task Scheduler jobs:
```powershell
.\scripts\install_tasks.ps1
```
- **08:40 IST:** Wakes PC, syncs reference universe (`universe_YYYY-MM-DD.parquet`), starts live engine.
- **18:30 IST:** Runs `collect-eod` to store 1m candles and compute S4 research stats.

#### Manual Live Run
Start the engine manually:
```powershell
python -m engine run
```
The engine will:
1. Load today's liquid universe and previous close / ATR / ADV reference data.
2. Poll BSE and NSE corporate announcement feeds every 10–30s.
3. Ingest live 1m ticks from broker WebSocket / feed.
4. Calculate RVOL rankings at 09:20 for Strategy S2.
5. Monitor active positions against 3-layer exits:
   - **Time exit:** Evaluated continuously against `exit_by` (e.g. 15:07 for F&O, 15:20 for cash).
   - **Thesis stop:** Evaluated strictly on **completed 5-minute candle closes** (+2s grace).
   - **Safety stop:** Evaluated on every tick to protect against sharp adverse spikes.
6. Push encrypted snapshots to the GitHub Pages dashboard every 60s.
7. Perform a clean shutdown at 15:45 IST.

---

### 3. Replay Historical Sessions
Replay past trading sessions deterministically with `FakeBroker` and `FakeClock` without placing real alerts:
```powershell
# Replay 2026-10-08 at 60x speed, outputting notifications to a local file
python -m engine replay --date 2026-10-08 --notify file
```
Notifications are written to `data/replay_notifications.jsonl`.

To replay corporate filings extraction for a specific date:
```powershell
python -m engine filings --replay 2026-10-08
```

---

### 4. Backtesting & Strength Calibration

#### Run Event-Driven Simulation
Simulates historical trades with realistic manual fill delays (0.5m, 1m, 2m, 3m, 5m, 10m) and exact transaction costs:
```powershell
# Run backtest simulation for Strategy S1
python -m backtest.simulate --strategy S1 --start 2025-10-15 --end 2026-08-31
```

#### Generate Reports
Generates detailed markdown & CSV performance summaries in `data/reports/`:
```powershell
python -m backtest.report --strategy S1
```
Reports contain:
- Out-of-Sample (40%) vs In-Sample (60%) statistics (Win Rate, Profit Factor, Expectancy R, Max Drawdown).
- Score monotonicity validation (higher scores must produce higher average net returns).
- MAE / MFE distributions in $\text{ATR14}$ units for winners vs losers.
- Edge-decay analysis across entry delays.

#### Calibrate Strength Scores
Computes empirical Bayes shrinkage for out-of-sample trades to standardize strength scores (1–10):
```powershell
python -m backtest.calibrate --strategy S1 --trades-csv data/reports/S1_2026-10-08.csv
```
Calibration parameters are saved to `data/calibration/S1.json` and automatically consumed by `core/strength.py`.

---

### 5. Evening Data Collection & Research

Download 1-minute historical candles and compute S4 square-off research metrics:
```powershell
python -m engine collect-eod --backfill 5
```
This updates:
- `data/candles/1m/YYYY-MM-DD.parquet`
- Baseline opening volume `or_vol_avg14`
- `data/research/s4_events.parquet` (displayed on the dashboard Research panel)

---

## Running the Automated Test Suite

The test suite covers unit logic, strategy scoring, 3-layer exits, position sizing, exactly-once delivery, backtesting determinism, and system hardening:

```powershell
# Run all non-network tests
pytest

# Run a specific test module
pytest tests/test_exits.py -v
pytest tests/test_s2.py -v
pytest tests/test_hardening.py -v
```

All 58 tests run completely offline using fixtures in `tests/fixtures/`.

---

## Push Updates to GitHub Securely

To push local code changes without entering credentials in interactive shell prompts:
```powershell
python scripts/push.py main
```
This helper securely reads `GITHUB_TOKEN` from your local `.env` and pushes without leaking secrets.

---

## Core Rules & Safety Guardrails

1. **Manual Order Execution Only:** The bot sends mobile push alerts; it never enters broker orders.
2. **Zero Secrets in Git:** `.env`, `secrets/`, `data/`, `*.pem`, and `*.db` are strictly git-ignored.
3. **No Magic Numbers:** All trade sizes, risk percentages, entry caps, and stop multipliers are read from `config.yaml`.
4. **Reproducible Time:** All timestamps originate from `engine/core/clock.py` (`RealClock` / `FakeClock`).
5. **Fail-Safe Exits:** Evaluates 3 distinct layers. A wick below thesis level on a 5-minute bar does not trigger an exit—only a candle close does.

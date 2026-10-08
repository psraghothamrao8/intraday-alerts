# 05: Data sources

Items marked **✅ verified** were tested live from the user's PC on 2026-10-08. Items marked **🔎 verify** are believed correct, but the implementer must confirm them (open the page in Chrome → DevTools → Network) before relying on them.

## 1. HTTP rules for exchange websites (`data/http.py`)

- ✅ **Plain `requests`/`curl` get HTTP 403 from BSE** (Akamai bot protection). ✅ **`curl_cffi` with `impersonate="chrome"` gets 200** from both BSE and NSE. Use `curl_cffi.requests.Session(impersonate="chrome")` for every exchange call. (`curl_cffi` 0.15 is already installed.)
- Use one long-lived session per exchange. Timeout 20 s.
- Be polite: BSE page 1 every 10 s; NSE every 30 s; reference downloads at most 1 request/second.
- On 401/403: back off 60 s, recreate the session (NSE: warm the cookies again, §3), retry. After 5 failures in 10 minutes, raise the health flag and send one ALERT.
- Never hammer: a block for the day means no S1/S3 signals for the day.

## 2. BSE corporate announcements ✅ verified

**Request**
```
GET https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w
    ?pageno=1&strCat=-1&strPrevDate=20261008&strScrip=&strSearch=P
    &strToDate=20261008&strType=C&subcategory=-1
Headers: Referer: https://www.bseindia.com/
         Origin:  https://www.bseindia.com
         Accept:  application/json, text/plain, */*
```
**Response:** `{"Table": [ ... up to 50 rows, newest first ... ], "Table1": [{"ROWCNT": 1046}]}`. On Oct 8 by 20:00 there were 1,046 rows (21 pages).

**Row fields seen:** `NEWSID`, `SCRIP_CD` (int, BSE code), `SLONGNAME` (company), `NEWSSUB` (subject), `HEADLINE`, `CATEGORYNAME`, `SUBCATNAME`, `ATTACHMENTNAME` (PDF file name), `DissemDT` (dissemination time, ISO, IST, no zone), `NEWS_DT`, `News_submission_dt`, `Fld_Attachsize` (bytes), `NSURL`, `CRITICALNEWS`, `TotalPageCnt` (pages of the **list**, not the PDF).

**PDF:** ✅ `https://www.bseindia.com/xml-data/corpfiling/AttachLive/{ATTACHMENTNAME}` (same session, `Referer: https://www.bseindia.com/`). Older files move to `.../AttachHis/{ATTACHMENTNAME}`: try Live first, then His.

**Polling:** fetch page 1 every 10 s. Track the newest `NEWSID`s already seen. If every row on page 1 is new (a burst), fetch page 2, and so on, until a row that's already been seen appears.

**History (backtest):** the same endpoint with `strPrevDate`/`strToDate` set to past dates, paginated. 🔎 verify whether a multi-day range works or whether it must go day by day, and whether the `subcategory` parameter filters server-side. If not, filter client-side.

**Size reference (Oct 8, early in results season):** 7 "Financial Results" (1 in session), 11 "Outcome of Board Meeting" (3 in session), 12 "Award of Order / Receipt of Order" (7 in session), 24 "Press Release / Media Release" (13 in session).

## 3. NSE corporate announcements ✅ verified

```
1) GET https://www.nseindia.com/                    (warm-up: sets cookies; repeat every 30 min or on 401/403)
2) GET https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=08-10-2026&to_date=08-10-2026
   Headers: Referer: https://www.nseindia.com/companies-listing/corporate-filings-announcements
            Accept:  application/json, text/plain, */*
```
**Response:** a JSON **list** of the whole day (595 rows, about 440 KB on Oct 8). That's heavy, so poll every 30 s and diff by `seq_id`.

**Row fields seen:** `symbol` (NSE symbol, directly usable), `sm_name`, `sm_isin`, `desc` (category), `attchmntText` (subject), `attchmntFile` (full PDF URL on `nsearchives.nseindia.com`), `an_dt`, `exchdisstime` (dissemination time, e.g. `"08-Oct-2026 19:59:34"`), `sort_date`, `seq_id`, `hasXbrl`, `fileSize`.

## 4. Trigger category values (✅ seen on 2026-10-08)

| Use | BSE `SUBCATNAME` | NSE `desc` |
|---|---|---|
| S1 results | `Financial Results`, `Outcome of Board Meeting` | `Outcome of Board Meeting`, anything matching `/financial result/i` |
| S3 orders | `Award of Order / Receipt of Order` | `Bagging/Receiving of orders/contracts` |
| S3 buybacks | `Buy back`, `Public Announcement-Buyback of Shares` | match `/buy ?back/i` |
| S3 keyword fallback | `Press Release / Media Release`, `General` | `Press Release`, `General Updates`, `Updates` |
| Catalyst flag for S2 | any row for the symbol since the previous close | same |

**Dedupe across exchanges:** map BSE `SCRIP_CD` to NSE symbol (§6), then use the key `(nse_symbol, trigger_group, sha256(pdf))`, plus a 60-minute window on `(nse_symbol, trigger_group)`.

## 5. Broker market data (`data/broker_base.py`)

Implement **one** adapter for the broker you already use. Upstox, Angel One (SmartAPI), Fyers, Dhan and Zerodha (Kite Connect) all offer APIs; check current pricing and data limits. The rest of the engine sees only this interface:

```python
@dataclass
class Quote:
    symbol: str; ltp: float; volume: int            # volume = today's cumulative
    open: float; high: float; low: float; prev_close: float
    upper_circuit: float | None; lower_circuit: float | None
    bid: float | None; ask: float | None; ts: datetime

@dataclass
class Tick:
    symbol: str; ltp: float; cum_volume: int; ts: datetime

class Broker(Protocol):
    name: str
    async def login(self) -> None: ...
    async def instruments(self) -> pd.DataFrame: ...          # symbol, token, exchange, series, isin, tick_size
    async def quotes(self, symbols: list[str]) -> dict[str, Quote]: ...   # batches internally
    async def intraday_candles(self, symbol: str, interval: str = "1minute",
                               day: date | None = None) -> pd.DataFrame: ...  # ts, open, high, low, close, volume
    async def daily_candles(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    async def subscribe(self, symbols: list[str], on_tick: Callable[[Tick], None]) -> None: ...
    async def unsubscribe(self, symbols: list[str]) -> None: ...
    async def mis_short_lists(self) -> pd.DataFrame | None: ...   # symbol, mis_allowed, short_allowed; None → use CSV
```
Also implement **`FakeBroker`** (reads recorded Parquet candles and drives ticks from them) for replay and tests. It's mandatory.

**Daily login** (SEBI requires a daily two-factor login for API sessions). Pick one in config, `broker.login_mode`:
- `manual`: at 08:40 the engine sends `🔑 Broker login needed` with the login URL. You log in **on the PC** (the redirect goes to `http://127.0.0.1:8765/callback`, where the engine captures the token). No login means no signals that day.
- `auto_totp`: the engine logs in with `pyotp` and the credentials and TOTP secret in `.env`. It's convenient, but those secrets then sit on the PC. It's your decision, and some brokers forbid it; check the terms.

**Data the engine needs:**

| Need | How |
|---|---|
| First-5-minute OHLCV for about 600 stocks at 09:20 (S2) | One batch `quotes()` at 09:20:02 (cumulative volume = first-5-minute volume), or WebSocket-built candles |
| Live prices for candidates and open trades | `subscribe()`; build 1-minute and 5-minute candles from ticks (§7) |
| Pre-filing reference price and 30-minute run-up (S1/S3) | `intraday_candles(sym)` for today |
| ATR14, ADV, prev close | `daily_candles()` nightly |
| 1-minute history (S2 baseline, S4 research, backtests) | `intraday_candles()` for each universe symbol, **every evening** (§8) |
| Circuit limits | `quotes()` → `upper_circuit` / `lower_circuit` at decision time |

## 6. Reference data (evening job, `data/universe.py`)

| Table | Source | Refresh |
|---|---|---|
| NSE equity list (symbol, ISIN, series) | ✅ `https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv` | Nightly |
| BSE code ↔ ISIN ↔ NSE symbol | ✅ BSE scrip master API: `https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scrip_cd=&Scrip_Name=&Industry=&Segment=Equity&Status=Active`, joined on ISIN | Weekly |
| F&O stock list | ✅ NSE `https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv` (Derivatives on Individual Securities) | Nightly |
| ASM / GSM / T2T lists | ✅ NSE APIs: `https://www.nseindia.com/api/reportASM` and `https://www.nseindia.com/api/reportGSM`; T2T = series BE/BZ in Bhavcopy/EQUITY_L | Nightly |
| Broker MIS + short lists | `broker.mis_short_lists()`, or a CSV you update: `data/ref/broker_mis.csv` (`symbol,mis_allowed,short_allowed`) | Weekly or monthly |
| Delivery % | ✅ NSE `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv` (`DELIV_PER` column) | Nightly |
| Shares outstanding (for mcap) | ✅ BSE scrip master `Mktcap` (in ₹ cr), or NSE `https://www.nseindia.com/api/quote-equity?symbol=SYM` → `securityInfo.issuedSize` | Weekly |
| Trading holidays | ✅ NSE `https://www.nseindia.com/api/holiday-master?type=trading` (the `CM` key) | Monthly |
| FX rates (S3 orders in USD/EUR) | `config.yaml` → `fx:` (update monthly by hand) | Monthly |

Output: `data/ref/universe_YYYY-MM-DD.parquet` with one row per NSE EQ symbol: `symbol, isin, bse_code, series, fno, asm_stage, gsm, mis_allowed, short_allowed, prev_close, atr14, atr_pct, adv_cr, mcap_cr, deliv_pct_20d, or_vol_avg14, tick_size`.

## 7. Candles, VWAP, anchored VWAP (`data/candles.py`)

- 1-minute candles from ticks: bucket by exchange timestamp floored to the minute. Volume = difference in cumulative volume. A minute with no tick copies the previous close and has volume 0.
- 5-minute candles are aligned to 09:15 (09:15–09:20, 09:20–09:25, …), built from 1-minute candles.
- A candle is **complete** at its end time plus 2 s of grace.
- Day VWAP = Σ(typical price × vol) ÷ Σ vol from 09:15, with typical price = (H+L+C)/3.
- **Anchored VWAP** (news trades): the same formula from the 1-minute bar that contains the filing time.
- On startup or restart, seed today's candles from `broker.intraday_candles()` before processing live ticks.

## 8. 1-minute data store (evening job: `python -m engine collect-eod`)

- For every universe symbol with `ADV_cr ≥ 2`, download today's 1-minute candles. Store them as `data/candles/1m/YYYY-MM-DD.parquet` with columns `symbol, ts, open, high, low, close, volume`.
- Update the derived baseline: `or_vol_avg14` (mean 09:15–09:20 volume over the last 14 files).
- Run the S4 event extraction (02 §S4.2).
- **Start this job as early as possible.** S2 needs 10+ sessions of baseline, S4 needs 40+ sessions, and backtests need history (06 explains how to backfill).

## 9. Cost model (`core/costs.py`), from the playbook's Zerodha rates

For an intraday round trip with buy value B and sell value S (₹):

```
brokerage = min(20, 0.0003·B) + min(20, 0.0003·S)
stt       = 0.00025·S
exchange  = 0.0000307·(B + S)
sebi      = 0.000001·(B + S)                 # ₹10 per crore
stamp     = 0.00003·B
gst       = 0.18·(brokerage + exchange + sebi)
slippage  = slip(ADV_cr)·(B + S)             # per side, see below
total     = brokerage + stt + exchange + sebi + stamp + gst + slippage
```
Check: B = S = ₹1,00,000 gives ₹82.7 before slippage. The playbook says about ₹83. ✓

Slippage per side by liquidity (config `costs.slippage`): `ADV_cr ≥ 50 → 0.05%`, `10–50 → 0.10%`, `3–10 → 0.20%`, `< 3 → 0.40%`. **News trades** (S1/S3) add **+0.10% per side** for the first 5 minutes after a filing. S4 (CNC bought and sold the same day) uses the same formula; confirm with your broker that it's charged as intraday.

## 10. Database tables (`data/state.db`, SQLite, WAL mode)

```
filings(id TEXT PK,                 -- "BSE:{NEWSID}" or "NSE:{seq_id}"
        exchange, symbol, isin, bse_code, company, category, subcategory, subject,
        disseminated_at, pdf_url, pdf_sha256, trigger_group, status, status_reason,
        processed_at, llm_model, llm_ms, extraction_json)
fundamentals(symbol, period_end, basis, unit, json, source_url, extracted_at,
             PRIMARY KEY(symbol, period_end, basis))
trades(... the Trade object in 04 §7.4 ...)
notifications(... 04 §4 ...)
devices(name, subscription_json, active, added_at)      -- mirrors secrets/subscriptions.json
events(ts, level, component, message)                   -- operational log for the Health panel
```
Every filing goes into `filings` with a final `status` (`signal`, `skipped:<reason>`, `no_trade:<score>`, `error:<msg>`). This log is what the backtest replays and what lets you check "why didn't it alert on X?".

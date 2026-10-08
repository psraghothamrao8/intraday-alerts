# 06: Backtest, calibration, paper trading, go-live

## 1. Principles

1. **One code path.** The backtest runs the *same* strategy and exit code as live, driven by `FakeBroker` + `FakeClock` + recorded filings. No second implementation of the rules.
2. **No look-ahead.** A decision at time t may use only data with timestamps < t. Universe filters use values known the evening before.
3. **Realistic entry delay** (§3.2) and **realistic costs** (05 §9).
4. **Out-of-sample.** Choose variants on the first 60% of dates and confirm them on the last 40%. Report both. A variant that only works in the first part is rejected.
5. **Small grids.** Only the variants listed in 03 §5 and §3.4 below. No per-symbol tuning. No adding score rules because they would have helped last season.

## 2. Data to fetch (`backtest/fetch_history.py`)

| Data | Range | Notes |
|---|---|---|
| BSE + NSE announcements | The last 4 results seasons (Oct–Nov 2025, Jan–Feb 2026, Apr–May 2026, Jul–Aug 2026) for S1; the last 12 months for S3 categories | 05 §2 history query. Store in `filings` with `source='history'` |
| PDFs | In-session (09:15–15:00) filings in the S1/S3 universe | Cache in `data/pdf/{sha256}.pdf` |
| Daily candles | 2 years, all symbols in any universe | ATR/ADV as of each date |
| 1-minute candles | (a) filing symbols on filing days; (b) the S2 universe for as many months as your broker's API allows (aim for 12); (c) non-F&O stocks 15:00–15:30 for S4 backfill | Parquet per day (05 §8) |
| Delivery % | 12 months of NSE bhavcopy | S4 |

**Known bias to note in reports:** today's shares outstanding are used for past market caps (approximate). Delisted or suspended stocks may be missing (survivorship). Both effects are small for intraday holding periods but should be stated.

## 3. S1 / S3 backtest (`backtest/extract_batch.py`, `backtest/simulate.py`)

### 3.1 Extraction
- Run the live extractor's prompts and schemas through the **Message Batches API** (50% cheaper, results within hours). Batch requests use the same model and parameters as live.
- Store the results in `fundamentals` and `filings.extraction_json`.

### 3.2 Entry delay model
```
t_signal = disseminated_at + processing_sec      (default 25 s; replace with the live median once measured)
t_fill   = t_signal + human_delay_sec            (default 45 s)
fill     = open of the first 1-minute bar starting at or after t_fill
MISSED if fill > max_entry (long) / < min_entry (short), or if that bar is locked at the circuit (high == low == band)
```

### 3.3 Edge-decay test (the most important S1 number)
Re-run the simulation with total delays of **0.5, 1, 2, 3, 5, 10 minutes** after dissemination. Report the average net per trade at each delay.
**Decision rule:** if the net at **2 minutes** (a realistic manual delay) is ≤ 0, S1 can't be traded by hand. Either accept that or consider automating orders later (needs the static-IP/algo setup, out of scope).

### 3.4 Variants
Thesis stop, profit lock and time exit variants from 03 §5; `max_hold_min` ∈ {off, 60, 90, 120}; entry threshold score ≥ {5, 6, 7}.

## 4. S2 backtest
- Universe and `or_vol_avg14` are rebuilt for each historical date from data before that date.
- Variants: trigger {1-minute close, first touch}; `entry_until` {10:30, 11:00, 13:00}; thesis {OR low close, OR mid close, 10% ATR tick, 25% ATR tick}; profit lock {off, VWAP after +1R}; top-N {10, 20}; max trades/day {3, 5}.
- **Report both** "all top-20 setups" (the US study's version) **and** "max 3 per day, first come" (what you can actually trade). The difference is the cost of trading by hand.

## 5. S4 backfill
Non-F&O stocks over the last 12 months (square-off has existed for years at about 15:15–15:25): run the S4 event extraction (02 §S4.2) over the history, split the report by year, and flag any period when your broker's square-off time differed. F&O stocks: data builds forward from the closing-auction start.

## 6. Reports (`backtest/report.py` → `data/reports/{strategy}_{date}.md` + CSV)

For every strategy and variant:
- n, win rate, average and median net % per trade, profit factor, expectancy in R, total net %, max drawdown (sequential, paper sizing), t-stat of the mean.
- By **month / season**, and by **score or strength bucket** (must rise monotonically to pass).
- **MAE/MFE** histograms in ATR units, winners vs losers (feeds 03 §5).
- **Stop-variant table** (03 §5).
- Entry-delay table (S1/S3).
- Missed-entry rate. Average position as a % of ADV (capacity).

## 7. Pass/fail gates (all on out-of-sample data, after costs)

| Strategy | Gate |
|---|---|
| S1 | Higher scores earn more (6 < 7 < 8 on average); top bucket ≥ **+1.0% net** per trade (playbook); net > 0 at a 2-minute delay; profitable in ≥ 3 of 4 seasons; ≥ 60 trades |
| S2 | ≥ 200 trades; average net ≥ **+0.15%** per trade; profit factor ≥ 1.2; positive in ≥ 60% of months; still positive when RVOL cut-off and `entry_until` move one step |
| S3 | ≥ 100 trades; average net ≥ **+0.5%**; materiality buckets monotonic |
| S4 | 02 §S4.3 |

A strategy that fails stays in **paper mode** (signals logged, no notifications). Nothing is deleted.

## 8. Strength calibration (`backtest/calibrate.py` → `data/calibration/{strategy}.json`)

Goal: **"strength 8/10" means the same thing in every strategy**: similar past signals averaged about +1% net.

1. Bucket out-of-sample trades by provisional strength (or raw score, if that's more granular).
2. Shrink each bucket toward the strategy mean: `expected = (n·bucket_mean + 20·strategy_mean) / (n + 20)`.
3. Map expected net % per trade to strength:

| Expected net per trade | ≤ 0 | 0–0.25% | 0.25–0.5% | 0.5–0.8% | 0.8–1.2% | 1.2–2.0% | > 2.0% |
|---|---|---|---|---|---|---|---|
| **Strength** | 3 | 5 | 6 | 7 | 8 | 9 | 10 |

4. Save the buckets with `n`, win rate, mean, expected and strength. `core/strength.py` loads the file. If no calibration file exists, use the provisional strength and show it as **`~7/10`** (the tilde means uncalibrated).
5. The dashboard shows, next to each trade: *"Similar past signals: 57% win, +0.9% avg net (n=84)"*.
6. Recalibrate monthly, adding paper and live results to the history.

## 9. Paper → live protocol

1. **Paper**: the engine runs live with `mode: paper`. Notifications are sent normally (the dashboard shows PAPER). Run 2–4 weeks per strategy. For S1, the rest of this results season *is* the forward test.
2. **Compare with the backtest:** average net within one standard error of the backtest's; missed-entry rate < 30%; no repeated data or extraction errors.
3. **Live at quarter size:** set `risk_per_trade_pct: 0.125` for that strategy for 30 trades.
4. **Full size** only if live ≈ paper. Optionally log your real fills in `data/my_fills.csv` (`date,trade_id,entry,exit,qty`); the evening report then shows your real slippage against paper.
5. **Auto-pause** rules: 03 §6.

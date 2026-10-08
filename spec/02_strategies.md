# 02: Strategies S1–S4

## 0. Why these four

From the playbook's 48 plays I picked two I **like** and two I **think will work**:

| Pick | Playbook # | My honest view |
|---|---|---|
| **S1 Results-Hour Reader** (like) | #1 | The edge is reading accuracy plus a speed that humans can't match on scanned or dense PDFs. **Risk:** cheap LLM parsers mean more people now race for the same filing, and you place orders by hand (30–90 s). The backtest must measure how fast the edge decays (06 §3.3). If it's gone after 2 minutes, manual execution can't capture it. |
| **S2 Stocks-in-play ORB** (will work) | #2 | The most evidence of any play: a published US test over 2016–2023 with simple mechanical rules, and it fires every day. **Risk:** never tested in India, ORB is popular here, and the US result came from 20 names a day while you can manage about 3. |
| **S3 Filing Flash** (will work) | #3 | Same engine as S1, so it's almost free to add, and it runs all year. The edge is **materiality** (order value ÷ revenue), not speed: a ₹40 cr order matters to a ₹150 cr-revenue company and is noise for L&T. **Risk:** MoUs dressed up as orders, and serial announcers. On Oct 8, BSE had 12 order filings, 7 of them in market hours. |
| **S4 Square-off crush** (like) | #10 | Forced, price-blind broker flow every day at known times. Nobody has measured it, so **measure first** and send alerts only if the numbers clear costs. |

**Why not the others in v1:** #4 sympathy chain and #5 government contract feed are good but need hand-built reference tables (theme baskets, name-to-ticker aliases). They're the best **Phase 2** additions because they reuse this engine. #6 duty desk fires weekly and needs a case table. #7 circuit magnet trades operator-heavy stocks, and brokers often block intraday trades in band stocks. #8 pre-open fade has only a month of data under the new rule. #9 crude radar depends on the current oil regime and needs MCX data.

---

## 1. Shared definitions (used by all strategies)

| Term | Definition |
|---|---|
| `fno_stock` | Symbol is in the NSE F&O list. F&O stocks trade 09:15–15:15, then the closing auction. Others trade until 15:30. |
| `squareoff_time(sym)` | From config: the broker's auto square-off for F&O stocks or for other stocks. Zerodha: 15:12 / 15:25. |
| `last_exit_time(sym)` | `squareoff_time − exit_buffer_min` (default 5). Every MIS trade is told to exit by then. |
| `entry_cutoff(sym)` | `last_exit_time − 30 min`. No new MIS entries after this. |
| `ATR14` | Mean true range of the last 14 daily bars, in ₹. `ATR%` = ATR14 ÷ previous close. |
| `ADV_cr` | 20-day mean daily traded value, in ₹ crore. |
| `mcap_cr` | Shares outstanding × previous close, in ₹ crore. |
| `ref_price` | (News strategies) Last traded price at the filing's dissemination time, i.e. the close of the 1-minute bar that contains it. |
| `move_since_filing` | (LTP ÷ ref_price − 1), signed **in the trade's direction** |
| `runup_30m` | ref_price ÷ price 30 min before the filing − 1, signed in the trade's direction |
| `band_room` | Long: (upper circuit − LTP) ÷ LTP. Short: (LTP − lower circuit) ÷ LTP. F&O stocks have no fixed band (treat as 99%). |
| `tick` | The instrument's tick size (from the broker instrument master). Round all prices to it. |

**Common filters (every strategy, every signal):**
1. NSE, series `EQ` (not BE/BZ/T2T).
2. Not in ASM stage II or higher, and not in GSM (lists refreshed nightly).
3. Broker allows MIS for the symbol (S4 uses CNC, so this filter doesn't apply to S4).
4. **Shorts only if** the symbol is on the broker's intraday short list **and** (`fno_stock` or `band_room ≥ 10%`). A short you can't buy back goes to an exchange auction, with close-out up to 20% above the close.
5. Never two open trades in the same symbol. One entry per symbol per strategy per day.
6. Risk checks pass (03 §6): daily loss stop, max open trades, max entries per day.

**Strength** (`1–10`): every strategy computes a provisional strength from simple rules (below). After the backtest, `core/strength.py` replaces it with a **calibrated** value (06 §5). Only signals with `strength ≥ notify.min_strength` (default 6) trigger a notification. All signals are stored and paper-tracked whether or not they're notified.

---

## S1: Results-Hour Reader (playbook #1)

### S1.1 Trigger
- **BSE** rows with `SUBCATNAME` ∈ {`Financial Results`, `Outcome of Board Meeting`}, or **NSE** rows whose `desc` matches `/financial result|outcome of board meeting/i`.
- Dissemination time between 09:15 and `entry_cutoff(sym)`.
- **Dedupe:** the same PDF is often filed twice (on Oct 8, Lotus Chocolate filed one PDF as both "Financial Results" and "Outcome of Board Meeting", and the company may also file on NSE). Key = sha256 of the PDF bytes; also skip if (symbol, "results", date) was already processed in the last 60 minutes.
- **Filings after 15:30 or before 09:15:** don't trade them. Queue them for the **evening batch** (Batch API) so the `fundamentals` table stays complete. S1's 4-quarter average and S3's TTM revenue both depend on it.

### S1.2 Cheap filters before calling the LLM
Resolve symbol → mcap ₹500–15,000 cr, `ADV_cr ≥ 3`, plus the common filters. If any fails, log `skipped:<reason>` and stop.

### S1.3 Read the PDF
1. Download (max 15 MB, 20 s timeout). See 05 for URLs.
2. Extract text per page with `pypdf`. A page is a **results page** if its text has ≥ 400 characters and contains ≥ 2 of: `revenue from operations`, `total income`, `profit before tax`, `net profit`, `profit for the period`, `total expenses` (case-insensitive).
3. **TEXT mode** if there's at least one results page: send the text of up to `llm.max_pages_text` (6) results pages, each prefixed with `--- page N ---`.
4. **PDF mode** otherwise (scanned): build a new PDF from the first `llm.max_pages_pdf` (8) pages with `pypdf.PdfWriter` and send it as a base64 `document` block.
5. If TEXT mode fails validation (S1.5 check A), retry **once** in PDF mode.

### S1.4 Extraction schema (Pydantic, used as `output_format`)

```python
from typing import Literal
from pydantic import BaseModel

class Period(BaseModel):
    revenue_ops: float | None          # "Revenue from operations" (NOT total income)
    other_income: float | None
    total_income: float | None
    total_expenses: float | None
    finance_costs: float | None
    depreciation: float | None         # "Depreciation and amortisation expense"
    exceptional_items: float | None    # as printed; gain positive, loss negative
    profit_before_tax: float | None
    tax_expense: float | None          # total tax (current + deferred)
    net_profit: float | None           # profit for the period after tax, before OCI
    net_profit_owners: float | None    # "attributable to owners of the company" (consolidated)

class Statement(BaseModel):
    current_qtr: Period
    previous_qtr: Period
    year_ago_qtr: Period
    ytd_current: Period | None         # half-year / nine-months columns, if printed
    ytd_previous: Period | None
    last_full_year: Period | None

class ResultsExtraction(BaseModel):
    is_financial_results: bool         # False if the outcome is only a dividend/fund-raise/etc.
    company_name: str | None
    period_end: str | None             # current quarter end, "YYYY-MM-DD"
    unit: Literal["rupees", "thousands", "lakhs", "millions", "crores", "unknown"]
    consolidated: Statement | None
    standalone: Statement | None
    auditor_modified_opinion: bool     # qualified / adverse / disclaimer in the review or audit report
    going_concern_doubt: bool          # "material uncertainty related to going concern"
    exceptional_item_note: str | None  # one sentence, if a one-off item is described
```

**System prompt** (`llm/prompts/results.md`):

```
You read quarterly financial results filed by Indian listed companies and copy numbers
exactly as printed. Rules:
- Never estimate, compute or infer a number. If a value is not printed, return null.
- Columns are usually: quarter ended (current), quarter ended (previous quarter),
  quarter ended (same quarter last year), year-to-date current, year-to-date previous,
  year ended (previous full year). Map each to the matching field.
- Numbers in brackets (1,234) are negative. Remove commas.
- revenue_ops is "Revenue from operations", never "Total income".
- Report the unit stated in the header (e.g. "₹ in lakhs"). All numbers must be in that unit.
- Fill both consolidated and standalone if both are present; otherwise null for the missing one.
- auditor_modified_opinion is true only if the auditor's report states a qualified, adverse
  or disclaimer of opinion. An "emphasis of matter" alone is not a modified opinion.
- going_concern_doubt is true only if the text says there is a material uncertainty
  about going concern.
- If the document is not a financial results statement, set is_financial_results=false
  and leave the statements null.
```

User text block: `"Company: {name} ({symbol}). Filing subject: {subject}. Extract the results."`

### S1.5 Validation (Python, deterministic)
- `is_financial_results` is true **and** `period_end` equals the latest quarter end before today (2026-09-30 this season). Otherwise skip, so restated or old results don't trade.
- **Basis:** use consolidated if its `revenue_ops` is present for the current and year-ago quarters; otherwise standalone.
- **Required:** `revenue_ops` (current, year-ago) > 0; `net_profit` (current, year-ago) not null; `profit_before_tax` (current) not null.
- **Check A (hard):** if all present, |total_income − revenue_ops − other_income| ≤ 2% of total_income. On failure, retry in PDF mode; if it still fails, skip.
- **Check B (soft):** if all present, |PBT − tax − net_profit| ≤ 5% × max(|net_profit|, 1% of revenue_ops). On failure, continue with strength −1. Associates and discontinued operations legitimately break this.
- Save every validated extraction to the `fundamentals` table: symbol, period_end, basis, unit, all fields, source URL, model, extraction time.

### S1.6 Derived numbers
- `pat` = `net_profit_owners` if consolidated and present, else `net_profit`.
- `rev_yoy` = rev_cur ÷ rev_yago − 1.
- `ebitda` = revenue_ops − (total_expenses − finance_costs − depreciation). Null if any input is null.
- `margin_change_bps` = (ebitda_cur ÷ rev_cur − ebitda_yago ÷ rev_yago) × 10,000.
- `other_income_share` = other_income ÷ PBT (only if PBT > 0).
- `exceptional_gain_share` = exceptional_items ÷ PBT (only if PBT > 0 and exceptional_items > 0).
- `rev_yoy_4q_avg` = mean `rev_yoy` of this symbol's previous 4 quarters in `fundamentals`. Null if fewer than 2 are available.
- `ttm_revenue` = last_full_year.revenue + ytd_current.revenue − ytd_previous.revenue if all present; for Q1 filings use the sum of the last 4 quarters in `fundamentals`. Store it for S3.

### S1.7 Score (the playbook's rubric, plus rules for loss-making bases, which it doesn't cover)

| Rule (vs the same quarter last year) | Points |
|---|---|
| Revenue YoY ≥ 20% / 10–20% / 0–10% / negative | +2 / +1 / 0 / −2 |
| PAT, both periods profitable: YoY ≥ 30% / 15–30% / 0–15% / negative | +3 / +1 / 0 / −3 |
| PAT swing from profit to loss | −4 |
| PAT turnaround from loss to profit *(added)* | +3 |
| PAT loss both periods: loss narrowed ≥ 30% / widened / otherwise *(added)* | +1 / −3 / 0 |
| EBITDA margin change ≥ +200 bps / ≤ −200 bps (null → 0) | +2 / −2 |
| rev_yoy faster / slower than `rev_yoy_4q_avg` by ≥ 5 points (null → 0) | +1 / −1 |
| other_income_share > 30% **or** exceptional_gain_share > 20% | −2 |
| auditor_modified_opinion **or** going_concern_doubt | −3 |

Range −14 to +8. **LONG if score ≥ +6. SHORT if score ≤ −6** (and the common short filter passes). Otherwise no trade, but still log it.

### S1.8 Market checks at decision time
Using `broker.intraday_candles(sym, "1minute")` and a live quote:
- `move_since_filing < 2.0%`, else `skipped:already_moved`
- `runup_30m ≤ 5%`, else `skipped:leak`
- `band_room ≥ 3%`, else `skipped:near_band`
- If market depth is available: spread ≤ 0.5% of mid, else `skipped:spread`

### S1.9 Provisional strength
- Base by |score|. Long: 6→6, 7→7, 8→8. Short: 6–7→6, 8–9→7, ≥10→8.
- +1 if `move_since_filing < 0.5%`
- +1 if `ADV_cr ≥ 10`
- −1 if check B warned
- −1 if Nifty 50 is down > 1% on the day (for a long) or up > 1% (for a short)
- Clamp to 1–10.

### S1.10 Entry and exits
- Entry: LONG `max_entry = round_tick(LTP × 1.003)`, SHORT `min_entry = round_tick(LTP × 0.997)`. Valid for **3 minutes**.
- Exits: **News exit template**, 03 §4.1.
- Why line in the notification: `Q2 results: Rev +28% · PAT +61% · margin +310bps (consol.)`
- Source link: the PDF URL (open it and check the numbers before trading; the playbook warns against trusting an AI number unchecked).

---

## S2: Stocks-in-play opening-range breakout (playbook #2)

### S2.1 Universe (built nightly)
Common filters + `ADV_cr ≥ 10` + previous close ≥ ₹50 + `ATR% ≥ 1%`.
`or_vol_avg14` = mean 09:15–09:20 volume over the last 14 sessions, from stored 1-minute data. It needs ≥ 10 sessions of history, which is why the 1-minute collector (Task 2.6) must start early.

### S2.2 Ranking at 09:20:02
- First 5-minute candle (09:15–09:20) O/H/L/C/V for every universe stock, from WebSocket-built candles or one batch-quote call. (Today's cumulative volume at 09:20 is the first-5-minute volume.)
- `RVOL = V ÷ or_vol_avg14`. Keep `RVOL ≥ 1.0`, rank by RVOL descending, take the **top 20**.

### S2.3 Setup per stock
- C > O → **LONG** setup, `trigger = H`. C < O → **SHORT** setup (only if shortable), `trigger = L`. C == O → skip.
- Skip if the opening range (H − L) > 0.6 × ATR14. The stop would be too wide and the move may be done already.

### S2.4 Trigger (09:21 to `orb.entry_until`, default 11:00)
- LONG: a **completed 1-minute candle closes above `trigger`** (close-confirmation; the backtest also tests "first touch").
- Skip if that close is > trigger × 1.004 (already too extended).
- `max_entry = round_tick(close × 1.003)`, valid 2 minutes. Mirror everything for SHORT.
- At most `orb.max_trades_per_day` (3) entries, first come first served among setups with strength ≥ min_strength. One per symbol.

### S2.5 Provisional strength
Base 5. +1 if RVOL ≥ 3. +1 if RVOL rank ≤ 5. +1 if the symbol has an exchange filing since the previous close (catalyst, from the filings DB). +1 if the opening gap is ≥ 1% in the trade's direction. +1 if Nifty 50's first 5-minute candle points the same way. −1 if the opening range > 0.4 × ATR14. Clamp to 1–10.

### S2.6 Exits
**ORB exit template**, 03 §4.2.
Why line: `Stock in play: volume 4.2× normal in first 5 min · gap +1.8% · filing yesterday`

---

## S3: Filing Flash, orders and buybacks (playbook #3)

### S3.1 Trigger
- BSE `SUBCATNAME` ∈ {`Award of Order / Receipt of Order`, `Buy back`, `Public Announcement-Buyback of Shares`}, or NSE `desc` ∈ {`Bagging/Receiving of orders/contracts`} or matching `/buy ?back/i`.
- **Keyword fallback:** BSE `Press Release / Media Release` or `General`, and NSE `Press Release` / `General Updates` / `Updates`, where the subject or headline matches `/\b(order|contract|letter of award|LoA|work order|purchase order|buy-?back)\b/i`. On Oct 8 there were 13 in-session press releases, and some of them were orders.
- Same time window and dedupe as S1.

### S3.2 Cheap filters
Common filters + `ADV_cr ≥ 2`. Symbol not in `s3.blacklist` (config, maintained by you). `ttm_revenue` from `fundamentals` **or** `mcap_cr` must be known.

### S3.3 Extraction schema

```python
class FilingExtraction(BaseModel):
    kind: Literal["order", "buyback", "other"]
    binding: bool | None            # True: order/contract/LoA/work order/purchase order.
                                    # False: MoU, LoI, "L1"/lowest bidder, framework/rate contract
    value: float | None
    currency: Literal["INR", "USD", "EUR", "GBP", "AED", "other"] | None
    unit: Literal["rupees", "thousands", "lakhs", "millions", "crores", "billions"] | None
    includes_gst: bool | None
    customer: str | None
    customer_type: Literal["government", "psu", "private", "export", "unknown"]
    execution_months: float | None
    company_share_pct: float | None # if a consortium/JV, this company's share
    is_repeat_or_extension: bool | None
    buyback_method: Literal["tender", "open_market", "unknown"] | None
    buyback_price: float | None     # ₹ per share
    summary: str                    # one plain sentence
```

The prompt (`llm/prompts/order.md`) uses the same "never estimate, null if absent" rules as S1, plus: *"binding is false for MoUs, letters of intent, being declared lowest bidder (L1), and framework or rate contracts without a firm value."*

### S3.4 Derived numbers and rules
- `value_cr` = value × unit factor × FX rate (config `fx`) ÷ 1e7, × company_share_pct/100 if given.
- **Order:** candidate if `binding is True` and `materiality = value_cr ÷ ttm_revenue_cr ≥ 10%`. If ttm_revenue is unknown, use `value_cr ÷ mcap_cr ≥ 5%` instead.
- **Buyback:** candidate if `buyback_method == "tender"` and `premium = buyback_price ÷ LTP − 1 ≥ 15%`. Open-market buybacks are ignored.
- **Serial announcer:** ≥ 4 order filings by this symbol in the last 60 days (from the filings DB) gives strength −2.
- **Long only.** Market checks as in S1.8.

### S3.5 Provisional strength
- Order, by materiality: 10–20% → 6, 20–40% → 7, ≥ 40% → 8. Buyback, by premium: 15–25% → 6, 25–40% → 7, ≥ 40% → 8.
- +1 if `move_since_filing < 0.5%`. +1 if `execution_months ≤ 24`. −1 if `is_repeat_or_extension`. −2 if serial announcer.
- Clamp to 1–10.

### S3.6 Entry and exits
Entry as in S1.10 (long only). Exits: **News exit template**, 03 §4.1.
Why line: `Order ₹120 cr from NHAI = 34% of yearly revenue · 18-month execution`

---

## S4: Square-off crush reversal (playbook #10). Research first

### S4.1 Hypothesis
Brokers auto-close leftover MIS positions with market orders at fixed times. F&O stocks: Share.Market 15:00, Motilal 15:00, Fyers 15:05, Angel 15:10, Zerodha 15:12. Others: Share.Market 15:15, Fyers 15:20, Zerodha 15:25. In a stock **down ≥ 3% on the day with low delivery %**, the leftover positions are mostly losing longs, so forced selling should cause a dip in those minutes that then bounces back.

### S4.2 Phase A: measure (no alerts). Starts with Task 2.6
Every evening, for every universe stock with `ADV_cr ≥ 5`:
- From today's stored 1-minute candles, compute:
  - `day_move` = close at 14:55 (F&O) or 15:05 (others) ÷ previous close − 1
  - `deliv_pct_20d` = mean delivery % over the last 20 sessions (NSE bhavcopy). Mark `low_delivery` if it's in the bottom third of the universe that day.
  - For each square-off minute `m` in config: `r_m` = close(m) ÷ close(m−1) − 1; `vol_ratio_m` = vol(m) ÷ median minute volume 14:30–14:55; `bounce_k` = close(m+k) ÷ close(m) − 1 for k ∈ {3, 5, 8}. Don't go past 15:14 for F&O stocks or 15:29 for others.
  - `had_filing_today` from the filings DB
- Append to `data/research/s4_events.parquet`.
- **Report** (evening, published to the dashboard research panel): group by {F&O or not} × {day_move bucket: ≤−3%, −3…−1%, −1…+1%, +1…+3%, ≥+3%} × {delivery tercile} × {minute}. For each group: n, mean `r_m`, mean `bounce_5`, t-stat, hit rate. Also a **simulated trade**: buy at close of minute m when `r_m ≤ −0.5%` and `day_move ≤ −3%` and `low_delivery` and no filing, sell at m+5 (capped as above), net of costs (06 §2).
- **Backfill:** for non-F&O stocks, brokers have squared off at roughly 15:15–15:25 for years, so historical 1-minute data gives a long sample (check each broker's past times). For F&O stocks, the staircase dates only from the closing-auction launch, so that sample builds forward.

### S4.3 Promotion gate (you decide, config flag `s4.alerts_enabled`)
At least 40 sessions **and** ≥ 100 simulated trades; mean net ≥ +0.15% per trade after costs (the playbook asks for the gross dip-then-bounce to clear 0.4%); t-stat ≥ 2; positive in both halves of the sample.

### S4.4 Phase B: live rule (only after promotion)
- At 14:55, candidates = universe ∩ `day_move ≤ −3%` ∩ `low_delivery` ∩ no filing today. Subscribe to their live data.
- In each square-off minute m: when the 1-minute bar closes with `r_m ≤ −0.5%`, send an ENTRY: **"BUY as delivery (CNC), full cash, ≤ max_entry"** (`max_entry = close × 1.002`).
- Exit: time exit at m + `s4.hold_min` (5), capped at 15:14 for F&O and 15:29 for others. Safety stop at entry × (1 − 1.0%), recalibrated by MAE. **No thesis stop**: the trade lasts minutes.
- **Why CNC:** your own broker would square off an MIS position at these same minutes. CNC needs full cash, so there's no leverage. A same-day buy and sell is charged as intraday at most brokers; confirm with yours. Short side: impossible (no CNC shorting), so long only.
- Strength comes from the research table: the expected net of the matching bucket, mapped to 1–10.

---

## Phase 2 candidates (not in v1)

| Playbook # | Reuses | What's extra |
|---|---|---|
| #4 Sympathy chain | Price engine, filings DB | A theme-basket table (about 25 themes) and 5-minute betas |
| #5 Government contract feed | LLM reader | PIB RSS pollers and a company-alias → ticker table |
| #8 Pre-open overshoot fade | Price engine | Record the pre-open order book 09:00–09:10 from day 1 so data exists when you want it |
| #12 / #22 regime filters | Price engine | Switch S2 off on predicted chop days |

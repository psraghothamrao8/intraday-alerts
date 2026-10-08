# 03: Exits and stop-losses (the redesign)

> You said: *"Most of the time when you give stop loss it is very bad."* This file is the fix. The short version: **most exits should be by time or by a broken idea, judged on 5-minute closes. The real stop-loss order is a wide safety net that rarely fires, and position size, not stop distance, controls how much you can lose.**

## 1. Why stops feel bad (the usual causes)

| Cause | What happens | Example from the playbook |
|---|---|---|
| **Stop inside normal noise** | Normal wiggles hit the stop before the move happens | S1 stop "1.5% away" on a small cap with 4% daily ATR. Rough math: a typical 15-minute swing is about ATR × √(15/375) ≈ 0.2 × ATR ≈ 0.8%, and in the hour after results volatility is often 2–3× that (≈1.6–2.4%). A 1.5% stop sits **inside** that range. |
| **"Whichever is closer" rules** | Always picks the tightest stop | S1: "below the 15-minute low **or** 1.5%, whichever is closer" |
| **Tick-triggered in thin stocks** | One stray print or wick fires the stop, then price recovers | Any small-cap SL order |
| **Obvious levels** | Everyone's stop sits just under the same low or round number, and those get swept | "Stop below the 15-minute low" |
| **Same % for every stock** | 1.5% is wide for a sleepy large cap and tiny for a volatile small cap | Fixed-% stops |
| **Late entry** | Buying 1% above the signal price makes the same stop 1% tighter | Manual execution lag |
| **Size first, stop second** | You pick a quantity, then squeeze the stop to cap the ₹ loss | Common habit |

## 2. The replacement: three exits plus sizing

Every trade gets these, computed at entry and shown in the entry notification:

| Layer | What it is | How it triggers | Who acts |
|---|---|---|---|
| **1. Time exit** (main exit) | Each strategy's edge has a natural horizon; the trade ends then | Clock reaches `exit_by` | You, on the SELL notification |
| **2. Thesis stop** (soft) | The price level where the trade's *reason* is proven wrong, e.g. the stock is back below its pre-results price | **A completed 5-minute candle closes beyond the level.** Wicks don't count. | You, on the SELL notification |
| **3. Safety stop** (hard) | A real SL order at the broker, placed right after entry. **Wide**: beyond where winning trades historically went against you. Protects against disconnects, a dead phone, a crash | Broker triggers it automatically | Your broker |
| **+ Profit lock** (optional, per strategy) | After a good gain, exit if price closes back below a meaningful average (anchored VWAP) | 5-minute close, only after activation | You, on the SELL notification |

**Sizing rule (this is what makes wide stops affordable):**

```
risk_inr  = capital × risk_per_trade_pct            (default 0.5%)
qty       = floor( min( risk_inr / |entry − safety_stop|,
                        max_notional / entry,
                        liquidity_cap_inr / entry ) )
skip the trade if qty × entry < min_notional_inr      (default ₹5,000)
```

A stop twice as wide means half the shares and the **same ₹ risk**. You stop getting shaken out, and a bad day still costs a known amount.

## 3. Placement rules

1. **Close-based thesis stops** use completed 5-minute candles aligned to 09:15 (09:20, 09:25, …), evaluated 2 seconds after each candle closes.
2. **Buffer beyond levels:** the thesis level sits `0.1 × ATR14` beyond the reference level, and the safety stop at least `0.25 × ATR14` beyond the thesis level, so the safety stop doesn't fire before the thesis stop in normal trading.
3. **Avoid round numbers:** if a stop lies within 0.15% of a multiple of ₹10 (price < ₹1,000), ₹50 (₹1,000–5,000) or ₹100 (above), move it 0.15% **beyond** that multiple (further from the entry).
4. **Never tighten to fit a size. Never widen after entry.**
5. **Safety-stop order type:** an SL (stop-limit) order with trigger = safety stop and limit = trigger × 0.99 for a long sell (× 1.01 for a short buy-back), so it fills in a fast move. SL-M is fine where your broker offers it. In a gap through the limit it may not fill; that's the tail risk that sizing caps.
6. MIS SL orders are cancelled by the broker at square-off. After every exit, **cancel the safety SL** (the exit notification reminds you).

## 4. Exit templates per strategy (defaults; the backtest may change them, see §5)

### 4.1 News template: S1 (results) and S3 (orders/buybacks)

For a LONG (mirror everything for a SHORT):

| Exit | Rule |
|---|---|
| Thesis stop | 5-minute close **below `ref_price − 0.1 × ATR14`**: the stock is back below where it traded when the news came out, so the market has rejected the news |
| Safety stop | `min(entry − 1.0 × ATR14, thesis_level − 0.25 × ATR14)`, then the round-number rule. The `1.0` (`k_safe`) is recalibrated from MAE data. |
| Profit lock | Activates once a 5-minute close ≥ entry × 1.02. Then exit on a 5-minute close below the **anchored VWAP from the filing time** (the average price everyone paid since the news) |
| Time exit | `last_exit_time(sym)`. Optional `news.max_hold_min` (default off; the backtest tests 60/90/120) |
| Target | None by default (the backtest tests +2 × ATR14) |

### 4.2 ORB template: S2

| Exit | Rule |
|---|---|
| Thesis stop | 5-minute close **below the opening-range low** (the far side of the range): the breakout has fully failed |
| Safety stop | `OR_low − 0.25 × ATR14`, then the round-number rule |
| Profit lock | **Off** by default. The published US version held to the close and made its money on trend days. Backtest variant: after +1R, exit on a 5-minute close below day VWAP |
| Time exit | `last_exit_time(sym)` |

### 4.3 S4 square-off trade

| Exit | Rule |
|---|---|
| Time exit | minute m + 5 (cap 15:14 for F&O stocks, 15:29 for others) |
| Safety stop | entry × (1 − 1.0%), MAE-calibrated |
| Thesis stop / profit lock | None. The trade lasts minutes |

## 5. Let the data choose the stops (MAE/MFE)

Opinions about stops are what produced the bad ones, so the backtest (06 §4) decides:

1. For every simulated trade under **time-exit-only** rules, record **MAE** (max adverse excursion: the worst point against you before exit) and **MFE** (max favourable excursion), in ATR14 units.
2. Look at the MAE of **winning** trades. Set `k_safe` so the safety stop sits beyond the **95th percentile** of winners' MAE. By design, it then cuts at most 1 in 20 eventual winners.
3. Run a small grid per strategy and pick the variant with the best **net expectancy that also holds in the second half of the data**:
   - S1/S3 thesis: {none, ref_price close, ref_price − 0.1 ATR close, 15-min-low close}; profit lock {off, AVWAP after +2%, AVWAP after +1R}
   - S2 thesis: {OR low close, OR mid close, 10% ATR tick (the US version), 25% ATR tick}; profit lock {off, VWAP after +1R}
4. **Prefer the simpler variant** when the difference is within noise (less than about one standard error).
5. Write the chosen parameters to `config.yaml`, and save the comparison table to `data/reports/stops_<strategy>.md` so you can see why.

If "no thesis stop, safety stop plus time exit" wins, that's the answer: data, not habit.

## 6. Day-level risk limits (`core/risk.py`)

| Limit | Default | Effect |
|---|---|---|
| `risk_per_trade_pct` | 0.5% of capital | Sizing, §2 |
| `max_notional_pct_mis` | 200% of capital | Caps MIS leverage, well below the broker's 5× |
| `max_notional_pct_cnc` | 50% of capital | S4 (full cash) |
| `liquidity_cap_pct_adv` | 0.5% of ADV value | Caps size in small caps |
| `max_open_trades` | 4 | New signals are logged but not notified |
| `max_entries_per_day` | 8 (S2 also has its own cap of 3) | Same |
| `daily_loss_stop_pct` | 2% (realised + open, paper) | No new entries for the rest of the day; one ALERT notification |
| `max_consecutive_losses` | 3 | Same as above |
| Strategy auto-pause | live drawdown > 2× backtest worst | Strategy drops to paper mode; one ALERT |

These limits run on **paper P&L**, because the engine doesn't see your real fills. That's close enough when you take most signals.

## 7. Exit engine behaviour (`core/exits.py`)

- **Every price update (or every 2 s):** if the price touches `safety_stop` → EXIT, reason `safety stop hit: your SL order should have filled`.
- **Every 5-minute candle close (+2 s):** evaluate the thesis stop, then the profit lock.
- **Every minute:** if `now ≥ exit_by` → EXIT, reason `time exit`.
- **First condition wins.** Trade state goes OPEN → EXITED and exactly **one** EXIT notification is sent (the DB enforces it, 04 §4).
- **Always send the EXIT for every ENTRY sent**, even if the paper model marked the entry MISSED: you may have filled anyway.
- **Paper exit price:** time, thesis or profit-lock exits use the open of the first 1-minute bar after `signal_time + human_delay_sec`. A safety-stop exit uses `safety_stop` minus one side's slippage, or the bar open if price gapped through.
- **On restart:** reload OPEN trades from SQLite, rebuild today's candles from `broker.intraday_candles`, and continue. If an exit condition happened while the engine was down, send the EXIT immediately with reason `(engine was offline) …`.

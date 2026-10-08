# Intraday Cash Playbook — Indian Stocks

Oct 8, 2026 · @vishal

My pick is #1, the Results-Hour Reader: an AI alert that reads small-cap results filed during market hours and tells you which way to trade within three minutes. No strategy wins every day, so run three or four unrelated plays and judge each over 50–100 trades.

## Read this first

No intraday strategy wins every day. A good one wins 40–60% of its trades and earns more on winners than it loses on losers, so judge each play over 50–100 trades, not one session. Run three or four plays that fire at different times, and something will trigger most days.

**Where intraday money goes.** SEBI found 71% of individual intraday traders lost money in FY23, rising to 80% among those making over 500 trades a year ([Motilal Oswal summary](https://www.motilaloswal.com/learning-centre/2024/7/sebi-study-reveals-key-insights-on-individual-intraday-traders-in-india)). For loss-makers, trading costs equalled 57% of their losses; profit-makers spent 19% of their profits on costs.

**Who's on the other side.** Institutions can't day trade in India: SEBI's short-selling framework bars them from squaring off intraday ([TaxGuru](https://taxguru.in/sebi/framework-short-selling-securities-market.html)). So intraday money moves between retail traders, proprietary desks and high-frequency firms. You take money from institutions in only two ways: trading against their predictable execution (block deals, index rebalances, the closing auction), and reading public information before the crowd does.

**What costs do.** At Zerodha's rates, a ₹1 lakh intraday round trip costs about ₹83, or 0.08%: ₹40 brokerage, ₹25 STT, ₹6 exchange charges, ₹8 GST and ₹3 stamp duty ([Zerodha](https://zerodha.com/charges)). Slippage adds 0.05–0.1% in liquid stocks and 0.3–1% in small caps. Scalps aiming for 0.2% die; plays targeting 1–3% moves survive.

**How I ranked them.** Each play is scored 1–5 on five tests, with the first three counting double (maximum 40):

| Test | Question it answers |
| --- | --- |
| Edge (×2) | Is there a named reason someone must trade against you? |
| Move vs cost (×2) | Is a typical winner at least 3× the all-in cost? |
| Frequency (×2) | Does it fire most days? |
| Build | How easy is the alert to automate? |
| Crowding | 5 = few traders do it |

Plays marked *filter* make other plays better rather than trading alone. Every trade is in cash stocks or ETFs; a few plays read futures, options or commodity prices as signals only.

## My pick: #1, the Results-Hour Reader

This is the one I'd build first, and the one I most want you to try. From now until the November 14 results deadline it fires many times a day, and its edge comes from what AI is genuinely good at: reading a results PDF exactly, in seconds.

**Why I love it**

- It's the rare intraday edge where a solo trader with Claude beats both kinds of big player. Funds can't buy a ₹500-crore company in size, and fast desks don't parse small-cap PDFs. The people you race are other humans opening the same file minutes later.
- The timing is set by rule. A company must file its board-meeting outcome within 30 minutes of the meeting ending, and machine-readable XBRL can follow up to 24 hours later ([LegalMantra](https://legalmantra.net/blog-detail/HOW-SHOULD-ONE-MANAGE-THE-INAUGURAL-BOARD-MEETING-REGARDING-THE-AUDITED-FINANCIAL-OUTCOMES-OF-A-PUBLICLY-LISTED-COMPANY)). Many small and mid caps meet during market hours, so whoever reads the PDF first wins.
- The signal is numbers, not chart shapes, so it's easy to test honestly.
- What I can't promise: how big the edge is in India today. The test below answers that in two weekends of coding.

**How it works**

1. **Watch.** Poll BSE and NSE corporate announcements every 10–15 seconds from 9:15 to 3:00 for "Financial Results" and "Outcome of Board Meeting" filings.
2. **Read.** Pull the PDF and extract revenue, EBITDA (operating profit), PAT, other income and exceptional items for this quarter, the same quarter last year and the previous quarter. Use text extraction first and Claude's PDF reading as the fallback; return nulls, never estimates.
3. **Score.** Apply the rubric below.
4. **Filter.** Market cap ₹500–15,000 crore; average daily turnover at least ₹3 crore; intraday allowed (not trade-for-trade or a high ASM stage); price moved under 2% since the filing; not within 3% of the price-band limit; no run-up over 5% in the 30 minutes before the filing (a leak that's already priced).
5. **Alert.** Send a Telegram message with side, score, the three key numbers, entry, stop, exit time and the PDF link. You place the order.
6. **Trade.** Go long at a score of +6 or more; short at −6 or less only if the stock is on your broker's intraday short list. Enter within 3 minutes with a limit order no more than 0.3% beyond the last price. Stop below the low of the 15 minutes before the filing, or 1.5% away, whichever is closer. After +2%, trail the stop under each 15-minute low, and exit everything 5 minutes before your broker's square-off time.

| Signal (vs the same quarter last year) | Points |
| --- | --- |
| Revenue growth ≥ 20% / 10–20% / negative | +2 / +1 / −2 |
| PAT growth ≥ 30% / 15–30% / negative / swing to loss | +3 / +1 / −3 / −4 |
| EBITDA margin change ≥ +200 bps / ≤ −200 bps | +2 / −2 |
| Revenue growth faster / slower than its 4-quarter average | +1 / −1 |
| Other income over 30% of pre-tax profit, or a one-off gain | −2 |
| Auditor qualification or going-concern doubt | −3 |

Scores run from +8 to −14, so +6 or more needs strong sales and profit growth with clean quality.

**Example alert** (made-up company):

```
RESULTS 11:42  LONG  XYZ  score +7
Revenue +28% YoY | PAT +61% | EBITDA margin +310 bps
Filed 11:39 | price +0.8% since filing | turnover ₹6.1 cr/day
Entry ≤ ₹412.0 | Stop ₹401.5 | Exit by 15:20
PDF: <link>
```

**Test it before trading**

1. Collect every in-session results filing from the last four seasons; BSE's announcement archive keeps the timestamps.
2. Run the same parser and score on each, and record returns from filing + 3 minutes to your exit time, charging 0.4% per round trip.
3. Keep the play only if higher scores clearly earn more and the top group averages at least +1% net per trade.
4. Paper-trade two weeks of this season, then go live at quarter size.

Outside results season, the same engine runs #3 (Filing Flash) on orders, buybacks and allotments, so it earns its keep all year.

**The wildcard I'm most curious about: #10, the square-off crush.** Since the closing auction began, brokers auto-close leftover intraday positions in F&O stocks at a staircase of times: 3:00 pm at Share.Market and Motilal Oswal, 3:05 at Fyers, 3:10 at Angel One and 3:12 at Zerodha, all before trading stops at 3:15 (sources in the rules table). That's a forced, price-blind flow that hits every single day, and I haven't seen anyone measure it. It may be too small to beat costs, so spend one weekend measuring it before you trust it.

## Master ranking

Ranks 1–10 are the ones worth building; ranks 38–48 are here so you know what to skip. Within tied scores, the plays I trust more come first.

Categories: **A** AI reading public information · **B** forced and rule-driven flows · **C** lead-lag between related prices · **D** price and volume patterns · **E** regime filters · **F** fading retail crowds.

| # | Play | Cat. | Fires | Side | Score /40 |
| --- | --- | --- | --- | --- | --- |
| 1 | Results-Hour Reader | A | Many times daily in results season | Both | 35 |
| 2 | Stocks-in-play opening-range breakout | D | Daily | Both | 34 |
| 3 | Filing Flash: orders, buybacks, allotments | A | Daily | Mostly long | 32 |
| 4 | Sympathy chain: theme leader to laggards | C | Most days | Both | 32 |
| 5 | Government contract feed | A | Most days | Long | 32 |
| 6 | Duty desk: anti-dumping and safeguard duties | A | Weekly | Both | 32 |
| 7 | Circuit magnet | B | Daily | Both | 31 |
| 8 | Pre-open overshoot fade | B | Daily | Both | 30 |
| 9 | Crude shock radar | C | Several times a week now | Both | 29 |
| 10 | Square-off crush reversal | B | Daily | Both | 28 |
| 11 | No-news gap fade | D | Daily | Both | 28 |
| 12 | Options-map regime switch | E | Daily | *Filter* | — |
| 13 | Retail-attention fade | F | Most days | Short | 27 |
| 14 | 52-week and all-time-high breakout | D | Most days in uptrends | Long | 27 |
| 15 | Block-window absorption | B | Weekly | Long | 27 |
| 16 | Morning margin-call flush | B | After sharp falls | Long | 27 |
| 17 | Rumour-denial snap-back | A | Weekly | Both | 27 |
| 18 | Regulator hits | A | Weekly | Short | 27 |
| 19 | Business-update day reader | A | Monthly clusters | Both | 26 |
| 20 | Pump fade | F | Most weeks | Short | 26 |
| 21 | Pledge invocation and auditor exits | A | Rare | Short | 26 |
| 22 | Day-type classifier | E | Daily | *Filter* | — |
| 23 | OFS-day convergence | B | Monthly | Short | 25 |
| 24 | Metals and bullion radar | C | Weekly | Both | 25 |
| 25 | ETF iNAV reversion | B | Weekly | Long | 25 |
| 26 | First-hour to last-hour momentum | D | A few days a month | Both | 25 |
| 27 | IPO listing-day playbook | B | Weekly | Both | 25 |
| 28 | Flash-dip reversal | D | Weekly | Long | 25 |
| 29 | Strength in weakness | D | Red mornings | Long | 25 |
| 30 | Broker-note open drive | A | Daily | Both | 25 |
| 31 | VWAP-algo footprint ride | B | Most days | Both | 25 |
| 32 | VWAP first pullback | D | Daily | Both | 24 |
| 33 | Live concall listener | A | Results season | Both | 24 |
| 34 | Rebalance-day auction flow | B | A few days a year | Both | 24 |
| 35 | VIX regime sizing | E | Daily | *Filter* | — |
| 36 | Asian-hours read-across | A | Monthly | Both | 23 |
| 37 | Macro-shock laggards | C | Monthly | Both | 23 |
| 38 | Round-number magnets | D | Daily | Both | 23 |
| 39 | Failed-breakout reversal | D | Daily | Both | 23 |
| 40 | Iceberg detection | D | Weekly | Both | 22 |
| 41 | NR7 and inside-day breakout | D | Daily | Both | 22 |
| 42 | Series-migration day | B | Rare | Long | 21 |
| 43 | Expiry-Tuesday heavyweights | D | Weekly | Both | 20 |
| 44 | Same-time-of-day periodicity | E | Daily | *Filter* | — |
| 45 | European-open handover | E | Daily | *Filter* | — |
| 46 | Rupee shock to exporters | C | Monthly | Both | 19 |
| 47 | Ex-date euphoria fade | F | Rare | Short | 19 |
| 48 | Order-book imbalance scalping | D | Constant | Both | 19 |

## Tier 1 — ranks 2–10

Each of these fires at least weekly and has a named reason to work; #1 has its own section above.

### 2. Stocks-in-play opening-range breakout

*Category D · daily · liquid stocks*

- **Why it works:** Stocks trading far above their normal volume in the first minutes usually carry news, and the orders behind that news keep coming all day. A US study traded the 20 stocks with the highest relative volume, buying or shorting a break of the first 5-minute range and holding to the close; it reported a Sharpe ratio of 2.81 over 2016–2023 ([Concretum Group](https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/)). Nobody has published an Indian test, so that's your first job.
- **How to run it:** At 9:20, rank stocks with at least ₹10 crore average daily turnover by first-5-minute volume against their 14-day average for those same minutes, and keep the top 20 that are at or above average, the US cut-off ([CXO Advisory](https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/)). If the first candle closed up, place a buy-stop at its high; if down, a sell-stop at its low. The US version used a stop of 10% of the 14-day ATR; test wider stops in India (25% of ATR, or the far end of the range), because 0.15% costs eat tiny stops. Claude checks each name for a catalyst and drops those with none.
- **What kills it:** Choppy range days (let #12 and #22 switch it off), slippage on stop orders at 9:20, and F&O stocks stopping at 3:15.

### 3. Filing Flash: orders, buybacks, allotments

*Category A · daily · small and mid caps*

- **Why it works:** It's the same slow-reader edge as #1, every day of the year. Order wins, buybacks, preferential allotments to well-known investors, capacity start-ups and drug approvals can move small caps for hours, and funds can't chase them.
- **How to run it:** Poll exchange announcements. Claude extracts the type, whether it's binding (an order, not an MoU or letter of intent), value, customer and execution period, then computes materiality as value ÷ trailing-12-month revenue. Alert when materiality is at least 10% (or a buyback premium is at least 15%), the price has moved under 2% since the filing, and daily turnover is at least ₹2 crore. Stop under the pre-filing 15-minute low; trail it or exit at square-off.
- **What kills it:** MoUs dressed up as orders, serial "order" announcements that never show up in revenue (keep a blacklist), upper-circuit locks before you can buy, and filings after 3:15 when F&O stocks have stopped trading.

### 4. Sympathy chain: theme leader to laggards

*Category C · most days · themes*

- **Why it works:** Indian retail trades in themes: defence, railways, power, shipbuilding, electronics manufacturing, PSU banks, sugar and ethanol. When a leader jumps on news that affects the whole theme, attention spreads to its peers over minutes to hours. Within industries, big firms' returns lead small firms' (Hou, 2007).
- **How to run it:** Deep research builds about 25 theme baskets, each with a leader, members and the link between them (a shared customer, policy or commodity). Each morning, compute every member's 5-minute beta to its leader over 60 days. Trigger: the leader moves at least 2.5% within 15 minutes on 3× normal volume, and Claude confirms the news applies to the whole theme. Buy the one or two highest-beta members that have moved less than a third of their expected move; exit when they catch up or at square-off.
- **What kills it:** Company-specific news mistaken for theme news, members stuck in surveillance (ASM) or trade-for-trade, and late-stage themes where everything has already run.

### 5. Government contract feed

*Category A · most days · defence, railways, roads, power*

- **Why it works:** Ministries announce contract signings and awards on PIB, often naming the company, and the company's own filing or wider news coverage can come later. Defence, railway and power stocks are retail favourites that move 2–5% on large orders.
- **How to run it:** Poll PIB's RSS feeds for Defence, Railways, Road Transport, Shipping and Power, plus SECI and NTPC auction results, every 30–60 seconds. Claude extracts the company, value and timeline, and maps names to tickers through an alias table ("Bharat Electronics Limited" → BEL). Alert when the value is at least 3% of market cap or 10% of trailing revenue and the stock has moved under 1.5% since the release.
- **What kills it:** The company filing first, large caps repricing in seconds, and contract values spread over many years or shared by a consortium.

### 6. Duty desk: anti-dumping and safeguard duties

*Category A · weekly · domestic producers*

- **Why it works:** Anti-dumping and safeguard duties can shift a small producer's profits overnight, and DGTR posts its findings online before most traders hear about them. On Sept 28, 2026, Borosil rose 6.2% after a DGTR anti-dumping recommendation on Chinese borosilicate glassware, on a day the Sensex fell over 1,000 points ([Business Today](https://www.businesstoday.in/markets/trending-stocks/story/borosil-shares-rise-amid-market-crash-today-heres-why-558209-2026-09-28)).
- **How to run it:** Deep research builds a pending-case table from DGTR initiation notices: product, countries, the applicant companies each notice names, their listed parents, and the decision deadline (12 months, extendable to 18). Poll DGTR findings and CBIC customs notifications every 5 minutes; Claude reads each one and fires alerts for the pre-mapped tickers. Buy on a recommendation or notification; avoid or short on a termination, or when the finance ministry declines to impose the duty.
- **What kills it:** Duties the market already expects, small duty rates, illiquid producers, and rejections.

### 7. Circuit magnet

*Category B · daily · stocks with fixed price bands*

- **Why it works:** Near a price limit, buyers rush to get in before it locks and sellers hold back, so prices tend to speed toward the limit; a Taiwan study found this "magnet effect" toward the upper limit in high-frequency data (Cho, Russell, Tiao and Tsay, 2003). The exit is built in: once a stock locks at its upper limit, buyers queue there and you can sell to them at once.
- **How to run it:** Universe: non-F&O stocks in the regular EQ series with 5%, 10% or 20% bands and at least ₹2 crore daily turnover. Trigger: price in the last quarter of the band (above +3.75% on a 5% band, +7.5% on 10%, +15% on 20%), three straight 1-minute candles at twice the day's average minute volume, and shrinking sell quantity in the 5-level order book. Sell at the limit if it locks; exit if price falls back out of the trigger zone. Mirror it near the lower limit only for stocks you're allowed to short.
- **What kills it:** Operator stocks that stall just below the limit, wide spreads, and brokers barring intraday trades in band stocks. The workaround is to buy with full cash as delivery and sell the same day, which still counts as an intraday trade.

### 8. Pre-open overshoot fade

*Category B · daily · liquid stocks · new rule*

- **Why it works:** Since Sept 7, 2026, the 9:00–9:10 pre-open auction matches market orders first, accepts them only until 9:05, and closes at a random moment between 9:08 and 9:10 ([TradingQnA](https://tradingqna.com/t/sebi-introduces-closing-auction-session-cas-for-f-o-stocks-and-revises-pre-open-session/190558)). Retail market orders chasing overnight hype can push the opening print past fair value, and with no news behind it, that overshoot should unwind in the first 15 minutes. There's only a month of data under the new rule, so treat this as a hypothesis to test.
- **How to run it:** Record the pre-open indicative price and the buy and sell quantities every 30 seconds from 9:00 to 9:10. At 9:16, fade gaps of 2.5% or more where Claude finds no filing or news and the first 1-minute candle closes back toward the previous close. Stop beyond the 9:15–9:16 extreme; target half the gap or VWAP.
- **What kills it:** Real news, market-wide trend days, and shorts limited to your broker's list.

### 9. Crude shock radar

*Category C · several times a week now · oil-sensitive stocks*

- **Why it works:** Brent was about $103 at the end of September with US–Iran talks unresolved ([Kotak Neo](https://www.kotakneo.com/news/market-news/pre-market-1-october-2026-gift-nifty-muted-start/)), so oil headlines are hitting margins at oil marketers, paint makers, tyre makers and airlines, and helping upstream producers. MCX crude futures trade through Indian hours, and mid-cap oil users often reprice minutes after crude does.
- **How to run it:** Stream MCX crude through your broker's API as data only. Build a basket of oil users (short on spikes, long on drops) and producers (the reverse), each with its 5-minute beta to crude over 60 days. Trigger: crude moves at least 1.5% within 15 minutes and Claude confirms an oil-supply headline. Trade the members that have moved less than a third of their beta-implied move; exit on catch-up, after 90 minutes, or if crude gives back half its move.
- **What kills it:** Headline reversals (talks, ceasefires), government-set fuel prices muting the oil marketers' link, and liquid names that fast traders reprice instantly.

### 10. Square-off crush reversal

*Category B · daily · retail-heavy stocks · experimental*

- **Why it works:** Brokers auto-close leftover intraday positions with market orders at fixed times. For F&O stocks the staircase runs from 3:00 to 3:12 pm, before trading stops at 3:15; for other stocks it runs from 3:15 to 3:25, before the 3:30 close (see the rules table). Leftover positions are mostly losers held against the day's trend, so the forced orders should push price further in the trend's direction for a minute or two, then snap back.
- **How to run it:** Measure first: record 1-minute bars from 2:55 to 3:15 for F&O stocks and from 3:05 to 3:30 for others over 40 sessions, split by the day's direction and by delivery percentage (low delivery means heavy intraday trading). Trade only if the average dip-then-bounce clears 0.4%. The rule: in a stock down 3% or more on the day with a low delivery share, buy a drop of 0.5% or more inside a square-off minute with no news, and exit within 5–8 minutes (or in the closing auction for F&O stocks). Use a delivery (CNC) order with full cash so your own broker doesn't square you off.
- **What kills it:** An effect smaller than costs, thin final minutes, and brokers changing their times. It's my most speculative Tier 1 play, and my favourite one to test.

## Tier 2 — ranks 11–24

These work, but each needs a specific event, market mood or extra skill. The two filters (#12, #22) don't trade alone; they switch other plays on and off.

### 11. No-news gap fade

*Category D · daily*

- **How it works:** Gaps of 2–5% in liquid stocks with no filing or news (Claude checks) often half-fill by midday as overnight enthusiasm fades. Enter after the first 5-minute candle closes against the gap; stop beyond the opening extreme; target half the gap or VWAP.
- **What kills it:** News you missed, and market-wide gaps on global moves, which tend to hold.

### 12. Options-map regime switch (filter)

*Category E · daily*

- **How it works:** The Nifty option chain, read as data, shows where option sellers are positioned. With Nifty between big call and put open-interest walls and heavy open interest near the price, days tend to chop, so favour fades (#11, #13). When price breaks a wall with India VIX rising, favour breakouts (#2, #4). On expiry Tuesdays, prices can pin near the biggest strikes, as Ni, Pearson and Poteshman (2005) found on US expiry days.
- **What kills it:** Walls move during the day; treat it as a tilt, not a signal.

### 13. Retail-attention fade

*Category F · most days*

- **How it works:** Stocks that jump into the "most active" lists with no news draw late retail buyers, and heavy herding into Robinhood favourites was followed by negative returns (Barber, Huang, Odean and Schwarz, 2022). After 11:00, fade names stretched more than 2× ATR above VWAP back toward VWAP, where shorting is allowed.
- **What kills it:** Hidden news, short squeezes, and broker short limits.

### 14. 52-week and all-time-high breakout

*Category D · most days in uptrends*

- **How it works:** Traders anchor to the 52-week high and buy late once it breaks, and stocks near it tend to keep outperforming (George and Hwang, 2004). Buy the first break of the 52-week high after 9:45 on at least 3× relative volume, with a stop below the old high; exit at square-off.
- **What kills it:** Few breakouts in a falling market, and false breaks at the open.

### 15. Block-window absorption

*Category B · weekly*

- **How it works:** Block deals trade in two windows, 8:45–9:00 and 2:05–2:20, within 3% of a reference price and at a minimum of ₹25 crore ([SCC Online](https://www.scconline.com/blog/post/2025/10/09/sebi-notifies-revised-block-deal-framework-compliance-update-scc-times/)). When a seller fully exits at a discount (term sheets often leak the night before) and long-only funds take the shares, the opening dip often recovers by midday. Buy the first reclaim of VWAP after a block-led dip.
- **What kills it:** Partial sales with more supply to come; buyer names are published only after hours.

### 16. Morning margin-call flush

*Category B · after sharp falls*

- **How it works:** After a sharp fall, brokers sell clients' margin-funded (MTF) shares that weren't topped up, and can do so any time within 5 working days of the margin call ([NSE](https://www.nseindia.com/trade/members-faqs-margin-trading-facility)). With the MTF book near ₹1.3 lakh crore ([BCAJ](https://bcajonline.org/?p=61299)), quality mid caps can be dumped at the open 1–3 days after a big fall. Buy the first higher low after 10:00 in no-news names that fell far more than their beta; exit by square-off.
- **What kills it:** Real bad news, a crash that keeps going, and the lack of public stock-wise MTF data, so you infer the selling from price and volume.

### 17. Rumour-denial snap-back

*Category A · weekly*

- **How it works:** The 250 largest listed companies must confirm, deny or clarify a mainstream-media rumour that causes a material price move: the top 100 since June 2024, the rest since December 2024 ([Business Today](https://www.businesstoday.in/amp/markets/top-story/story/sebi-issues-new-guidelines-to-manage-stock-prices-impacted-due-to-rumours-430428-2024-05-21)). A stock that spiked on a "talks to acquire" story tends to give the spike back when the company files a denial, and a confirmation tends to extend it. Claude watches for "clarification on news item" filings and checks for a prior spike.
- **What kills it:** Vague replies ("no proposal at present") and few events per week.

### 18. Regulator hits

*Category A · weekly · short side*

- **How it works:** SEBI orders, RBI business restrictions on lenders, USFDA import alerts and warning letters, and Competition Commission actions appear on regulators' websites during market hours. Claude watches these pages, maps each entity to its ticker, and alerts you to short (where allowed) or exit.
- **What kills it:** Slow website updates, and companies disclosing first.

### 19. Business-update day reader

*Category A · monthly clusters*

- **How it works:** Many companies publish updates during market hours: automakers' monthly sales on the 1st, and banks', lenders' and retailers' quarterly updates in the first week after quarter-end. Claude compares each with the previous four periods and with peers, and alerts on the clearest surprises.
- **What kills it:** Large caps repricing instantly, and updates the market already expects.

### 20. Pump fade

*Category F · most weeks*

- **How it works:** Small caps hyped on Telegram or YouTube with no filing often fade after the first hour. Short a break of the first-hour low only if the stock is on your broker's short list and at least 4% below its upper price limit.
- **What kills it:** Upper-circuit locks (see Traps: a short you can't buy back goes to an exchange auction) and surveillance restrictions.

### 21. Pledge invocation and auditor exits

*Category A · rare · short side*

- **How it works:** When lenders invoke pledged promoter shares they often sell them in the market, and an auditor's resignation flags accounting risk. Both arrive as exchange filings during the day; short or exit on the filing.
- **What kills it:** Rarity, and weak stocks already pricing the risk.

### 22. Day-type classifier (filter)

*Category E · daily*

- **How it works:** Claude Code trains a model on five or more years of 5-minute data using first-45-minute features: gap, range against ATR, advance–decline ratio, share of Nifty 500 stocks above VWAP, VIX change, crude and US futures. It predicts trend or range days, which switches breakout plays or fade plays on.
- **What kills it:** Overfitting and regime changes; retrain every quarter and keep the model simple.

### 23. OFS-day convergence

*Category B · monthly*

- **How it works:** A seller using an offer for sale must announce the floor price by 5 pm the day before; non-retail investors bid on day one and retail investors on day two ([BSE](https://bseindia.com/Static/PublicIssues/aboutOFS.aspx)). Because buyers can get shares near the floor, the market price often drifts toward it on day one. Short early if the stock trades well above the floor, and cover as it converges.
- **What kills it:** Strong demand lifting the cut-off price, and short limits.

### 24. Metals and bullion radar

*Category C · weekly*

- **How it works:** Shanghai metal futures trade from 11:00 to 12:30 IST and MCX metals and gold trade all day, while metal producers and gold-loan lenders can reprice minutes behind. It runs on the same engine as #9, with a metals basket.
- **What kills it:** Liquid large caps that reprice instantly, and mixed effects: rising gold hurts jewellers' demand but lifts gold-loan collateral.

## Tier 3 — ranks 25–37

These are real ideas with one weakness that keeps them out of the top tiers: small moves, rare events or a hard build.

| # | Play | The idea | Why it's Tier 3 |
| --- | --- | --- | --- |
| 25 | ETF iNAV reversion | Buy an ETF trading clearly below its live iNAV and sell when the gap closes. Gold ETFs pay no STT; equity ETFs pay 0.025% on intraday sales ([Zerodha](https://support.zerodha.com/category/account-opening/charges-at-zerodha/articles/stt-etfs)). | Gaps are small, and market makers close most of them fast |
| 26 | First-hour to last-hour momentum | When Nifty's first half-hour move is large, trade NIFTYBEES the same way from 2:45 to 3:25. The first half-hour predicts the last in US data (Gao, Han, Li and Zhou, 2018), a pattern linked to option-hedging flows (Baltussen, Da, Lammers and Martens, 2021). | Small moves, and the closing auction changed how the last half-hour trades |
| 27 | IPO listing-day playbook | Issues above ₹250 crore list through a 9:00–10:00 pre-open, then trade with a 20% band from 10:00 ([Rupeezy](https://support.rupeezy.in/support/solutions/articles/21000005008-what-happens-on-an-ipos-listing-day)). Fade weak-subscription pops below the first 15-minute low; buy strong-subscription listings that reclaim the listing price. | Few samples, and smaller issues trade-for-trade for 10 days with no intraday |
| 28 | Flash-dip reversal | Buy no-news drops of 1.5% or more within 2 minutes in large caps once the order book refills; target half the drop. | Rare, and fast traders usually get there first |
| 29 | Strength in weakness | On red mornings, stocks holding green tend to lead the rebound; buy them when Nifty reclaims VWAP. | Popular, and weak on its own |
| 30 | Broker-note open drive | Big target-price changes from major brokers move the open, and recommendation changes drift for weeks (Womack, 1996). Trade the direction if the first 15 minutes hold it. | Widely watched; most of the move happens at the open |
| 31 | VWAP-algo footprint ride | Steady one-sided flow all morning in a large cap signals an institution working an order, and order flow is persistent (Lillo and Farmer, 2004). Ride it with a stop at VWAP. | Hard to detect, and it reverses when the order ends |
| 32 | VWAP first pullback | On a clear trend day, buy the first pullback to VWAP with a stop just beyond it. | Crowded, with small targets |
| 33 | Live concall listener | Transcribe in-session earnings calls live and alert on guidance changes before the market digests them. | A complex build, and few calls happen during market hours |
| 34 | Rebalance-day auction flow | On index effective days, buy additions in the morning and sell into the closing auction, where index funds buy at any price; reverse it for deletions. Next dates: Nov 30 (MSCI) and Dec 31 (factor indices). Use a delivery order, because intraday positions are squared off before the auction. | Only a few days a year |
| 35 | VIX regime sizing (*filter*) | Scale every play's risk by the median India VIX divided by the current VIX. | A sizing tool, not a signal |
| 36 | Asian-hours read-across | Japanese, Korean and Taiwanese releases land during the Indian morning; Suzuki Motor's results matter for Maruti Suzuki, for example. | Few clean links, and most of the move comes at the open |
| 37 | Macro-shock laggards | After in-session macro news, sector indices move first; buy the components that haven't caught up. | Rare events, and the catch-up is fast |

## Tier 4 — ranks 38–48

These are okayish at best: tiny edges, crowded setups or rare events. Use them as filters or skip them.

| # | Play | The idea | Why it's weak |
| --- | --- | --- | --- |
| 38 | Round-number magnets | Prices stall and cluster at round levels such as ₹500 or ₹1,000. | A tiny, unreliable edge |
| 39 | Failed-breakout reversal | Fade breakouts above yesterday's high that fail on falling volume. | Popular "trap" setups with little evidence |
| 40 | Iceberg detection | A best-price order that keeps refilling reveals a hidden large order; trade the break once it's filled. | Needs tick-level work for a small edge |
| 41 | NR7 and inside-day breakout | Trade breakouts after the narrowest daily range in seven days. | Classic and crowded; weak after costs |
| 42 | Series-migration day | Stocks moving out of trade-for-trade can be traded intraday again, so volume returns. | Rare, with no reliable direction |
| 43 | Expiry-Tuesday heavyweights | Nifty giants can pin near big option strikes on expiry day. | The effect lives mostly in options, and the closing auction now sets the settlement price |
| 44 | Same-time-of-day periodicity (*filter*) | A stock's return in a given half-hour tends to repeat at the same time on later days (Heston, Korajczyk and Sadka, 2010). | Worth a few basis points; use it only to time entries |
| 45 | European-open handover (*filter*) | Volatility can pick up when European markets open: 12:30 IST until Oct 23, then 13:30 IST from Oct 26. | Untested in India |
| 46 | Rupee shock to exporters | Sharp rupee moves feed into IT and pharma prices with a lag. | Daily rupee moves are usually too small |
| 47 | Ex-date euphoria fade | Retail excitement around bonus and split ex-dates fades. | Small and rare |
| 48 | Order-book imbalance scalping | The imbalance between bids and offers predicts the next few ticks (Cont, Kukanov and Stoikov, 2014). | High-frequency firms own it, and 0.15% costs kill it |

## A trading day

&#91;embedded content: trading day · 12 windows from 8:45 am to 3:35 pm\]

The forced flows sit at the edges of the day (#8, #10, #15, #34), while the filings lane that feeds my pick runs from the open until 3:00. European markets open at 1:30 pm from Oct 26.

## Intraday rules for October 2026

The closing auction changed the end of the day: F&O stocks stop trading at 3:15 pm, and brokers now square off intraday positions in them between 3:00 and 3:12. Check your own broker's times; they can change.

| Rule | What it says | Plays it shapes |
| --- | --- | --- |
| Pre-open auction (from Sept 7, 2026) | 9:00–9:05 market and limit orders; 9:05–9:10 limit orders only, closing at a random moment between 9:08 and 9:10; matching 9:10–9:12; market orders matched first; no stop-loss or iceberg orders ([TradingQnA](https://tradingqna.com/t/sebi-introduces-closing-auction-session-cas-for-f-o-stocks-and-revises-pre-open-session/190558)) | #8 |
| Trading hours | F&O stocks trade 9:15–3:15, then a closing auction sets their close (orders 3:20–3:30, random close 3:28–3:30). Other stocks trade until 3:30, and their close is the VWAP of 3:00–3:30 ([Zerodha](https://zerodha.com/z-connect/general/everything-you-need-to-know-about-closing-auction-session-cas)) | #10, #34 |
| Intraday square-off, F&O stocks | [Share.Market](https://www.share.market/support/home/trading-investment/closing-auction-session-cas/what-will-be-the-new-mis-auto-square-off-timings/) 3:00 · [Motilal Oswal](https://www.motilaloswal.com/learning-centre/2026/8/closing-auction-session-complete-faq-guide) 3:00 · [Fyers](https://fyers.in/notice-board/introduction-of-the-closing-auction-session-cas-as-per-sebi-guidelines/) 3:05 · [Angel One](https://www.angelone.in/knowledge-center/share-market/closing-auction-session-cas-meaning-timings-and-how-it-works) 3:10 · [Zerodha](https://zerodha.com/z-connect/general/everything-you-need-to-know-about-closing-auction-session-cas) 3:12 | #10, every exit |
| Intraday square-off, other stocks | Share.Market 3:15 · Fyers 3:20 · Zerodha 3:25 | #10, every exit |
| Shorting | Retail traders can short and buy back the same day in stocks on their broker's intraday list; institutions can't day trade at all ([TaxGuru](https://taxguru.in/sebi/framework-short-selling-securities-market.html)). If you can't buy back, for example in an upper-circuit lock, the exchange auctions the shares; with no sellers, close-out is at the higher of the highest price since your trade or 20% above the auction-day close ([Zerodha](https://zerodha.com/z-connect/trending/consequences-of-short-delivery-nse-bse)) | Every short |
| Intraday costs (Zerodha) | Brokerage 0.03% or ₹20 per order, whichever is lower; STT 0.025% on sells; NSE charges 0.00307%; SEBI ₹10 per crore; GST 18% on brokerage and charges; stamp duty 0.003% on buys ([Zerodha](https://zerodha.com/charges)) | All |
| ETF STT | 0.025% on intraday sells, 0.001% on delivery sells; gold ETFs are exempt ([Zerodha](https://support.zerodha.com/category/account-opening/charges-at-zerodha/articles/stt-etfs)) | #25, #26 |
| Results disclosure | Board-meeting outcomes within 30 minutes; XBRL within 24 hours ([LegalMantra](https://legalmantra.net/blog-detail/HOW-SHOULD-ONE-MANAGE-THE-INAUGURAL-BOARD-MEETING-REGARDING-THE-AUDITED-FINANCIAL-OUTCOMES-OF-A-PUBLICLY-LISTED-COMPANY)); September-quarter results are due by Nov 14 | #1, #3 |
| Block deals | 8:45–9:00 (reference: previous close) and 2:05–2:20 (reference: 1:45–2:00 VWAP); minimum ₹25 crore; within 3% of the reference; client names published after hours ([SCC Online](https://www.scconline.com/blog/post/2025/10/09/sebi-notifies-revised-block-deal-framework-compliance-update-scc-times/)) | #15 |
| IPO listing day | Special pre-open 9:00–10:00, limit orders only; trading from 10:00; 20% band for issues above ₹250 crore; smaller issues get a 5% band and trade-for-trade for 10 days ([Rupeezy](https://support.rupeezy.in/support/solutions/articles/21000005008-what-happens-on-an-ipos-listing-day)) | #27 |
| Offer for sale | Floor price by 5 pm the day before; non-retail bids on day one, retail on day two; at least 10% reserved for retail ([BSE](https://bseindia.com/Static/PublicIssues/aboutOFS.aspx)) | #23 |
| Your own algo | Up to 10 orders per second needs no exchange registration, but must run through your broker's API from a static IP mapped to your API key ([Zerodha](https://zerodha.com/z-connect/general/a-comprehensive-overview-of-nses-circular-on-the-new-retail-algo-trading-framework)), with a two-factor login every day ([Fyers](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026/)) | The alert bot |

## Build the alert bot

Start with alerts you act on by hand, and automate orders only after a play has proven itself live.

1. **Data feeds.** Use your broker's websocket for live prices and 5-level order books; Zerodha, Upstox, Dhan, Fyers and Angel One all offer APIs. Enable the commodity segment for MCX crude, metals and gold (#9, #24). Poll BSE and NSE announcements every 10–15 seconds (#1, #3, #17, #19, #21), PIB ministry RSS feeds every minute (#5), DGTR and CBIC pages every 5 minutes (#6), regulators' pages (#18), and NSE's pre-open and option-chain pages (#8, #12).
2. **Reference tables, built with deep research and refreshed monthly.** Theme baskets (#4), crude and metals baskets with betas (#9, #24), a company-name-to-ticker alias table (#5, #18), the DGTR pending-case table (#6), your broker's intraday and short lists, and the daily price-band file (#7).
3. **Engine, written with Claude Code.** One Python service with a module per play, a shared risk module (position size, daily loss cap, maximum open trades), and a log of every signal, taken or not, so you can test later.
4. **AI reading layer.** Claude reads PDFs and press releases and returns strict JSON, with null for anything not stated. It never estimates numbers.
5. **Alerts.** A Telegram bot sends one message per signal: side, entry, stop, exit time, the reason and the source link.
6. **Execution.** Place orders yourself at first. Automate later only through your broker's API, from your registered static IP, under 10 orders per second.
7. **Kill switches.** Stop for the day after losing 2% of capital or three trades in a row, and pause a play after a drawdown twice its backtest worst.

**Testing protocol**

1. Backtest each play on 2–5 years of 1-minute data, charging 0.15% per round trip for large caps and 0.4% for small caps.
2. Require at least 100 trades, profits in most years, and settings that work across a range rather than at one magic value.
3. Paper-trade for 2–4 weeks and compare the results with the backtest.
4. Go live at a quarter of full size for 30 trades, and scale up only if live results match.

**Deep-research prompts to start with**

```
Build a table of listed Indian defence companies: name, NSE symbol, main
products, top customers, share of revenue from the Ministry of Defence,
and the three most similar listed peers. Cite the annual-report page for
each row.
```

```
List every DGTR anti-dumping, countervailing and safeguard investigation
initiated since October 2025 that is still pending. For each: product,
countries, applicant companies named in the initiation notice, their
listed parent and NSE symbol, initiation date and 12-month deadline.
Link each notice.
```

```
For each company in this list, find every name variant that government
press releases use (full legal name, abbreviations, former names) and
map each one to its NSE symbol.
```

## Traps that blow up intraday accounts

Most intraday blow-ups come from a few repeated mistakes, not from bad strategies.

- **Shorting near the upper limit.** If the stock locks at its upper circuit, you can't buy back; the shares go to an exchange auction, and close-out can cost 20% above the close or more.
- **Buying near the lower limit.** If it locks at the lower circuit, you can't sell, and the position can roll into an overnight delivery with gap risk.
- **Trading stocks that block intraday.** Trade-for-trade and some surveillance (ASM/GSM) stocks don't allow intraday trades; filter them out before an alert fires.
- **Over-trading.** SEBI found that 80% of individuals making over 500 intraday trades a year lost money.
- **Market orders in the first minute or in thin stocks.** That's when spreads are widest; use limit orders.
- **Averaging down and revenge trades.** One stop-loss is a cost; doubling down turns it into a blow-up.
- **Leaving exits to your broker's auto square-off.** You get whatever price the busiest minutes of the day give you.
- **Trusting an AI number without checking it.** Open the filing line behind every alert before you place the order.
- **Tips and "leaks".** Paid Telegram calls usually mean someone is selling to you, and trading on non-public results or orders is insider trading.

## Sources

Academic studies in the cards are cited by author and year from general knowledge, not from pages opened for this doc.

- [SEBI study on individual intraday traders (Motilal Oswal summary)](https://www.motilaloswal.com/learning-centre/2024/7/sebi-study-reveals-key-insights-on-individual-intraday-traders-in-india)
- [SEBI short-selling framework (TaxGuru)](https://taxguru.in/sebi/framework-short-selling-securities-market.html)
- [Zerodha charges](https://zerodha.com/charges)
- [STT on ETFs (Zerodha)](https://support.zerodha.com/category/account-opening/charges-at-zerodha/articles/stt-etfs)
- [Closing auction session and square-off times (Zerodha)](https://zerodha.com/z-connect/general/everything-you-need-to-know-about-closing-auction-session-cas)
- [New intraday square-off timings (Share.Market)](https://www.share.market/support/home/trading-investment/closing-auction-session-cas/what-will-be-the-new-mis-auto-square-off-timings/)
- [Closing auction FAQ (Motilal Oswal)](https://www.motilaloswal.com/learning-centre/2026/8/closing-auction-session-complete-faq-guide)
- [Closing auction notice (Fyers)](https://fyers.in/notice-board/introduction-of-the-closing-auction-session-cas-as-per-sebi-guidelines/)
- [Closing auction explained (Angel One)](https://www.angelone.in/knowledge-center/share-market/closing-auction-session-cas-meaning-timings-and-how-it-works)
- [Closing auction and revised pre-open session (TradingQnA)](https://tradingqna.com/t/sebi-introduces-closing-auction-session-cas-for-f-o-stocks-and-revises-pre-open-session/190558)
- [Consequences of short delivery (Zerodha)](https://zerodha.com/z-connect/trending/consequences-of-short-delivery-nse-bse)
- [Retail algo framework overview (Zerodha)](https://zerodha.com/z-connect/general/a-comprehensive-overview-of-nses-circular-on-the-new-retail-algo-trading-framework)
- [Retail algo framework from April 1, 2026 (Fyers)](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026/)
- [Board-meeting outcome disclosure timelines (LegalMantra)](https://legalmantra.net/blog-detail/HOW-SHOULD-ONE-MANAGE-THE-INAUGURAL-BOARD-MEETING-REGARDING-THE-AUDITED-FINANCIAL-OUTCOMES-OF-A-PUBLICLY-LISTED-COMPANY)
- [A Profitable Day Trading Strategy for the U.S. Equity Market (Concretum Group)](https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/)
- [Stocks-in-play opening-range rules (CXO Advisory)](https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/)
- [Borosil rises on DGTR recommendation (Business Today)](https://www.businesstoday.in/markets/trending-stocks/story/borosil-shares-rise-amid-market-crash-today-heres-why-558209-2026-09-28)
- [Pre-market, Oct 1, 2026 (Kotak Neo)](https://www.kotakneo.com/news/market-news/pre-market-1-october-2026-gift-nifty-muted-start/)
- [Revised block deal framework (SCC Online)](https://www.scconline.com/blog/post/2025/10/09/sebi-notifies-revised-block-deal-framework-compliance-update-scc-times/)
- [Margin trading facility FAQ (NSE)](https://www.nseindia.com/trade/members-faqs-margin-trading-facility)
- [Margin Trading Facility in India (BCAJ)](https://bcajonline.org/?p=61299)
- [Rumour verification framework (Business Today)](https://www.businesstoday.in/amp/markets/top-story/story/sebi-issues-new-guidelines-to-manage-stock-prices-impacted-due-to-rumours-430428-2024-05-21)
- [Offer for sale mechanism (BSE)](https://bseindia.com/Static/PublicIssues/aboutOFS.aspx)
- [IPO listing day (Rupeezy)](https://support.rupeezy.in/support/solutions/articles/21000005008-what-happens-on-an-ipos-listing-day)
- [Magnet effect of price limits, Cho et al. 2003 (IDEAS/RePEc)](https://ideas.repec.org/a/eee/empfin/v10y2003i1-2p133-168.html)

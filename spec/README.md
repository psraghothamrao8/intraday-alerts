# Intraday Alert Bot: design spec

This folder is the full design for an intraday alert system for Indian cash stocks. It's written so a coding model can build it task by task without needing this conversation.

- **Owner:** the user (manual trader, India)
- **Source of strategy ideas:** [`../intraday.md`](../intraday.md), the "Intraday Cash Playbook" (48 ranked plays)
- **Spec date:** 2026-10-08. Market rules are as of October 2026; the closing auction and new pre-open are live.

---

## What the system does, in one paragraph

A Python engine runs on the user's Windows PC during market hours. It watches BSE/NSE company filings and live prices, runs **four strategies**, and sends a **push notification to the phone** when to buy and when to sell (or short and buy back), with a strength score out of 10. It sends one notification to enter and one to exit, and states a stop level only where the strategy needs one. A **GitHub Pages** site is the dashboard and the place where the phone subscribes to notifications. The user places every order by hand; the bot never trades.

## The four strategies (playbook numbers in brackets)

| ID | Strategy | Why it's here | Fires | Side |
|---|---|---|---|---|
| **S1** | Results-Hour Reader (#1) | The pick I like most: an AI reads results PDFs filed during market hours | Many times a day in results season (now to Nov 14) | Mostly long |
| **S2** | Stocks-in-play opening-range breakout (#2) | Best-evidenced mechanical play; fires every day | 09:20–11:00 daily | Both |
| **S3** | Filing Flash: orders and buybacks (#3) | Same engine as S1, so it works all year; edge = materiality, not speed | Most days | Long |
| **S4** | Square-off crush reversal (#10) | The one I'm most curious about. **Research mode first**: it measures, then alerts only if the data says so | 15:00–15:25 daily | Long (delivery/CNC) |

The four fire at different times of day, so their results aren't tied together. See [02_strategies.md](02_strategies.md) for why these four and not the others.

## Read in this order

| File | What's in it |
|---|---|
| [01_architecture.md](01_architecture.md) | Decisions, what runs where, why GitHub Pages alone can't do it, machine/LLM choice, security |
| [02_strategies.md](02_strategies.md) | Exact rules for S1–S4: filters, triggers, scoring, strength, notifications |
| [03_exits_and_stops.md](03_exits_and_stops.md) | **Stop-loss redesign.** Why stops felt bad and the three-layer exit that replaces them |
| [04_notifications_and_dashboard.md](04_notifications_and_dashboard.md) | Web Push from GitHub Pages, notification texts, encrypted dashboard, watchdog |
| [05_data_sources.md](05_data_sources.md) | BSE/NSE endpoints (verified live on 2026-10-08), broker API interface, reference data, costs |
| [06_backtest_and_calibration.md](06_backtest_and_calibration.md) | How each strategy is tested before money goes in; how "strength x/10" is calibrated |
| [07_build_plan.md](07_build_plan.md) | **Task list for the coding model**, in order, each with acceptance tests |
| [08_config_reference.md](08_config_reference.md) | Full `config.yaml` and `.env` reference: every tunable number in one place |

## How to use this with a coding model

1. Do **Task 0** in [07_build_plan.md](07_build_plan.md) yourself (accounts, keys, repo). It takes about 30 minutes and involves secrets, so the model shouldn't do it.
2. Give the model the repo with this `spec/` folder and [`AGENTS.md`](../AGENTS.md). Say: *"Implement Task 1 from spec/07_build_plan.md. Stop when its acceptance tests pass."*
3. Go one task at a time. Check the acceptance test yourself before starting the next task.
4. **Never paste secrets into a chat with the model.** The code reads them from `.env` on your PC.

## Timeline that matters

- September-quarter results run until **Nov 14, 2026**, and the peak is late October to early November. S1 is most useful now, so Tasks 1–4 come first.
- S4 needs about 40 sessions of data before anyone can judge it. Its data collector (Task 2.6) is tiny and should start running as early as possible.
- Every strategy goes **backtest → 2–4 weeks paper → live at quarter size**, as the playbook says. Paper trading S1 through this season is a valid forward test even if it starts late.

## Non-goals (v1)

- No automatic order placement. That would need a static IP and the broker's algo registration under SEBI's retail-algo framework, and it's risky.
- No options or futures trading. Futures/options data may be read as signals only.
- No 24/7 operation. No local GPU/LLM.
- No strategies beyond S1–S4. Phase-2 candidates are listed at the end of [02_strategies.md](02_strategies.md).

> This is software design, not investment advice. I'm not a licensed advisor. Every strategy here is a hypothesis until the backtest and paper trading support it.

# Rules for the coding model

You are building the intraday alert bot described in `spec/`. Start with `spec/README.md`, then do the task you were given from `spec/07_build_plan.md`.

## How to work
1. **One task at a time.** Do only the task you were asked for. Stop when its acceptance tests pass, and report what you did and how you tested it.
2. **The spec is the source of truth.** If something in the spec is wrong or impossible (for example an endpoint marked 🔎 doesn't work), don't silently improvise. Make the smallest reasonable fix, **edit the spec file to record it**, and mention it in your report.
3. **Every number comes from `config.yaml`.** No magic numbers in strategy, exit or risk code.
4. **Time comes from `core/clock.py`.** Never call `datetime.now()` directly. Replay and tests depend on this.
5. **Live and backtest share code.** Never write a second copy of a strategy rule for the backtest.
6. **Write tests with the code.** Put fixtures in `tests/fixtures/`. Tests must not need the internet unless they're marked `@pytest.mark.live` or `@pytest.mark.live_llm`.
7. **Fail safe.** On any error in data, the LLM or validation: no signal, a log line, and a `filings.status`. Never guess a number. Never crash the main loop; catch exceptions per component.

## Hard rules
- **Never place orders.** The system only sends notifications.
- **Never read, print, log or commit secrets.** Load them from `.env` via `engine/config.py`. Never ask the user to paste a secret into chat. Never hardcode tokens or keys.
- `.env`, `secrets/`, `data/`, `*.pem` and `*.db` must stay git-ignored.
- Exchange websites (BSE/NSE) must be called through `data/http.py` (curl_cffi, Chrome impersonation, polite rates). Don't add faster polling.
- Claude API: use the official `anthropic` Python SDK with the pattern in `spec/01_architecture.md` §5. The model ID comes from `config.yaml` (`claude-opus-5-5` default, `claude-haiku-5-5` optional). Don't set `temperature`; don't use assistant prefill.
- Dashboard (`docs/`): plain HTML/CSS/JS, no frameworks, no build step, no CDNs.

## Stack
Python 3.12 on Windows 11 · asyncio · SQLite (WAL) · pandas + pyarrow Parquet · pydantic v2 · pytest.
Shell commands must work in PowerShell (the user's default shell).

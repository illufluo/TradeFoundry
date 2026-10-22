# TradeFoundry — Roadmap and Acceptance Criteria

## Objective
Own the entire autonomous research pipeline while keeping **real funds out of scope**. Canonical execution data: OKX BTC-USDT-SWAP and ETH-USDT-SWAP. Other providers, including CoinGlass, Etherscan and other venues, are optional point-in-time research feature sources. A research model proposes, tests, learns from failures, and publishes reports within strict budgets. Grok Bot is optional. Feishu is the preferred replaceable Chinese-mainland-accessible interface.

## Delivery phases

### P0 — Skeleton and offline vertical slice
- Python package, pyproject.toml with pinned dependencies/lock or equivalent, CLI, configs, .env.example, .gitignore, tests, CI, README setup.
- Synthetic historical OKX-like fixtures, one baseline strategy, deterministic backtest, saved SQLite experiment, Plotly HTML report, CLI invocation.
- Progress document and no-credentials runnable demonstration.
- Acceptance: clean environment can reproduce results offline with one command; tests pass.

### P1 — OKX historical market data
- Reliable REST pagination/backfill and incremental update for BTC-USDT-SWAP and ETH-USDT-SWAP, immutable/raw snapshots where practical, normalized Parquet, metadata and dedupe/checkpoint.
- First market data: 1h/4h/1d historical OHLCV derived consistently from exchange data; funding and mark/index inputs as separate datasets when genuinely obtainable; no unsupported promises of full history. Document historical availability. Explicit UTC candle boundaries, completed candles, gaps, duplicate handling, unit conversions and contract metadata.
- Acceptance: historical fetch resume, temporal checks and repeatability proven with deterministic mock APIs; real public-network smoke test only when reachable.

### P2 — Trustworthy strategy and costs
- Versioned declarative strategy proposal schema plus example trend and funding/OI-inspired proposals when data is actually available.
- Event-aware accounting with positions, fee, rebate, funding, equity, drawdown, trade ledger; maker/taker per fill, execution cost model, fee sensitivity; conservative fallback execution. Strong unit tests for fees and timestamps.
- Baselines and multi-window/timeframe research, including disjoint and rolling walk-forward splits; do not claim 12 nested backtests are independent.
- Acceptance: known-value golden tests for P&L, fees, rebate and funding; declared limitations of candle execution.

### P3 — Fully automatic research pipeline
- Replaceable standard LLM API adapter + optional Grok proposal intake (e.g. validated file/inbox), no requirement for Grok credentials. Bounded job runner with SQLite lifecycle, retries, budgets and resumability; proposal -> validation -> strategy -> experiment -> ranking -> follow-up proposal.
- Isolate untrusted AI-generated code or initially prohibit arbitrary code and use restricted DSL. Final holdout sealed until a candidate is frozen; protect it against repetitive tuning. Capture failed and rejected proposals.
- Acceptance: offline/mock model proposes >=10 candidate hypotheses, system evaluates and records every attempt and generates a summary without manual clicks; restart can resume.

### P4 — Reporting and Feishu messaging
- Daily digest, critical alerts, status, named experiment reports, side-by-side comparisons, interactive Plotly HTML plus image/fallback as possible; optional Feishu application bot integration with allowlisted users and bounded commands. No arbitrary shell execution.
- Acceptance: local mock notification path works without credentials, and optional real bot end-to-end works when configured.

### P5 — Continuous paper trading
- Exchange-public-live-data paper execution and/or OKX demo mode ONLY, separate execution service/job with independent risk caps, heartbeat, recovery and accounting reconciliation. Verify simulated modes against exchange docs and ensure real execution endpoints are excluded.
- Acceptance: multi-day forward test records intended and simulated fills; restart recovers positions; no capability to send a live order.

## Not in V1
Real orders or live account credentials, withdrawals, precision L2 maker queue simulation, automatic purchases, production server deployment, paid data subscriptions, full custom frontend, massive microservice infrastructure.

## Scientific and safety gates
- Define availability timestamps and prevent lookahead on every joined source.
- Fixed controlled fee profile: maker 0.016%, taker 0.045%, rebate 20% for both; separately track cash rebates and gross deducted fees.
- Include conservative slippage/spread, delayed fill sensitivity, funding settlement, position and leverage risk; state model limitations.
- Multiple hypotheses correction / strategy search audit, walk-forward validation, final one-shot holdout check, then forward paper results before considering live trading outside this roadmap.
- Every experiment has strategy source hash, data provenance/hash, code version, parameters, time splits, metric formulas, and cost model version.
- Default safe: no live orders, no money use, no credential leakage.

## Definition of done for any phase
Runnable code, deterministic tests, reproducible examples, honest limitations, docs updated, progress updated and pushed to GitHub. Do not substitute architecture prose for functioning code.

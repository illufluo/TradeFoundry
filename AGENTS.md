# TradeFoundry Agent Instructions

Read README.md, docs/ROADMAP.md, and docs/PROGRESS.md at the start of every work session. Work incrementally, test before committing, and update docs/PROGRESS.md after each meaningful milestone and at session end. This file is durable guidance; progress is mutable.

## Mission and scope
Build an autonomous, auditable crypto quantitative research laboratory in Python. Only OKX BTC-USDT-SWAP and ETH-USDT-SWAP may be simulated as trade instruments. Other assets/venues and providers may be used solely as research features. Focus on historical research, validation, reporting, and *paper* trading. Never activate live capital trading, enable withdrawals, acquire credentials, or make paid purchases/subscriptions.

## Ownership and interfaces
- Core Python program owns scheduling, authoritative experiments, data, scoring, cost rules, and research state. External agents (Grok Bot, Codex, other LLMs) submit proposals through validated structured schemas; they do not own the evaluator.
- Feishu is a replaceable chat adapter; the bot may report, query, pause/resume bounded research, but must not execute arbitrary shell commands.
- No hard dependency on Grok Bot or Feishu credentials for local smoke tests. Provide .env.example and fixture-driven demonstrations.
- Favor a simple single Python codebase, SQLite metadata, Parquet market data, Plotly HTML charts. Introduce complexity only when justified.

## Research and data integrity
- Canonical simulated execution uses OKX instrument-specific market data and UTC timestamps. Handle exchange bar conventions explicitly, track data provenance, timestamp, availability timestamp, update time, and quality checks. Use only *closed* bars. Check instrument contract metadata and point-in-time eligibility.
- Download paginated REST history within documented limits, rate limit, retry with bounded backoff, checkpoint, dedupe, and resume; never silently manufacture missing candles or fake history. Test with deterministic fixtures without network.
- Initially use exchange OHLCV for 1h/4h/1d, with lower timeframe bars when justified. Mark/index/funding data are separate from trade prices. Funding applies only at actual settlement events for positions then held. OI and on-chain signals only if truly available historically at the decision time.
- User's nominal OKX fees: maker 0.00016, taker 0.00045; 20% rebate on each, conditional on rebate actually qualifying. Net maker 0.000128, net taker 0.00036. Book original fee and later rebate separately, by actual filled notional. Record bids/asks, slippage, partial fills, funding, leverage, margins, mark-price liquidation approximations as applicable. Don't claim precise maker queue simulation from candles. Default to conservative taker execution with clearly disclosed assumptions.
- Prevent look-ahead and data leakage. Segregate discovery, validation, final holdout; enforce holdout access programmatically and log each access. Freeze strategy artifacts and parameters before final test; do not repeatedly optimize on revealed holdout results. Record all attempts, including failures, with data, code, parameter, cost model, and run versions. Benchmark against buy-and-hold and simple baselines; assess trade counts, exposure, drawdown, robustness, sensitivity and multiple testing.
- Never claim profit, statistical significance, or production-readiness without evidence.

## Safety and engineering
- No live trading calls, no live trading keys, no withdrawal permission; simulated trading must be explicit and separate from live exchange access. Disable any live-order path structurally, not just via a bool.
- Treat model-generated strategies and external inputs as untrusted. Prefer a declarative DSL or strict function contract. If running generated Python, use an isolated process/container with CPU/time/memory/file/network restrictions, and without access to credentials, evaluator code, final holdout, or writable canonical data. Python language-only sandboxing is not sufficient.
- Never let generated code modify the evaluation rules, cost model, risk limits, official experiment records or test data. Test deterministic accounting invariants and hostile input cases.
- Secrets from environment/secret manager only; never commit actual keys, .env, data dumps, private chat content, or reports containing sensitive values. Maintain .gitignore.
- Resource ceilings: configurable LLM cost, API requests, experiments, time, memory and disk. Stop safely on budget exhaustion. Scheduler jobs must be idempotent/recoverable; alerts for failures and stalled processes.
- Keep dependencies modest and pinned/locked; include formatting, linting, type checking where practical, unit/integration tests, user docs and runnable CLI examples.
- Do not deploy, rent a server, initiate third-party purchases, or spend money without explicit approval.

## Git and progress
- Make meaningful, small commits on a feature branch; push to origin if authenticated. Do not force-push or overwrite unrelated changes. Prefer a PR for review over directly changing main.
- Maintain docs/PROGRESS.md as the latest truthful current state. It may be rewritten/reorganized; preserve short milestone and blocker history. Include UTC timestamp, active phase, done/in progress/not started, commands executed with outcomes, commits/branch/PR links, outstanding risks, and next concrete steps.
- Before ending, run whatever checks are available, write candid limits, update PROGRESS.md, commit, and push. If push fails, explicitly disclose why. Do not label unimplemented code complete.

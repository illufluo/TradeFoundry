# TradeFoundry

An autonomous, auditable AI-assisted quantitative research laboratory focused on OKX BTC-USDT-SWAP and ETH-USDT-SWAP.

Current phase: research and paper trading only. No live orders or real-capital execution.

## Start here

1. Read AGENTS.md for permanent coding and safety rules.
2. Read docs/ROADMAP.md for specifications and delivery phases.
3. Read docs/PROGRESS.md for the current implementation state.
4. Give Codex the task in docs/CODEX_START.md.

Documentation starts before the implementation. The repository is not yet a functioning trading system.

## Working principles

- OKX market and instrument data are the canonical basis for simulated fills and P&L.
- External data (CoinGlass, on-chain data and other venues) may enrich research signals, with point-in-time availability enforced.
- Research may operate autonomously within resource budgets, but must not place live orders, access exchange live trading credentials, or subscribe to paid services.
- Experiment history must be reproducible; unsuccessful experiments matter too.
- Feishu and Grok Bot are optional integration surfaces, not dependencies of the core research engine.

# Codex Start — Build TradeFoundry

You are the lead engineer for TradeFoundry, the private repository illufluo/TradeFoundry. The objective is to IMPLEMENT a working autonomous AI-assisted quantitative research laboratory, not merely write a plan.

First:
1. Inspect the actual repository and read AGENTS.md, docs/ROADMAP.md, and docs/PROGRESS.md fully. These documents are authoritative. Do not assume components exist.
2. Create a feature branch, preserve existing work, implement P0 as a fully runnable offline vertical slice with deterministic tests and report output. Execute tests and show their results.
3. Keep moving through P1–P4 in order as far as tools, runtime, dependencies, budgets and permissions allow. Use mock adapters and fixtures for providers not configured. P5 paper-only must be strictly isolated and comes after validation.
4. At every milestone update docs/PROGRESS.md with verified progress, test commands/results, blockers and next actions. Make small commits and push to GitHub; open a PR where permissions permit. Never claim a push, test, data download, or integration worked unless confirmed.
5. End by reporting what ACTUALLY runs, what remains unimplemented, which commands reproduce the demonstration, and a GitHub branch/PR/commit reference. Do not ask me to repeat constraints already present. Avoid excessive dependencies and don't spend money.

Core requirements: OKX BTC-USDT-SWAP and ETH-USDT-SWAP canonical trade and P&L data, flexible external research datasets, deterministic conservative fee/funding/slippage accounting (raw maker 0.016%, taker 0.045%, 20% rebate both), no lookahead, independent sealed out-of-sample evaluation, all experiment attempts recorded, automated model-driven proposal/evaluate/report cycle, Plotly reports, Feishu optional bot, Grok optional proposal adapter, later simulated-only trading. AI-generated code must be sandboxed or replaced by a safe restricted strategy schema.

CRITICAL: NO REAL-MONEY TRADING, NO LIVE EXCHANGE ORDER ACTIONS OR CREDENTIALS, NO PAID API/SUBSCRIPTIONS. External AI and chat services must be optional; offline mock demos and tests must always run without them.

Start implementing now, not just planning.

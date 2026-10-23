# TradeFoundry

一个面向 **OKX BTC/ETH USDT 永续合约**的 AI 自动化量化研究项目。

目标是让 AI 自主提出交易假设，系统自动完成策略实现、历史回测、统计验证、记录、可视化报告和模拟交易。第一版通过命令行与本地报告查看状态，不依赖外部聊天机器人。**当前项目不涉及真实资金交易。**

## 从这里开始

- [AGENTS.md](AGENTS.md)：**唯一的项目需求与开发规范**，包含架构原则、风险边界和分阶段验收要求。
- [PROGRESS.md](PROGRESS.md)：**当前真实进度**，Codex 每次工作都应更新，可按需修改或重组。

使用 Codex 时，只需让它阅读以上两个文件并从未完成的任务继续开发。不要把尚未实现的功能写成已完成。

## 项目边界

- 交易标的仅限 OKX 的 `BTC-USDT-SWAP`、`ETH-USDT-SWAP`；模拟成交与盈亏优先基于 OKX 相应市场的数据。
- 研究数据不限来源，可逐步增加 CoinGlass、链上、其他交易所等历史特征数据。
- 在不动用真实资金、不产生未经批准的费用的前提下，尽量实现全自动研究。
- 第一版不默认接入 Grok Bot、飞书或其他聊天平台。AI 研究使用可替换的标准 LLM API；未配置时使用模拟模型验证流程。
- 未来可让 Grok Bot 直接承担聊天、报告解释和受控研究指令，不必同时开发飞书机器人。核心研究程序保持独立。

## 安装与离线演示

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。首次安装需要下载免费依赖；完成安装后，演示和测试均无需网络、账号或密钥。

```bash
uv sync --locked --extra dev
uv run --no-sync tradefoundry demo
```

命令会输出实验编号、指标和报告绝对路径，并在 `artifacts/` 中生成 SQLite 数据库和内嵌 Plotly 的独立 HTML。浏览器直接打开报告即可离线查看净值、基准对照、手续费敏感性和可复现元数据。重复运行相同代码和输入会得到相同指标及实验编号。

```bash
# 另一个允许标的的固定夹具
uv run --no-sync tradefoundry demo --instrument ETH-USDT-SWAP
# 可选成本及输出配置；默认不确认返佣可得
uv run --no-sync tradefoundry --config config.example.toml demo
# 查询、重新导出已保存报告
uv run --no-sync tradefoundry experiments
uv run --no-sync tradefoundry report <实验编号> --output artifacts/export.html
# 检查
uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
```

输出目录可通过 `demo --output <目录>` 修改。`experiments` 和 `report` 的 `--db` 参数支持其他数据库路径。配置使用严格校验的 TOML，未知字段或非法数值直接拒绝；项目不读取 `.env`，也不接收任何交易密钥。

## 当前模型口径

- 随包提供 240 根固定合成 1h K 线，BTC/ETH 使用演示用合约单位，**不是真实 OKX 历史数据或当前合约规格**。数据版本由完整内容哈希标识。
- 策略为受约束的均线规则，对照为买入持有。信号只看 `available_at <= 当前开盘时间` 的此前已收盘 K 线；最后一根预定收盘平仓。只做多、无杠杆、按整数张数模拟，资金和仓位均以 USDT 计。
- Taker 原始费率 0.045%，Maker 原始费率 0.016% 仅作配置预留，**没有 Maker 撮合**。默认按原始手续费扣款；只有 `rebate_confirmed = true` 时才生成 20% 应收返佣，并至少延后 1 小时到账（默认 24 小时）。对应净费率 0.036% / 0.0128% 仅在返佣确实可得时成立。未到账返佣不计现金和净收益。
- 不利成交价格使用半价差加滑点；初版假设小额 Taker 全额成交，未模拟盘口、部分成交、资金费、标记价、保证金或强平。期末权益为现金加持仓收盘估值；该实现只是无杠杆研究近似。
- 最大回撤包含初始资金点；净收益以已到账权益计算。Sharpe 使用逐 K 线收益、样本标准差、365 天年化且无无风险利率；零波动时为 `null`。成交笔数与完整买卖次数分别记录；持仓暴露为持仓 K 线占比。手续费敏感性重新运行两倍原始费率模型。
- SQLite 保存输入行情、来源/哈希、策略参数/哈希、完整成交/权益/返佣明细、成本及指标版本和运行代码提交（未提交代码标记 `-dirty`）。当前属于研发演示，未做样本外、封存测试及统计显著性筛选，不能据此宣称盈利。

阶段进展及尚未实现的能力见 [PROGRESS.md](PROGRESS.md)。

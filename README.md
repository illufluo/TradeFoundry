# TradeFoundry

一个面向 **OKX BTC/ETH USDT 永续合约**的 AI 自动化量化研究项目。

目标是让 AI 自主提出交易假设，系统自动完成策略实现、历史回测、统计验证、记录、可视化报告和模拟交易。第一版通过命令行与本地报告查看状态，不依赖外部聊天机器人。**当前项目不涉及真实资金交易。**

## macOS 首次 OKX 模拟盘接入

Codex 已实现签名、UTC 校时、站点选择、只读权限检查、账户字段转换、错误提示、真实公共行情下载和离线 Mock。你无需写代码；你需要亲自在 OKX 网站创建模拟盘 Key，并在本地填写三个凭证。

### 1. 安装环境（在“终端”执行）

已有本项目目录时直接进入；尚未下载时执行 `git clone https://github.com/illufluo/TradeFoundry.git`。本功能须在对应 PR 合并后的版本，或审查分支上使用。

```bash
cd ~/TradeFoundry
# 已安装 uv 可跳过以下两行；这是 uv 官方免费安装器
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv sync --locked --extra dev
uv run --no-sync tradefoundry start --offline
```

uv 会按项目的 `.python-version` 准备 Python 和锁定依赖。首次安装需要网络，完成后离线模式无需网络和账号。最后一条命令输出 `mode: offline_mock`、`account_connected: false` 和合成行情报告路径；它仅表示本机演示正常，**不表示真实模拟盘已连接**。

### 2. 在 OKX 网站亲自创建 Key

1. 登录自己的 OKX 账户，进入 **交易 → 模拟交易**，确认页面显示模拟环境；按页面提示完成模拟账户初始化。
2. 在模拟交易个人中心/API 页面选择 **创建模拟交易 API Key**，只勾选 **Read/读取**。不要使用实盘 API 管理页面创建的 Key，不勾选 Trade 或 Withdraw。
3. 保存 API Key、Secret Key，以及自己设置的 Passphrase（不是登录密码）。如果绑定 IP，填写本机实际访问 OKX 的出口 IP；网络变化后需在网站更新白名单。
4. 确认账户注册站点。全球站选择 `global`；注册于 `app.okx.com` 的美国/澳洲账户选择 `us`；注册于 `my.okx.com` 的欧洲账户选择 `eea`。按实际站点选择，不自动跨站试探密钥。特定站点若不提供 BTC/ETH 永续或模拟账户，该能力会明确失败，不绕过站点限制。

网页菜单名称可能随语言变化；官方入口说明见 [OKX Demo Trading](https://www.okx.com/docs-v5/en/#overview-demo-trading-services)。本程序严格只支持 Read；若网页无法创建仅 Read 的模拟盘 Key，请先向 OKX 确认，不能用开启 Trade 代替。

### 3. 填写本地配置

```bash
# 仅第一次执行复制；已有 .env 时不要重复覆盖
cp -n .env.example .env
chmod 600 .env
open -e .env
```

在编辑器里替换这三个值并保存，不要粘贴到聊天、Shell 命令参数或截图中：

```dotenv
OKX_DEMO_API_KEY=你的模拟盘APIKey
OKX_DEMO_SECRET_KEY=你的模拟盘SecretKey
OKX_DEMO_PASSPHRASE=创建Key时设置的Passphrase
OKX_SITE=global
OKX_TIMEOUT_SECONDS=15
```

填写时使用普通英文引号或不加引号。配置支持 `.env` 的 `KEY=VALUE`、整行注释和配对引号；不执行 Shell、不作变量替换。环境变量中同名字段优先于 `.env`。其他目录的配置可通过 `--env-file /绝对路径/.env` 选择。

`.env` 已加入 Git 忽略规则。程序不打印凭证/签名，不保存私有原始响应，不把账户快照写进数据库或 HTML；余额和目标合约持仓只在当前终端显示，请自行保护终端记录。公共行情和研究产物可正常保存。

### 4. 启动并检查结果

```bash
uv run --no-sync tradefoundry start
open artifacts/start/market.html
```

正常输出包括 `account_connected: true`、`permission: read_only`、模拟账户模式、USD 折算总权益、USDT/BTC/ETH 余额、BTC/ETH 永续持仓（张数），以及 `market_ready: true`。没有持仓时列表为空属于正常情况。账户检查不要求设置杠杆或修改账户模式。

默认检查最近完整的 7 天 1h 行情，收盘边界额外留出一小时。质量结果含两个标的的 `rows`、`expected_rows`、`missing_count` 和 `complete`；文件位于 `artifacts/start/quality.json`，公共 Parquet 位于 `artifacts/start/warehouse/`。当前市场 HTML 展示真实合约价格曲线与质量信息，**不是完整可信历史回测或可盈利证明**。

```bash
# 分开验证账户与公开市场，排查问题时使用
uv run --no-sync tradefoundry start --account-only
uv run --no-sync tradefoundry market-check --site global --days 1
# 完整离线测试与检查
uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
```

退出码：`0` 表示所请求步骤成功，`2` 表示配置/账户/本地执行失败，`3` 表示账户可能已连接但公共数据不完整。后者会保留账户成功信息及市场失败说明；不要把“账户成功”误认为“研究数据完整”。

### 常见错误

| 提示 | 你需要做的操作 |
|---|---|
| 凭证缺失/格式错误 | 确认 `.env` 已保存且不再含 `your_...` 占位值，三项来自同一个模拟盘 Key |
| 环境不匹配 | 在模拟交易页面重新创建 Key；程序不会退回实盘请求 |
| Passphrase/签名错误 | 核对 Passphrase 和 Secret Key，避免多余空格及编辑器智能引号 |
| 找不到 Key/站点错误 | 按账户注册站点检查 `OKX_SITE`，不切换到其他站点绕过限制 |
| 权限不足或不是仅 Read | 创建仅 Read 的模拟盘 Key，移除 Trade/Withdraw，不增加权限 |
| 时间校验失败/过期 | macOS“系统设置 → 通用 → 日期与时间”打开自动设置，再重新运行 |
| IP 不在白名单 | 在 OKX 检查 Key 的 IP 设置与本机出口 IP |
| 网络/TLS/重定向/超时 | 检查到所选 OKX 官方域名的网络，稍后重试；不关闭证书校验 |
| 公共数据有缺口 | 查看质量结果，重试 `market-check --days 1`；程序不填补缺失行情 |

HTTP 请求固定为 GET，私有端点只有账户配置、余额和持仓；所有私有请求固定携带 `x-simulated-trading: 1`，不跟随重定向。全球站 REST 使用 `openapi.okx.com`，美国/澳洲 `us.okx.com`，欧洲 `eea.okx.com`。来源：[官方认证与站点文档](https://www.okx.com/docs-v5/en/#overview-rest-authentication)。

Codex 的 Mock 测试和公开行情连通性检查不使用你的密钥；**首次真实私有连接验收由你在本地执行 `start --account-only` 完成**。当前不提供下单、撤单、划转、LLM 或持续模拟交易执行功能。

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

输出目录可通过 `demo --output <目录>` 修改。`experiments` 和 `report` 的 `--db` 参数支持其他数据库路径。回测成本使用严格校验的 TOML；仅首次模拟盘接入命令读取 `.env` 中的模拟盘只读凭证，离线演示不读取凭证。

## 当前模型口径

- 随包提供 240 根固定合成 1h K 线，BTC/ETH 使用演示用合约单位，**不是真实 OKX 历史数据或当前合约规格**。数据版本由完整内容哈希标识。
- 策略为受约束的均线规则，对照为买入持有。信号只看 `available_at <= 当前开盘时间` 的此前已收盘 K 线；最后一根预定收盘平仓。只做多、无杠杆、按整数张数模拟，资金和仓位均以 USDT 计。
- Taker 原始费率 0.045%，Maker 原始费率 0.016% 仅作配置预留，**没有 Maker 撮合**。默认按原始手续费扣款；只有 `rebate_confirmed = true` 时才生成 20% 应收返佣，并至少延后 1 小时到账（默认 24 小时）。对应净费率 0.036% / 0.0128% 仅在返佣确实可得时成立。未到账返佣不计现金和净收益。
- 不利成交价格使用半价差加滑点；初版假设小额 Taker 全额成交，未模拟盘口、部分成交、资金费、标记价、保证金或强平。期末权益为现金加持仓收盘估值；该实现只是无杠杆研究近似。
- 最大回撤包含初始资金点；净收益以已到账权益计算。Sharpe 使用逐 K 线收益、样本标准差、365 天年化且无无风险利率；零波动时为 `null`。成交笔数与完整买卖次数分别记录；持仓暴露为持仓 K 线占比。手续费敏感性重新运行两倍原始费率模型。
- SQLite 保存输入行情、来源/哈希、策略参数/哈希、完整成交/权益/返佣明细、成本及指标版本和运行代码提交（未提交代码标记 `-dirty`）。当前属于研发演示，未做样本外、封存测试及统计显著性筛选，不能据此宣称盈利。

## OKX 真实历史数据

公共 REST 下载仅使用 OKX 两个无需凭证的只读端点（历史 OHLCV 与当前合约规格），无需安装任何交易 SDK。

```bash
uv run --no-sync tradefoundry download --instrument BTC-USDT-SWAP --interval 1h \
  --start 2024-01-01T00:00:00Z --end 2024-01-02T00:00:00Z \
  --max-pages 10 --max-requests 30
uv run --no-sync tradefoundry quality --instrument BTC-USDT-SWAP --interval 1h \
  --start 2024-01-01T00:00:00Z --end 2024-01-02T00:00:00Z
```

支持 `1h`、`4h`、`1day`；日线明确请求 `1Dutc`，所有区间为对齐 UTC 的 `[start, end)`。数据保存在 `warehouse/<标的>/<周期>/` 的内容哈希 Parquet 页面中，断点及当前合约规格快照在 `warehouse/catalog.sqlite3`。每页先原子写入并同步文件，再推进 SQLite 断点；同分区拒绝同时写入。再次执行相同命令自动恢复；扩大或移动时间范围可增量写入，重叠数据去重。`--refresh` 重扫既有范围修复缺口；冲突价格直接报错，原数据不被覆盖。

下载按 `after` 向更早历史翻页，每页保守请求 100 条；请求间隔至少 0.15 秒，限流及暂时网络异常最多尝试 3 次，所有尝试和规格查询均占请求预算。默认每次最多 100 页、100 次请求，达到预算后安全退出，保留已完成页面。多个进程访问不同分区时须自行共享 IP 请求预算，当前限速器为单进程。

质量结果给出完整性、实际覆盖、缺失数量、合并缺口区间和数据哈希。`finished` 仅表示已遍历到请求起点，`exhausted` 表示接口已无更多记录；两者都不等于无缺口，应以 `complete` 判断。程序不会填补缺口，`confirm=0` 未收盘数据不会入库，不能承诺 API 没有提供的历史覆盖。可用 `--warehouse` 修改仓库路径。

`vol`、`volCcy`、`volCcyQuote` 分别保存为张数、基础币和计价币成交量；原始 9 字段同时保存。当前下载的是成交 K 线，**不是标记价、指数价、资金费、OI 或盘口**。历史发布时间不可还原，`available_at` 保守记录实际采集时刻，`availability_basis` 明确说明局限；当前合约规格也不代表历史规格。因此暂不把该仓库直接连接历史回测，后续需要独立校验历史合约规格、数据发布延迟和其他成本事件。

接口依据：[OKX 官方 API 文档](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks-history)。当前阶段及尚未实现的能力见 [PROGRESS.md](PROGRESS.md)。

## 独立验证与封存访问演示

```bash
# 只运行研发/验证区间及固定参数的滚动窗口
uv run --no-sync tradefoundry validate-demo
# 冻结全部输入后，才允许一次最终测试；以下都只使用合成夹具
uv run --no-sync tradefoundry freeze-demo
uv run --no-sync tradefoundry final-demo-test
uv run --no-sync tradefoundry test-audit
```

固定夹具按前 120 根研发、随后 60 根验证、最后 60 根封存切分；各分区从空仓重新运行。`--fast`、`--slow` 选择受约束的均线窗口，`--instrument` 选择标的，`--db` 选择同一个审计数据库。滚动窗口只使用前 180 根，报告明确窗口相关性，禁止按窗口个数累计独立样本数。研发命令不计算封存区间结果。

同一数据身份在一个数据库中只能冻结一组策略、配置和切分方案；冻结包含完整行情哈希、成本/指标版本及 Python 源码内容指纹。最终测试在计算前原子记录访问，同一数据集禁止再次测试，失败或中断也保留名额。禁止因结果不好而删库、改数据身份或重建切分来反复调优。审计入口属于本地流程保护，无法抵御拥有文件修改权限的进程；当前随包夹具公开可读，仅验证工作流，**不构成真实封存隔离**。真实研究仍需单独受控的评分程序和封存数据权限。

研发/封存明细以 JSON 存在 SQLite 中，当前 HTML 导出支持 `demo` 实验。未实现真实策略筛选、多重尝试统计校正、自动 AI 研究队列和持续模拟盘。

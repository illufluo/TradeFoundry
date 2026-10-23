# TradeFoundry｜开发进度

更新日期：2026-10-24
当前状态：**阶段 0 已完成本地验收；阶段 1 开发中**。
仓库分支：`codex/offline-lab`（从现有文档分支继续，包含尚未推送的进度修正）

## 已完成
- [x] 确认私有仓库 `illufluo/TradeFoundry` 可访问。
- [x] 用中文整理统一需求与开发规范至 `AGENTS.md`。
- [x] 精简项目文档，将固定规范和动态进度分离。
- [x] 调整 V1 范围：不默认接入 Grok Bot 或飞书，保留外部聊天适配能力。
- [x] 阶段 0：Python 包、uv 锁文件、CLI、严格 TOML 配置、固定合成 BTC/ETH 行情、无杠杆滞后 Taker 回测、原始手续费/延迟返佣、SQLite、独立 Plotly HTML、基础 CI。

## 正在进行
- [ ] 阶段 1：OKX 历史下载、Parquet、质量检查、断点与增量更新。

## 尚未开始
- [ ] 阶段 2：完整成本模型、策略接口及独立验证
- [ ] 阶段 3：自动 AI 研究循环
- [ ] 阶段 4：可视化报告与本地任务查询、控制
- [ ] 阶段 5：持续模拟盘（不涉及实盘）

## 已知限制
- 演示使用固定合成数据，不能当作真实 OKX 历史回测或盈利证据。引擎缺少资金费、部分成交、标记价、保证金、强平及独立样本外验证。
- 本地 Python 3.13 验证通过；CI 已配置 3.11/3.13，远端执行尚未验证。
- V1 无需 Grok Bot 或飞书；未来可利用 Grok Bot 自带聊天界面接入受控报告/查询接口。
- 外部 LLM 和数据供应商凭证可由用户后续配置；开发阶段用 Mock 验证。
- 不需要、也不得请求真实资金交易权限。

## 最近执行记录
- 将进度文件迁至仓库根目录，并修正 README 链接。
- 验证：`git diff --cached --check` 通过；本次仅修改文档，未运行测试。
- 2026-10-24：读取根目录规范、进度及真实 Git 状态；开始实现 Python 包、配置、固定合成行情、保守滞后成交、SQLite 和独立 HTML 报告。
- 环境：系统 `python3` 为 3.9；使用已安装的 Python 3.13。uv 默认缓存不可写，改用 `/private/tmp/tradefoundry-uv-cache`。GitHub 连接器可访问仓库；本机 gh 授权检查失败，后续验证 Git 推送并按需使用连接器。
- 阶段 0 验证：`.venv/bin/pytest -q`：**26 passed**；`.venv/bin/ruff check .`、`.venv/bin/ruff format --check .` 通过。
- `.venv/bin/tradefoundry demo`、`demo --instrument ETH-USDT-SWAP`、`experiments` 实际运行成功；测试同时覆盖数据库读写、报告重新导出、已知费用、返佣延迟、行情缺口、无未来信号和严格输入校验。报告为本地忽略产物 `artifacts/reports/`。
- 首次沙箱内依赖下载 DNS 失败；允许的网络环境中 `uv sync --python /opt/homebrew/bin/python3.13 --extra dev` 成功，已生成 `uv.lock`。

## 下一步
1. 完成阶段 1 的模拟接口测试；网络允许时验证 OKX 公共历史接口，记录真实覆盖及缺口。
2. 推进阶段 2 的成本/验证能力，不将演示结果标记为有效策略。
3. 持续更新进度，Commit、Push 并创建 PR 供审查。

> 本文件是**可随时修改的工作日志**，不是永久规范。日期、任务状态、失败原因、测试结果和 GitHub 链接必须与实际工作相符。

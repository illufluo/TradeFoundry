"""命令行入口；输入仅映射到明确允许的操作。"""

import argparse
import sys
from dataclasses import asdict, replace
from pathlib import Path

from tradefoundry.config import Config
from tradefoundry.demo_account import SITES, ConnectionFailure, DemoSettings
from tradefoundry.engine import COST_VERSION, METRIC_VERSION, backtest
from tradefoundry.market import INSTRUMENTS, INTERVALS, sample_data, utc
from tradefoundry.okx import PublicClient
from tradefoundry.onboarding import check_markets, first_start
from tradefoundry.report import write_report
from tradefoundry.store import Store, code_revision, encode
from tradefoundry.strategy import Strategy
from tradefoundry.validation import (
    SplitPlan,
    ValidationLedger,
    evaluate_development,
    walk_forward,
)
from tradefoundry.warehouse import Warehouse, sync_history


def demo(config: Config, instrument: str):
    data = sample_data(instrument)
    strategy = Strategy()
    result = backtest(data, strategy, config)
    payload = {
        "instrument": instrument,
        "source": data.source,
        "data_hash": data.digest,
        "data": asdict(data),
        "strategy": asdict(strategy),
        "strategy_hash": strategy.digest,
        "config": asdict(config),
        "cost_version": COST_VERSION,
        "metric_version": METRIC_VERSION,
        "code_revision": code_revision(),
        "window": [str(data.bars[0].timestamp), str(data.bars[-1].available_at)],
        "result": result.to_dict(),
        "benchmark": backtest(data, Strategy("buy_hold"), config).to_dict(),
        "fee_sensitivity": {
            "double_fee_net_return": backtest(
                data, strategy, replace(config, taker_fee=config.taker_fee * 2)
            ).metrics["net_return"]
        },
    }
    store = Store(Path(config.output_dir) / "experiments.sqlite3")
    experiment_id = store.record(payload)
    path = Path(config.output_dir) / "reports" / f"{experiment_id}.html"
    write_report(payload, path, experiment_id)
    return {"experiment_id": experiment_id, "report": str(path.resolve()), **result.metrics}


def parser():
    root = argparse.ArgumentParser(description="TradeFoundry：仅历史研究与模拟，无真实下单能力")
    root.add_argument("--config", type=Path, help="TOML 配置文件")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("demo", help="固定合成行情离线演示")
    run.add_argument("--instrument", choices=INSTRUMENTS, default=INSTRUMENTS[0])
    run.add_argument("--output", type=Path, help="输出目录")
    start = commands.add_parser("start", help="首次 OKX 官方模拟盘只读接入与市场检查")
    start.add_argument("--env-file", type=Path, default=Path(".env"))
    start.add_argument("--output", type=Path, default=Path("artifacts/start"))
    start.add_argument("--days", type=int, default=7)
    start.add_argument("--account-only", action="store_true", help="只检查真实模拟账户")
    start.add_argument("--offline", action="store_true", help="完全离线 Mock，绝不加载密钥")
    start.add_argument(
        "--scenario",
        choices=("success", "auth", "permission", "timeout", "environment", "excess-permission"),
        default="success",
    )
    market = commands.add_parser("market-check", help="无密钥检查真实 BTC/ETH 历史数据")
    market.add_argument("--site", choices=tuple(SITES), default="global")
    market.add_argument("--days", type=int, default=7)
    market.add_argument("--output", type=Path, default=Path("artifacts/start"))
    research = commands.add_parser("research", help="无密钥下载真实行情并运行有明确假设的条件重放")
    research.add_argument("--site", choices=tuple(SITES), default="global")
    research.add_argument("--days", type=int, default=7)
    research.add_argument("--output", type=Path, default=Path("artifacts/start"))
    status = commands.add_parser("experiments", help="查询 SQLite 实验记录")
    status.add_argument("--db", type=Path, default=Path("artifacts/experiments.sqlite3"))
    status.add_argument("--limit", type=int, default=20)
    export = commands.add_parser("report", help="从已保存实验导出报告")
    export.add_argument("experiment_id")
    export.add_argument("--db", type=Path, default=Path("artifacts/experiments.sqlite3"))
    export.add_argument("--output", type=Path, required=True)
    for command, help_text in (
        ("download", "下载或恢复 OKX 公共历史 K 线"),
        ("quality", "查询 Parquet 数据覆盖及缺口"),
    ):
        data = commands.add_parser(command, help=help_text)
        data.add_argument("--instrument", choices=INSTRUMENTS, required=True)
        data.add_argument("--interval", choices=tuple(INTERVALS), default="1h")
        data.add_argument("--start", type=utc, required=True, help="含 UTC 时区的起点（含）")
        data.add_argument("--end", type=utc, required=True, help="含 UTC 时区的终点（不含）")
        data.add_argument("--warehouse", type=Path, default=Path("warehouse"))
        if command == "download":
            data.add_argument("--max-pages", type=int, default=100)
            data.add_argument(
                "--max-requests", type=int, default=100, help="包含规格查询和所有重试的请求预算"
            )
            data.add_argument("--refresh", action="store_true", help="重扫同区间以修复缺口")
    for command, help_text in (
        ("validate-demo", "固定合成数据的研发/验证与滚动窗口演示"),
        ("freeze-demo", "冻结合成数据最终测试的全部输入"),
        ("final-demo-test", "运行一次冻结后的合成数据最终测试"),
        ("test-audit", "查看冻结及最终测试访问审计"),
    ):
        research = commands.add_parser(command, help=help_text)
        research.add_argument("--db", type=Path, default=Path("artifacts/experiments.sqlite3"))
        if command != "test-audit":
            research.add_argument("--instrument", choices=INSTRUMENTS, default=INSTRUMENTS[0])
            research.add_argument("--fast", type=int, default=3)
            research.add_argument("--slow", type=int, default=8)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config)
        if args.command == "start":
            if args.offline:
                from tradefoundry.mock_account import mock_account

                account = mock_account(args.scenario).snapshot()
                result = {
                    "mode": "offline_mock",
                    "account_connected": False,
                    "message": "离线 Mock 成功；没有连接真实 OKX 模拟盘",
                    "mock_account": account,
                    "synthetic_demo": demo(
                        replace(config, output_dir=str(args.output)), INSTRUMENTS[0]
                    ),
                }
            else:
                if args.scenario != "success":
                    raise ConnectionFailure("--scenario 仅可与 --offline 一起使用")
                settings = DemoSettings.load(args.env_file)
                result = first_start(
                    settings,
                    output=args.output,
                    days=args.days,
                    account_only=args.account_only,
                    research_config=config,
                )
            print(encode(result))
            return 0 if result.get("research_ready", result.get("market_ready", True)) else 3
        elif args.command == "research":
            from tradefoundry.historical_replay import run_research

            market = check_markets(args.site, output=args.output, days=args.days)
            result = market | {
                "account_connected": False,
                "account_status": "not_checked",
                "research_ready": False,
                "trusted_backtest_ready": False,
            }
            if market["market_ready"]:
                result |= run_research(
                    Warehouse(args.output / "warehouse"), market["quality"], args.output, config
                )
            print(encode(result))
            return 0 if result["research_ready"] else 3
        elif args.command == "market-check":
            result = check_markets(args.site, output=args.output, days=args.days)
            print(encode(result | {"account_connected": False, "account_status": "not_checked"}))
            return 0 if result["market_ready"] else 3
        elif args.command == "demo":
            if args.output:
                config = replace(config, output_dir=str(args.output))
            result = demo(config, args.instrument)
        elif args.command == "experiments":
            result = [
                {key: row[key] for key in ("id", "created_at", "status")}
                | {"metrics": row["payload"].get("result", {}).get("metrics")}
                for row in Store(args.db).list(args.limit)
            ]
        elif args.command == "report":
            write_report(Store(args.db).get(args.experiment_id), args.output, args.experiment_id)
            result = {"report": str(args.output.resolve())}
        elif args.command == "download":
            result = sync_history(
                Warehouse(args.warehouse),
                PublicClient(max_requests=args.max_requests),
                args.instrument,
                args.interval,
                args.start,
                args.end,
                max_pages=args.max_pages,
                refresh=args.refresh,
            )
        elif args.command == "quality":
            result = Warehouse(args.warehouse).quality(
                args.instrument,
                args.interval,
                args.start,
                args.end,
            )
        elif args.command == "test-audit":
            result = ValidationLedger(Store(args.db)).audit()
        else:
            data, strategy = sample_data(args.instrument), Strategy(fast=args.fast, slow=args.slow)
            plan = SplitPlan(120, 180, len(data.bars))
            store = Store(args.db)
            if args.command == "validate-demo":
                payload = evaluate_development(data, strategy, config, plan)
                payload["walk_forward"] = walk_forward(
                    data,
                    strategy,
                    config,
                    train_bars=60,
                    validation_bars=30,
                    step_bars=30,
                    development_end=plan.validation_end,
                )
                experiment_id = store.record(payload)
                result = {
                    "experiment_id": experiment_id,
                    "sealed_accessed": False,
                    "metrics": {
                        key: value["result"]["metrics"]
                        for key, value in payload["partitions"].items()
                    },
                    "walk_forward": payload["walk_forward"],
                }
            elif args.command == "freeze-demo":
                result = ValidationLedger(store).freeze(data, strategy, config, plan)
            else:
                result = ValidationLedger(store).final_test(data, strategy, config, plan)
        print(encode(result))
        return 0
    except (ValueError, TypeError, OSError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2

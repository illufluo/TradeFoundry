"""命令行入口；输入仅映射到明确允许的操作。"""

import argparse
import sys
from dataclasses import asdict, replace
from pathlib import Path

from tradefoundry.config import Config
from tradefoundry.engine import COST_VERSION, METRIC_VERSION, backtest
from tradefoundry.market import INSTRUMENTS, INTERVALS, sample_data, utc
from tradefoundry.okx import PublicClient
from tradefoundry.report import write_report
from tradefoundry.store import Store, code_revision, encode
from tradefoundry.strategy import Strategy
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
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config)
        if args.command == "demo":
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
        else:
            result = Warehouse(args.warehouse).quality(
                args.instrument,
                args.interval,
                args.start,
                args.end,
            )
        print(encode(result))
        return 0
    except (ValueError, TypeError, OSError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2

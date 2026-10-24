"""固定时间切分、冻结输入及一次性最终测试审计；不执行生成代码。"""

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from tradefoundry.config import Config
from tradefoundry.engine import COST_VERSION, METRIC_VERSION, backtest
from tradefoundry.market import MarketData
from tradefoundry.store import Store, code_revision, encode
from tradefoundry.strategy import Strategy


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def engine_fingerprint() -> str:
    """内容指纹防止冻结后悄悄修改代码，不能替代操作系统权限隔离。"""
    directory = Path(__file__).parent
    return digest({file.name: file.read_text() for file in sorted(directory.glob("*.py"))})


@dataclass(frozen=True)
class SplitPlan:
    train_end: int
    validation_end: int
    total: int
    version: int = 1

    def __post_init__(self):
        if any(type(value) is not int for value in asdict(self).values()):
            raise ValueError("切分参数须为整数")
        if (
            self.version != 1
            or not 2 <= self.train_end <= self.validation_end - 2 <= self.total - 4
        ):
            raise ValueError("研发、验证、封存区间各须至少两根 K 线且互不重叠")

    def partition(self, data: MarketData, name: str) -> MarketData:
        if len(data.bars) != self.total:
            raise ValueError("切分方案与数据长度不符")
        bounds = {
            "train": (0, self.train_end),
            "validation": (self.train_end, self.validation_end),
            "sealed": (self.validation_end, self.total),
        }
        if name not in bounds:
            raise ValueError("未知数据分区")
        start, end = bounds[name]
        return replace(data, bars=data.bars[start:end]).validate()


def evaluate_development(data: MarketData, strategy: Strategy, config: Config, plan: SplitPlan):
    """研发命令只回测 train/validation；不会运行 sealed。"""
    data.validate()
    results = {}
    for name in ("train", "validation"):
        partition = plan.partition(data, name)
        results[name] = {
            "window": [str(partition.bars[0].timestamp), str(partition.bars[-1].available_at)],
            "result": backtest(partition, strategy, config).to_dict(),
            "benchmark": backtest(partition, Strategy("buy_hold"), config).to_dict(),
        }
    return {
        "phase": "development_validation",
        "source": data.source,
        "data_hash": data.digest,
        "plan": asdict(plan),
        "strategy": asdict(strategy),
        "strategy_hash": strategy.digest,
        "cost_version": COST_VERSION,
        "metric_version": METRIC_VERSION,
        "config": asdict(config),
        "code_revision": code_revision(),
        "engine_fingerprint": engine_fingerprint(),
        "partitions": results,
        "notice": "仅描述性研发/验证结果；未访问最终测试，不声明统计显著性。各分区从空仓重启。",
    }


def walk_forward(
    data: MarketData,
    strategy: Strategy,
    config: Config,
    *,
    train_bars: int,
    validation_bars: int,
    step_bars: int,
    development_end: int,
):
    """策略参数保持固定；只允许在显式研发范围内滚动，重叠窗口不视作独立样本。"""
    values = (train_bars, validation_bars, step_bars, development_end)
    if any(type(value) is not int or value < 2 for value in values):
        raise ValueError("滚动窗口参数须为至少 2 的整数")
    if not train_bars + validation_bars <= development_end <= len(data.bars):
        raise ValueError("滚动窗口超出研发范围")
    data.validate()
    windows = []
    for start in range(0, development_end - train_bars - validation_bars + 1, step_bars):
        boundary, end = start + train_bars, start + train_bars + validation_bars
        train = replace(data, bars=data.bars[start:boundary])
        validation = replace(data, bars=data.bars[boundary:end])
        windows.append(
            {
                "train_indices": [start, boundary],
                "validation_indices": [boundary, end],
                "train": backtest(train, strategy, config).metrics,
                "validation": backtest(validation, strategy, config).metrics,
            }
        )
    return {
        "windows": windows,
        "overlapping_validation": step_bars < validation_bars,
        "independent_sample_count": None,
        "notice": "同一历史序列上的窗口具有相关性；禁止按窗口数量累计独立样本或显著性。",
    }


class ValidationLedger:
    def __init__(self, store: Store):
        self.store = store
        with store.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS frozen_tests (
                cohort TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS test_accesses (
                cohort TEXT PRIMARY KEY REFERENCES frozen_tests(cohort),
                status TEXT NOT NULL, accessed_at TEXT NOT NULL,
                experiment_id TEXT, error TEXT
            )""")

    @staticmethod
    def inputs(data, strategy, config, plan):
        data.validate()
        if len(data.bars) != plan.total:
            raise ValueError("冻结方案与数据长度不符")
        # 同一数据集不能通过更换策略、成本或切分边界反复申请封存测试。
        cohort = digest([data.instrument, data.source, data.digest])
        frozen = {
            "data_hash": data.digest,
            "strategy": asdict(strategy),
            "config": asdict(config),
            "plan": asdict(plan),
            "cost_version": COST_VERSION,
            "metric_version": METRIC_VERSION,
            "engine_fingerprint": engine_fingerprint(),
        }
        return cohort, frozen

    def freeze(self, data, strategy, config, plan):
        cohort, frozen = self.inputs(data, strategy, config, plan)
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT payload FROM frozen_tests WHERE cohort = ?",
                (cohort,),
            ).fetchone()
            if previous is not None and previous["payload"] != encode(frozen):
                raise ValueError("该数据集已冻结，禁止修改参数、切分或成本后再次测试")
            connection.execute(
                "INSERT OR IGNORE INTO frozen_tests VALUES (?, ?, ?)",
                (cohort, encode(frozen), datetime.now(UTC).isoformat()),
            )
        return {"cohort": cohort, "frozen_hash": digest(frozen), "status": "frozen"}

    def final_test(self, data, strategy, config, plan):
        cohort, frozen = self.inputs(data, strategy, config, plan)
        # 在执行前原子占用唯一访问名额；即使崩溃或计算失败也保留访问记录。
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM frozen_tests WHERE cohort = ?", (cohort,)
            ).fetchone()
            if row is None or json.loads(row["payload"]) != frozen:
                raise ValueError("须先冻结完全相同的策略、成本、代码、切分及数据")
            try:
                connection.execute(
                    "INSERT INTO test_accesses VALUES (?, ?, ?, NULL, NULL)",
                    (cohort, "running", datetime.now(UTC).isoformat()),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("该数据集已访问最终测试；失败/中断也不允许自动重试") from error
        try:
            sealed = plan.partition(data, "sealed")
            payload = {
                "phase": "sealed_final_test",
                "cohort": cohort,
                "frozen_hash": digest(frozen),
                "frozen_inputs": frozen,
                "code_revision": code_revision(),
                "source": data.source,
                "window": [str(sealed.bars[0].timestamp), str(sealed.bars[-1].available_at)],
                "result": backtest(sealed, strategy, config).to_dict(),
                "benchmark": backtest(sealed, Strategy("buy_hold"), config).to_dict(),
                "notice": "单次封存测试不等于可盈利，仍需成本完整性及多重尝试统计审查。",
            }
            experiment_id = self.store.record(payload)
        except Exception as error:
            with self.store.connect() as connection:
                connection.execute(
                    "UPDATE test_accesses SET status='failed', error=? WHERE cohort=?",
                    (type(error).__name__, cohort),
                )
            raise
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE test_accesses SET status='completed', experiment_id=? WHERE cohort=?",
                (experiment_id, cohort),
            )
        return {
            "experiment_id": experiment_id,
            "cohort": cohort,
            "metrics": payload["result"]["metrics"],
            "status": "completed",
        }

    def audit(self):
        with self.store.connect() as connection:
            rows = connection.execute("""SELECT f.cohort, f.created_at AS frozen_at,
                a.status, a.accessed_at, a.experiment_id, a.error
                FROM frozen_tests f LEFT JOIN test_accesses a ON a.cohort=f.cohort
                ORDER BY f.created_at""").fetchall()
        return [dict(row) for row in rows]

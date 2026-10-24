"""固定的无杠杆、仅做多 Taker 演示引擎；所有信号滞后成交。"""

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from tradefoundry.config import Config
from tradefoundry.market import INTERVALS, MarketData
from tradefoundry.strategy import Strategy

COST_VERSION = "taker-unlevered-v1"
METRIC_VERSION = "bar-mtm-cash-rebates-v1"
LIMITATIONS = [
    "仅功能演示，不构成统计证据或投资建议。",
    "仅做多、无杠杆；以 K 线收盘价估值，不代表标记价或保证金/强平模型。",
    "下一可用 K 线开盘按半价差和滑点不利成交；小额全额 Taker 假设，未模拟盘口和部分成交。",
    "没有资金费、真实盘口及标记价数据；不能据此判断策略可盈利。",
    "窗口结束按预定收盘强制平仓；未到账返佣仅列应收，不计可用现金及净收益。",
    "Sharpe 为同周期收益的描述性年化值，未作多重尝试校正或样本外验证。",
]


@dataclass(frozen=True)
class Fill:
    timestamp: datetime
    side: str
    contracts: int
    price: float
    notional: float
    gross_fee: float
    rebate_receivable: float
    reason: str


@dataclass(frozen=True)
class Equity:
    timestamp: datetime
    cash: float
    contracts: int
    equity: float
    rebate_pending: float


@dataclass(frozen=True)
class Rebate:
    timestamp: datetime
    amount: float


@dataclass(frozen=True)
class Result:
    metrics: dict
    fills: tuple[Fill, ...]
    equity: tuple[Equity, ...]
    rebates: tuple[Rebate, ...]

    def to_dict(self):
        return asdict(self)


def backtest(data: MarketData, strategy: Strategy, config: Config) -> Result:
    data.validate()
    cash = config.initial_cash
    contracts = 0
    fills = []
    points = [Equity(data.bars[0].timestamp, cash, 0, cash, 0)]
    pending: list[tuple[datetime, float]] = []
    rebates = []
    closes = []
    next_observation = 0
    held_bars = 0
    friction = (config.spread_bps / 2 + config.slippage_bps) / 10000

    def settle(now):
        nonlocal cash, pending
        due = [(time, amount) for time, amount in pending if time <= now]
        for time, amount in due:
            cash += amount
            rebates.append(Rebate(time, amount))
        pending = [(time, amount) for time, amount in pending if time > now]

    def fill(side, count, reference, time, reason):
        nonlocal cash, contracts
        price = reference * (1 + friction if side == "buy" else 1 - friction)
        notional = count * data.contract_value * price
        fee = notional * config.taker_fee
        rebate = fee * config.rebate_fraction if config.rebate_confirmed else 0
        cash += (-notional if side == "buy" else notional) - fee
        contracts += count if side == "buy" else -count
        if rebate:
            pending.append((time + timedelta(hours=config.rebate_delay_hours), rebate))
        fills.append(Fill(time, side, count, price, notional, fee, rebate, reason))

    for index, bar in enumerate(data.bars):
        settle(bar.timestamp)
        # 只能读取此前已经收盘且实际可用的 K 线，延迟数据不会提前进入信号。
        while next_observation < index:
            previous = data.bars[next_observation]
            if previous.available_at > bar.timestamp:
                break
            closes.append(previous.close)
            next_observation += 1
        target = strategy.target(closes)
        if target and not contracts:
            unit_cost = data.contract_value * bar.open * (1 + friction) * (1 + config.taker_fee)
            count = math.floor(cash * config.position_fraction / unit_cost)
            if count:
                fill("buy", count, bar.open, bar.timestamp, "lagged_signal")
        elif not target and contracts:
            fill("sell", contracts, bar.open, bar.timestamp, "lagged_signal")
        held_bars += bool(contracts)
        end = bar.timestamp + INTERVALS[data.interval]
        settle(end)
        if index == len(data.bars) - 1 and contracts:
            fill("sell", contracts, bar.close, end, "scheduled_window_end")
        value = cash + contracts * data.contract_value * bar.close
        points.append(Equity(end, cash, contracts, value, sum(x[1] for x in pending)))

    values = [point.equity for point in points]
    returns = [b / a - 1 for a, b in zip(values, values[1:], strict=False)]
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    std = statistics.stdev(returns) if len(returns) > 1 else 0
    periods = timedelta(days=365).total_seconds() / INTERVALS[data.interval].total_seconds()
    sharpe = statistics.mean(returns) / std * math.sqrt(periods) if std else None
    return Result(
        {
            "net_return": values[-1] / config.initial_cash - 1,
            "max_drawdown": drawdown,
            "sharpe_descriptive": sharpe,
            "fill_count": len(fills),
            "round_trips": sum(fill.side == "sell" for fill in fills),
            "exposure": held_bars / len(data.bars),
            "gross_fees": sum(fill.gross_fee for fill in fills),
            "rebates_received": sum(rebate.amount for rebate in rebates),
            "rebates_pending": sum(amount for _, amount in pending),
            "final_equity": values[-1],
        },
        tuple(fills),
        tuple(points),
        tuple(rebates),
    )

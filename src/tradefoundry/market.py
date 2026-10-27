"""UTC 行情类型和严格质量检查；不填补缺口。"""

import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.resources import files

INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
INTERVALS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1day": timedelta(days=1)}


def utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("时间必须显式使用 UTC 时区")
    return result.astimezone(UTC)


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume_contracts: float


def validate_bar(bar: Bar, interval: str):
    if interval not in INTERVALS:
        raise ValueError("不支持的周期")
    for value in (bar.timestamp, bar.available_at):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("时间必须为 UTC")
    if bar.available_at < bar.timestamp + INTERVALS[interval]:
        raise ValueError("未收盘行情不能提前可用")
    if bar.timestamp.timestamp() % INTERVALS[interval].total_seconds():
        raise ValueError("K 线未对齐 UTC 周期边界")
    values = (bar.open, bar.high, bar.low, bar.close, bar.volume_contracts)
    if not all(math.isfinite(x) for x in values):
        raise ValueError("行情不能含 NaN 或无穷值")
    if min(values[:4]) <= 0 or bar.volume_contracts < 0:
        raise ValueError("价格须大于零，成交量不能为负")
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
        raise ValueError("OHLC 高低价不一致")


@dataclass(frozen=True)
class MarketData:
    instrument: str
    interval: str
    source: str
    contract_value: float
    bars: tuple[Bar, ...]
    contract_step: float = 1.0
    minimum_contracts: float = 1.0
    price_tick: float = 0.0

    def validate(self, *, require_contiguous: bool = True):
        if self.instrument not in INSTRUMENTS or self.interval not in INTERVALS:
            raise ValueError("不支持的标的或周期")
        if not self.source or not math.isfinite(self.contract_value) or self.contract_value <= 0:
            raise ValueError("数据来源及合约单位无效")
        if (
            not all(
                math.isfinite(value) and value > 0
                for value in (
                    self.contract_step,
                    self.minimum_contracts,
                )
            )
            or not math.isfinite(self.price_tick)
            or self.price_tick < 0
        ):
            raise ValueError("合约数量步长、最小数量或价格步长无效")
        if Decimal(str(self.minimum_contracts)) % Decimal(str(self.contract_step)):
            raise ValueError("最小合约数量必须对齐数量步长")
        if len(self.bars) < 2:
            raise ValueError("至少需要两根已收盘 K 线")
        previous = None
        for bar in self.bars:
            validate_bar(bar, self.interval)
            if previous is not None:
                if bar.timestamp <= previous:
                    raise ValueError("行情时间重复或未升序排列")
                if require_contiguous and bar.timestamp - previous != INTERVALS[self.interval]:
                    raise ValueError("行情存在缺口，拒绝直接回测")
            previous = bar.timestamp
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, default=str).encode()
        ).hexdigest()


def sample_data(instrument: str = INSTRUMENTS[0]) -> MarketData:
    """固定合成夹具用于功能演示，绝不作为真实 OKX 历史行情。"""
    if instrument not in INSTRUMENTS:
        raise ValueError("仅支持 BTC/ETH USDT 永续")
    resource = files("tradefoundry").joinpath("data/sample.csv")
    with resource.open() as file:
        rows = list(csv.DictReader(file))
    scale = 1.0 if instrument == INSTRUMENTS[0] else 0.05
    bars = tuple(
        Bar(
            utc(row["timestamp"]),
            utc(row["available_at"]),
            *(float(row[key]) * scale for key in ("open", "high", "low", "close")),
            float(row["volume_contracts"]),
        )
        for row in rows
    )
    return MarketData(
        instrument,
        "1h",
        "synthetic-fixture-v1-not-okx-history",
        0.01 if instrument == INSTRUMENTS[0] else 0.1,
        bars,
    ).validate()

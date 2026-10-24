"""固定成本配置；未知配置项直接拒绝。"""

import math
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    output_dir: str = "artifacts"
    initial_cash: float = 10000.0
    position_fraction: float = 0.25
    taker_fee: float = 0.00045
    maker_fee: float = 0.00016
    rebate_fraction: float = 0.20
    rebate_confirmed: bool = False
    rebate_delay_hours: int = 24
    spread_bps: float = 2.0
    slippage_bps: float = 3.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name not in {"output_dir", "rebate_confirmed"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{name} 必须为数值")
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"{name} 必须为非负有限数值")
        if not isinstance(self.rebate_confirmed, bool):
            raise ValueError("rebate_confirmed 必须为布尔值")
        if not isinstance(self.output_dir, str) or not self.output_dir:
            raise ValueError("output_dir 必须为非空路径")
        if self.initial_cash <= 0 or not 0 < self.position_fraction <= 0.9:
            raise ValueError("初始资金须大于零，仓位比例须在 (0, 0.9] 内")
        if max(self.taker_fee, self.maker_fee, self.rebate_fraction) > 1:
            raise ValueError("费率及返佣比例不能超过 1")
        if self.rebate_delay_hours < 1 or int(self.rebate_delay_hours) != self.rebate_delay_hours:
            raise ValueError("返佣延迟须为至少 1 小时的整数")
        if self.spread_bps / 2 + self.slippage_bps >= 10000:
            raise ValueError("成交成本不得超过价格本身")

    @classmethod
    def load(cls, path: Path | None = None):
        if path is None:
            return cls()
        with path.open("rb") as file:
            return cls(**tomllib.load(file))

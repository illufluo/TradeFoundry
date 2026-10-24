"""策略只接受受约束规则；不加载、解释或执行用户 Python。"""

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Strategy:
    kind: str = "sma"
    fast: int = 3
    slow: int = 8
    version: int = 1

    def __post_init__(self):
        if self.kind not in {"sma", "buy_hold", "flat"} or self.version != 1:
            raise ValueError("策略类型或版本不在允许列表")
        if any(type(x) is not int for x in (self.fast, self.slow, self.version)):
            raise ValueError("策略窗口及版本必须为整数")
        if not 1 <= self.fast < self.slow <= 1000:
            raise ValueError("窗口必须满足 1 <= fast < slow <= 1000")

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def target(self, closes: list[float]) -> bool:
        if self.kind == "flat":
            return False
        if self.kind == "buy_hold":
            return bool(closes)
        if len(closes) < self.slow:
            return False
        return sum(closes[-self.fast :]) / self.fast > sum(closes[-self.slow :]) / self.slow

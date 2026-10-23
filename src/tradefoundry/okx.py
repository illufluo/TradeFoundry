"""只有两个 GET 公共数据端点的客户端，不提供私有接口及下单方法。"""

import json
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tradefoundry.market import INSTRUMENTS

HISTORY_PATH = "/api/v5/market/history-candles"
INSTRUMENT_PATH = "/api/v5/public/instruments"
BAR_CODES = {"1h": "1H", "4h": "4H", "1day": "1Dutc"}


class DataError(ValueError):
    """服务响应或数据质量异常。"""


class RequestBudgetExceeded(DataError):
    """请求次数达到上限；已下载页面保留，下一次可恢复。"""


def public_get(path: str, params: dict) -> dict:
    if path not in {HISTORY_PATH, INSTRUMENT_PATH}:
        raise DataError("只允许已审核的 OKX 公共行情 GET 路径")
    request = Request(
        "https://www.okx.com" + path + "?" + urlencode(params),
        headers={"User-Agent": "TradeFoundry/0.1 research-only"},
        method="GET",
    )
    with urlopen(request, timeout=15) as response:
        body = response.read(5_000_001)
    if len(body) > 5_000_000:
        raise DataError("响应超过 5 MB 限制")
    try:
        return json.loads(body)
    except (ValueError, UnicodeError) as error:
        raise DataError("OKX 响应不是有效 JSON") from error


class PublicClient:
    def __init__(
        self,
        *,
        transport=public_get,
        sleep=time.sleep,
        clock=time.monotonic,
        max_requests=100,
        attempts=3,
        min_interval=0.15,
    ):
        if type(max_requests) is not int or not 1 <= max_requests <= 10000:
            raise ValueError("单次请求预算须在 1 到 10000 之间")
        if type(attempts) is not int or not 1 <= attempts <= 5:
            raise ValueError("重试总尝试次数须在 1 到 5 之间")
        if not 0.1 <= min_interval <= 60:
            raise ValueError("请求间隔须在 0.1 到 60 秒之间")
        self.transport, self.sleep, self.clock = transport, sleep, clock
        self.max_requests, self.attempts = max_requests, attempts
        self.min_interval = min_interval
        self.requests = 0
        self.last_request = None

    def get(self, path, params):
        if path not in {HISTORY_PATH, INSTRUMENT_PATH}:
            raise DataError("不允许访问非公共数据端点")
        for attempt in range(self.attempts):
            if self.requests >= self.max_requests:
                raise RequestBudgetExceeded("OKX 请求预算已耗尽，保留断点后停止")
            if self.last_request is not None:
                self.sleep(max(0, self.min_interval - (self.clock() - self.last_request)))
            self.requests += 1
            self.last_request = self.clock()
            retry_after = 0
            try:
                response = self.transport(path, params)
                if not isinstance(response, dict) or not isinstance(response.get("data"), list):
                    raise DataError("OKX 响应结构无效")
                if response.get("code") == "0":
                    return response["data"]
                if response.get("code") not in {"50011", "50040", "50013", "50026"}:
                    raise DataError(f"OKX 公共接口错误：{response.get('code')}")
                error = DataError(f"OKX 暂时限流或不可用：{response['code']}")
            except HTTPError as exception:
                if exception.code != 429 and not 500 <= exception.code <= 599:
                    raise DataError(f"OKX HTTP 错误：{exception.code}") from exception
                error = exception
                try:
                    retry_after = min(10, max(0, float(exception.headers.get("Retry-After", 0))))
                except (TypeError, ValueError):
                    retry_after = 0
            except (URLError, TimeoutError, ConnectionError) as exception:
                error = exception
            if attempt == self.attempts - 1:
                raise DataError(f"OKX 请求在 {self.attempts} 次尝试后失败：{error}") from error
            self.sleep(max(retry_after, min(2**attempt, 10)))
        raise AssertionError("不可达路径")

    def history(self, instrument, interval, after):
        if instrument not in INSTRUMENTS or interval not in BAR_CODES:
            raise DataError("不支持的标的或周期")
        return self.get(
            HISTORY_PATH,
            {
                "instId": instrument,
                "bar": BAR_CODES[interval],
                "after": str(after),
                "limit": "100",
            },
        )

    def instrument(self, instrument):
        if instrument not in INSTRUMENTS:
            raise DataError("不支持的标的")
        rows = self.get(INSTRUMENT_PATH, {"instType": "SWAP", "instId": instrument})
        if len(rows) != 1 or rows[0].get("instId") != instrument:
            raise DataError("合约规格响应与请求不一致")
        row = rows[0]
        if row.get("ctType") != "linear" or row.get("settleCcy") != "USDT":
            raise DataError("仅接受 USDT 线性永续")
        return {
            "observed_at": datetime.now(UTC).isoformat(),
            "raw": row,
            "notice": "仅当前规格快照，不能推定历史规格；不得据此直接回测",
        }

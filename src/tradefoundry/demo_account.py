"""OKX 官方模拟盘只读接入。凭证仅驻留内存，私有端点按精确白名单封闭。"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tradefoundry.market import INSTRUMENTS

SITES = {
    "global": "https://openapi.okx.com",
    "us": "https://us.okx.com",
    "eea": "https://eea.okx.com",
}
TIME_PATH = "/api/v5/public/time"
CONFIG_PATH = "/api/v5/account/config"
BALANCE_PATH = "/api/v5/account/balance"
POSITIONS_PATH = "/api/v5/account/positions"
PRIVATE_PATHS = frozenset({CONFIG_PATH, BALANCE_PATH, POSITIONS_PATH})
PUBLIC_PATHS = frozenset(
    {TIME_PATH, "/api/v5/public/instruments", "/api/v5/market/history-candles"}
)
ENV_FIELDS = {
    "OKX_DEMO_API_KEY",
    "OKX_DEMO_SECRET_KEY",
    "OKX_DEMO_PASSPHRASE",
    "OKX_SITE",
    "OKX_TIMEOUT_SECONDS",
}


class ConnectionFailure(ValueError):
    """只包含固定安全说明；不回显服务端消息、响应、请求头或底层异常。"""


def load_env_file(path: Path) -> dict:
    if not path.exists():
        return {}
    result = {}
    # 只解析 KEY=VALUE；不执行 Shell、不插值、不修改全局环境。
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in ENV_FIELDS or key in result:
            raise ConnectionFailure(".env 含未知/重复字段或格式错误，请对照 .env.example 检查")
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConnectionFailure(".env 引号未配对")
            value = value[1:-1]
        result[key] = value
    return result


@dataclass(frozen=True, repr=False)
class DemoCredentials:
    api_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    passphrase: str = field(repr=False)

    def __repr__(self):
        return "DemoCredentials(<redacted>)"

    def __post_init__(self):
        for value in (self.api_key, self.secret_key, self.passphrase):
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 256
                or any(ord(char) < 33 or ord(char) > 126 for char in value)
                or value.lower().startswith(("your_", "replace_", "填入"))
            ):
                raise ConnectionFailure("模拟盘凭证缺失或格式无效，请填写 .env 中的三个凭证字段")


@dataclass(frozen=True)
class DemoSettings:
    credentials: DemoCredentials = field(repr=False)
    site: str = "global"
    timeout: float = 15

    def __post_init__(self):
        if self.site not in SITES:
            raise ConnectionFailure("OKX_SITE 只能为 global、us 或 eea，请按账户注册站点选择")
        if not isinstance(self.timeout, (int, float)) or not 1 <= self.timeout <= 30:
            raise ConnectionFailure("OKX_TIMEOUT_SECONDS 必须在 1 到 30 秒之间")

    @classmethod
    def load(cls, path=Path(".env"), environ=None):
        values = load_env_file(path)
        environment = os.environ if environ is None else environ
        values.update({key: environment[key] for key in ENV_FIELDS if key in environment})
        try:
            timeout = float(values.get("OKX_TIMEOUT_SECONDS", "15"))
        except ValueError:
            raise ConnectionFailure("OKX_TIMEOUT_SECONDS 必须为数值") from None
        return cls(
            DemoCredentials(
                *(
                    values.get(key, "")
                    for key in ("OKX_DEMO_API_KEY", "OKX_DEMO_SECRET_KEY", "OKX_DEMO_PASSPHRASE")
                )
            ),
            values.get("OKX_SITE", "global"),
            timeout,
        )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 带凭证的请求不跟随任何重定向，包括同主机跳转。
        raise ConnectionFailure("OKX 返回重定向，已停止；请核对账户站点和网络")


def request_json(base_url, path, params, headers, timeout):
    if base_url not in SITES.values() or path not in PRIVATE_PATHS | PUBLIC_PATHS:
        raise ConnectionFailure("请求不在已审核的 OKX 只读白名单中")
    private = path in PRIVATE_PATHS
    if private and headers.get("x-simulated-trading") != "1":
        raise ConnectionFailure("缺少固定模拟盘请求头，已拒绝请求")
    if not private and any(key.upper().startswith("OK-ACCESS-") for key in headers):
        raise ConnectionFailure("公共行情请求不得携带私有认证头")
    query = urlencode(sorted(params.items()))
    headers = {"User-Agent": "TradeFoundry/0.1 research-only", **headers}
    request = Request(
        base_url + path + ("?" + query if query else ""), headers=headers, method="GET"
    )
    try:
        opener = build_opener(NoRedirect())
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as error:
            # OKX 的鉴权错误经常以 HTTP 401 + JSON 错误码返回。
            if error.code not in {400, 401, 403, 429}:
                raise ConnectionFailure("OKX 服务暂不可用，请稍后重试") from None
            response = error
        with response:
            raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ConnectionFailure("OKX 响应超出大小上限")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ConnectionFailure(
                "OKX 未返回 API JSON（可能为 HTTP 403 站点/网络限制）；请核对账户站点及网络"
            ) from None
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except ConnectionFailure:
        raise
    except Exception:
        raise ConnectionFailure("OKX 网络、TLS 或响应异常；请检查网络后重试") from None


ERRORS = {
    "50101": "密钥与模拟环境不匹配；请在 OKX 模拟交易页面重新创建只读 API Key",
    "50102": "签名时间过期；请开启 macOS 自动日期与时间并重试",
    "50105": "Passphrase 不正确；请核对创建模拟盘密钥时设置的密码",
    "50110": "当前出口 IP 不在 API 白名单；请在 OKX 检查模拟盘 Key 的 IP 设置",
    "50111": "API Key 无效；请核对模拟盘 Key 与所选账户站点",
    "50113": "签名无效；请核对模拟盘 Secret Key，并确保三项凭证来自同一个 Key",
    "50119": "所选站点找不到该 Key；请核对 OKX_SITE 与模拟盘 Key",
    "50120": "API 权限不足；请确认模拟盘 Key 包含 Read 权限",
    "50123": "账户或站点权限不支持该请求；本项目仅需 Read，请勿增加 Trade 权限",
    "50011": "OKX 请求限流，请稍后重新运行",
}


def response_data(payload):
    if not isinstance(payload, dict):
        raise ConnectionFailure("OKX 响应格式无效")
    code = payload.get("code")
    if code != "0":
        # code 和 msg 都可能由外部输入控制，不回显未知原文。
        raise ConnectionFailure(ERRORS.get(code, "OKX 请求被拒绝；请核对模拟盘配置和账户状态"))
    data = payload.get("data")
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ConnectionFailure("OKX 响应字段不完整")
    return data


def number(value):
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite() or len(str(value)) > 100:
            raise InvalidOperation
        return str(result)
    except (InvalidOperation, ValueError):
        raise ConnectionFailure("OKX 账户数值格式无效") from None


class DemoReadClient:
    def __init__(
        self, settings, *, transport=request_json, now=lambda: datetime.now(UTC), sleep=time.sleep
    ):
        self.settings, self.transport, self.now, self.sleep = settings, transport, now, sleep
        self.offset = None
        self.requests = 0

    def _call(self, path, params, headers):
        if self.requests >= 10:
            raise ConnectionFailure("首次接入请求预算已耗尽，请重新运行")
        if self.requests:
            self.sleep(0.25)
        self.requests += 1
        try:
            return response_data(
                self.transport(
                    SITES[self.settings.site], path, params, headers, self.settings.timeout
                )
            )
        except ConnectionFailure:
            raise
        except Exception:
            raise ConnectionFailure("OKX 网络或响应异常，请检查连接后重试") from None

    def sync_time(self):
        before = self.now()
        rows = self._call(TIME_PATH, {}, {})
        after = self.now()
        try:
            if len(rows) != 1 or not re.fullmatch(r"\d{13}", rows[0]["ts"]):
                raise ValueError
            server = datetime.fromtimestamp(int(rows[0]["ts"]) / 1000, UTC)
            midpoint = before + (after - before) / 2
            self.offset = server - midpoint
            if abs(self.offset.total_seconds()) > 300 or (after - before).total_seconds() > 10:
                raise ValueError
        except (ValueError, KeyError, TypeError, OverflowError):
            self.offset = None
            raise ConnectionFailure("服务器时间校验失败；请开启 macOS 自动时间并检查网络") from None

    def _get(self, path, params=None):
        params = {} if params is None else params
        allowed = {CONFIG_PATH: {}, BALANCE_PATH: {}, POSITIONS_PATH: {"instType": "SWAP"}}
        if path not in allowed or params != allowed[path]:
            raise ConnectionFailure("仅允许固定的余额、持仓及账户配置查询")
        if self.offset is None:
            raise ConnectionFailure("签名前必须先校验 OKX 服务器时间")
        timestamp = (
            (self.now() + self.offset).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
        query = urlencode(sorted(params.items()))
        request_path = path + ("?" + query if query else "")
        credentials = self.settings.credentials
        signature = base64.b64encode(
            hmac.new(
                credentials.secret_key.encode(),
                (timestamp + "GET" + request_path).encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        return self._call(
            path,
            params,
            {
                "OK-ACCESS-KEY": credentials.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": credentials.passphrase,
                "x-simulated-trading": "1",
                "Content-Type": "application/json",
            },
        )

    def snapshot(self):
        self.sync_time()
        configs = self._get(CONFIG_PATH)
        if len(configs) != 1 or configs[0].get("perm") != "read_only":
            raise ConnectionFailure("无法确认仅 Read 权限；请创建只勾选 Read 的模拟盘 Key")
        account = configs[0]
        mode, position_mode = account.get("acctLv"), account.get("posMode")
        if mode not in {"1", "2", "3", "4"} or position_mode not in {"net_mode", "long_short_mode"}:
            raise ConnectionFailure("账户模式未知，请先在 OKX 模拟交易页面完成账户初始化")
        balances = self._get(BALANCE_PATH)
        positions = self._get(POSITIONS_PATH, {"instType": "SWAP"})
        if len(balances) != 1 or not isinstance(balances[0].get("details"), list):
            raise ConnectionFailure("余额响应不完整")
        safe_balances = []
        for row in balances[0]["details"]:
            if not isinstance(row, dict):
                raise ConnectionFailure("余额明细无效")
            if row.get("ccy") in {"USDT", "BTC", "ETH"}:
                safe_balances.append(
                    {
                        "currency": row["ccy"],
                        "equity": number(row.get("eq")),
                        "available": number(row.get("availBal")),
                    }
                )
        safe_positions = []
        for row in positions:
            if row.get("instId") not in INSTRUMENTS:
                continue
            if row.get("posSide") not in {"long", "short", "net"}:
                raise ConnectionFailure("持仓方向未知")
            safe_positions.append(
                {
                    "instrument": row["instId"],
                    "side": row["posSide"],
                    "contracts": number(row.get("pos")),
                    "average_price": number(row.get("avgPx")),
                    "unrealized_pnl": number(row.get("upl")),
                }
            )
        return {
            "environment": "OKX official demo (read only)",
            "site": self.settings.site,
            "permission": "read_only",
            "account_mode": mode,
            "position_mode": position_mode,
            "total_equity_usd": number(balances[0].get("totalEq")),
            "balances": safe_balances,
            "positions": safe_positions,
            "positions_scope": "仅 BTC/ETH USDT 永续；pos 为张数，totalEq 为 USD 折算权益",
        }

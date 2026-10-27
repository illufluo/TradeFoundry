"""完全离线的协议夹具，绝不表示真实模拟盘已连接。"""

from datetime import UTC, datetime

from tradefoundry.demo_account import (
    BALANCE_PATH,
    CONFIG_PATH,
    TIME_PATH,
    DemoCredentials,
    DemoReadClient,
    DemoSettings,
)

SCENARIOS = ("success", "auth", "permission", "timeout", "environment", "excess-permission")


def mock_account(scenario="success"):
    if scenario not in SCENARIOS:
        raise ValueError("未知 Mock 情况")
    now = datetime(2024, 1, 11, tzinfo=UTC)

    def transport(base, path, params, headers, timeout):
        if scenario == "timeout":
            raise TimeoutError
        if path == TIME_PATH:
            rows = [{"ts": str(int(now.timestamp() * 1000))}]
        elif scenario in {"auth", "permission", "environment"}:
            return {
                "code": {"auth": "50113", "permission": "50120", "environment": "50101"}[scenario],
                "data": [],
            }
        elif path == CONFIG_PATH:
            rows = [
                {
                    "perm": "read_only,trade" if scenario == "excess-permission" else "read_only",
                    "acctLv": "2",
                    "posMode": "net_mode",
                }
            ]
        elif path == BALANCE_PATH:
            rows = [
                {
                    "totalEq": "10000",
                    "details": [
                        {"ccy": "USDT", "eq": "10000", "availBal": "10000"},
                    ],
                }
            ]
        else:
            rows = []
        return {"code": "0", "data": rows}

    settings = DemoSettings(DemoCredentials("offline-key", "offline-secret", "offline-passphrase"))
    return DemoReadClient(settings, transport=transport, now=lambda: now, sleep=lambda _: None)

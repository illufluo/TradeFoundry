import base64
import hashlib
import hmac
import io
import json
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError

import pytest

from tradefoundry import demo_account
from tradefoundry.cli import main
from tradefoundry.demo_account import (
    BALANCE_PATH,
    CONFIG_PATH,
    POSITIONS_PATH,
    TIME_PATH,
    ConnectionFailure,
    DemoCredentials,
    DemoReadClient,
    DemoSettings,
    NoRedirect,
    request_json,
)
from tradefoundry.okx import PublicClient
from tradefoundry.onboarding import first_start, site_public_transport

NOW = datetime(2024, 1, 11, tzinfo=UTC)
SECRETS = ("TEST-API-KEY-DO-NOT-LOG", "TEST-SECRET-DO-NOT-LOG", "TestPassphrase!234")


def settings():
    return DemoSettings(DemoCredentials(*SECRETS))


def client_with(response=None):
    calls = []

    def transport(base, path, params, headers, timeout):
        calls.append((base, path, params, headers))
        if path == TIME_PATH:
            data = [{"ts": str(int(NOW.timestamp() * 1000))}]
        elif path == CONFIG_PATH:
            if response is not None:
                return response
            data = [
                {
                    "perm": "read_only",
                    "acctLv": "2",
                    "posMode": "net_mode",
                    "apiKey": SECRETS[0],
                    "secretKey": SECRETS[1],
                    "label": SECRETS[2],
                }
            ]
        elif path == BALANCE_PATH:
            data = [
                {
                    "totalEq": "10000",
                    "details": [
                        {"ccy": "USDT", "eq": "9999", "availBal": "9000"},
                    ],
                }
            ]
        elif path == POSITIONS_PATH:
            data = [
                {
                    "instId": "BTC-USDT-SWAP",
                    "posSide": "long",
                    "pos": "2",
                    "avgPx": "60000",
                    "upl": "12",
                    "extra": SECRETS[0],
                },
                {"instId": "OTHER", "posSide": "long", "pos": "1"},
            ]
        return {"code": "0", "data": data}

    return DemoReadClient(
        settings(), transport=transport, now=lambda: NOW, sleep=lambda _: None
    ), calls


def test_snapshot_signature_query_demo_header_and_secret_exclusion():
    client, calls = client_with()
    result = client.snapshot()
    assert result["positions"][0]["contracts"] == "2" and len(result["positions"]) == 1
    for _, path, params, headers in calls:
        if path == TIME_PATH:
            assert headers == {}
            continue
        assert headers["x-simulated-trading"] == "1"
        query = "?instType=SWAP" if params else ""
        expected = base64.b64encode(
            hmac.new(
                SECRETS[1].encode(),
                ("2024-01-11T00:00:00.000ZGET" + path + query).encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        assert headers["OK-ACCESS-SIGN"] == expected
    serialized = json.dumps(result) + repr(settings()) + repr(settings().credentials)
    assert all(secret not in serialized for secret in SECRETS)


@pytest.mark.parametrize(
    "code,text",
    [
        ("50101", "环境"),
        ("50105", "Passphrase"),
        ("50113", "签名"),
        ("50119", "站点"),
        ("50120", "权限"),
        ("50102", "时间"),
        ("50110", "IP"),
        ("50123", "Read"),
        ("50011", "限流"),
        (SECRETS[0], "被拒绝"),
    ],
)
def test_error_messages_never_echo_server_content(code, text):
    client, _ = client_with({"code": code, "data": [], "msg": " ".join(SECRETS)})
    with pytest.raises(ConnectionFailure, match=text) as error:
        client.snapshot()
    assert all(secret not in str(error.value) for secret in SECRETS)


@pytest.mark.parametrize("permission", ["read_only,trade", "read_only,withdraw", "trade", "", None])
def test_excess_or_unknown_permissions_stop_before_balance(permission):
    client, calls = client_with(
        {
            "code": "0",
            "data": [
                {"perm": permission, "acctLv": "2", "posMode": "net_mode"},
            ],
        }
    )
    with pytest.raises(ConnectionFailure, match="Read"):
        client.snapshot()
    assert len(calls) == 2


def test_write_paths_and_private_params_blocked_before_transport():
    client, calls = client_with()
    client.sync_time()
    for path, params in (
        ("/api/v5/trade/order", {}),
        (BALANCE_PATH, {"extra": "bad"}),
        (CONFIG_PATH + "?other=1", {}),
    ):
        with pytest.raises(ConnectionFailure):
            client._get(path, params)
    assert len(calls) == 1


def test_time_offset_and_large_skew():
    client, calls = client_with()
    client.now = lambda: NOW - timedelta(seconds=60)
    client.snapshot()
    assert calls[1][3]["OK-ACCESS-TIMESTAMP"] == "2024-01-11T00:00:00.000Z"
    client, _ = client_with()
    client.now = lambda: NOW - timedelta(minutes=10)
    with pytest.raises(ConnectionFailure, match="时间"):
        client.snapshot()


def test_env_loading_precedence_and_safe_errors(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            f'{key}="{value}"'
            for key, value in zip(
                ("OKX_DEMO_API_KEY", "OKX_DEMO_SECRET_KEY", "OKX_DEMO_PASSPHRASE"),
                SECRETS,
                strict=True,
            )
        )
    )
    loaded = DemoSettings.load(path, {"OKX_SITE": "eea"})
    assert loaded.credentials.api_key == SECRETS[0] and loaded.site == "eea"
    path.write_text("UNKNOWN=" + SECRETS[0])
    with pytest.raises(ConnectionFailure) as error:
        DemoSettings.load(path, {})
    assert SECRETS[0] not in str(error.value)
    with pytest.raises(ConnectionFailure, match="凭证"):
        DemoSettings.load(tmp_path / "missing", {})


@pytest.mark.parametrize("site", ["https://evil.test", "live", "www.okx.com"])
def test_custom_site_cannot_receive_credentials(site):
    with pytest.raises(ConnectionFailure):
        DemoSettings(DemoCredentials(*SECRETS), site)


def test_no_redirect_or_public_auth_leak():
    with pytest.raises(ConnectionFailure, match="重定向"):
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test")
    for args in (
        ("https://evil.test", BALANCE_PATH, {}, {"x-simulated-trading": "1"}, 15),
        ("https://openapi.okx.com", BALANCE_PATH, {}, {}, 15),
        ("https://openapi.okx.com", TIME_PATH, {}, {"OK-ACCESS-KEY": SECRETS[0]}, 15),
    ):
        with pytest.raises(ConnectionFailure):
            request_json(*args)


def test_http401_json_and_timeout_scrubbing(monkeypatch):
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError(
                "url",
                401,
                " ".join(SECRETS),
                {},
                io.BytesIO(json.dumps({"code": "50101", "data": [], "msg": SECRETS[0]}).encode()),
            )

    monkeypatch.setattr(demo_account, "build_opener", lambda *args: Opener())
    client = DemoReadClient(settings(), now=lambda: NOW, sleep=lambda _: None)
    client.offset = timedelta(0)
    with pytest.raises(ConnectionFailure, match="环境"):
        client._get(CONFIG_PATH)
    client.transport = lambda *args: (_ for _ in ()).throw(TimeoutError(SECRETS[0]))
    with pytest.raises(ConnectionFailure) as error:
        client._get(CONFIG_PATH)
    assert SECRETS[0] not in str(error.value)


def test_offline_ignores_real_env_and_does_not_persist_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OKX_DEMO_API_KEY", SECRETS[0])
    monkeypatch.setattr(DemoSettings, "load", lambda *args: pytest.fail("不得加载真实密钥"))
    assert main(["start", "--offline", "--output", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["account_connected"] is False
    assert SECRETS[0] not in output
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert all(secret.encode() not in path.read_bytes() for secret in SECRETS)


@pytest.mark.parametrize(
    "scenario", ["auth", "permission", "environment", "timeout", "excess-permission"]
)
def test_offline_failure_scenarios(tmp_path, capsys, scenario):
    assert main(["start", "--offline", "--scenario", scenario, "--output", str(tmp_path)]) == 2
    assert "错误" in capsys.readouterr().err


def test_account_only_never_persists_private_data(tmp_path):
    client, _ = client_with()
    result = first_start(settings(), account_client=client, account_only=True, output=tmp_path)
    assert result["account_connected"] and list(tmp_path.iterdir()) == []


def test_public_site_transport_has_no_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "tradefoundry.onboarding.request_json",
        lambda *args: calls.append(args) or {"code": "0", "data": []},
    )
    site_public_transport("eea")(TIME_PATH, {})
    assert calls[0][0] == "https://eea.okx.com" and calls[0][3] == {}


def test_full_start_mock_private_and_public_do_not_persist_credentials(tmp_path):
    end = NOW - timedelta(hours=1)
    start = end - timedelta(days=1)

    def transport(path, params):
        if path.endswith("/instruments"):
            data = [{"instId": params["instId"], "ctType": "linear", "settleCcy": "USDT"}]
        else:
            data = [
                [
                    str(int((start + timedelta(hours=i)).timestamp() * 1000)),
                    "100",
                    "100",
                    "100",
                    "100",
                    "10",
                    "1",
                    "100",
                    "1",
                ]
                for i in reversed(range(24))
            ]
        return {"code": "0", "data": data}

    client, _ = client_with()
    public = PublicClient(transport=transport, sleep=lambda _: None)
    result = first_start(
        settings(), output=tmp_path, days=1, account_client=client, public_client=public, now=NOW
    )
    assert result["market_ready"] and len(result["quality"]) == 2
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert all(secret.encode() not in path.read_bytes() for secret in SECRETS)


def test_account_success_and_public_failure_are_distinct(tmp_path):
    client, _ = client_with()
    public = PublicClient(
        transport=lambda *args: {"code": "50000", "data": []}, sleep=lambda _: None
    )
    result = first_start(
        settings(), output=tmp_path, days=1, account_client=client, public_client=public, now=NOW
    )
    assert result["account_connected"] and not result["market_ready"]
    assert len(result["failures"]) == 2 and (tmp_path / "market.html").exists()

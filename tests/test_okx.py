from datetime import UTC, datetime, timedelta
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from tradefoundry.okx import (
    HISTORY_PATH,
    INSTRUMENT_PATH,
    DataError,
    PublicClient,
    RequestBudgetExceeded,
    public_get,
)
from tradefoundry.warehouse import Warehouse, milliseconds, parse_page, sync_history

START = datetime(2024, 1, 1, tzinfo=UTC)


def raw_row(hour, *, confirm="1", price="100"):
    return [
        str(milliseconds(START + timedelta(hours=hour))),
        price,
        price,
        price,
        price,
        "1000",
        "10",
        "1000",
        confirm,
    ]


def mock_client(pages, *, instrument="BTC-USDT-SWAP", max_requests=100):
    calls = []
    iterator = iter(pages)

    def transport(path, params):
        calls.append((path, params))
        if path == INSTRUMENT_PATH:
            data = [
                {
                    "instId": instrument,
                    "ctType": "linear",
                    "settleCcy": "USDT",
                    "ctVal": "0.01",
                    "lotSz": "0.01",
                }
            ]
        else:
            item = next(iterator)
            if isinstance(item, Exception):
                raise item
            data = item
        return {"code": "0", "data": data}

    return PublicClient(
        transport=transport, sleep=lambda _: None, attempts=1, max_requests=max_requests
    ), calls


@pytest.mark.parametrize("instrument", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
@pytest.mark.parametrize(
    "interval,api_bar,step", [("1h", "1H", 1), ("4h", "4H", 4), ("1day", "1Dutc", 24)]
)
def test_pagination_dedup_and_utc(tmp_path, instrument, interval, api_bar, step):
    client, calls = mock_client(
        [
            [raw_row(5 * step), raw_row(4 * step)],
            [raw_row(4 * step), raw_row(3 * step), raw_row(2 * step)],
            [raw_row(step), raw_row(0)],
        ],
        instrument=instrument,
    )
    warehouse = Warehouse(tmp_path)
    report = sync_history(
        warehouse, client, instrument, interval, START, START + timedelta(hours=6 * step)
    )
    assert report["complete"] and report["rows"] == 6
    assert report["download_state"] == "finished"
    history = [params for path, params in calls if path == HISTORY_PATH]
    assert [int(params["after"]) for params in history] == [
        milliseconds(START + timedelta(hours=h * step)) for h in (6, 4, 2)
    ]
    assert all(params["bar"] == api_bar and params["limit"] == "100" for params in history)
    rows = warehouse.rows(instrument, interval)
    assert len(rows) == 6
    assert rows[0]["available_at"] == rows[0]["observed_at"]
    assert rows[0]["volume_contracts"] == 1000
    assert rows[0]["volume_base"] == 10
    assert rows[0]["volume_quote"] == 1000
    assert rows[0]["raw_json"]


def test_resume_after_page_limit_and_noop_when_finished(tmp_path):
    warehouse = Warehouse(tmp_path)
    args = ("BTC-USDT-SWAP", "1h", START, START + timedelta(hours=4))
    client, _ = mock_client([[raw_row(3), raw_row(2)]])
    first = sync_history(warehouse, client, *args, max_pages=1)
    assert first["download_state"] == "partial" and first["missing_count"] == 2
    client, calls = mock_client([[raw_row(1), raw_row(0)]])
    second = sync_history(warehouse, client, *args)
    assert int(calls[1][1]["after"]) == milliseconds(START + timedelta(hours=2))
    assert second["complete"]
    client, calls = mock_client([])
    assert sync_history(warehouse, client, *args)["pages_this_run"] == 0
    assert calls == []


def test_request_budget_preserves_previous_checkpoint(tmp_path):
    warehouse = Warehouse(tmp_path)
    args = ("BTC-USDT-SWAP", "1h", START, START + timedelta(hours=4))
    client, _ = mock_client([[raw_row(3), raw_row(2)]], max_requests=2)
    with pytest.raises(RequestBudgetExceeded):
        sync_history(warehouse, client, *args)
    assert len(warehouse.rows(*args[:2])) == 2
    client, calls = mock_client([[raw_row(1), raw_row(0)]])
    assert sync_history(warehouse, client, *args)["complete"]
    assert int(calls[1][1]["after"]) == milliseconds(START + timedelta(hours=2))


def test_gaps_and_unclosed_are_never_filled(tmp_path):
    client, _ = mock_client([[raw_row(3), raw_row(2, confirm="0"), raw_row(0)]])
    warehouse = Warehouse(tmp_path)
    report = sync_history(
        warehouse, client, "BTC-USDT-SWAP", "1h", START, START + timedelta(hours=4)
    )
    assert not report["complete"]
    assert report["missing_count"] == 2
    assert len(warehouse.rows("BTC-USDT-SWAP", "1h")) == 2
    client, _ = mock_client([[raw_row(3), raw_row(2), raw_row(1), raw_row(0)]])
    assert sync_history(
        warehouse, client, "BTC-USDT-SWAP", "1h", START, START + timedelta(hours=4), refresh=True
    )["complete"]


def test_empty_history_is_exhausted_not_complete(tmp_path):
    client, _ = mock_client([[]])
    report = sync_history(
        Warehouse(tmp_path), client, "BTC-USDT-SWAP", "1h", START, START + timedelta(hours=3)
    )
    assert report["download_state"] == "exhausted"
    assert report["rows"] == 0 and report["missing_count"] == 3


def test_conflicting_prices_and_stalled_cursor_are_rejected(tmp_path):
    warehouse = Warehouse(tmp_path)
    args = ("BTC-USDT-SWAP", "1h", START, START + timedelta(hours=3))
    client, _ = mock_client([[raw_row(2), raw_row(0)]])
    sync_history(warehouse, client, *args)
    client, _ = mock_client([[raw_row(2, price="101"), raw_row(1), raw_row(0)]])
    with pytest.raises(DataError, match="冲突"):
        sync_history(warehouse, client, *args, refresh=True)
    client, _ = mock_client([[raw_row(3)]])
    with pytest.raises(DataError, match="游标"):
        sync_history(warehouse, client, *args, refresh=True)


def test_incremental_range_retains_old_rows(tmp_path):
    warehouse = Warehouse(tmp_path)
    client, _ = mock_client([[raw_row(1), raw_row(0)]])
    sync_history(warehouse, client, "BTC-USDT-SWAP", "1h", START, START + timedelta(hours=2))
    client, _ = mock_client([[raw_row(3), raw_row(2), raw_row(1)]])
    sync_history(
        warehouse,
        client,
        "BTC-USDT-SWAP",
        "1h",
        START + timedelta(hours=1),
        START + timedelta(hours=4),
    )
    assert warehouse.quality("BTC-USDT-SWAP", "1h", START, START + timedelta(hours=4))["rows"] == 4


def test_crash_after_page_before_checkpoint_is_idempotent(tmp_path, monkeypatch):
    warehouse = Warehouse(tmp_path)
    args = ("BTC-USDT-SWAP", "1h", START, START + timedelta(hours=2))
    client, _ = mock_client([[raw_row(1), raw_row(0)]])
    original = warehouse.save_checkpoint
    monkeypatch.setattr(warehouse, "save_checkpoint", lambda *a: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        sync_history(warehouse, client, *args)
    monkeypatch.setattr(warehouse, "save_checkpoint", original)
    client, _ = mock_client([[raw_row(1), raw_row(0)]])
    assert sync_history(warehouse, client, *args)["rows"] == 2
    assert len(list(tmp_path.rglob("*.parquet"))) == 1


def test_partition_lock_refuses_second_writer(tmp_path):
    warehouse = Warehouse(tmp_path)
    with warehouse.lock("BTC-USDT-SWAP", "1h"):
        with pytest.raises(DataError, match="已有下载进程"):
            with warehouse.lock("BTC-USDT-SWAP", "1h"):
                pass


def test_corrupt_parquet_rejected(tmp_path):
    import pyarrow.parquet as pq

    warehouse = Warehouse(tmp_path)
    client, _ = mock_client([[raw_row(1), raw_row(0)]])
    sync_history(warehouse, client, "BTC-USDT-SWAP", "1h", START, START + timedelta(hours=2))
    path = next(tmp_path.rglob("*.parquet"))
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["close"] += 1
    pq.write_table(type(table).from_pylist(rows, schema=table.schema), path)
    with pytest.raises(DataError, match="哈希不匹配"):
        warehouse.rows("BTC-USDT-SWAP", "1h")


@pytest.mark.parametrize(
    "response",
    [
        {"code": "51000", "data": []},
        {"code": "0", "data": "invalid"},
        [],
    ],
)
def test_bad_response_does_not_retry(response):
    client = PublicClient(transport=lambda *args: response, sleep=lambda _: None)
    with pytest.raises(DataError):
        client.history("BTC-USDT-SWAP", "1h", 1)
    assert client.requests == 1


def test_wrong_contract_and_future_close_rejected():
    client = PublicClient(
        transport=lambda *args: {
            "code": "0",
            "data": [
                {"instId": "BTC-USDT-SWAP", "ctType": "inverse", "settleCcy": "BTC"},
            ],
        },
        sleep=lambda _: None,
    )
    with pytest.raises(DataError, match="USDT"):
        client.instrument("BTC-USDT-SWAP")
    with pytest.raises(DataError, match="收盘"):
        parse_page([raw_row(0)], "1h", START)


@pytest.mark.parametrize(
    "bad",
    [
        ["bad"],
        raw_row(0, confirm="2"),
        raw_row(0, price="nan"),
        raw_row(0, price="-1"),
        ["bad-time", *raw_row(0)[1:]],
        raw_row(0)[:5] + ["-1", "1", "1", "1"],
    ],
)
def test_invalid_api_rows_rejected(bad):
    with pytest.raises(ValueError):
        parse_page([bad], "1h", datetime.now(UTC))


def test_retry_rate_limit_and_http_retry_after():
    sleeps = []
    responses = iter([{"code": "50011", "data": []}, {"code": "0", "data": []}])
    client = PublicClient(
        transport=lambda *args: next(responses), sleep=sleeps.append, clock=lambda: 0
    )
    assert client.history("BTC-USDT-SWAP", "1h", 1) == []
    assert client.requests == 2 and 1 in sleeps and 0.15 in sleeps
    headers = Message()
    headers["Retry-After"] = "4"
    sequence = iter([HTTPError("url", 429, "slow", headers, None), {"code": "0", "data": []}])

    def transport(*args):
        result = next(sequence)
        if isinstance(result, Exception):
            raise result
        return result

    client = PublicClient(transport=transport, sleep=sleeps.append)
    assert client.history("BTC-USDT-SWAP", "1h", 1) == []
    assert 4 in sleeps


def test_network_failure_is_bounded_and_private_paths_blocked():
    def broken(*args):
        raise URLError("offline")

    client = PublicClient(transport=broken, sleep=lambda _: None)
    with pytest.raises(DataError, match="3 次"):
        client.history("BTC-USDT-SWAP", "1h", 1)
    assert client.requests == 3
    for call in (
        lambda: client.get("/api/v5/trade/order", {}),
        lambda: public_get("/api/v5/trade/order", {}),
    ):
        with pytest.raises(DataError):
            call()

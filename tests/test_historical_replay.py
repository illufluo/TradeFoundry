import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tradefoundry.config import Config
from tradefoundry.engine import backtest
from tradefoundry.historical_replay import replay_payload, run_research
from tradefoundry.market import Bar, MarketData
from tradefoundry.okx import DataError, PublicClient
from tradefoundry.store import Store
from tradefoundry.strategy import Strategy
from tradefoundry.warehouse import Warehouse, sync_history

START = datetime(2024, 1, 1, tzinfo=UTC)


@pytest.fixture
def warehouse_quality(tmp_path):
    warehouse = Warehouse(tmp_path / "warehouse")

    def transport(path, params):
        if path.endswith("/instruments"):
            data = [
                {
                    "instId": params["instId"],
                    "ctType": "linear",
                    "settleCcy": "USDT",
                    "ctValCcy": params["instId"].split("-")[0],
                    "ctVal": "0.1",
                    "ctMult": "2",
                    "lotSz": "0.01",
                    "minSz": "0.01",
                    "tickSz": "0.1",
                    "state": "live",
                }
            ]
        else:
            data = [
                [
                    str(int((START + timedelta(hours=i)).timestamp() * 1000)),
                    str(100 + i),
                    str(100 + i),
                    str(100 + i),
                    str(100 + i),
                    "100",
                    "20",
                    str(20 * (100 + i)),
                    "1",
                ]
                for i in reversed(range(48))
            ]
        return {"code": "0", "data": data}

    client = PublicClient(transport=transport, sleep=lambda _: None)
    qualities = [
        sync_history(warehouse, client, inst, "1h", START, START + timedelta(hours=48))
        for inst in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    ]
    return warehouse, qualities


def test_real_data_adapter_preserves_observation_times_and_marks_assumptions(warehouse_quality):
    warehouse, qualities = warehouse_quality
    before = warehouse.rows("BTC-USDT-SWAP", "1h")
    result = replay_payload(warehouse, qualities[0], Config())
    assert result["funding_included"] is False
    assert result["historical_spec_verified"] is False
    assert result["historical_release_verified"] is False
    assert result["data"]["contract_value"] == 0.2
    assert result["data"]["contract_step"] == 0.01
    assert result["data"]["bars"][0]["available_at"] == START + timedelta(hours=2)
    assert result["actual_observation_times"][0]["available_at"] == str(before[0]["available_at"])
    assert warehouse.rows("BTC-USDT-SWAP", "1h") == before
    assert all(
        fill["timestamp"] >= START + timedelta(hours=9) for fill in result["result"]["fills"]
    )


def test_replay_reports_and_recording(warehouse_quality, tmp_path):
    warehouse, qualities = warehouse_quality
    result = run_research(warehouse, qualities, tmp_path)
    assert result["research_ready"] and result["trusted_backtest_ready"] is False
    for item in result["research_runs"]:
        html = (tmp_path / "research" / f"{item['instrument']}.html").read_text()
        assert "未计资金费" in html and "ctMult" in html and "lotSz" in html
        payload = Store(tmp_path / "research.sqlite3").get(item["experiment_id"])
        assert payload["current_spec_snapshot"]["raw"]["ctMult"] == "2"
        assert "account" not in payload and "credentials" not in payload


@pytest.mark.parametrize(
    "mutation", ["missing_multiplier", "wrong_currency", "inconsistent_volume"]
)
def test_unknown_or_inconsistent_units_are_rejected(warehouse_quality, mutation):
    warehouse, qualities = warehouse_quality
    with warehouse.lock("BTC-USDT-SWAP", "1h"):
        snapshot = {
            "observed_at": "2099-01-01T00:00:00+00:00",
            "raw": {
                "instId": "BTC-USDT-SWAP",
                "ctType": "linear",
                "settleCcy": "USDT",
                "ctValCcy": "BTC",
                "ctVal": "0.1",
                "ctMult": "2",
                "lotSz": "0.01",
                "minSz": "0.01",
                "tickSz": "0.1",
                "state": "live",
            },
        }
        if mutation == "missing_multiplier":
            snapshot["raw"].pop("ctMult")
        elif mutation == "wrong_currency":
            snapshot["raw"]["ctValCcy"] = "USDT"
        else:
            snapshot["raw"]["ctVal"] = "10"
        warehouse.save_instrument("BTC-USDT-SWAP", snapshot)
    with pytest.raises(DataError):
        replay_payload(warehouse, qualities[0], Config())


def test_incomplete_or_changed_quality_cannot_replay(warehouse_quality):
    warehouse, qualities = warehouse_quality
    for change in ({"complete": False}, {"data_hash": "modified"}):
        with pytest.raises(DataError):
            replay_payload(warehouse, qualities[0] | change, Config())


def test_fractional_contracts_minimums_and_ticks():
    bars = tuple(
        Bar(START + timedelta(hours=i), START + timedelta(hours=i + 1), 100, 100, 100, 100, 100)
        for i in range(4)
    )
    data = MarketData(
        "BTC-USDT-SWAP",
        "1h",
        "synthetic-test",
        2,
        bars,
        contract_step=0.01,
        minimum_contracts=0.01,
        price_tick=0.1,
    )
    config = Config(
        initial_cash=1000, position_fraction=0.5, taker_fee=0, spread_bps=0, slippage_bps=0
    )
    result = backtest(data, Strategy("buy_hold"), config)
    assert result.fills[0].contracts == 2.5 and result.fills[0].notional == 500
    assert result.metrics["final_equity"] == 1000
    assert not backtest(replace(data, minimum_contracts=3), Strategy("buy_hold"), config).fills
    adverse = backtest(data, Strategy("buy_hold"), replace(config, slippage_bps=1))
    assert adverse.fills[0].price == 100.1 and adverse.fills[1].price == 99.9
    with pytest.raises(ValueError, match="步长"):
        replace(data, contract_step=0.03, minimum_contracts=0.01).validate()


def test_failed_replay_is_archived(warehouse_quality, tmp_path):
    warehouse, qualities = warehouse_quality
    result = run_research(warehouse, [qualities[0] | {"complete": False}], tmp_path)
    assert not result["research_ready"]
    records = Store(tmp_path / "research.sqlite3").list()
    assert records[0]["status"] == "rejected"
    assert json.loads(json.dumps(records[0]["payload"]))["instrument"] == "BTC-USDT-SWAP"

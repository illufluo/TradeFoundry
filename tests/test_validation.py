import json
from dataclasses import replace

import pytest

from tradefoundry import validation
from tradefoundry.cli import main
from tradefoundry.config import Config
from tradefoundry.market import sample_data
from tradefoundry.store import Store
from tradefoundry.strategy import Strategy
from tradefoundry.validation import (
    SplitPlan,
    ValidationLedger,
    evaluate_development,
    walk_forward,
)


@pytest.fixture
def inputs():
    return sample_data(), Strategy(), Config(), SplitPlan(120, 180, 240)


def test_development_never_backtests_sealed(inputs, monkeypatch):
    data, strategy, config, plan = inputs
    observed = []
    original = validation.backtest

    def spy(partition, strategy, config):
        observed.extend(bar.timestamp for bar in partition.bars)
        return original(partition, strategy, config)

    monkeypatch.setattr(validation, "backtest", spy)
    result = evaluate_development(*inputs)
    assert set(result["partitions"]) == {"train", "validation"}
    assert max(observed) < data.bars[plan.validation_end].timestamp
    assert plan.partition(data, "train").bars[-1].timestamp < (
        plan.partition(data, "validation").bars[0].timestamp
    )
    changed = replace(
        data,
        bars=data.bars[:180]
        + tuple(
            replace(bar, open=bar.open * 2, high=bar.high * 2, low=bar.low * 2, close=bar.close * 2)
            for bar in data.bars[180:]
        ),
    )
    assert (
        result["partitions"] == evaluate_development(changed, strategy, config, plan)["partitions"]
    )


def test_freeze_is_required_and_final_access_is_once(tmp_path, inputs):
    store = Store(tmp_path / "experiments.sqlite3")
    ledger = ValidationLedger(store)
    with pytest.raises(ValueError, match="先冻结"):
        ledger.final_test(*inputs)
    freeze = ledger.freeze(*inputs)
    assert ledger.freeze(*inputs) == freeze
    result = ledger.final_test(*inputs)
    assert result["status"] == "completed"
    assert store.get(result["experiment_id"])["phase"] == "sealed_final_test"
    with pytest.raises(ValueError, match="已访问"):
        ledger.final_test(*inputs)
    assert len(ledger.audit()) == 1
    assert ledger.audit()[0]["status"] == "completed"


def test_freeze_rejects_parameter_and_code_changes(tmp_path, inputs, monkeypatch):
    ledger = ValidationLedger(Store(tmp_path / "experiments.sqlite3"))
    data, strategy, config, plan = inputs
    ledger.freeze(*inputs)
    changed = (data, replace(strategy, fast=4), config, plan)
    with pytest.raises(ValueError, match="已冻结"):
        ledger.freeze(*changed)
    with pytest.raises(ValueError, match="先冻结"):
        ledger.final_test(*changed)
    with pytest.raises(ValueError, match="已冻结"):
        ledger.freeze(data, strategy, config, SplitPlan(100, 170, 240))
    monkeypatch.setattr(validation, "engine_fingerprint", lambda: "modified")
    with pytest.raises(ValueError, match="先冻结"):
        ledger.final_test(*inputs)


def test_failed_final_test_stays_audited_and_cannot_retry(tmp_path, inputs, monkeypatch):
    ledger = ValidationLedger(Store(tmp_path / "experiments.sqlite3"))
    ledger.freeze(*inputs)

    def fail(*args):
        raise RuntimeError("模拟计算失败")

    monkeypatch.setattr(validation, "backtest", fail)
    with pytest.raises(RuntimeError):
        ledger.final_test(*inputs)
    assert ledger.audit()[0]["status"] == "failed"
    assert ledger.audit()[0]["error"] == "RuntimeError"
    with pytest.raises(ValueError, match="已访问"):
        ledger.final_test(*inputs)


def test_overlapping_windows_are_not_independent(inputs):
    data, strategy, config, _ = inputs
    result = walk_forward(
        data, strategy, config, train_bars=60, validation_bars=30, step_bars=10, development_end=180
    )
    assert result["overlapping_validation"]
    assert result["independent_sample_count"] is None
    assert all(window["validation_indices"][1] <= 180 for window in result["windows"])


@pytest.mark.parametrize(
    "values", [(1, 180, 240), (120, 121, 240), (120, 239, 240), (120, 180, True)]
)
def test_invalid_split_plan(values):
    with pytest.raises(ValueError):
        SplitPlan(*values)


def test_validation_cli_offline(tmp_path, capsys):
    args = ["--db", str(tmp_path / "experiments.sqlite3")]
    assert main(["validate-demo", *args]) == 0
    assert json.loads(capsys.readouterr().out)["sealed_accessed"] is False
    assert main(["freeze-demo", *args]) == 0
    capsys.readouterr()
    assert main(["final-demo-test", *args]) == 0
    capsys.readouterr()
    assert main(["final-demo-test", *args]) == 2
    assert "已访问" in capsys.readouterr().err
    assert main(["test-audit", *args]) == 0
    assert json.loads(capsys.readouterr().out)[0]["status"] == "completed"

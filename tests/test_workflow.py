import json
import sqlite3

import pytest

from tradefoundry.cli import main
from tradefoundry.config import Config
from tradefoundry.market import sample_data
from tradefoundry.store import Store


@pytest.mark.parametrize("instrument", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
def test_offline_demo_and_export(tmp_path, capsys, instrument):
    assert main(["demo", "--instrument", instrument, "--output", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    path = tmp_path / "reports" / f"{result['experiment_id']}.html"
    html = path.read_text()
    assert "plotly.js" in html
    assert "synthetic-fixture" in html
    assert "资金费" in html
    store = Store(tmp_path / "experiments.sqlite3")
    assert len(store.list()) == 1
    payload = store.get(result["experiment_id"])
    assert payload["data_hash"] == sample_data(instrument).digest
    assert payload["strategy_hash"]
    assert payload["code_revision"]
    assert (
        main(
            [
                "report",
                result["experiment_id"],
                "--db",
                str(store.path),
                "--output",
                str(tmp_path / "export.html"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (tmp_path / "export.html").exists()
    assert main(["experiments", "--db", str(store.path)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == result["experiment_id"]


def test_store_idempotence_and_sql_parameters(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    first = store.record({"strategy": "基准"})
    assert store.record({"strategy": "基准"}) == first
    assert len(store.list()) == 1
    with pytest.raises(ValueError, match="不存在"):
        store.get("'; DROP TABLE experiments; --")
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 1


def test_invalid_config_and_missing_report(tmp_path, capsys):
    path = tmp_path / "bad.toml"
    path.write_text("live = true\n")
    with pytest.raises(TypeError):
        Config.load(path)
    assert (
        main(
            [
                "report",
                "missing",
                "--db",
                str(tmp_path / "empty.sqlite3"),
                "--output",
                str(tmp_path / "report.html"),
            ]
        )
        == 2
    )
    assert "实验不存在" in capsys.readouterr().err

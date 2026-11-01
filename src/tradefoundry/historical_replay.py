"""真实成交 K 线的条件重放；明确不声称历史规格、发布延迟或资金费已被证明。"""

import json
import math
import sqlite3
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from html import escape

from tradefoundry.config import Config
from tradefoundry.engine import COST_VERSION, LIMITATIONS, METRIC_VERSION, backtest
from tradefoundry.market import INSTRUMENTS, Bar, MarketData, utc
from tradefoundry.okx import DataError
from tradefoundry.report import write_report
from tradefoundry.store import Store, code_revision
from tradefoundry.strategy import Strategy

ASSUMPTIONS = [
    "真实 OKX 成交 K 线，非合成行情；本报告是条件重放，不是已验证的合约历史净收益。",
    "历史合约规格未经独立验证。使用采集时当前规格作为重放情景，并检查历史成交量单位一致性。",
    "历史实际发布时间未知；重放副本假设收盘后一小时可用。原始 available_at/observed_at 不改写。",
    "资金费未取得，不编造费率，也不认定实际资金费为零；所有收益均未计资金费。",
    "仍缺少标记价、强平、盘口和部分成交模型。无杠杆、小额全额 Taker 成交是简化假设。",
    "仅作首次接入和计算流程演示，没有样本外或封存测试，不作为有效策略筛选结果。",
]


def current_spec(warehouse, instrument):
    with sqlite3.connect(warehouse.database) as connection:
        rows = connection.execute(
            "SELECT payload FROM instrument_snapshots WHERE instrument=?", (instrument,)
        ).fetchall()
    if not rows:
        raise DataError("缺少采集时的合约规格快照，拒绝重放")
    snapshot = max((json.loads(row[0]) for row in rows), key=lambda item: item["observed_at"])
    raw = snapshot["raw"]
    if (
        instrument not in INSTRUMENTS
        or raw.get("instId") != instrument
        or raw.get("ctType") != "linear"
        or raw.get("settleCcy") != "USDT"
        or raw.get("ctValCcy") != instrument.split("-")[0]
        or raw.get("state") != "live"
    ):
        raise DataError("当前合约规格不支持 USDT 线性合约重放")
    values = {}
    for name in ("ctVal", "ctMult", "lotSz", "minSz", "tickSz"):
        try:
            value = Decimal(raw[name])
            if not value.is_finite() or value <= 0 or not math.isfinite(float(value)):
                raise InvalidOperation
        except (InvalidOperation, KeyError, TypeError, ValueError):
            raise DataError("合约规格缺失或非法，不推定默认面值/乘数/步长") from None
        values[name] = value
    if values["minSz"] % values["lotSz"]:
        raise DataError("合约最小数量与步长不一致")
    return snapshot, values


def replay_payload(warehouse, quality, config):
    if not quality["complete"] or quality["interval"] != "1h":
        raise DataError("仅对无缺口的 1h 行情运行条件重放")
    instrument = quality["instrument"]
    start, end = utc(quality["requested_start"]), utc(quality["requested_end_exclusive"])
    fresh = warehouse.quality(instrument, "1h", start, end)
    if not fresh["complete"] or fresh["data_hash"] != quality["data_hash"]:
        raise DataError("质量报告与当前数据不一致，拒绝重放")
    snapshot, spec = current_spec(warehouse, instrument)
    rows = [row for row in warehouse.rows(instrument, "1h") if start <= row["timestamp"] < end]
    base_per_contract = spec["ctVal"] * spec["ctMult"]
    # volCcy 为基础币量，vol 为张数；该检查只能发现不一致，不能证明历史规格。
    for row in rows:
        if row["volume_contracts"] > 0:
            expected = Decimal(str(row["volume_contracts"])) * base_per_contract
            actual = Decimal(str(row["volume_base"]))
            if abs(expected - actual) > max(
                Decimal("0.00000001"), abs(expected) * Decimal("0.00001")
            ):
                raise DataError("历史成交量与当前合约单位不一致，拒绝套用当前规格")
    data = MarketData(
        instrument,
        "1h",
        quality["source"] + ":conditional-replay",
        float(base_per_contract),
        tuple(
            Bar(
                row["timestamp"],
                row["timestamp"] + timedelta(hours=2),
                *(row[key] for key in ("open", "high", "low", "close", "volume_contracts")),
            )
            for row in rows
        ),
        contract_step=float(spec["lotSz"]),
        minimum_contracts=float(spec["minSz"]),
        price_tick=float(spec["tickSz"]),
    ).validate()
    strategy = Strategy()
    # 研究资金独立于模拟账户余额；不使用账户快照作成本配置。
    config = replace(config, output_dir="public-research", rebate_confirmed=False)
    result = backtest(data, strategy, config)
    return {
        "phase": "conditional_real_history_replay",
        "instrument": instrument,
        "source": data.source,
        "data_hash": data.digest,
        "warehouse_data_hash": quality["data_hash"],
        "data": asdict(data),
        "strategy": asdict(strategy),
        "strategy_hash": strategy.digest,
        "config": asdict(config),
        "cost_version": COST_VERSION,
        "metric_version": METRIC_VERSION,
        "code_revision": code_revision(),
        "window": [str(start), str(end)],
        "current_spec_snapshot": snapshot,
        "quality": quality,
        "actual_observation_times": [
            {
                "timestamp": str(row["timestamp"]),
                "available_at": str(row["available_at"]),
                "observed_at": str(row["observed_at"]),
            }
            for row in rows
        ],
        "historical_spec_verified": False,
        "historical_release_verified": False,
        "funding_included": False,
        "limitations": ASSUMPTIONS + LIMITATIONS,
        "report_title": "真实行情条件重放（未计资金费，历史规格与发布时间未核实）",
        "metric_notice": "表中净收益只扣已建模手续费/价差/滑点，未计资金费；不是完整合约净收益。",
        "extra_metadata": {
            "spec_observed_at": snapshot["observed_at"],
            "current_spec_scenario": {key: str(value) for key, value in spec.items()},
            "base_currency_per_contract": str(base_per_contract),
            "quantity_unit": "张；支持按 lotSz 取整的小数张数",
            "historical_spec_verified": False,
            "availability_assumption": "收盘后一小时可用，最早再下一根开盘成交",
        },
        "result": result.to_dict(),
        "benchmark": backtest(data, Strategy("buy_hold"), config).to_dict(),
        "fee_sensitivity": {
            "double_fee_net_return": backtest(
                data, strategy, replace(config, taker_fee=config.taker_fee * 2)
            ).metrics["net_return"]
        },
    }


def run_research(warehouse, qualities, output, config=None):
    config = config or Config()
    store = Store(output / "research.sqlite3")
    results, failures = [], []
    for quality in qualities:
        instrument = quality["instrument"]
        try:
            payload = replay_payload(warehouse, quality, config)
            experiment_id = store.record(payload)
            report = output / "research" / f"{instrument}.html"
            write_report(payload, report, experiment_id)
            results.append(
                {
                    "instrument": instrument,
                    "experiment_id": experiment_id,
                    "report": str(report.resolve()),
                    "metrics_excluding_funding": payload["result"]["metrics"],
                }
            )
        except (DataError, ValueError) as error:
            # 仅本模块固定的公共数据校验说明；从不接收账户或凭证对象。
            store.record(
                {
                    "phase": "conditional_real_history_replay",
                    "instrument": instrument,
                    "quality": quality,
                    "error": str(error),
                },
                status="rejected",
            )
            failures.append(instrument + "：" + str(error))
    links = "".join(
        f'<li><a href="research/{escape(item["instrument"])}.html">'
        f"{escape(item['instrument'])}</a></li>"
        for item in results
    )
    notes = "".join(f"<li>{escape(item)}</li>" for item in ASSUMPTIONS)
    errors = "".join(f"<li>{escape(item)}</li>" for item in failures)
    index = output / "research.html"
    index.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        "<title>真实行情条件重放</title><style>body{font:17px system-ui;"
        "max-width:950px;margin:40px auto;padding:20px;line-height:1.7}</style>"
        "<h1>真实行情条件重放</h1><ul>"
        + notes
        + "</ul><h2>报告</h2><ul>"
        + links
        + "</ul><h2>未运行项目</h2><ul>"
        + errors
        + "</ul></html>",
        encoding="utf-8",
    )
    return {
        "research_ready": len(results) == 2 and not failures,
        "research_runs": results,
        "research_failures": failures,
        "research_report": str(index.resolve()),
        "trusted_backtest_ready": False,
    }

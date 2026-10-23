from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tradefoundry.config import Config
from tradefoundry.engine import backtest
from tradefoundry.market import Bar, MarketData, sample_data
from tradefoundry.strategy import Strategy


def market(prices=(100, 100, 100, 100)):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return MarketData(
        "BTC-USDT-SWAP",
        "1h",
        "synthetic-test",
        1.0,
        tuple(
            Bar(
                start + timedelta(hours=i),
                start + timedelta(hours=i + 1),
                price,
                price,
                price,
                price,
                1000,
            )
            for i, price in enumerate(prices)
        ),
    )


def config(**kwargs):
    return Config(initial_cash=1000, position_fraction=0.5, spread_bps=0, slippage_bps=0, **kwargs)


def test_known_round_trip_and_gross_fee():
    result = backtest(market(), Strategy("buy_hold"), config(taker_fee=0.01))
    assert [(x.side, x.contracts, x.notional) for x in result.fills] == [
        ("buy", 4, 400),
        ("sell", 4, 400),
    ]
    assert result.metrics["gross_fees"] == 8
    assert result.metrics["final_equity"] == 992
    assert result.metrics["net_return"] == pytest.approx(-0.008)


def test_rebate_is_not_immediate_cash():
    result = backtest(
        market(),
        Strategy("buy_hold"),
        config(taker_fee=0.01, rebate_confirmed=True),
    )
    assert result.metrics["rebates_received"] == 0
    assert result.metrics["rebates_pending"] == pytest.approx(1.6)
    assert result.metrics["final_equity"] == 992
    assert result.equity[2].cash == 596


def test_rebates_settle_separately_after_delay():
    result = backtest(
        market((100,) * 30),
        Strategy("buy_hold"),
        config(taker_fee=0.01, rebate_confirmed=True),
    )
    assert result.metrics["rebates_received"] == pytest.approx(0.8)
    assert result.metrics["rebates_pending"] == pytest.approx(0.8)
    assert result.rebates[0].timestamp == market().bars[0].timestamp + timedelta(hours=25)
    assert result.metrics["final_equity"] == pytest.approx(992.8)


def test_no_fee_rebate_without_confirmation():
    result = backtest(market(), Strategy("buy_hold"), config())
    assert result.metrics["rebates_pending"] == 0


def test_signal_executes_next_bar_and_honors_available_at():
    data = market()
    result = backtest(data, Strategy("buy_hold"), config())
    assert result.fills[0].timestamp == data.bars[1].timestamp
    delayed = replace(
        data,
        bars=tuple(
            replace(bar, available_at=bar.available_at + timedelta(hours=1)) for bar in data.bars
        ),
    )
    assert backtest(delayed, Strategy("buy_hold"), config()).fills[0].timestamp == (
        data.bars[2].timestamp
    )


def test_future_price_change_does_not_change_prior_fills():
    data = sample_data()
    cut = 100
    changed = replace(
        data,
        bars=data.bars[:cut]
        + tuple(
            replace(bar, open=bar.open * 2, high=bar.high * 2, low=bar.low * 2, close=bar.close * 2)
            for bar in data.bars[cut:]
        ),
    )
    first = backtest(data, Strategy(), Config())
    second = backtest(changed, Strategy(), Config())
    boundary = data.bars[cut].timestamp
    assert [fill for fill in first.fills if fill.timestamp < boundary] == [
        fill for fill in second.fills if fill.timestamp < boundary
    ]


def test_adverse_execution_reduces_equity():
    plain = backtest(market(), Strategy("buy_hold"), config())
    adverse = backtest(market(), Strategy("buy_hold"), replace(config(), slippage_bps=10))
    assert adverse.metrics["final_equity"] < plain.metrics["final_equity"]


def test_flat_strategy_and_determinism():
    data = sample_data()
    flat = backtest(data, Strategy("flat"), Config())
    assert flat.metrics["final_equity"] == 10000
    assert flat.metrics["sharpe_descriptive"] is None
    assert backtest(data, Strategy(), Config()) == backtest(data, Strategy(), Config())


@pytest.mark.parametrize(
    "change",
    [
        {"open": float("nan")},
        {"low": 1000},
        {"volume_contracts": -1},
        {"available_at": datetime(2024, 1, 1, tzinfo=UTC)},
        {"timestamp": datetime(2024, 1, 1)},
    ],
)
def test_bad_market_rejected(change):
    data = market()
    with pytest.raises(ValueError):
        replace(data, bars=(replace(data.bars[0], **change), *data.bars[1:])).validate()


def test_gaps_and_duplicates_rejected():
    data = market()
    for bars in (data.bars[:1] + data.bars[2:], data.bars[:1] + data.bars):
        with pytest.raises(ValueError):
            replace(data, bars=bars).validate()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"position_fraction": 2},
        {"initial_cash": float("nan")},
        {"rebate_delay_hours": 0},
        {"rebate_confirmed": "false"},
        {"taker_fee": True},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)


@pytest.mark.parametrize("kwargs", [{"kind": "exec"}, {"fast": True}, {"slow": 2}])
def test_untrusted_strategy_rejected(kwargs):
    with pytest.raises(ValueError):
        Strategy(**kwargs)

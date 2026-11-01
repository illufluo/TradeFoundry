"""首次接入编排；账户快照只返回终端，文件仅保存公共市场数据。"""

from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from tradefoundry.demo_account import SITES, ConnectionFailure, DemoReadClient, request_json
from tradefoundry.market import INSTRUMENTS
from tradefoundry.okx import DataError, PublicClient
from tradefoundry.store import encode
from tradefoundry.warehouse import Warehouse, sync_history


def site_public_transport(site, timeout=15):
    if site not in SITES:
        raise ValueError("未知 OKX 账户站点")

    def transport(path, params):
        try:
            return request_json(SITES[site], path, params, {}, timeout)
        except ConnectionFailure:
            raise DataError("OKX 公共数据连接失败，请检查账户站点与网络") from None

    return transport


def market_report(warehouse, qualities, path):
    chart = go.Figure()
    for quality in qualities:
        rows = [
            row
            for row in warehouse.rows(quality["instrument"], "1h")
            if quality["requested_start"]
            <= str(row["timestamp"])
            < quality["requested_end_exclusive"]
        ]
        if rows:
            initial = rows[0]["close"]
            chart.add_scatter(
                x=[row["timestamp"] for row in rows],
                y=[row["close"] / initial for row in rows],
                name=quality["instrument"] + " 收盘价比值",
            )
    chart.update_layout(title="真实 OKX 合约收盘价（首根归一为 1；非策略净值）", xaxis_title="UTC")
    table = "".join(
        f"<tr><td>{escape(item['instrument'])}</td><td>{item['rows']}/{item['expected_rows']}</td>"
        f"<td>{item['missing_count']}</td><td>{escape(item['data_hash'])}</td></tr>"
        for item in qualities
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>TradeFoundry 首次市场检查</title><style>body{font:16px system-ui;"
        "max-width:1100px;margin:32px auto;padding:20px}td,th{padding:8px;border:1px solid #ccc;"
        "overflow-wrap:anywhere}table{width:100%;table-layout:fixed;border-collapse:collapse}</style>"
        "<h1>真实 OKX 市场数据检查</h1><p>本页仅含公共数据，不保存模拟盘账户或凭证。</p>"
        "<p>这是市场数据与质量演示；归一化价格不是合约回测收益。历史发布时间及合约规格"
        "仍需验证，不得把未知资金费当作零。</p><script>"
        + get_plotlyjs()
        + "</script>"
        + chart.to_html(full_html=False, include_plotlyjs=False)
        + "<table><tr><th>标的</th><th>实际/预期根数</th><th>缺口</th><th>数据哈希</th></tr>"
        + table
        + "</table></html>",
        encoding="utf-8",
    )


def first_start(
    settings,
    *,
    output=Path("artifacts/start"),
    days=7,
    account_only=False,
    account_client=None,
    public_client=None,
    now=None,
    research_config=None,
):
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError("研究窗口须为 1 到 30 天")
    account_client = account_client or DemoReadClient(settings)
    account = account_client.snapshot()
    result = {
        "mode": "official_demo_read_only",
        "account_connected": True,
        "account": account,
        "message": "OKX 模拟盘只读账户检查成功",
    }
    if account_only:
        return result
    market = check_markets(
        settings.site,
        output=output,
        days=days,
        timeout=settings.timeout,
        public_client=public_client,
        now=now,
    )
    if not market["market_ready"]:
        return result | market | {"research_ready": False, "trusted_backtest_ready": False}
    from tradefoundry.historical_replay import run_research

    research = run_research(
        Warehouse(output / "warehouse"), market["quality"], output, research_config
    )
    return result | market | research


def check_markets(
    site="global",
    *,
    output=Path("artifacts/start"),
    days=7,
    timeout=15,
    public_client=None,
    now=None,
):
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError("研究窗口须为 1 到 30 天")
    public_client = public_client or PublicClient(
        transport=site_public_transport(site, timeout),
        max_requests=50,
    )
    # 额外留出一小时，避免请求刚刚收盘但尚未公布的边界 K 线。
    end = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    start = end - timedelta(days=days)
    warehouse = Warehouse(output / "warehouse")
    qualities, failures = [], []
    for instrument in INSTRUMENTS:
        try:
            quality = sync_history(
                warehouse, public_client, instrument, "1h", start, end, max_pages=10
            )
            qualities.append(quality)
            if not quality["complete"]:
                failures.append(instrument + " 历史覆盖不完整，已保留缺口，请重试或缩短 --days")
        except (DataError, OSError):
            failures.append(instrument + " 公共数据检查失败，请核对站点、网络并重试")
    report = output / "market.html"
    market_report(warehouse, qualities, report)
    (output / "quality.json").write_text(encode(qualities), encoding="utf-8")
    return {
        "market_ready": len(qualities) == 2 and not failures,
        "quality": qualities,
        "failures": failures,
        "report": str(report.resolve()),
    }

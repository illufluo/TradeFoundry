"""内嵌 Plotly 的独立离线 HTML 报告。"""

from html import escape
from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from tradefoundry.engine import LIMITATIONS

LABELS = {
    "net_return": "净收益率",
    "max_drawdown": "最大回撤",
    "sharpe_descriptive": "描述性年化 Sharpe",
    "fill_count": "成交笔数",
    "round_trips": "完整交易次数",
    "exposure": "持仓暴露比例",
    "gross_fees": "原始手续费 USDT",
    "rebates_received": "已到账返佣 USDT",
    "rebates_pending": "应收返佣 USDT",
    "final_equity": "期末权益 USDT",
}


def write_report(payload: dict, path: Path, experiment_id: str):
    required = {"instrument", "strategy_hash", "fee_sensitivity", "result", "benchmark"}
    if not required <= payload.keys():
        raise ValueError("该实验类型暂不支持 HTML 导出；研发/封存明细保存在 SQLite 的 JSON 中")
    chart = go.Figure()
    for label, key in (("策略", "result"), ("买入持有基准", "benchmark")):
        points = payload[key]["equity"]
        chart.add_scatter(
            x=[str(point["timestamp"]) for point in points],
            y=[point["equity"] for point in points],
            name=label,
            mode="lines",
        )
    title = "净值曲线（USDT，已扣原始手续费）"
    if payload.get("phase") == "conditional_real_history_replay":
        title = "条件重放净值（USDT，未计资金费，非完整合约净收益）"
    chart.update_layout(title=title, xaxis_title="UTC 时间")
    metrics = payload["result"]["metrics"]
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(metrics[key]))}</td>"
        f"<td>{escape(str(payload['benchmark']['metrics'][key]))}</td></tr>"
        for key, label in LABELS.items()
    )
    warnings = "".join(
        f"<li>{escape(text)}</li>" for text in payload.get("limitations", LIMITATIONS)
    )
    metadata = "".join(
        f"<li>{escape(key)}：{escape(str(payload[key]))}</li>"
        for key in (
            "instrument",
            "source",
            "data_hash",
            "strategy",
            "strategy_hash",
            "cost_version",
            "metric_version",
            "code_revision",
            "window",
        )
    )
    metadata += "".join(
        f"<li>{escape(key)}：{escape(str(value))}</li>"
        for key, value in payload.get("extra_metadata", {}).items()
    )
    sensitivity = payload["fee_sensitivity"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>TradeFoundry 研究报告</title>"
        "<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;"
        "line-height:1.6}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;"
        "padding:8px;text-align:left}li{overflow-wrap:anywhere}.warning{background:#fff1cf;"
        "padding:20px}</style>"
        f"<h1>{escape(payload.get('report_title', 'TradeFoundry 离线实验'))}</h1>"
        f"<p>实验编号：{escape(experiment_id)}</p>"
        f'<div class="warning"><strong>数据及可信边界</strong><ul>{warnings}</ul>'
        "<p>synthetic 表示固定合成夹具，绝非 OKX 真实历史行情。</p></div>"
        "<script>"
        + get_plotlyjs()
        + "</script>"
        + chart.to_html(full_html=False, include_plotlyjs=False)
        + "<h2>结果与基准</h2>"
        + f"<p>{escape(payload.get('metric_notice', ''))}</p>"
        + "<table><tr><th>指标</th><th>策略</th><th>买入持有</th></tr>"
        + rows
        + "</table><h2>手续费敏感性</h2>"
        + f"<p>原始费率加倍后的净收益率：{sensitivity['double_fee_net_return']:.6%}</p>"
        + "<h2>可复现记录</h2><ul>"
        + metadata
        + "</ul></html>",
        encoding="utf-8",
    )

"""Deterministic chart selection: data shape in, Chart.js v4 config out.

The LLM never chooses a Chart.js type directly — it classifies the data
shape; this module owns the shape -> chart mapping (assignment table).
"""
import re
from typing import Any

# Olist amounts are Brazilian Real. Series whose name looks monetary get an
# R$-labelled axis and R$-formatted ticks/tooltips (frontend reads _meta).
CURRENCY_RE = re.compile(r"revenue|sales|value|gmv|spend|price|freight", re.I)


def fmt_value(name: str, v) -> str:
    """Format a value for prose (insights): R$ with separators when monetary."""
    if isinstance(v, (int, float)) and CURRENCY_RE.search(name or ""):
        return f"R$ {v:,.2f}"
    return str(v)

DATA_SHAPES = frozenset({
    "time_series_single", "time_series_dual", "ranking", "category_comparison",
    "part_to_whole", "correlation", "score_distribution",
})

_PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6",
            "#14b8a6", "#f43f5e", "#a3a3a3"]

_JUSTIFICATIONS = {
    "time_series_single": "Single metric over time — line chart shows the trend.",
    "time_series_dual": "Two metrics share one time axis — dual-axis line chart keeps both scales readable.",
    "ranking": "Ranked top-N list — horizontal bar sorted descending makes rank order explicit.",
    "category_comparison": "Comparing categories in one period — vertical bar.",
    "part_to_whole": "Shares of a whole — donut chart shows proportions.",
    "correlation": "Two continuous variables per entity — scatter plot, one dot per entity.",
    "score_distribution": "1–5 star distribution — stacked horizontal bar shows the score mix.",
}

_CHART_TYPES = {
    "time_series_single": "line",
    "time_series_dual": "line",
    "ranking": "bar",
    "category_comparison": "bar",
    "part_to_whole": "doughnut",
    "correlation": "scatter",
    "score_distribution": "bar",
}


def select_chart(shape: str) -> tuple[str, str]:
    if shape not in DATA_SHAPES:
        raise ValueError(f"Unknown data shape: {shape!r}. Valid: {sorted(DATA_SHAPES)}")
    return _CHART_TYPES[shape], _JUSTIFICATIONS[shape]


def _color(i: int, alpha: str = "") -> str:
    return _PALETTE[i % len(_PALETTE)] + alpha


def build_chart(shape: str, labels: list, series: list[dict], title: str) -> dict:
    chart_type, justification = select_chart(shape)
    options: dict[str, Any] = {
        "responsive": True,
        "plugins": {"title": {"display": True, "text": title},
                    "legend": {"display": len(series) > 1 or shape == "part_to_whole"}},
    }

    if shape == "correlation":
        datasets = [{
            "label": s["name"],
            "data": s["points"],  # [{"x":..,"y":..,"label":..}]
            "backgroundColor": _color(i),
        } for i, s in enumerate(series)]
        data = {"datasets": datasets}
        # Axis titles from the extracted field names (e.g. avg_delivery_days).
        s0 = series[0] if series else {}
        for ax, key in (("x", "x_name"), ("y", "y_name")):
            if s0.get(key):
                text = str(s0[key]).replace("_", " ").strip().capitalize()
                options.setdefault("scales", {}).setdefault(ax, {})["title"] = {
                    "display": True, "text": text}
        return {"type": chart_type, "justification": justification,
                "chartjs_config": {"type": "scatter", "data": data,
                                   "options": options,
                                   "_meta": {"currency": False}}}

    if shape == "ranking":
        # enforce descending sort by the (single) metric
        pairs = sorted(zip(labels, series[0]["data"]), key=lambda p: p[1], reverse=True)
        labels = [p[0] for p in pairs]
        series = [{**series[0], "data": [p[1] for p in pairs]}]
        options["indexAxis"] = "y"

    if shape == "score_distribution":
        options["indexAxis"] = "y"
        options["scales"] = {"x": {"stacked": True}, "y": {"stacked": True}}

    if shape == "time_series_dual":
        options["scales"] = {
            "y": {"type": "linear", "position": "left"},
            "y1": {"type": "linear", "position": "right",
                   "grid": {"drawOnChartArea": False}},
        }

    datasets = []
    for i, s in enumerate(series):
        d: dict[str, Any] = {"label": s["name"], "data": s["data"]}
        if shape == "part_to_whole":
            d["backgroundColor"] = [_color(j) for j in range(len(s["data"]))]
        else:
            d["backgroundColor"] = _color(i, "cc")
            d["borderColor"] = _color(i)
        if shape.startswith("time_series"):
            d["fill"] = False
            d["tension"] = 0.2
        if shape == "time_series_dual":
            d["yAxisID"] = s.get("axis", "y" if i == 0 else "y1")
        datasets.append(d)

    currency = bool(any(CURRENCY_RE.search(s.get("name", "")) for s in series)
                    or CURRENCY_RE.search(title or ""))

    # Axis titles: label the value axis with the series name (+ R$ when monetary).
    if shape != "part_to_whole" and series:
        scales = options.setdefault("scales", {})
        def _suffix(name: str, is_currency: bool) -> str:
            # Don't double-tag names that already carry a currency marker.
            if not is_currency or "R$" in name or "BRL" in name.upper():
                return ""
            return " (R$)"

        if shape == "time_series_dual":
            for i, s in enumerate(series):
                ax = s.get("axis", "y" if i == 0 else "y1")
                sfx = _suffix(s["name"], bool(CURRENCY_RE.search(s["name"])))
                scales.setdefault(ax, {})["title"] = {"display": True,
                                                      "text": s["name"] + sfx}
        else:
            value_axis = "x" if options.get("indexAxis") == "y" else "y"
            scales.setdefault(value_axis, {})["title"] = {
                "display": True,
                "text": series[0]["name"] + _suffix(series[0]["name"], currency)}

    return {"type": chart_type, "justification": justification,
            "chartjs_config": {"type": chart_type,
                               "data": {"labels": labels, "datasets": datasets},
                               "options": options,
                               "_meta": {"currency": currency}}}

"""Backend chart image renderer for Workbench display."""

from __future__ import annotations

import base64
import math
from dataclasses import replace
from html import escape
from typing import Any

from data_agent_core.contracts.response_contracts import ChartSpec


PALETTE = ["#2563eb", "#0ea5e9", "#14b8a6", "#f59e0b", "#4f46e5", "#64748b", "#22c55e", "#ef4444"]


def attach_rendered_chart(chart: ChartSpec) -> ChartSpec:
    """Attach a backend-rendered SVG data URI to a chart spec when possible."""

    if not chart or not chart.chart_type or chart.chart_type == "kpi" or chart.image_data_uri:
        return chart
    svg = render_chart_svg(chart)
    if not svg:
        return chart
    data_uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return replace(chart, image_data_uri=data_uri, image_format="svg", render_engine="python_svg")


def render_chart_svg(chart: ChartSpec) -> str:
    """Render a compact, readable SVG chart from verified chart data."""

    values = _chart_values(chart)
    if len(values) <= 1:
        return ""
    chart_type = chart.chart_type or "bar"
    if chart_type == "line":
        return _line_chart(values[:24], chart)
    if chart_type in {"pie", "donut"}:
        return _pie_chart(values[:8], chart, donut=chart_type == "donut")
    return _bar_chart(values[:14], chart, horizontal=chart_type == "horizontal_bar" or len(values) > 8)


def _chart_values(chart: ChartSpec) -> list[dict[str, Any]]:
    rows = [row for row in (chart.data or []) if isinstance(row, dict)]
    if not rows:
        return []
    x_column = chart.x or chart.encoding.get("x")
    y_column = chart.y or chart.encoding.get("y")
    if not x_column:
        x_column = next(iter(rows[0].keys()), "")
    if not y_column:
        y_column = next((key for key in rows[0].keys() if key != x_column and _to_float(rows[0].get(key)) is not None), "")
    values = []
    for row in rows:
        label = str(row.get(str(x_column), "")).strip()
        value = _to_float(row.get(str(y_column)))
        if label and value is not None and math.isfinite(value):
            values.append({"label": label, "value": value})
    return values


def _bar_chart(values: list[dict[str, Any]], chart: ChartSpec, *, horizontal: bool) -> str:
    width = 920
    height = max(420, 146 + len(values) * 34) if horizontal else 460
    title = chart.title or "数据对比"
    max_value = max((abs(item["value"]) for item in values), default=1) or 1
    body = []
    if horizontal:
        left = 178
        right = 112
        top = 78
        row_height = 34
        plot_width = width - left - right
        body.append(_grid_lines(width, height, left, top - 16, plot_width, len(values) * row_height, horizontal=True))
        for index, item in enumerate(values):
            y = top + index * row_height
            bar_width = max(3, abs(item["value"]) / max_value * plot_width)
            color = PALETTE[index % len(PALETTE)]
            body.append(f'<text x="{left - 12}" y="{y + 17}" class="axis-label" text-anchor="end">{escape(_short_label(item["label"], 18))}</text>')
            body.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="22" rx="7" fill="{color}"/>')
            body.append(f'<text x="{left + bar_width + 10:.1f}" y="{y + 16}" class="value-label">{escape(_format_number(item["value"]))}</text>')
    else:
        left = 70
        right = 34
        top = 76
        bottom = 86
        plot_width = width - left - right
        plot_height = height - top - bottom
        body.append(_grid_lines(width, height, left, top, plot_width, plot_height))
        gap = 14
        bar_width = max(22, (plot_width - gap * (len(values) - 1)) / len(values))
        for index, item in enumerate(values):
            bar_height = abs(item["value"]) / max_value * plot_height
            x = left + index * (bar_width + gap)
            y = top + plot_height - bar_height
            color = PALETTE[index % len(PALETTE)]
            body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" rx="8" fill="{color}"/>')
            body.append(f'<text x="{x + bar_width / 2:.1f}" y="{y - 10:.1f}" class="value-label" text-anchor="middle">{escape(_format_number(item["value"]))}</text>')
            body.append(f'<text x="{x + bar_width / 2:.1f}" y="{height - 42}" class="axis-label" text-anchor="middle">{escape(_short_label(item["label"], 8))}</text>')
    return _wrap_svg(width, height, title, "".join(body))


def _line_chart(values: list[dict[str, Any]], chart: ChartSpec) -> str:
    width = 920
    height = 450
    title = chart.title or "趋势图"
    left = 72
    right = 36
    top = 76
    bottom = 80
    plot_width = width - left - right
    plot_height = height - top - bottom
    min_value = min(item["value"] for item in values)
    max_value = max(item["value"] for item in values)
    span = max(max_value - min_value, 1)
    points = []
    for index, item in enumerate(values):
        x = left + index / max(len(values) - 1, 1) * plot_width
        y = top + plot_height - (item["value"] - min_value) / span * plot_height
        points.append((x, y, item))
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)
    body = [_grid_lines(width, height, left, top, plot_width, plot_height)]
    body.append(f'<polyline points="{path}" fill="none" stroke="#2563eb" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
    for index, (x, y, item) in enumerate(points):
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#ffffff" stroke="#2563eb" stroke-width="3"/>')
        if index in {0, len(points) - 1}:
            body.append(f'<text x="{x:.1f}" y="{y - 14:.1f}" class="value-label" text-anchor="middle">{escape(_format_number(item["value"]))}</text>')
    step = max(1, math.ceil(len(points) / 6))
    for index, (x, _, item) in enumerate(points):
        if index % step == 0 or index == len(points) - 1:
            body.append(f'<text x="{x:.1f}" y="{height - 38}" class="axis-label" text-anchor="middle">{escape(_short_label(item["label"], 8))}</text>')
    return _wrap_svg(width, height, title, "".join(body))


def _pie_chart(values: list[dict[str, Any]], chart: ChartSpec, *, donut: bool) -> str:
    width = 920
    height = 430
    title = chart.title or "构成图"
    total = sum(max(item["value"], 0) for item in values) or 1
    cx = 255
    cy = 235
    radius = 122
    start = -90.0
    body = []
    for index, item in enumerate(values):
        pct = max(item["value"], 0) / total
        end = start + pct * 360
        body.append(_sector_path(cx, cy, radius, start, end, PALETTE[index % len(PALETTE)]))
        legend_y = 120 + index * 30
        body.append(f'<rect x="510" y="{legend_y - 13}" width="14" height="14" rx="4" fill="{PALETTE[index % len(PALETTE)]}"/>')
        body.append(f'<text x="534" y="{legend_y}" class="axis-label">{escape(_short_label(item["label"], 20))}  {pct * 100:.1f}%</text>')
        start = end
    if donut:
        body.append(f'<circle cx="{cx}" cy="{cy}" r="58" fill="#ffffff"/>')
    return _wrap_svg(width, height, title, "".join(body))


def _grid_lines(width: int, height: int, left: int, top: int, plot_width: int, plot_height: int, *, horizontal: bool = False) -> str:
    lines: list[str] = []
    if horizontal:
        for step in range(5):
            x = left + plot_width * step / 4
            lines.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" class="grid-line"/>')
    else:
        for step in range(5):
            y = top + plot_height * step / 4
            lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" class="grid-line"/>')
    return "".join(lines)


def _wrap_svg(width: int, height: int, title: str, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
<style>
text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }}
.chart-title {{ fill: #111827; font-size: 24px; font-weight: 700; }}
.axis-label {{ fill: #4b5563; font-size: 14px; }}
.value-label {{ fill: #111827; font-size: 13px; font-weight: 650; }}
.grid-line {{ stroke: #e5e7eb; stroke-width: 1; }}
</style>
<rect x="0" y="0" width="{width}" height="{height}" rx="24" fill="#ffffff"/>
<text x="34" y="43" class="chart-title">{escape(title)}</text>
{body}
</svg>"""


def _sector_path(cx: int, cy: int, radius: int, start_deg: float, end_deg: float, color: str) -> str:
    start = math.radians(start_deg)
    end = math.radians(end_deg)
    x1 = cx + radius * math.cos(start)
    y1 = cy + radius * math.sin(start)
    x2 = cx + radius * math.cos(end)
    y2 = cy + radius * math.sin(end)
    large_arc = 1 if end_deg - start_deg > 180 else 0
    return f'<path d="M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large_arc} 1 {x2:.2f} {y2:.2f} Z" fill="{color}"/>'


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _short_label(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(limit - 1, 1)] + "…"

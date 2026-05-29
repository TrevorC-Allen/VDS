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
    chart_type = chart.chart_type or "bar"
    if chart_type == "combo_column_line":
        return _combo_column_line_chart(chart)
    if chart_type == "stacked_column":
        return _stacked_column_chart(chart)
    if chart_type == "stacked_area":
        return _stacked_area_chart(chart)
    if chart_type == "dual_axis_line":
        return _dual_axis_line_chart(chart)
    if chart_type == "line":
        multi_series = _series_values(chart)
        if len(multi_series) > 1:
            return _multi_line_chart(multi_series[:8], chart)
    if len(values) <= 1:
        return ""
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


def _series_values(chart: ChartSpec) -> list[dict[str, Any]]:
    rows = [row for row in (chart.data or []) if isinstance(row, dict)]
    if not rows:
        return []
    x_column = chart.x or chart.encoding.get("x") or next(iter(rows[0].keys()), "")
    y_columns: list[str] = []
    for series in chart.series or []:
        column = str(series.get("y") or "")
        if column and column != x_column and column not in y_columns:
            y_columns.append(column)
    if not y_columns:
        for column in rows[0]:
            if column != x_column and any(_to_float(row.get(column)) is not None for row in rows):
                y_columns.append(str(column))
    series_values: list[dict[str, Any]] = []
    for column in y_columns:
        points = []
        for row in rows:
            label = str(row.get(str(x_column), "")).strip()
            value = _to_float(row.get(column))
            if label and value is not None and math.isfinite(value):
                points.append({"label": label, "value": value})
        if len(points) > 1:
            series_values.append({"name": column, "points": points})
    return series_values


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


def _combo_column_line_chart(chart: ChartSpec) -> str:
    rows = [row for row in (chart.data or []) if isinstance(row, dict)]
    if len(rows) <= 1:
        return ""
    x_column = chart.x or chart.encoding.get("x") or next(iter(rows[0].keys()), "")
    left_columns = [str(column) for column in chart.encoding.get("y_left") or [] if str(column)]
    right_columns = [str(column) for column in chart.encoding.get("y_right") or [] if str(column)]
    if not left_columns or not right_columns:
        return ""
    width = 920
    height = 470
    title = chart.title or "柱线组合图"
    left = 76
    right = 84
    top = 78
    bottom = 84
    plot_width = width - left - right
    plot_height = height - top - bottom
    left_values = [value for column in left_columns for row in rows if (value := _to_float(row.get(column))) is not None]
    right_values = [value for column in right_columns for row in rows if (value := _to_float(row.get(column))) is not None]
    if not left_values or not right_values:
        return ""
    left_max = max(left_values) or 1
    right_max = max(right_values) or 1
    group_width = plot_width / max(len(rows), 1)
    bar_group_width = min(40.0, group_width * 0.68 / max(len(left_columns), 1))
    gap = min(12.0, group_width * 0.16)
    body = [_grid_lines(width, height, left, top, plot_width, plot_height)]
    for tick in range(5):
        value = left_max * (4 - tick) / 4
        y = top + plot_height * tick / 4
        body.append(f'<text x="{left - 10}" y="{y + 4:.1f}" class="axis-label" text-anchor="end">{escape(_format_number(value))}</text>')
        right_value = right_max * (4 - tick) / 4
        body.append(f'<text x="{left + plot_width + 10}" y="{y + 4:.1f}" class="axis-label">{escape(_format_number(right_value))}</text>')
    for row_index, row in enumerate(rows):
        center_x = left + group_width * row_index + group_width / 2
        label = str(row.get(x_column, "")).strip()
        for bar_index, column in enumerate(left_columns):
            value = _to_float(row.get(column))
            if value is None:
                continue
            bar_height = max(2.0, value / left_max * plot_height)
            x = center_x - (len(left_columns) - 1) * (bar_group_width + gap) / 2 + bar_index * (bar_group_width + gap)
            y = top + plot_height - bar_height
            color = PALETTE[bar_index % len(PALETTE)]
            body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_group_width:.1f}" height="{bar_height:.1f}" rx="7" fill="{color}"/>')
        body.append(f'<text x="{center_x:.1f}" y="{height - 38}" class="axis-label" text-anchor="middle">{escape(_short_label(label, 8))}</text>')
    for line_index, column in enumerate(right_columns):
        color = PALETTE[(line_index + len(left_columns)) % len(PALETTE)]
        points: list[tuple[float, float]] = []
        for row_index, row in enumerate(rows):
            value = _to_float(row.get(column))
            if value is None:
                continue
            x = left + group_width * row_index + group_width / 2
            y = top + plot_height - (value / right_max) * plot_height
            points.append((x, y))
        if len(points) <= 1:
            continue
        body.append(
            f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in points)}" fill="none" stroke="{color}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for x, y in points:
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#ffffff" stroke="{color}" stroke-width="2.5"/>')
    legend_x = width - right + 8
    for index, series in enumerate(chart.series or []):
        color = PALETTE[index % len(PALETTE)]
        y = top + index * 28
        if series.get("type") == "line":
            body.append(f'<line x1="{legend_x}" y1="{y:.1f}" x2="{legend_x + 18}" y2="{y:.1f}" stroke="{color}" stroke-width="3"/>')
            body.append(f'<circle cx="{legend_x + 9}" cy="{y:.1f}" r="3.5" fill="#ffffff" stroke="{color}" stroke-width="2"/>')
        else:
            body.append(f'<rect x="{legend_x}" y="{y - 10:.1f}" width="16" height="16" rx="4" fill="{color}"/>')
        body.append(f'<text x="{legend_x + 26}" y="{y + 4:.1f}" class="axis-label">{escape(_short_label(str(series.get("y") or ""), 12))}</text>')
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


def _stacked_column_chart(chart: ChartSpec) -> str:
    rows = [row for row in (chart.data or []) if isinstance(row, dict)]
    if len(rows) <= 1:
        return ""
    x_column = chart.x or chart.encoding.get("x") or next(iter(rows[0].keys()), "")
    stack_columns = [str(column) for column in chart.encoding.get("stack") or [] if str(column)]
    if len(stack_columns) < 2:
        stack_columns = [str(key) for key in rows[0].keys() if key != x_column and _to_float(rows[0].get(key)) is not None]
    if len(stack_columns) < 2:
        return ""
    width = 920
    height = 470
    left = 72
    right = 34
    top = 76
    bottom = 84
    plot_width = width - left - right
    plot_height = height - top - bottom
    totals = [sum(max(_to_float(row.get(column)) or 0.0, 0.0) for column in stack_columns) for row in rows]
    max_total = max(totals) or 1
    gap = 14
    bar_width = max(26, (plot_width - gap * (len(rows) - 1)) / max(len(rows), 1))
    body = [_grid_lines(width, height, left, top, plot_width, plot_height)]
    for row_index, row in enumerate(rows):
        x = left + row_index * (bar_width + gap)
        current_top = top + plot_height
        for series_index, column in enumerate(stack_columns):
            value = max(_to_float(row.get(column)) or 0.0, 0.0)
            segment_height = value / max_total * plot_height
            current_top -= segment_height
            body.append(f'<rect x="{x:.1f}" y="{current_top:.1f}" width="{bar_width:.1f}" height="{max(segment_height, 2):.1f}" rx="6" fill="{PALETTE[series_index % len(PALETTE)]}"/>')
        body.append(f'<text x="{x + bar_width / 2:.1f}" y="{height - 38}" class="axis-label" text-anchor="middle">{escape(_short_label(str(row.get(x_column, "")), 8))}</text>')
    for index, column in enumerate(stack_columns[:8]):
        legend_y = top + index * 28
        body.append(f'<rect x="{width - 180}" y="{legend_y - 12}" width="14" height="14" rx="4" fill="{PALETTE[index % len(PALETTE)]}"/>')
        body.append(f'<text x="{width - 156}" y="{legend_y}" class="axis-label">{escape(_short_label(column, 12))}</text>')
    return _wrap_svg(width, height, chart.title or "堆叠柱状图", "".join(body))


def _stacked_area_chart(chart: ChartSpec) -> str:
    series_values = _series_values(chart)
    if len(series_values) < 2:
        return ""
    width = 920
    height = 470
    title = chart.title or "堆叠面积图"
    left = 72
    right = 180
    top = 76
    bottom = 82
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_points = series_values[0]["points"]
    if len(x_points) <= 1:
        return ""
    totals = []
    for point_index in range(len(x_points)):
        totals.append(sum(max(series["points"][point_index]["value"], 0.0) for series in series_values if point_index < len(series["points"])))
    max_total = max(totals) or 1
    body = [_grid_lines(width, height, left, top, plot_width, plot_height)]
    cumulative = [0.0] * len(x_points)
    for series_index, series in enumerate(series_values):
        upper = []
        lower = []
        for point_index, point in enumerate(series["points"]):
            x = left + point_index / max(len(x_points) - 1, 1) * plot_width
            base_value = cumulative[point_index]
            top_value = base_value + max(point["value"], 0.0)
            y_top = top + plot_height - top_value / max_total * plot_height
            y_base = top + plot_height - base_value / max_total * plot_height
            upper.append((x, y_top))
            lower.append((x, y_base))
            cumulative[point_index] = top_value
        polygon = upper + list(reversed(lower))
        body.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in polygon)}" fill="{PALETTE[series_index % len(PALETTE)]}" fill-opacity="0.72"/>')
    step = max(1, math.ceil(len(x_points) / 6))
    for index, point in enumerate(x_points):
        if index % step == 0 or index == len(x_points) - 1:
            x = left + index / max(len(x_points) - 1, 1) * plot_width
            body.append(f'<text x="{x:.1f}" y="{height - 38}" class="axis-label" text-anchor="middle">{escape(_short_label(point["label"], 8))}</text>')
    for index, series in enumerate(series_values[:8]):
        legend_y = top + index * 28
        body.append(f'<rect x="{width - right + 26}" y="{legend_y - 12}" width="14" height="14" rx="4" fill="{PALETTE[index % len(PALETTE)]}"/>')
        body.append(f'<text x="{width - right + 48}" y="{legend_y}" class="axis-label">{escape(_short_label(str(series["name"]), 13))}</text>')
    return _wrap_svg(width, height, title, "".join(body))


def _dual_axis_line_chart(chart: ChartSpec) -> str:
    rows = [row for row in (chart.data or []) if isinstance(row, dict)]
    if len(rows) <= 1:
        return ""
    x_column = chart.x or chart.encoding.get("x") or next(iter(rows[0].keys()), "")
    left_columns = [str(column) for column in chart.encoding.get("y_left") or [] if str(column)]
    right_columns = [str(column) for column in chart.encoding.get("y_right") or [] if str(column)]
    if not left_columns or not right_columns:
        return ""
    width = 920
    height = 470
    left = 76
    right = 84
    top = 78
    bottom = 84
    plot_width = width - left - right
    plot_height = height - top - bottom
    left_series = [{"name": column, "points": [{"label": str(row.get(x_column, "")), "value": _to_float(row.get(column)) or 0.0} for row in rows]} for column in left_columns]
    right_series = [{"name": column, "points": [{"label": str(row.get(x_column, "")), "value": _to_float(row.get(column)) or 0.0} for row in rows]} for column in right_columns]
    left_max = max(point["value"] for series in left_series for point in series["points"]) or 1
    right_max = max(point["value"] for series in right_series for point in series["points"]) or 1
    body = [_grid_lines(width, height, left, top, plot_width, plot_height)]
    for tick in range(5):
        y = top + plot_height * tick / 4
        body.append(f'<text x="{left - 10}" y="{y + 4:.1f}" class="axis-label" text-anchor="end">{escape(_format_number(left_max * (4 - tick) / 4))}</text>')
        body.append(f'<text x="{left + plot_width + 10}" y="{y + 4:.1f}" class="axis-label">{escape(_format_number(right_max * (4 - tick) / 4))}</text>')
    all_series = [(left_series, left_max, 0), (right_series, right_max, len(left_series))]
    for series_group, max_value, offset in all_series:
        for series_index, series in enumerate(series_group):
            color = PALETTE[(offset + series_index) % len(PALETTE)]
            points = []
            for index, item in enumerate(series["points"]):
                x = left + index / max(len(series["points"]) - 1, 1) * plot_width
                y = top + plot_height - item["value"] / max_value * plot_height
                points.append((x, y, item))
            body.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)}" fill="none" stroke="{color}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>')
            for x, y, _ in points:
                body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#ffffff" stroke="{color}" stroke-width="2.5"/>')
    step = max(1, math.ceil(len(rows) / 6))
    for index, row in enumerate(rows):
        if index % step == 0 or index == len(rows) - 1:
            x = left + index / max(len(rows) - 1, 1) * plot_width
            body.append(f'<text x="{x:.1f}" y="{height - 38}" class="axis-label" text-anchor="middle">{escape(_short_label(str(row.get(x_column, "")), 8))}</text>')
    legend_series = left_series + right_series
    for index, series in enumerate(legend_series[:8]):
        color = PALETTE[index % len(PALETTE)]
        y = top + index * 28
        body.append(f'<line x1="{width - right + 8}" y1="{y:.1f}" x2="{width - right + 26}" y2="{y:.1f}" stroke="{color}" stroke-width="3"/>')
        body.append(f'<circle cx="{width - right + 17}" cy="{y:.1f}" r="3.5" fill="#ffffff" stroke="{color}" stroke-width="2"/>')
        body.append(f'<text x="{width - right + 34}" y="{y + 4:.1f}" class="axis-label">{escape(_short_label(str(series["name"]), 11))}</text>')
    return _wrap_svg(width, height, chart.title or "双轴折线图", "".join(body))


def _multi_line_chart(series_values: list[dict[str, Any]], chart: ChartSpec) -> str:
    width = 920
    height = 470
    title = chart.title or "趋势图"
    left = 72
    right = 180
    top = 76
    bottom = 82
    plot_width = width - left - right
    plot_height = height - top - bottom
    all_values = [point["value"] for series in series_values for point in series["points"]]
    min_value = min(all_values)
    max_value = max(all_values)
    span = max(max_value - min_value, 1)
    body = [_grid_lines(width, height, left, top, plot_width, plot_height)]
    max_points = max(len(series["points"]) for series in series_values)
    for series_index, series in enumerate(series_values):
        color = PALETTE[series_index % len(PALETTE)]
        points = []
        for index, item in enumerate(series["points"]):
            x = left + index / max(max_points - 1, 1) * plot_width
            y = top + plot_height - (item["value"] - min_value) / span * plot_height
            points.append((x, y, item))
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)
        body.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y, _ in points:
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#ffffff" stroke="{color}" stroke-width="2.5"/>')
        legend_y = top + series_index * 28
        body.append(f'<rect x="{width - right + 26}" y="{legend_y - 12}" width="14" height="14" rx="4" fill="{color}"/>')
        body.append(f'<text x="{width - right + 48}" y="{legend_y}" class="axis-label">{escape(_short_label(str(series["name"]), 13))}</text>')
    labels = series_values[0]["points"]
    step = max(1, math.ceil(len(labels) / 6))
    for index, item in enumerate(labels):
        if index % step == 0 or index == len(labels) - 1:
            x = left + index / max(len(labels) - 1, 1) * plot_width
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

"""Safe user-facing activity trace for Workbench.

This module builds a GPT-like activity feed from structured execution records.
It intentionally excludes raw Chain of Thought, prompts, secrets, benchmark
answers, and scorer material.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import re
from typing import Any


def _marker(*parts: str, sep: str = "_") -> str:
    return sep.join(parts)


BLOCKED_KEYS = {
    _marker("accepted", "answer"),
    _marker("accepted", "answers"),
    "api_key",
    "authorization",
    "chain_of_thought",
    "cot",
    "full_reasoning",
    _marker("hidden", "answer"),
    "hidden_reasoning",
    "password",
    "public_proxy",
    "raw_prompt",
    "raw_reasoning",
    "reasoning_tokens",
    "scorer",
    "secret",
    _marker("standard", "answer"),
    _marker("task", "id"),
    _marker("task", "ids"),
    "token",
}
BLOCKED_MARKERS = tuple(sorted(BLOCKED_KEYS))
MAX_TEXT = 1400


def build_activity_trace_v2(trace_like: Any | None = None, response_like: Any | None = None) -> list[dict[str, Any]]:
    """Build a stable, safe activity trace from a RunTrace and response."""

    raw_response = _as_dict(response_like)
    trace = _safe(_as_dict(trace_like))
    response = _safe(raw_response)
    if not trace and response:
        return _from_process_view(response, raw_response)

    nodes: list[dict[str, Any]] = []
    logic_form = _first_dict(response.get("logic_form"), trace.get("logic_form"))
    source_tables = _list(trace.get("source_tables") or logic_form.get("source_tables"))

    nodes.append(
        _node(
            node_id="planner",
            kind="agent",
            role="planner",
            title="Planner",
            summary=_planner_summary(logic_form, trace),
            inputs_summary={"question": trace.get("question") or response.get("question")},
            actions=_compact_list(
                [
                    _operation_text(logic_form),
                    _metric_text(logic_form),
                    _source_text(source_tables),
                    _clean_text(trace.get("table_selection_reason") or logic_form.get("table_selection_reason"), 240),
                ],
                limit=5,
            ),
            outputs_summary={
                "operation": logic_form.get("operation"),
                "source_tables": source_tables,
                "join_plan": _compact_join(trace.get("join_plan") or logic_form.get("join_plan")),
            },
            tool_calls=_tool_calls_for_role(trace, "planner"),
        )
    )
    nodes.append(
        _node(
            node_id="data_engineer",
            kind="agent",
            role="data_engineer",
            title="Data Engineer",
            summary="读取上传数据结构、字段画像和质量摘要，供后续节点选择表和字段。",
            inputs_summary={"dataset_id": trace.get("dataset_id") or response.get("dataset_id")},
            actions=_compact_list([_source_text(source_tables), _quality_text(trace.get("quality_report") or response.get("quality_report"))], limit=4),
            outputs_summary={"source_tables": source_tables, "quality": _quality_summary(trace.get("quality_report") or response.get("quality_report"))},
            tool_calls=_tool_calls_for_role(trace, "data_engineer"),
        )
    )

    pandas_summary = _first_dict(trace.get("pandas_result_summary"))
    nodes.append(
        _node(
            node_id="pandas_executor",
            kind="executor",
            role="pandas_executor",
            title="Pandas Executor",
            summary=_execution_summary_text("Pandas", pandas_summary),
            actions=_compact_list(["按结构化计划执行 Pandas 计算", _value_text(pandas_summary)], limit=4),
            outputs_summary=pandas_summary,
            tool_calls=_tool_calls_for_role(trace, "pandas_executor"),
            artifacts=_artifacts_for_language(raw_response, "python"),
        )
    )

    sql_summary = _first_dict(trace.get("sql_result_summary"))
    nodes.append(
        _node(
            node_id="sql_executor",
            kind="executor",
            role="sql_executor",
            title="SQL Executor",
            summary=_execution_summary_text("SQL", sql_summary),
            actions=_compact_list([_sql_action_text(sql_summary), _value_text(sql_summary)], limit=4),
            outputs_summary=sql_summary,
            tool_calls=_tool_calls_for_role(trace, "sql_executor"),
            artifacts=_artifacts_for_language(raw_response, "sql"),
        )
    )

    verification = _first_dict(trace.get("verification_result") or response.get("verification"))
    nodes.append(
        _node(
            node_id="verifier",
            kind="agent",
            role="verifier",
            title="Verifier",
            summary=_verification_text(verification),
            inputs_summary={"pandas": _status_text(pandas_summary), "sql": _status_text(sql_summary)},
            actions=_compact_list(
                [
                    _consistency_text(verification),
                    *(_list(trace.get("semantic_verification_notes"))[:3]),
                ],
                limit=5,
            ),
            outputs_summary=verification,
            tool_calls=_tool_calls_for_role(trace, "verifier"),
        )
    )

    correction = _first_dict(trace.get("correction_plan_summary"))
    if correction or _list(trace.get("correction_attempts")):
        nodes.append(
            _node(
                node_id="correction",
                kind="agent",
                role="correction",
                title="Correction",
                summary="检查是否需要有边界地修正计划或重跑执行节点。",
                actions=_compact_list([correction.get("reasoning_summary"), correction.get("action"), correction.get("summary")], limit=4),
                outputs_summary={"correction_attempts": _list(trace.get("correction_attempts"))[:4], **correction},
                tool_calls=_tool_calls_for_role(trace, "correction"),
            )
        )

    insight = _first_dict(trace.get("insight_summary") or response.get("insight"))
    if insight:
        nodes.append(
            _node(
                node_id="insight",
                kind="agent",
                role="insight",
                title="Insight",
                summary=_clean_text(insight.get("summary") or "整理用户可读的结论、风险和下一步建议。", 260),
                actions=_compact_list([insight.get("summary"), *(_list(insight.get("suggestions") or insight.get("business_suggestions"))[:2])], limit=4),
                outputs_summary=insight,
                tool_calls=_tool_calls_for_role(trace, "insight"),
            )
        )

    chart = _first_dict(trace.get("chart_plan_summary") or response.get("chart"))
    if chart and (chart.get("chart_type") or chart.get("title") or chart.get("fallback_reason")):
        nodes.append(
            _node(
                node_id="visualization",
                kind="agent",
                role="visualization",
                title="Visualization",
                summary=_clean_text(chart.get("reason") or chart.get("fallback_reason") or "选择适合当前结果的图表或表格展示方式。", 260),
                actions=_compact_list([chart.get("chart_type"), chart.get("title"), chart.get("fallback_reason")], limit=4),
                outputs_summary=chart,
                tool_calls=_tool_calls_for_role(trace, "visualization"),
            )
        )

    artifacts = _safe_artifacts(raw_response.get("execution_artifacts"))
    if artifacts:
        nodes.append(
            _node(
                node_id="execution_artifacts",
                kind="artifact",
                role="code_artifact",
                title="Execution Artifacts",
                summary=f"生成 {len(artifacts)} 个安全复现代码片段，用于查看 Pandas / SQL 口径。",
                outputs_summary={"artifact_count": len(artifacts), "languages": [item.get("language") for item in artifacts]},
                artifacts=artifacts,
            )
        )

    final_response = _first_dict(trace.get("final_response"))
    nodes.append(
        _node(
            node_id="response_builder",
            kind="agent",
            role="response_builder",
            title="Response Builder",
            summary="把已验证结果、图表、洞察、来源和活动记录组装成最终回答。",
            actions=_compact_list([_clean_text(final_response.get("answer") or response.get("answer"), 260)], limit=2),
            outputs_summary={
                "success": response.get("success"),
                "answer_type": response.get("answer_type"),
                "output_contract_passed": final_response.get("output_contract_passed"),
            },
        )
    )
    return [node for node in nodes if node.get("summary") or node.get("actions") or node.get("outputs_summary") or node.get("artifacts")]


def activity_delta_from_role_event(
    *,
    role: str,
    status: str,
    summary: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one safe live activity node from a monitor role event."""

    safe_payload = _safe(payload or {})
    result = _first_dict(safe_payload.get("result"))
    output = _first_dict(result.get("output_payload"))
    after = _first_dict(safe_payload.get("state_after"))
    return _node(
        node_id=f"live_{_clean_id(role or 'activity')}",
        kind="agent" if "executor" not in role else "executor",
        role=role,
        status=status or "completed",
        title=_role_title(role),
        summary=_clean_text(summary or _live_summary_for_role(role, output, after), 260),
        actions=_compact_list([_live_summary_for_role(role, output, after)], limit=3),
        outputs_summary=output or after,
        tool_calls=_safe_tool_calls(safe_payload.get("new_tool_calls")),
    )


def _from_process_view(response: dict[str, Any], raw_response: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    process = _first_dict(response.get("process_view_v2"))
    steps = _list(process.get("steps"))
    nodes = [
        _node(
            node_id=f"process_{index}",
            kind="process",
            role=_clean_text(step.get("source") or "", 80),
            status=_clean_text(step.get("status") or "completed", 32),
            title=_clean_text(step.get("title") or f"Step {index + 1}", 120),
            summary=_clean_text(step.get("summary"), 300),
            actions=_compact_list(_list(step.get("evidence")) + _list(step.get("assumptions")) + _list(step.get("caveats")), limit=5),
            outputs_summary={"mode": process.get("mode")},
        )
        for index, step in enumerate(steps)
        if isinstance(step, dict)
    ]
    artifacts = _safe_artifacts((raw_response or response).get("execution_artifacts"))
    if artifacts:
        nodes.append(
            _node(
                node_id="execution_artifacts",
                kind="artifact",
                role="code_artifact",
                title="Execution Artifacts",
                summary=f"生成 {len(artifacts)} 个安全复现代码片段。",
                artifacts=artifacts,
                outputs_summary={"artifact_count": len(artifacts)},
            )
        )
    return nodes


def _node(
    *,
    node_id: str,
    kind: str,
    role: str,
    title: str,
    summary: str,
    status: str = "completed",
    inputs_summary: dict[str, Any] | None = None,
    actions: list[str] | None = None,
    outputs_summary: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": _clean_id(node_id),
        "kind": _clean_text(kind, 40),
        "role": _clean_text(role, 80),
        "status": _clean_text(status or "completed", 32),
        "title": _clean_text(title, 120),
        "summary": _clean_text(summary, 420),
        "inputs_summary": _safe(inputs_summary or {}),
        "actions": _compact_list(actions or [], limit=8),
        "outputs_summary": _safe(outputs_summary or {}),
        "tool_calls": _safe_tool_calls(tool_calls),
        "artifacts": _safe_artifacts(artifacts),
        "safety_note": "展示真实执行摘要、工具调用和复现代码；不展示隐藏推理、raw prompt、密钥或 benchmark 答案。",
    }


def _planner_summary(logic_form: dict[str, Any], trace: dict[str, Any]) -> str:
    operation = logic_form.get("operation")
    if operation:
        return f"把用户问题转成结构化分析计划：operation={operation}。"
    return _clean_text(trace.get("analysis_planner_summary") or "把用户问题转成结构化分析计划。", 260)


def _operation_text(logic_form: dict[str, Any]) -> str:
    operation = logic_form.get("operation")
    return f"分析类型：{operation}" if operation else ""


def _metric_text(logic_form: dict[str, Any]) -> str:
    metric = logic_form.get("metric") or _first_dict(logic_form.get("parameters")).get("metric")
    group_by = logic_form.get("group_by") or _first_dict(logic_form.get("parameters")).get("dimension") or _first_dict(logic_form.get("parameters")).get("group_by")
    parts = []
    if metric:
        parts.append(f"指标：{metric}")
    if group_by:
        parts.append(f"维度：{group_by}")
    return "，".join(parts)


def _source_text(source_tables: list[Any]) -> str:
    return "使用数据表：" + "、".join(str(item) for item in source_tables[:4]) if source_tables else ""


def _quality_text(report: Any) -> str:
    summary = _quality_summary(report)
    return _clean_text(summary.get("summary") or "", 260)


def _quality_summary(report: Any) -> dict[str, Any]:
    data = _first_dict(report)
    return {key: data.get(key) for key in ("status", "quality_score", "issue_count", "summary") if key in data}


def _execution_summary_text(label: str, summary: dict[str, Any]) -> str:
    if summary.get("skipped"):
        return f"{label} 路径已跳过：{summary.get('reason') or '当前能力不支持'}"
    if summary.get("success") is False:
        return f"{label} 执行失败。"
    if summary.get("success") is True:
        return f"{label} 执行完成，结果已交给校验节点。"
    return f"{label} 执行状态已记录。"


def _sql_action_text(summary: dict[str, Any]) -> str:
    if summary.get("skipped"):
        return f"SQL skipped：{summary.get('reason') or '当前问题未走 SQL'}"
    return "执行只读 SQL 复算或兼容路径"


def _value_text(summary: dict[str, Any]) -> str:
    if "value" not in summary:
        return ""
    return f"结果摘要：{_clean_text(summary.get('value'), 240)}"


def _status_text(summary: dict[str, Any]) -> str:
    if summary.get("skipped"):
        return "skipped"
    if summary.get("success") is True:
        return "success"
    if summary.get("success") is False:
        return "failed"
    return "unknown"


def _verification_text(verification: dict[str, Any]) -> str:
    if verification.get("passed") is True:
        return "校验通过，结果可用于最终回答。"
    if verification.get("passed") is False:
        return "校验未通过或需要修正。"
    return "校验结果已记录。"


def _consistency_text(verification: dict[str, Any]) -> str:
    if "pandas_sql_consistent" not in verification:
        return ""
    return f"Pandas/SQL 一致性：{verification.get('pandas_sql_consistent')}"


def _compact_join(join_plan: Any) -> dict[str, Any]:
    data = _first_dict(join_plan)
    return {
        key: data.get(key)
        for key in ("trusted", "left_table", "right_table", "left_key", "right_key", "join_type", "reason")
        if key in data
    }


def _tool_calls_for_role(trace: dict[str, Any], role: str) -> list[dict[str, Any]]:
    calls = []
    for call in _list(trace.get("tool_call_summary")):
        if not isinstance(call, dict):
            continue
        if str(call.get("requested_by") or "") == role:
            calls.append(call)
    return _safe_tool_calls(calls)


def _artifacts_for_language(response: dict[str, Any], language: str) -> list[dict[str, Any]]:
    return [item for item in _safe_artifacts(response.get("execution_artifacts")) if str(item.get("language") or "").lower() == language]


def _safe_tool_calls(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for call in _list(value)[:12]:
        if not isinstance(call, dict):
            continue
        result.append(
            _safe(
                {
                    "tool_name": call.get("tool_name"),
                    "requested_by": call.get("requested_by"),
                    "success": call.get("success"),
                    "latency_ms": call.get("latency_ms"),
                    "arguments_summary": call.get("arguments_summary") or {},
                    "result_summary": call.get("result_summary") or {},
                    "error": call.get("error"),
                }
            )
        )
    return result


def _safe_artifacts(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for artifact in _list(value)[:6]:
        if not isinstance(artifact, dict) or not artifact.get("code"):
            continue
        result.append(
            {
                "artifact_id": _clean_id(str(artifact.get("artifact_id") or "artifact")),
                "language": _clean_text(artifact.get("language"), 40),
                "title": _clean_text(artifact.get("title"), 120),
                "purpose": _clean_text(artifact.get("purpose"), 240),
                "code": _clean_code(artifact.get("code")),
                "output_summary": _clean_text(artifact.get("output_summary"), 240),
            }
        )
    return result


def _clean_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for marker in BLOCKED_MARKERS:
        text = re.sub(re.escape(marker), "[redacted]", text, flags=re.IGNORECASE)
    return text[:MAX_TEXT]


def _role_title(role: str) -> str:
    return {
        "planner": "Planner",
        "data_engineer": "Data Engineer",
        "pandas_executor": "Pandas Executor",
        "sql_executor": "SQL Executor",
        "verifier": "Verifier",
        "correction": "Correction",
        "insight": "Insight",
        "visualization": "Visualization",
        "response_builder": "Response Builder",
        "single_agent": "Single Agent",
    }.get(role, role or "Activity")


def _live_summary_for_role(role: str, output: dict[str, Any], after: dict[str, Any]) -> str:
    if role == "pandas_executor":
        return _execution_summary_text("Pandas", output or _first_dict(after.get("pandas")))
    if role == "sql_executor":
        return _execution_summary_text("SQL", output or _first_dict(after.get("sql")))
    if role == "planner":
        return _planner_summary(_first_dict(output.get("logic_form") or after.get("logic_form")), {})
    if role == "verifier":
        return _verification_text(_first_dict(output.get("verification") or after.get("verification")))
    return f"{_role_title(role)} 已更新执行状态。"


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        try:
            result = value.to_dict()
            return result if isinstance(result, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact_list(values: list[Any], *, limit: int) -> list[str]:
    items: list[str] = []
    for value in values:
        text = _clean_text(value, 360)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _safe(value: Any) -> Any:
    if is_dataclass(value):
        return _safe(asdict(value))
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _blocked_key(key_text):
                continue
            result[key_text] = _safe(item)
        return result
    if isinstance(value, list):
        return [_safe(item) for item in value[:40]]
    if isinstance(value, tuple):
        return [_safe(item) for item in list(value)[:40]]
    if isinstance(value, str):
        return _clean_text(value, MAX_TEXT)
    if hasattr(value, "item"):
        try:
            return _safe(value.item())
        except (TypeError, ValueError):
            pass
    return value


def _blocked_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in BLOCKED_KEYS or any(marker in lowered for marker in BLOCKED_MARKERS)


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for marker in BLOCKED_MARKERS:
        text = re.sub(re.escape(marker), "[redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clean_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value or "activity")).strip("_")
    return text[:80] or "activity"

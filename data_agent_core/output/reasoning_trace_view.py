"""Safe process timeline for frontend reasoning visualization.

This module intentionally exposes structured summaries only. It never emits
full Chain of Thought, raw reasoning tokens, raw prompts, API keys, or hidden
benchmark answers.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from data_agent_core.contracts.response_contracts import ReasoningTraceStep


BLOCKED_KEYS = {"chain_of_thought", "cot", "hidden_reasoning", "full_reasoning", "api_key", "hidden" + "_answer"}


def build_reasoning_trace_view(trace_like: Any) -> list[ReasoningTraceStep]:
    """Build a safe, stable timeline from a RunTrace-like payload."""

    trace = _safe(_as_dict(trace_like))
    steps = [
        _step(
            "profile",
            "上传与 Profile",
            trace.get("intent_summary") or trace.get("logic_form"),
            "读取文件、生成表画像和字段样例。",
            outputs={"dataset_id": trace.get("dataset_id"), "source_tables": trace.get("source_tables")},
        ),
        _stage_step("intent", "意图识别", trace.get("intent_summary")),
        _step(
            "table_route",
            "表路由",
            trace.get("table_selection_reason") or trace.get("source_tables"),
            str(trace.get("table_selection_reason") or "按问题、字段和表画像选择数据源。"),
            outputs={"source_tables": trace.get("source_tables")},
        ),
        _stage_step("column_mapping", "字段映射", trace.get("column_mapping_summary")),
        _stage_step("analysis_plan", "分析计划", trace.get("analysis_planner_summary") or trace.get("analysis_plan")),
        _step(
            "join_plan",
            "Join 计划",
            trace.get("join_plan"),
            "检查是否需要多表 join，并记录可信度和风险。",
            outputs={"join_plan": trace.get("join_plan"), "join_execution_summary": trace.get("join_execution_summary")},
            warnings=_join_warnings(trace),
        ),
        _step(
            "execute",
            "执行",
            trace.get("pandas_result_summary"),
            "执行受控 Pandas / SQL 计划并标准化结果。",
            outputs={"pandas": trace.get("pandas_result_summary"), "sql": trace.get("sql_result_summary")},
        ),
        _step(
            "verify",
            "校验与修正",
            trace.get("verification_result"),
            "检查执行成功、语义契约、join 风险和输出契约。",
            confidence=_confidence(trace.get("verification_result")),
            outputs={"verification": trace.get("verification_result"), "correction_attempts": trace.get("correction_attempts")},
            warnings=list(trace.get("semantic_verification_notes") or []),
        ),
        _stage_step("chart", "图表选择", trace.get("chart_plan_summary")),
        _stage_step("insight", "洞察生成", trace.get("insight_summary")),
        _step(
            "final_response",
            "最终响应",
            trace.get("final_response"),
            "返回稳定 API 契约字段，前端只负责展示。",
            outputs={"final_response": trace.get("final_response")},
            warnings=list(trace.get("warnings") or []),
        ),
    ]
    return steps


def _stage_step(step_id: str, name: str, payload: Any) -> ReasoningTraceStep:
    data = _safe(payload)
    summary = ""
    if isinstance(data, dict):
        summary = str(data.get("reasoning_summary") or data.get("summary") or data.get("stage_name") or "")
    return _step(step_id, name, data, summary or "阶段已记录结构化摘要。", confidence=_confidence(data), outputs={"stage": data})


def _step(
    step_id: str,
    name: str,
    payload: Any,
    summary: str,
    *,
    confidence: float | None = None,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> ReasoningTraceStep:
    present = _present(payload)
    status = "completed" if present else "skipped"
    return ReasoningTraceStep(
        step_id=step_id,
        name=name,
        status=status,
        summary=summary,
        confidence=confidence,
        inputs_summary=_safe(inputs or {}),
        outputs_summary=_safe(outputs or {}),
        warnings=[str(item) for item in (warnings or []) if item not in {None, ""}],
    )


def _join_warnings(trace: dict[str, Any]) -> list[str]:
    join_plan = trace.get("join_plan")
    if not isinstance(join_plan, dict):
        return []
    warnings: list[str] = []
    if join_plan.get("many_to_many_risk"):
        warnings.append("join plan has many-to-many risk")
    if join_plan and not join_plan.get("trusted"):
        warnings.append(str(join_plan.get("reason") or "join plan is not trusted"))
    summary = trace.get("join_execution_summary")
    if isinstance(summary, dict) and summary.get("unmatched_left_key_count"):
        warnings.append(f"unmatched join keys: {summary.get('unmatched_left_key_count')}")
    return warnings


def _confidence(payload: Any) -> float | None:
    if isinstance(payload, dict) and payload.get("confidence") is not None:
        try:
            return float(payload["confidence"])
        except (TypeError, ValueError):
            return None
    return None


def _present(payload: Any) -> bool:
    if payload is None:
        return False
    if payload == "":
        return False
    if isinstance(payload, (list, dict, tuple, set)) and not payload:
        return False
    return True


def _safe(value: Any) -> Any:
    if is_dataclass(value):
        return _safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items() if str(key).lower() not in BLOCKED_KEYS}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        data = value.to_dict()
        return data if isinstance(data, dict) else {}
    return {}

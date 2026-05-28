"""Source-file overview response builder for uploaded dataset packages."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_agent_core.contracts.response_contracts import InsightResult
from data_agent_core.output.process_narrative import build_dataset_source_process_view


def build_dataset_source_overview_response(
    *,
    run_id: str,
    dataset_id: str,
    question: str,
    source_manifest: dict[str, Any],
    tables: dict[str, pd.DataFrame],
    agent_mode: str = "multi_agent",
) -> dict[str, Any]:
    """Build a user-facing overview of all uploaded table and knowledge files."""

    sources = _normalize_sources(source_manifest.get("sources") or [])
    table_sources = [item for item in sources if item.get("source_type") == "table"]
    knowledge_sources = [item for item in sources if item.get("source_type") != "table"]
    result_rows = _source_result_rows(sources)
    answer = _source_answer(question, sources, table_sources, knowledge_sources)
    source_names = [str(item.get("file_name")) for item in sources if item.get("file_name")]
    execution_artifacts = _source_execution_artifacts(sources)
    insight = _source_insight(sources, table_sources, knowledge_sources)

    return {
        "response_version": "v1",
        "success": True,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "question": question,
        "answer_type": "overview",
        "execution_mode": "overview",
        "answer": answer,
        "logic_form": {
            "task_type": "dataset_source_overview",
            "operation": "dataset_source_overview",
            "parameters": {
                "source_count": len(sources),
                "table_source_count": len(table_sources),
                "knowledge_source_count": len(knowledge_sources),
                "source_names": source_names,
            },
            "source_tables": [str(name) for name in tables],
            "output_format": {"answer_type": "overview"},
        },
        "result": {
            "columns": ["文件", "类型", "用途", "读取状态", "关键内容"],
            "rows": result_rows,
            "value": {
                "source_count": len(sources),
                "table_source_count": len(table_sources),
                "knowledge_source_count": len(knowledge_sources),
                "source_names": source_names,
                "sources": sources,
            },
        },
        "overview_report": {
            "report_type": "source_overview_report",
            "question": question,
            "source_count": len(sources),
            "table_source_count": len(table_sources),
            "knowledge_source_count": len(knowledge_sources),
            "sources": sources,
            "ignored_files": list(source_manifest.get("ignored_files") or []),
        },
        "verification": {
            "passed": True,
            "confidence": 1.0,
            "notes": ["Source-file overview was computed from the stored upload manifest and readable source excerpts."],
        },
        "insight": insight.__dict__,
        "chart": None,
        "quality_report": None,
        "execution_artifacts": execution_artifacts,
        "reasoning_trace_view": [
            {
                "step_id": "intent",
                "name": "理解问题",
                "status": "completed",
                "summary": "这是上传来源文件用途问题，先读取完整来源清单，不进入计算型分析链。",
            },
            {
                "step_id": "scan_sources",
                "name": "读取来源",
                "status": "completed",
                "summary": f"识别到 {len(sources)} 个来源，其中 {len(table_sources)} 个表格来源、{len(knowledge_sources)} 个说明/规则来源。",
            },
            {
                "step_id": "summarize_sources",
                "name": "解释用途",
                "status": "completed",
                "summary": "已按事实表、维表、规则文件和业务手册解释每个文件的作用。",
            },
        ],
        "process_view_v2": build_dataset_source_process_view(
            question=question,
            source_count=len(sources),
            table_count=len(table_sources),
            knowledge_count=len(knowledge_sources),
            source_names=source_names,
            artifact_count=len(execution_artifacts),
        ),
        "source_references": _source_references(sources),
        "warnings": [],
        "errors": [],
        "debug": {
            "agent_mode": agent_mode,
            "dataset_kind": source_manifest.get("dataset_kind") or "uploaded_tables",
            "message_intent": "dataset_source_overview",
            "operation": "dataset_source_overview",
            "source_files": source_names,
            "knowledge_files": [str(item.get("file_name")) for item in knowledge_sources if item.get("file_name")],
            "user_experience_shaping": {
                "applied": True,
                "reason": "source_file_question_reads_full_upload_manifest",
                "source_count": len(sources),
                "knowledge_source_count": len(knowledge_sources),
            },
        },
    }


def _normalize_sources(raw_sources: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        file_name = str(raw.get("file_name") or raw.get("source_file") or "").strip()
        if not file_name or file_name in seen:
            continue
        seen.add(file_name)
        result.append(
            {
                "file_name": file_name,
                "source_type": str(raw.get("source_type") or "source"),
                "source_role": str(raw.get("source_role") or ""),
                "purpose": str(raw.get("purpose") or ""),
                "read_status": str(raw.get("read_status") or "unknown"),
                "table_name": str(raw.get("table_name") or ""),
                "row_count": raw.get("row_count"),
                "column_count": raw.get("column_count"),
                "key_fields": [str(value) for value in raw.get("key_fields") or []],
                "content_summary": str(raw.get("content_summary") or ""),
                "content_excerpt": str(raw.get("content_excerpt") or ""),
            }
        )
    return sorted(result, key=_source_sort_key)


def _source_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    type_order = {"table": 0, "knowledge": 1, "rule": 2}
    return (type_order.get(str(item.get("source_type")), 3), str(item.get("file_name") or ""))


def _source_answer(
    question: str,
    sources: list[dict[str, Any]],
    table_sources: list[dict[str, Any]],
    knowledge_sources: list[dict[str, Any]],
) -> str:
    compact = str(question or "").replace(" ", "")
    focus_other_files = any(token in compact for token in ("还有几个文件", "其他几个文件", "说明文件", "规则文件", "知识文件"))
    lines: list[str] = []
    if knowledge_sources and focus_other_files:
        lines.append(
            f"可以，这次上传的不只是 {len(table_sources)} 个可计算表，还读到了 {len(knowledge_sources)} 个说明/规则文件；这些文件会作为字段含义、规则口径和业务背景的解释来源。"
        )
    else:
        lines.append(f"这次一共识别到 {len(sources)} 个上传来源：{len(table_sources)} 个表格文件、{len(knowledge_sources)} 个说明/规则文件。")

    if table_sources:
        table_text = "、".join(
            f"{item['file_name']}（{_format_count(item.get('row_count'))} 行）" for item in table_sources[:5]
        )
        lines.append(f"可计算表主要用于 Pandas/SQL 分析：{table_text}。")

    if knowledge_sources:
        lines.append("其他说明/规则文件的作用是：")
        for item in knowledge_sources[:8]:
            lines.append(
                f"- {item['file_name']}：{item.get('purpose') or item.get('source_role') or '补充业务说明'}"
                f" 读取状态：{_read_status_label(item.get('read_status'))}；{_summary_or_excerpt(item)}"
            )
    else:
        lines.append("当前没有识别到单独的说明/规则文件；如果上传 md/txt/json/yaml/Word/RTF/ODT/PDF/Pages/HTML，我会把它们作为来源文件读取并解释用途。")

    lines.append("后续如果你问字段含义、费率口径、账户类型或某个文件讲什么，我会优先引用这些说明文件；如果你问金额、排名、趋势或 join，再交给数据分析链路计算。")
    return "\n".join(lines)


def _source_result_rows(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sources[:50]:
        rows.append(
            {
                "文件": item.get("file_name"),
                "类型": _type_label(item),
                "用途": item.get("purpose") or item.get("source_role"),
                "读取状态": _read_status_label(item.get("read_status")),
                "关键内容": _summary_or_excerpt(item, limit=220),
            }
        )
    return rows


def _type_label(item: dict[str, Any]) -> str:
    source_type = str(item.get("source_type") or "")
    if source_type == "table":
        return "表格数据"
    if source_type == "knowledge":
        return "说明/知识文件"
    if source_type == "rule":
        return "规则文件"
    return "来源文件"


def _read_status_label(value: Any) -> str:
    status = str(value or "")
    if status == "read":
        return "已读取正文/结构"
    if status == "metadata_only":
        return "已识别文件，正文需转换或抽取"
    return "已识别"


def _summary_or_excerpt(item: dict[str, Any], *, limit: int = 180) -> str:
    text = str(item.get("content_summary") or item.get("content_excerpt") or "").strip()
    if not text and item.get("key_fields"):
        text = "关键字段：" + "、".join(str(value) for value in item.get("key_fields") or [])
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _source_insight(
    sources: list[dict[str, Any]],
    table_sources: list[dict[str, Any]],
    knowledge_sources: list[dict[str, Any]],
) -> InsightResult:
    first_knowledge = str(knowledge_sources[0].get("file_name")) if knowledge_sources else "说明文件"
    suggestion = (
        f"观察：这组上传内容由表格和说明/规则文件共同构成；依据：已识别 {len(table_sources)} 个表格来源和 {len(knowledge_sources)} 个说明/规则来源；"
        f"建议：下一步先用 {first_knowledge} 确认字段/规则口径，再让分析链路对主事实表做金额、趋势或异常分析。"
    )
    return InsightResult(
        summary="这不是单纯的多 CSV 数据集，说明/规则文件应该作为解释口径进入回答。",
        business_suggestions=[suggestion],
        suggestions=[suggestion],
        caveats=["文档内容只用于解释和约束；涉及数值结论仍以表格计算结果为准。"],
        next_questions=[
            "manual.md 里定义了哪些关键字段和取值？",
            "这些规则文件和 payments 表可以怎样一起用于分析？",
        ],
        evidence_rows=_source_result_rows(sources)[:6],
        confidence=0.86,
    )


def _source_execution_artifacts(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    python_code = "\n".join(
        [
            "from pathlib import Path",
            "import json",
            "import pandas as pd",
            "",
            "source_dir = Path('uploaded_source_dir')",
            "overview = []",
            "for path in source_dir.iterdir():",
            "    if path.suffix.lower() in {'.csv', '.xlsx', '.xls'}:",
            "        df = pd.read_csv(path) if path.suffix.lower() == '.csv' else pd.read_excel(path)",
            "        overview.append({'file': path.name, 'type': 'table', 'rows': len(df), 'columns': len(df.columns)})",
            "    elif path.suffix.lower() == '.json':",
            "        payload = json.loads(path.read_text(encoding='utf-8'))",
            "        overview.append({'file': path.name, 'type': 'json_source', 'summary': type(payload).__name__})",
            "    elif path.suffix.lower() in {'.md', '.txt', '.yaml', '.yml'}:",
            "        text = path.read_text(encoding='utf-8')",
            "        overview.append({'file': path.name, 'type': 'text_source', 'chars': len(text)})",
        ]
    )
    sql_code = "\n".join(
        [
            "-- source_manifest is built by the backend from uploaded files.",
            "SELECT",
            "  file_name,",
            "  source_type,",
            "  read_status,",
            "  row_count,",
            "  column_count",
            "FROM source_manifest",
            "ORDER BY",
            "  CASE source_type",
            "    WHEN 'table' THEN 0",
            "    WHEN 'knowledge' THEN 1",
            "    WHEN 'rule' THEN 2",
            "    ELSE 3",
            "  END,",
            "  file_name;",
        ]
    )
    return [
        {
            "artifact_id": "dataset_source_overview_python",
            "language": "python",
            "title": "上传来源读取代码",
            "purpose": "展示如何枚举表格和说明/规则文件；表格用 Pandas，JSON/文本用结构化读取。",
            "code": python_code,
            "output_summary": f"返回 {len(sources)} 个来源文件的类型、读取状态和用途摘要。",
        },
        {
            "artifact_id": "dataset_source_overview_sql",
            "language": "sql",
            "title": "SQL 来源清单口径",
            "purpose": "展示同一批上传来源在只读 SQL 视角下如何枚举；用于和 Pandas 来源清单对照。",
            "code": sql_code,
            "output_summary": f"返回 {len(sources)} 个来源文件的类型、读取状态和行列规模。",
        },
    ]


def _source_references(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_name": item.get("file_name"),
            "source_type": item.get("source_type"),
            "source_role": item.get("source_role"),
            "read_status": item.get("read_status"),
        }
        for item in sources
    ]


def _format_count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "未知"

"""Backend service shell for calling data_agent_core."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from backend.schemas.data_agent_schema import (
    RESPONSE_VERSION,
    VALID_AGENT_MODES,
    VALID_EXECUTION_MODES,
    dataset_profile_response,
    error_response,
    to_json_ready,
)
from backend.storage.conversation_store import ConversationStore
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.agent.single_agent import UploadedDatasetAgent
from data_agent_core.core.message_intent import classify_workbench_message, is_dataset_overview_question
from data_agent_core.core.file_parser import parse_dataset_file
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import FILE_PARSE_ERROR, LOGIC_FORM_ERROR
from data_agent_core.llm.client import LLMClient
from data_agent_core.output.dataset_overview import build_dataset_overview_response
from multi_agent_workflows.end_to_end_data_analysis_workflow import DataAnalysisMultiAgentWorkflow


class DataAgentService:
    """Thin service layer that owns storage lookup and delegates analysis to core."""

    def __init__(
        self,
        *,
        file_store: TempFileStore | None = None,
        conversation_store: ConversationStore | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.file_store = file_store or TempFileStore()
        self.conversation_store = conversation_store or ConversationStore(self.file_store.root / "conversations")
        self.llm_client = llm_client

    def upload_dataset(self, file_path: str | Path, original_filename: str | None = None) -> dict[str, Any]:
        """Parse an uploaded CSV / Excel file and return its dataset profile."""

        try:
            parsed = parse_dataset_file(file_path, source_name=original_filename)
            self.file_store.save_parsed_dataset(file_path, parsed)
            return dataset_profile_response(parsed.profile)
        except Exception as exc:  # noqa: BLE001 - service must normalize API errors.
            return error_response(
                error=ErrorResult(
                    error_type=FILE_PARSE_ERROR,
                    error_message=str(exc),
                    failed_step="upload_dataset",
                    recoverable=True,
                    suggested_fix="Upload a supported CSV or Excel file with a readable header row.",
                )
            )

    def upload_datasets(
        self,
        file_paths: list[str | Path],
        original_filenames: list[str | None] | None = None,
    ) -> dict[str, Any]:
        """Parse multiple uploaded CSV / Excel files into one dataset profile."""

        try:
            stored = self.file_store.save_uploaded_files(file_paths, original_filenames=original_filenames)
            return dataset_profile_response(stored.profile)
        except Exception as exc:  # noqa: BLE001 - service must normalize API errors.
            return error_response(
                error=ErrorResult(
                    error_type=FILE_PARSE_ERROR,
                    error_message=str(exc),
                    failed_step="upload_datasets",
                    recoverable=True,
                    suggested_fix="Upload one or more supported CSV or Excel files with readable header rows.",
                )
            )

    def analyze_dataset(
        self,
        *,
        dataset_id: str,
        question: str,
        execution_mode: str = "dual",
        guidelines: str = "",
        agent_mode: str = "multi_agent",
    ) -> dict[str, Any]:
        """Run the configured Data Agent workflow for an uploaded dataset."""

        run_id = "run_" + uuid.uuid4().hex[:16]
        if execution_mode not in VALID_EXECUTION_MODES:
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Unsupported execution_mode: {execution_mode}",
                    failed_step="analyze_dataset",
                    recoverable=True,
                    suggested_fix="Use one of auto, pandas, sql, or dual.",
                ),
            )
        if agent_mode not in VALID_AGENT_MODES:
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Unsupported agent_mode: {agent_mode}",
                    failed_step="analyze_dataset",
                    recoverable=True,
                    suggested_fix="Use multi_agent or single_agent.",
                ),
            )

        tables = self.file_store.get_tables(dataset_id)
        if tables is None:
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=FILE_PARSE_ERROR,
                    error_message=f"Dataset not found in temporary store: {dataset_id}",
                    failed_step="analyze_dataset",
                    recoverable=True,
                    suggested_fix="Upload the dataset again before submitting an analysis question.",
                ),
            )

        try:
            profile = self.file_store.get_profile(dataset_id)
            if is_dataset_overview_question(question):
                return to_json_ready(
                    build_dataset_overview_response(
                        run_id=run_id,
                        dataset_id=dataset_id,
                        question=question.strip(),
                        tables=tables,
                        profile=profile,
                        agent_mode=agent_mode,
                    )
                )
            if agent_mode == "single_agent":
                agent = UploadedDatasetAgent(tables=tables, dataset_id=dataset_id, llm_client=self.llm_client)
                response, trace = agent.analyze(question=question, guidelines=guidelines, execution_mode=execution_mode)
            else:
                agent = DataAnalysisMultiAgentWorkflow.from_uploaded_tables(
                    tables,
                    dataset_id=dataset_id,
                    dataset_profile=profile,
                    llm_client=self.llm_client,
                )
                response, trace = agent.analyze(question=question, guidelines=guidelines, execution_mode=execution_mode)
            trace_path = self.file_store.write_run_trace(trace)
            payload = response.to_dict()
            payload.setdefault("debug", {})
            payload["debug"]["trace_path"] = str(trace_path)
            payload["debug"]["agent_mode"] = agent_mode
            return to_json_ready(payload)
        except Exception as exc:  # noqa: BLE001 - service must normalize API errors.
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=str(exc),
                    failed_step="analyze_dataset",
                    recoverable=True,
                    suggested_fix="Check that the question references columns present in the uploaded dataset.",
                ),
            )

    def respond_to_message(
        self,
        *,
        question: str,
        dataset_id: str = "",
        conversation_id: str = "",
        owner_id: str = "",
        tenant_id: str = "",
        owner_context: dict[str, Any] | None = None,
        execution_mode: str = "dual",
        guidelines: str = "",
        agent_mode: str = "multi_agent",
    ) -> dict[str, Any]:
        """Route one workbench message to chat, overview, or full analysis."""

        cleaned_question = question.strip()
        if not dataset_id:
            response = self.chat_without_dataset(question=cleaned_question, agent_mode=agent_mode)
            return self._record_conversation_turn(
                response,
                conversation_id=conversation_id,
                question=cleaned_question,
                dataset_id="",
                owner_id=owner_id,
                tenant_id=tenant_id,
                owner_context=owner_context,
            )
        intent = classify_workbench_message(cleaned_question, has_dataset=True)
        if intent == "chat":
            response = self.chat_with_dataset(dataset_id=dataset_id, question=cleaned_question, agent_mode=agent_mode)
        else:
            response = self.analyze_dataset(
                dataset_id=dataset_id,
                question=cleaned_question,
                execution_mode=execution_mode,
                guidelines=guidelines,
                agent_mode=agent_mode,
            )
        return self._record_conversation_turn(
            response,
            conversation_id=conversation_id,
            question=cleaned_question,
            dataset_id=dataset_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            owner_context=owner_context,
        )

    def create_conversation(
        self,
        *,
        title: str = "",
        dataset_id: str = "",
        owner_id: str = "",
        tenant_id: str = "",
        owner_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an empty persistent workbench conversation."""

        record = self.conversation_store.create_conversation(
            title=title,
            dataset_id=dataset_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            owner_context=owner_context,
        )
        return _conversation_response(record)

    def list_conversations(self, *, limit: int = 50, owner_id: str = "", tenant_id: str = "") -> dict[str, Any]:
        """Return recent persistent workbench conversations."""

        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "conversations": self.conversation_store.list_conversations(
                    limit=limit,
                    owner_id=owner_id,
                    tenant_id=tenant_id,
                ),
                "warnings": [],
                "errors": [],
            }
        )

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Return one persistent workbench conversation."""

        record = self.conversation_store.get_conversation(conversation_id)
        if record is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Conversation not found: {conversation_id}",
                    failed_step="get_conversation",
                    recoverable=True,
                    suggested_fix="Start a new conversation or choose another history item.",
                )
            )
        return _conversation_response(record)

    def rename_conversation(self, conversation_id: str, title: str) -> dict[str, Any]:
        """Rename one persistent workbench conversation."""

        record = self.conversation_store.rename_conversation(conversation_id, title)
        if record is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Conversation could not be renamed: {conversation_id}",
                    failed_step="rename_conversation",
                    recoverable=True,
                    suggested_fix="Use a non-empty title and an existing conversation_id.",
                )
            )
        return _conversation_response(record)

    def _record_conversation_turn(
        self,
        response: dict[str, Any],
        *,
        conversation_id: str,
        question: str,
        dataset_id: str,
        owner_id: str,
        tenant_id: str,
        owner_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Persist a completed workbench turn and attach conversation metadata."""

        if not question.strip():
            return response
        record = self.conversation_store.append_turn(
            conversation_id=conversation_id,
            question=question,
            response=response,
            dataset_id=dataset_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            owner_context=owner_context,
        )
        response["conversation_id"] = record["conversation_id"]
        response["conversation"] = {
            "conversation_id": record["conversation_id"],
            "title": record.get("title") or "",
            "dataset_id": record.get("dataset_id") or "",
            "updated_at": record.get("updated_at"),
            "message_count": len(record.get("messages") or []),
        }
        return to_json_ready(response)

    def chat_without_dataset(
        self,
        *,
        question: str,
        agent_mode: str = "multi_agent",
    ) -> dict[str, Any]:
        """Return a VDS assistant reply when no dataset has been uploaded yet."""

        run_id = "run_" + uuid.uuid4().hex[:16]
        cleaned_question = question.strip()
        if not cleaned_question:
            return error_response(
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message="question is required for chat.",
                    failed_step="chat_without_dataset",
                    recoverable=True,
                    suggested_fix="Ask a data-analysis question or describe the dataset you plan to upload.",
                ),
            )
        if agent_mode not in VALID_AGENT_MODES:
            return error_response(
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Unsupported agent_mode: {agent_mode}",
                    failed_step="chat_without_dataset",
                    recoverable=True,
                    suggested_fix="Use multi_agent or single_agent.",
                ),
            )

        answer = _chat_answer(cleaned_question, has_dataset=False)
        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "run_id": run_id,
                "dataset_id": "",
                "question": cleaned_question,
                "answer_type": "chat",
                "execution_mode": "chat",
                "answer": answer,
                "logic_form": None,
                "result": {"columns": [], "rows": [], "value": None},
                "verification": {"passed": True, "confidence": 1.0, "notes": ["No dataset was required for this chat reply."]},
                "insight": None,
                "chart": None,
                "quality_report": None,
                "reasoning_trace_view": [
                    {
                        "step_id": "intent",
                        "name": "理解问题",
                        "status": "completed",
                        "summary": f"用户提到了“{cleaned_question[:40]}”，当前没有上传数据，我会先按分析助手方式回应。",
                    },
                    {
                        "step_id": "guidance",
                        "name": "给出下一步",
                        "status": "completed",
                        "summary": "如果需要真实业务结论，需要上传包含相关字段的数据；如果只是讨论口径、字段或分析方案，可以继续直接对话。",
                    },
                ],
                "warnings": [],
                "errors": [],
                "debug": {"agent_mode": "chat_without_dataset", "requires_dataset": False},
            }
        )

    def chat_with_dataset(
        self,
        *,
        dataset_id: str,
        question: str,
        agent_mode: str = "multi_agent",
    ) -> dict[str, Any]:
        """Return an ordinary assistant reply while keeping dataset context available."""

        run_id = "run_" + uuid.uuid4().hex[:16]
        cleaned_question = question.strip()
        if not cleaned_question:
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message="question is required for chat.",
                    failed_step="chat_with_dataset",
                    recoverable=True,
                    suggested_fix="Ask a data-analysis question or send a normal chat message.",
                ),
            )
        if agent_mode not in VALID_AGENT_MODES:
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Unsupported agent_mode: {agent_mode}",
                    failed_step="chat_with_dataset",
                    recoverable=True,
                    suggested_fix="Use multi_agent or single_agent.",
                ),
            )
        if self.file_store.get_tables(dataset_id) is None:
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=FILE_PARSE_ERROR,
                    error_message=f"Dataset not found in temporary store: {dataset_id}",
                    failed_step="chat_with_dataset",
                    recoverable=True,
                    suggested_fix="Upload the dataset again before continuing this chat.",
                ),
            )

        answer = _chat_answer(cleaned_question, has_dataset=True)
        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "run_id": run_id,
                "dataset_id": dataset_id,
                "question": cleaned_question,
                "answer_type": "chat",
                "execution_mode": "chat",
                "answer": answer,
                "logic_form": None,
                "result": {"columns": [], "rows": [], "value": None},
                "verification": {"passed": True, "confidence": 1.0, "notes": ["No data analysis was required for this chat reply."]},
                "insight": None,
                "chart": None,
                "quality_report": None,
                "reasoning_trace_view": [
                    {
                        "step_id": "intent",
                        "name": "理解问题",
                        "status": "completed",
                        "summary": "这是普通对话或助手身份问题，不需要调用数据分析链路。",
                    },
                    {
                        "step_id": "reply",
                        "name": "直接回复",
                        "status": "completed",
                        "summary": "已保留当前数据集上下文，后续分析问题仍可继续使用已上传数据。",
                    },
                ],
                "warnings": [],
                "errors": [],
                "debug": {"agent_mode": "chat_with_dataset", "requires_dataset": False, "message_intent": "chat"},
            }
        )

    def get_dataset_profile(self, dataset_id: str) -> dict[str, Any]:
        """Return a stored dataset profile by dataset_id."""

        profile = self.file_store.get_profile(dataset_id)
        if profile is None:
            return error_response(
                dataset_id=dataset_id,
                error=ErrorResult(
                    error_type=FILE_PARSE_ERROR,
                    error_message=f"Dataset not found in temporary store: {dataset_id}",
                    failed_step="get_dataset_profile",
                    recoverable=True,
                    suggested_fix="Upload the dataset again before requesting its profile.",
                ),
            )
        return dataset_profile_response(profile)

    def run_agent_with_inline_tables(
        self,
        *,
        question: str,
        tables: Any,
        execution_mode: str = "dual",
        guidelines: str = "",
        agent_mode: str = "multi_agent",
        dataset_id: str | None = None,
        request_id: str | None = None,
        source_name: str = "api_inline_tables",
    ) -> dict[str, Any]:
        """Create an inline dataset and run the existing Data Agent workflow."""

        request_run_id = "run_" + uuid.uuid4().hex[:16]
        if not question.strip():
            return _attach_external_metadata(
                error_response(
                    dataset_id=dataset_id,
                    run_id=request_run_id,
                    error=ErrorResult(
                        error_type=LOGIC_FORM_ERROR,
                        error_message="question is required for an external agent run.",
                        failed_step="run_agent_with_inline_tables",
                        recoverable=True,
                        suggested_fix="Provide a non-empty natural-language analysis question.",
                    ),
                ),
                request_id=request_id,
                source_name=source_name,
            )

        if execution_mode not in VALID_EXECUTION_MODES:
            return _attach_external_metadata(
                error_response(
                    dataset_id=dataset_id,
                    run_id=request_run_id,
                    error=ErrorResult(
                        error_type=LOGIC_FORM_ERROR,
                        error_message=f"Unsupported execution_mode: {execution_mode}",
                        failed_step="run_agent_with_inline_tables",
                        recoverable=True,
                        suggested_fix="Use one of auto, pandas, sql, or dual.",
                    ),
                ),
                request_id=request_id,
                source_name=source_name,
            )
        if agent_mode not in VALID_AGENT_MODES:
            return _attach_external_metadata(
                error_response(
                    dataset_id=dataset_id,
                    run_id=request_run_id,
                    error=ErrorResult(
                        error_type=LOGIC_FORM_ERROR,
                        error_message=f"Unsupported agent_mode: {agent_mode}",
                        failed_step="run_agent_with_inline_tables",
                        recoverable=True,
                        suggested_fix="Use multi_agent or single_agent.",
                    ),
                ),
                request_id=request_id,
                source_name=source_name,
            )

        try:
            stored = self.file_store.save_inline_table_payload(
                tables,
                dataset_id=dataset_id,
                source_name=source_name,
            )
        except Exception as exc:  # noqa: BLE001 - service must normalize API errors.
            return _attach_external_metadata(
                error_response(
                    dataset_id=dataset_id,
                    run_id=request_run_id,
                    error=ErrorResult(
                        error_type=FILE_PARSE_ERROR,
                        error_message=str(exc),
                        failed_step="run_agent_with_inline_tables",
                        recoverable=True,
                        suggested_fix="Send tables as JSON records, for example [{'table_name': 'sales', 'rows': [{'city': '上海', 'sales': 100}]}].",
                    ),
                ),
                request_id=request_id,
                source_name=source_name,
            )

        response = self.analyze_dataset(
            dataset_id=stored.dataset_id,
            question=question,
            execution_mode=execution_mode,
            guidelines=guidelines,
            agent_mode=agent_mode,
        )
        return _attach_external_metadata(
            response,
            request_id=request_id,
            source_name=source_name,
        )


def _attach_external_metadata(response: dict[str, Any], *, request_id: str | None, source_name: str) -> dict[str, Any]:
    """Attach trace-safe external API metadata without changing analysis logic."""

    if request_id:
        response["request_id"] = request_id
    response.setdefault("debug", {})
    response["debug"]["api_source"] = source_name
    return to_json_ready(response)


def _conversation_response(record: dict[str, Any]) -> dict[str, Any]:
    """Build a stable conversation API response."""

    return to_json_ready(
        {
            "response_version": RESPONSE_VERSION,
            "success": True,
            "conversation": record,
            "warnings": [],
            "errors": [],
        }
    )


def _chat_answer(question: str, *, has_dataset: bool) -> str:
    lowered = question.lower()
    compact = lowered.replace(" ", "")
    if any(token in question for token in ("你好", "您好")) or lowered in {"hello", "hi", "hey"} or lowered.startswith(("hello ", "hi ", "hey ")):
        if has_dataset:
            return "你好，我是 VDS。当前数据已就绪，你可以直接问具体分析问题，也可以让我先做数据概览。"
        return "你好，我是 VDS。你可以直接和我讨论分析思路、指标口径、字段设计，也可以上传 CSV 或 Excel 后让我基于数据给出结论。"
    if any(token in question for token in ("你是什么模型", "你是哪个模型", "底层模型", "什么模型", "你是谁", "介绍一下你")):
        return "我是 VDS 数据分析助手，运行在当前 VDS 后端和可配置 LLM provider 之上。我的职责是理解数据问题、调用受控分析链路，并把结果整理成可核对的回答。"
    if any(token in compact for token in ("能做什么", "怎么用", "功能", "帮助")) or "help" in lowered:
        if has_dataset:
            return "当前数据已经上传。你可以问概览、排序、汇总、趋势、对比、多文件命中文件或多表关联问题；如果只是聊天或讨论口径，我也会直接回复。"
        return "我可以先帮你梳理分析目标、确认需要的字段和指标口径；上传数据后，我可以做聚合、排序、趋势、对比、多文件命中和多表关联分析。"
    if any(token in question for token in ("字段", "口径", "指标", "维度", "关联", "数据表")) or "join" in lowered:
        return "可以先不用上传文件。你把字段名、表结构或想看的指标告诉我，我可以帮你整理分析口径、推荐维度、判断是否需要多表关联。"
    if any(token in lowered for token in ("sales", "revenue", "overall", "summary")) or any(token in question for token in ("销售", "收入", "整体", "概览", "情况")):
        return "可以，我先理解为你想做数据概览。真实结论需要上传相关销售或收入数据；上传后我会优先返回汇总指标、趋势和关键下钻方向，而不是直接展开明细行。"
    return "可以继续聊。当前还没有上传数据，所以我不会编造业务结论；你可以描述分析目标、数据字段或上传文件后让我基于真实数据分析。"

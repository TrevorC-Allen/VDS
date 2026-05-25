"""Backend service shell for calling data_agent_core."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from backend.schemas.data_agent_schema import (
    BENCHMARK_RULE_SCOPE,
    DATASET_FILE_EXTENSIONS,
    DATASET_FILE_ROLE,
    RESPONSE_VERSION,
    RULE_FILE_EXTENSIONS,
    RULE_FILE_ROLE,
    USER_ANALYSIS_RULE_SCOPE,
    VALID_AGENT_MODES,
    VALID_EXECUTION_MODES,
    VALID_FILE_ROLES,
    dataset_profile_response,
    error_response,
    to_json_ready,
)
from backend.storage.conversation_store import ConversationStore
from backend.storage.project_store import ProjectStore, build_project_context
from backend.storage.temp_file_store import StoredRuleFile, TempFileStore
from data_agent_core.agent.single_agent import DataAnalysisAgent, UploadedDatasetAgent
from data_agent_core.benchmark.evaluator import question_scorer
from data_agent_core.core.message_intent import classify_workbench_message, is_cleaning_guidance_question, is_dataset_overview_question
from data_agent_core.core.file_parser import parse_dataset_file
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import FILE_PARSE_ERROR, LOGIC_FORM_ERROR
from data_agent_core.llm.client import LLMClient
from data_agent_core.output.cleaning_guidance import build_cleaning_guidance_response
from data_agent_core.output.dataset_overview import build_dataset_overview_response
from data_agent_core.output.process_narrative import build_chat_process_view, process_view_monitor_payload
from data_agent_core.tracing.live_monitor import emit_monitor_event
from multi_agent_workflows.end_to_end_data_analysis_workflow import DataAnalysisMultiAgentWorkflow


class DataAgentService:
    """Thin service layer that owns storage lookup and delegates analysis to core."""

    def __init__(
        self,
        *,
        file_store: TempFileStore | None = None,
        conversation_store: ConversationStore | None = None,
        project_store: ProjectStore | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.file_store = file_store or TempFileStore()
        self.conversation_store = conversation_store or ConversationStore(self.file_store.root / "conversations")
        self.project_store = project_store or ProjectStore(self.file_store.root / "projects")
        self.llm_client = llm_client

    def upload_dataset(
        self,
        file_path: str | Path,
        original_filename: str | None = None,
        *,
        file_role: str = DATASET_FILE_ROLE,
        rule_scope: str = "",
        bind_dataset_id: str = "",
    ) -> dict[str, Any]:
        """Parse a dataset upload or persist an explicitly marked rule file."""

        try:
            role = _normalize_file_role(file_role)
            if role == RULE_FILE_ROLE:
                record = self.file_store.save_rule_file(
                    file_path,
                    original_filename=original_filename,
                    rule_scope=rule_scope,
                    dataset_id=bind_dataset_id,
                )
                return _rule_file_response(record)
            _validate_dataset_upload(file_path, original_filename=original_filename, rule_scope=rule_scope)
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
                    suggested_fix=(
                        "Upload a supported dataset file, or upload a rule file with "
                        "file_role=rule and rule_scope=user_analysis or benchmark."
                    ),
                )
            )

    def upload_datasets(
        self,
        file_paths: list[str | Path],
        original_filenames: list[str | None] | None = None,
        *,
        file_role: str = DATASET_FILE_ROLE,
        rule_scope: str = "",
        bind_dataset_id: str = "",
    ) -> dict[str, Any]:
        """Parse multiple dataset files or persist same-scope rule files."""

        try:
            role = _normalize_file_role(file_role)
            if role == RULE_FILE_ROLE:
                records = self.file_store.save_rule_files(
                    file_paths,
                    original_filenames=original_filenames,
                    rule_scope=rule_scope,
                    dataset_id=bind_dataset_id,
                )
                return _rule_files_response(records)
            if rule_scope:
                raise ValueError("dataset uploads must not include rule_scope.")
            _raise_if_rule_only_dabstep_partial(file_paths, original_filenames)
            dataset_paths, dataset_names, rule_paths, rule_names = _split_dataset_and_auto_rule_files(
                file_paths,
                original_filenames,
            )
            if not dataset_paths:
                raise ValueError("Upload at least one dataset file together with optional rule files.")
            stored = self.file_store.save_uploaded_files(dataset_paths, original_filenames=dataset_names)
            bound_rules: list[StoredRuleFile] = []
            if rule_paths:
                bound_rules = self.file_store.save_rule_files(
                    rule_paths,
                    original_filenames=rule_names,
                    rule_scope=USER_ANALYSIS_RULE_SCOPE,
                    dataset_id=stored.dataset_id,
                )
            response = dataset_profile_response(stored.profile)
            if bound_rules:
                response["auto_bound_user_rule_file_ids"] = [record.file_id for record in bound_rules]
                response["auto_bound_rule_files"] = [_public_rule_record(record) for record in bound_rules]
                response.setdefault("warnings", [])
                response["warnings"].append(
                    "已自动识别并绑定用户分析规则文件：" + ", ".join(record.file_name for record in bound_rules)
                )
            return to_json_ready(response)
        except Exception as exc:  # noqa: BLE001 - service must normalize API errors.
            return error_response(
                error=ErrorResult(
                    error_type=FILE_PARSE_ERROR,
                    error_message=str(exc),
                    failed_step="upload_datasets",
                    recoverable=True,
                    suggested_fix=(
                        "Upload one or more supported dataset files. If these are rules, upload them with "
                        "file_role=rule and rule_scope=user_analysis or benchmark."
                    ),
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
        user_rule_file_id: str = "",
        monitor_run_id: str = "",
    ) -> dict[str, Any]:
        """Run the configured Data Agent workflow for an uploaded dataset."""

        run_id = "run_" + uuid.uuid4().hex[:16]
        emit_monitor_event(
            monitor_run_id,
            "analysis_requested",
            title="收到分析请求",
            summary=f"dataset={dataset_id or '-'}，agent_mode={agent_mode}，execution_mode={execution_mode}",
            stage="service",
            status="active",
            payload={
                "dataset_id": dataset_id,
                "question": question,
                "execution_mode": execution_mode,
                "agent_mode": agent_mode,
            },
        )
        if execution_mode not in VALID_EXECUTION_MODES:
            emit_monitor_event(
                monitor_run_id,
                "analysis_failed",
                title="执行模式不支持",
                summary=f"Unsupported execution_mode: {execution_mode}",
                stage="service",
                status="failed",
                payload={"dataset_id": dataset_id, "run_id": run_id, "execution_mode": execution_mode},
            )
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
            emit_monitor_event(
                monitor_run_id,
                "analysis_failed",
                title="Agent 模式不支持",
                summary=f"Unsupported agent_mode: {agent_mode}",
                stage="service",
                status="failed",
                payload={"dataset_id": dataset_id, "run_id": run_id, "agent_mode": agent_mode},
            )
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

        try:
            guidelines, user_rule_context = self._guidelines_with_user_rule(
                guidelines,
                user_rule_file_id=user_rule_file_id,
                dataset_id=dataset_id,
            )
        except Exception as exc:  # noqa: BLE001 - normalized API error.
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=str(exc),
                    failed_step="analyze_dataset",
                    recoverable=True,
                    suggested_fix="Upload a valid user_analysis rule file and pass its file_id.",
                ),
            )

        tables = self.file_store.get_tables(dataset_id)
        if tables is None:
            emit_monitor_event(
                monitor_run_id,
                "analysis_failed",
                title="数据集不存在",
                summary=f"Dataset not found in temporary store: {dataset_id}",
                stage="service",
                status="failed",
                payload={"dataset_id": dataset_id, "run_id": run_id},
            )
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
            dataset_kind = self.file_store.get_dataset_kind(dataset_id)
            analysis_context = self.file_store.get_analysis_context(dataset_id)
            emit_monitor_event(
                monitor_run_id,
                "data_scan_note",
                title="检查文件结构",
                summary=f"我先检查已上传数据结构：{len(tables)} 张表。",
                stage="service",
                status="completed",
                payload={"dataset_id": dataset_id, "table_count": len(tables)},
            )
            if is_cleaning_guidance_question(question):
                response = to_json_ready(
                    build_cleaning_guidance_response(
                        run_id=run_id,
                        dataset_id=dataset_id,
                        question=question.strip(),
                        tables=tables,
                        agent_mode=agent_mode,
                    )
                )
                emit_monitor_event(
                    monitor_run_id,
                    "answer_outline_ready",
                    title="清洗建议已整理",
                    summary="已整理清洗规则、影响范围和用户确认边界。",
                    stage="cleaning_guidance",
                    status="completed",
                    payload={"run_id": run_id, "dataset_id": dataset_id, "answer_type": response.get("answer_type")},
                )
                emit_monitor_event(
                    monitor_run_id,
                    "workflow_completed",
                    title="清洗模拟完成",
                    summary="本次问题命中清洗策略路径，只生成模拟和安全边界说明。",
                    stage="cleaning_guidance",
                    status="completed",
                    payload=process_view_monitor_payload(response),
                )
                return response
            if is_dataset_overview_question(question):
                response = to_json_ready(
                    build_dataset_overview_response(
                        run_id=run_id,
                        dataset_id=dataset_id,
                        question=question.strip(),
                        tables=tables,
                        profile=profile,
                        agent_mode=agent_mode,
                    )
                )
                if response.get("execution_artifacts"):
                    emit_monitor_event(
                        monitor_run_id,
                        "code_artifact_ready",
                        title="复现代码已准备",
                        summary="概览复现代码已准备好，最终会放在处理过程详情中。",
                        stage="dataset_overview",
                        status="completed",
                        payload={"run_id": run_id, "dataset_id": dataset_id, "artifact_count": len(response.get("execution_artifacts") or [])},
                    )
                emit_monitor_event(
                    monitor_run_id,
                    "answer_outline_ready",
                    title="概览回答已整理",
                    summary="已整理表含义、关键字段、洞察和可追问方向。",
                    stage="dataset_overview",
                    status="completed",
                    payload={"run_id": run_id, "dataset_id": dataset_id, "answer_type": response.get("answer_type")},
                )
                emit_monitor_event(
                    monitor_run_id,
                    "workflow_completed",
                    title="数据概览完成",
                    summary="本次问题命中数据概览路径，未进入完整 multi-agent 执行链。",
                    stage="dataset_overview",
                    status="completed",
                    payload=process_view_monitor_payload(response),
                )
                return response
            if agent_mode == "single_agent":
                emit_monitor_event(
                    monitor_run_id,
                    "agent_started",
                    title="single_agent 开始",
                    summary="Single Agent 正在执行完整分析链。",
                    role="single_agent",
                    stage="single_agent",
                    status="active",
                    payload={
                        "dataset_id": dataset_id,
                        "dataset_kind": dataset_kind,
                        "question": question,
                        "execution_mode": execution_mode,
                    },
                )
                if dataset_kind == "dabstep_context":
                    context_dir = self.file_store.get_context_dir(dataset_id)
                    if context_dir is None:
                        raise ValueError("DABstep context files are not available for single_agent analysis.")
                    agent = DataAnalysisAgent(context_dir=context_dir, dataset_id=dataset_id, llm_client=self.llm_client)
                else:
                    agent = UploadedDatasetAgent(tables=tables, dataset_id=dataset_id, llm_client=self.llm_client)
                response, trace = agent.analyze(question=question, guidelines=guidelines, execution_mode=execution_mode)
                emit_monitor_event(
                    monitor_run_id,
                    "agent_completed",
                    title="single_agent 完成",
                    summary="Single Agent 已返回响应和 trace。",
                    role="single_agent",
                    stage="single_agent",
                    status="completed" if response.success else "failed",
                    payload={
                        "run_id": response.run_id,
                        "dataset_id": response.dataset_id,
                        "success": response.success,
                        "answer_type": response.answer_type,
                        "process_view_v2": response.process_view_v2,
                    },
                )
            elif dataset_kind == "dabstep_context" and analysis_context is not None:
                agent = DataAnalysisMultiAgentWorkflow(
                    dataset_id=dataset_id,
                    context=analysis_context,
                    dataset_profile=profile,
                    llm_client=self.llm_client,
                )
                response, trace = agent.analyze(
                    question=question,
                    guidelines=guidelines,
                    execution_mode=execution_mode,
                    monitor_run_id=monitor_run_id,
                )
            else:
                agent = DataAnalysisMultiAgentWorkflow.from_uploaded_tables(
                    tables,
                    dataset_id=dataset_id,
                    dataset_profile=profile,
                    llm_client=self.llm_client,
                )
                response, trace = agent.analyze(
                    question=question,
                    guidelines=guidelines,
                    execution_mode=execution_mode,
                    monitor_run_id=monitor_run_id,
                )
            trace_path = self.file_store.write_run_trace(trace)
            payload = response.to_dict()
            payload.setdefault("debug", {})
            payload["debug"]["trace_path"] = str(trace_path)
            payload["debug"]["agent_mode"] = agent_mode
            payload["debug"]["dataset_kind"] = dataset_kind
            payload["debug"]["user_rule_context"] = user_rule_context
            if monitor_run_id:
                payload["debug"]["monitor_run_id"] = monitor_run_id
            if dataset_kind == "dabstep_context":
                payload["debug"]["knowledge_files"] = ["manual.md", "fees.json", "merchant_data.json"]
            payload = _suppress_raw_detail_answer(
                payload,
                question=question,
                tables=tables,
                profile=profile,
                agent_mode=agent_mode,
            )
            if payload.get("execution_artifacts"):
                emit_monitor_event(
                    monitor_run_id,
                    "code_artifact_ready",
                    title="复现代码已准备",
                    summary="安全复现代码已准备好，最终会放在处理过程详情中。",
                    stage="service",
                    status="completed",
                    payload={"run_id": payload.get("run_id"), "dataset_id": dataset_id, "artifact_count": len(payload.get("execution_artifacts") or [])},
                )
            emit_monitor_event(
                monitor_run_id,
                "answer_outline_ready",
                title="回答结构已整理",
                summary="最终回答、图表、洞察和过程视图已整理完成。",
                stage="service",
                status="completed",
                payload={"run_id": payload.get("run_id"), "dataset_id": dataset_id, "answer_type": payload.get("answer_type")},
            )
            emit_monitor_event(
                monitor_run_id,
                "response_ready",
                title="响应已生成",
                summary="响应已生成并写入安全运行记录。",
                stage="service",
                status="completed" if response.success else "failed",
                payload=process_view_monitor_payload(payload),
            )
            return to_json_ready(payload)
        except Exception as exc:  # noqa: BLE001 - service must normalize API errors.
            emit_monitor_event(
                monitor_run_id,
                "analysis_failed",
                title="分析异常",
                summary=str(exc),
                stage="service",
                status="failed",
                payload={"dataset_id": dataset_id, "run_id": run_id, "error": str(exc)},
            )
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
        project_id: str = "",
        owner_id: str = "",
        tenant_id: str = "",
        owner_context: dict[str, Any] | None = None,
        execution_mode: str = "dual",
        guidelines: str = "",
        agent_mode: str = "multi_agent",
        user_rule_file_id: str = "",
        monitor_run_id: str = "",
    ) -> dict[str, Any]:
        """Route one workbench message to chat, overview, or full analysis."""

        cleaned_question = question.strip()
        project_context = {"enabled": False}
        if project_id:
            project = self.project_store.get_project(project_id)
            if project is None:
                return error_response(
                    error=ErrorResult(
                        error_type=LOGIC_FORM_ERROR,
                        error_message=f"Project not found: {project_id}",
                        failed_step="respond_to_message",
                        recoverable=True,
                        suggested_fix="Choose an existing project or clear project_id.",
                    )
                )
            project_context = build_project_context(project)
            dataset_id = dataset_id or str(project_context.get("default_dataset_id") or "")
            guidelines = _combine_guidelines(
                str(project_context.get("instructions_guidelines") or ""),
                guidelines,
                str(project_context.get("memory_guidelines") or ""),
                str(project_context.get("source_guidelines") or ""),
            )
        emit_monitor_event(
            monitor_run_id,
            "message_requested",
            title="收到用户消息",
            summary=f"conversation={conversation_id or 'new'}，project={project_id or '-'}，dataset={dataset_id or '-'}",
            stage="message",
            status="active",
            payload={
                "conversation_id": conversation_id,
                "project_id": project_id,
                "dataset_id": dataset_id,
                "question": cleaned_question,
                "execution_mode": execution_mode,
                "agent_mode": agent_mode,
            },
        )
        if not dataset_id:
            response = self.chat_without_dataset(question=cleaned_question, agent_mode=agent_mode, monitor_run_id=monitor_run_id)
            _attach_project_metadata(response, project_context)
            return self._record_conversation_turn(
                response,
                conversation_id=conversation_id,
                question=cleaned_question,
                dataset_id="",
                project_id=project_id,
                owner_id=owner_id,
                tenant_id=tenant_id,
                owner_context=owner_context,
            )
        intent = classify_workbench_message(cleaned_question, has_dataset=True)
        if intent == "chat":
            response = self.chat_with_dataset(
                dataset_id=dataset_id,
                question=cleaned_question,
                agent_mode=agent_mode,
                monitor_run_id=monitor_run_id,
            )
        elif intent == "cleaning_guidance":
            response = self.analyze_dataset(
                dataset_id=dataset_id,
                question=cleaned_question,
                execution_mode=execution_mode,
                guidelines=guidelines,
                agent_mode=agent_mode,
                user_rule_file_id=user_rule_file_id,
                monitor_run_id=monitor_run_id,
            )
        else:
            response = self.analyze_dataset(
                dataset_id=dataset_id,
                question=cleaned_question,
                execution_mode=execution_mode,
                guidelines=guidelines,
                agent_mode=agent_mode,
                user_rule_file_id=user_rule_file_id,
                monitor_run_id=monitor_run_id,
            )
        _attach_project_metadata(response, project_context)
        return self._record_conversation_turn(
            response,
            conversation_id=conversation_id,
            question=cleaned_question,
            dataset_id=dataset_id,
            project_id=project_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            owner_context=owner_context,
        )

    def run_benchmark_from_rule(
        self,
        *,
        dataset_id: str,
        benchmark_rule_file_id: str,
        user_rule_file_id: str = "",
        execution_mode: str = "auto",
        agent_mode: str = "multi_agent",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Run an explicitly scoped benchmark rule without entering ordinary chat."""

        run_id = "bench_" + uuid.uuid4().hex[:16]
        if execution_mode not in VALID_EXECUTION_MODES:
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Unsupported execution_mode: {execution_mode}",
                    failed_step="run_benchmark_from_rule",
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
                    failed_step="run_benchmark_from_rule",
                    recoverable=True,
                    suggested_fix="Use multi_agent or single_agent.",
                ),
            )
        try:
            benchmark_rule = self.file_store.get_rule_context(
                benchmark_rule_file_id,
                expected_scope=BENCHMARK_RULE_SCOPE,
            )
            questions = _benchmark_questions(benchmark_rule["parsed_rule"])
            if limit is not None:
                questions = questions[: max(0, limit)]
            user_guidelines = ""
            user_rule_context = {"enabled": False}
            if user_rule_file_id:
                user_context = self.file_store.get_rule_context(
                    user_rule_file_id,
                    expected_scope=USER_ANALYSIS_RULE_SCOPE,
                )
                user_guidelines = _user_rule_guidelines(user_context)
                user_rule_context = _public_rule_context(user_context)
            tables = self.file_store.get_tables(dataset_id)
            if tables is None:
                raise ValueError(f"Dataset not found in temporary store: {dataset_id}")
            profile = self.file_store.get_profile(dataset_id)
            dataset_kind = self.file_store.get_dataset_kind(dataset_id)
            analysis_context = self.file_store.get_analysis_context(dataset_id)
            if dataset_kind == "dabstep_context" and analysis_context is not None:
                workflow = DataAnalysisMultiAgentWorkflow(
                    dataset_id=dataset_id,
                    context=analysis_context,
                    dataset_profile=profile,
                    llm_client=self.llm_client,
                )
            else:
                workflow = DataAnalysisMultiAgentWorkflow.from_uploaded_tables(
                    tables,
                    dataset_id=dataset_id,
                    dataset_profile=profile,
                    llm_client=self.llm_client,
                )
            details: list[dict[str, Any]] = []
            correct = 0
            scored = 0
            for index, item in enumerate(questions, start=1):
                item_guidelines = _combine_guidelines(str(item.get("guidelines") or ""), user_guidelines)
                response, trace = workflow.analyze(
                    question=str(item["question"]),
                    guidelines=item_guidelines,
                    execution_mode=execution_mode,
                )
                trace_path = self.file_store.write_run_trace(trace)
                target = "" if item.get("expected_output") is None else str(item.get("expected_output"))
                predicted = "" if response.answer is None else str(response.answer)
                passed = question_scorer(target, predicted) if target else None
                if passed is not None:
                    scored += 1
                    correct += int(passed)
                details.append(
                    {
                        "case_id": item.get("id") or f"case_{index}",
                        "question": item["question"],
                        "success": response.success,
                        "agent_answer": predicted,
                        "expected_available": bool(target),
                        "correct": passed,
                        "errors": to_json_ready(response.errors),
                        "warnings": to_json_ready(response.warnings),
                        "trace_path": str(trace_path),
                    }
                )
            report = {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "run_id": run_id,
                "dataset_id": dataset_id,
                "benchmark_rule_file_id": benchmark_rule_file_id,
                "user_rule_file_id": user_rule_file_id,
                "benchmark": _benchmark_name(benchmark_rule["parsed_rule"], benchmark_rule["file_name"]),
                "total": len(details),
                "scored": scored,
                "correct": correct,
                "accuracy": None if scored == 0 else correct / scored,
                "details": details,
                "user_rule_context": user_rule_context,
                "warnings": [],
                "errors": [],
            }
            report_path = self.file_store.write_benchmark_report(run_id, report)
            report["report_path"] = str(report_path)
            return to_json_ready(report)
        except Exception as exc:  # noqa: BLE001 - service must normalize API errors.
            return error_response(
                dataset_id=dataset_id,
                run_id=run_id,
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=str(exc),
                    failed_step="run_benchmark_from_rule",
                    recoverable=True,
                    suggested_fix=(
                        "Use file_role=rule with rule_scope=benchmark for the benchmark rule, "
                        "and pass a dataset_id that points to uploaded dataset files."
                    ),
                ),
            )

    def _guidelines_with_user_rule(
        self,
        guidelines: str,
        *,
        user_rule_file_id: str = "",
        dataset_id: str = "",
    ) -> tuple[str, dict[str, Any]]:
        """Append explicit and auto-bound user analysis rules to guidelines."""

        rule_ids: list[str] = []
        if user_rule_file_id:
            rule_ids.append(user_rule_file_id)
        for file_id in self.file_store.get_bound_rule_file_ids(dataset_id, rule_scope=USER_ANALYSIS_RULE_SCOPE):
            if file_id not in rule_ids:
                rule_ids.append(file_id)
        if not rule_ids:
            return guidelines, {"enabled": False}
        contexts = [
            self.file_store.get_rule_context(file_id, expected_scope=USER_ANALYSIS_RULE_SCOPE)
            for file_id in rule_ids
        ]
        public_contexts = [_public_rule_context(context) for context in contexts]
        context_payload: dict[str, Any] = {
            "enabled": True,
            "auto_bound": bool(dataset_id and not user_rule_file_id),
            "files": public_contexts,
        }
        if public_contexts:
            context_payload.update(public_contexts[0])
        return (
            _combine_guidelines(guidelines, *[_user_rule_guidelines(context) for context in contexts]),
            context_payload,
        )

    def create_conversation(
        self,
        *,
        title: str = "",
        dataset_id: str = "",
        project_id: str = "",
        owner_id: str = "",
        tenant_id: str = "",
        owner_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an empty persistent workbench conversation."""

        record = self.conversation_store.create_conversation(
            title=title,
            dataset_id=dataset_id,
            project_id=project_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            owner_context=owner_context,
        )
        if project_id:
            self.project_store.attach_conversation(project_id, record["conversation_id"])
        return _conversation_response(record)

    def list_conversations(
        self,
        *,
        limit: int = 50,
        owner_id: str = "",
        tenant_id: str = "",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Return recent persistent workbench conversations."""

        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "conversations": self.conversation_store.list_conversations(
                    limit=limit,
                    owner_id=owner_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
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

        record = self.update_conversation(conversation_id, title=title)
        if record.get("success") is False:
            return record
        return record

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Update conversation title or project assignment."""

        current = self.conversation_store.get_conversation(conversation_id)
        if current is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Conversation not found: {conversation_id}",
                    failed_step="update_conversation",
                    recoverable=True,
                    suggested_fix="Choose an existing conversation.",
                )
            )
        if project_id:
            project = self.project_store.get_project(project_id)
            if project is None:
                return _project_not_found_response(project_id, failed_step="update_conversation")
        previous_project_id = str(current.get("project_id") or "")
        record = self.conversation_store.update_conversation(
            conversation_id,
            title=title,
            project_id=project_id,
        )
        if record is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Conversation could not be updated: {conversation_id}",
                    failed_step="update_conversation",
                    recoverable=True,
                    suggested_fix="Use an existing conversation_id and valid project_id.",
                )
            )
        new_project_id = str(record.get("project_id") or "")
        if previous_project_id and previous_project_id != new_project_id:
            self.project_store.detach_conversation(previous_project_id, record["conversation_id"])
        if new_project_id:
            self.project_store.attach_conversation(new_project_id, record["conversation_id"])
        return _conversation_response(record)

    def delete_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Delete one persistent workbench conversation."""

        record = self.conversation_store.delete_conversation(conversation_id)
        if record is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Conversation not found: {conversation_id}",
                    failed_step="delete_conversation",
                    recoverable=True,
                    suggested_fix="Choose an existing conversation.",
                )
            )
        project_id = str(record.get("project_id") or "")
        if project_id:
            self.project_store.detach_conversation(project_id, conversation_id)
        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "deleted": True,
                "conversation_id": conversation_id,
                "warnings": [],
                "errors": [],
            }
        )

    def create_project(
        self,
        *,
        name: str = "",
        description: str = "",
        instructions: str = "",
        owner_id: str = "",
        tenant_id: str = "",
        owner_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a project workspace."""

        record = self.project_store.create_project(
            name=name,
            description=description,
            instructions=instructions,
            owner_id=owner_id,
            tenant_id=tenant_id,
            owner_context=owner_context,
        )
        return _project_response(record)

    def list_projects(self, *, limit: int = 50, owner_id: str = "", tenant_id: str = "") -> dict[str, Any]:
        """Return recent project workspaces."""

        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "projects": self.project_store.list_projects(limit=limit, owner_id=owner_id, tenant_id=tenant_id),
                "warnings": [],
                "errors": [],
            }
        )

    def get_project(self, project_id: str) -> dict[str, Any]:
        """Return one project workspace."""

        record = self.project_store.get_project(project_id)
        if record is None:
            return _project_not_found_response(project_id, failed_step="get_project")
        return _project_response(record)

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        default_dataset_id: str | None = None,
    ) -> dict[str, Any]:
        """Update one project workspace."""

        record = self.project_store.update_project(
            project_id,
            name=name,
            description=description,
            instructions=instructions,
            default_dataset_id=default_dataset_id,
        )
        if record is None:
            return _project_not_found_response(project_id, failed_step="update_project")
        return _project_response(record)

    def delete_project(self, project_id: str) -> dict[str, Any]:
        """Delete one project metadata record."""

        project = self.project_store.get_project(project_id)
        if project is None or not self.project_store.delete_project(project_id):
            return _project_not_found_response(project_id, failed_step="delete_project")
        detached_count = 0
        for conversation_id in project.get("conversation_ids") or []:
            updated = self.conversation_store.update_conversation(str(conversation_id), project_id="")
            if updated is not None:
                detached_count += 1
        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "deleted": True,
                "detached_conversation_count": detached_count,
                "warnings": [],
                "errors": [],
            }
        )

    def create_project_source(
        self,
        project_id: str,
        *,
        source_type: str = "note",
        title: str = "",
        content: str = "",
        dataset_id: str = "",
        file_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach a text or reference source to a project."""

        if self.project_store.get_project(project_id) is None:
            return _project_not_found_response(project_id, failed_step="create_project_source")
        source = self.project_store.add_source(
            project_id,
            source_type=source_type,
            title=title,
            content=content,
            dataset_id=dataset_id,
            file_id=file_id,
            metadata=metadata,
        )
        if source is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message="Project source could not be created.",
                    failed_step="create_project_source",
                    recoverable=True,
                    suggested_fix="Use a valid project_id and non-empty source content or reference.",
                )
            )
        return _project_source_response(self.project_store.get_project(project_id), source)

    def upload_project_sources(
        self,
        project_id: str,
        file_paths: list[str | Path],
        *,
        original_filenames: list[str | None] | None = None,
        file_role: str = DATASET_FILE_ROLE,
        rule_scope: str = "",
        bind_dataset_id: str = "",
    ) -> dict[str, Any]:
        """Upload dataset/rule files and attach resulting references to a project."""

        if self.project_store.get_project(project_id) is None:
            return _project_not_found_response(project_id, failed_step="upload_project_sources")
        try:
            normalized_file_role = _normalize_file_role(file_role)
        except Exception as exc:  # noqa: BLE001 - normalize upload errors at the service boundary.
            return error_response(
                error=ErrorResult(
                    error_type=FILE_PARSE_ERROR,
                    error_message=str(exc),
                    failed_step="upload_project_sources",
                    recoverable=True,
                    suggested_fix="Use file_role=dataset or file_role=rule for project source uploads.",
                )
            )
        if normalized_file_role == DATASET_FILE_ROLE and _is_project_text_source_upload(file_paths, original_filenames):
            try:
                sources: list[dict[str, Any]] = []
                for index, file_path in enumerate(file_paths):
                    original_name = None if original_filenames is None else original_filenames[index]
                    source = self.project_store.add_source(
                        project_id,
                        source_type="note",
                        title=str(original_name or Path(file_path).name),
                        content=_read_project_text_source(file_path),
                        metadata={
                            "file_role": "project_source",
                            "source_file_name": str(original_name or Path(file_path).name),
                        },
                    )
                    if source:
                        sources.append(source)
                project = self.project_store.get_project(project_id) or {}
                return to_json_ready(
                    {
                        "response_version": RESPONSE_VERSION,
                        "success": True,
                        "project_id": project_id,
                        "project": _project_summary_response(project),
                        "project_sources": sources,
                        "file_role": "project_source",
                        "warnings": [],
                        "errors": [],
                    }
                )
            except Exception as exc:  # noqa: BLE001 - normalize upload errors at the service boundary.
                return error_response(
                    error=ErrorResult(
                        error_type=FILE_PARSE_ERROR,
                        error_message=str(exc),
                        failed_step="upload_project_sources",
                        recoverable=True,
                        suggested_fix="Upload valid md, txt, yaml, or yml project source files.",
                    )
                )
        upload = self.upload_datasets(
            file_paths,
            original_filenames=original_filenames,
            file_role=normalized_file_role,
            rule_scope=rule_scope,
            bind_dataset_id=bind_dataset_id,
        )
        if not upload.get("success"):
            return upload
        sources: list[dict[str, Any]] = []
        if upload.get("dataset_id"):
            source = self.project_store.add_source(
                project_id,
                source_type="dataset",
                title=str(upload.get("file_name") or "Uploaded dataset"),
                dataset_id=str(upload.get("dataset_id") or ""),
                metadata={"tables": upload.get("tables") or [], "file_role": upload.get("file_role") or DATASET_FILE_ROLE},
            )
            if source:
                sources.append(source)
        for rule in upload.get("auto_bound_rule_files") or []:
            source = self.project_store.add_source(
                project_id,
                source_type="rule",
                title=str(rule.get("file_name") or "Rule file"),
                dataset_id=str(rule.get("dataset_id") or upload.get("dataset_id") or ""),
                file_id=str(rule.get("file_id") or ""),
                metadata={"rule_scope": rule.get("rule_scope") or USER_ANALYSIS_RULE_SCOPE},
            )
            if source:
                sources.append(source)
        for rule in upload.get("files") or []:
            source = self.project_store.add_source(
                project_id,
                source_type="rule",
                title=str(rule.get("file_name") or "Rule file"),
                dataset_id=str(rule.get("dataset_id") or ""),
                file_id=str(rule.get("file_id") or ""),
                metadata={"rule_scope": rule.get("rule_scope") or rule_scope},
            )
            if source:
                sources.append(source)
        project = self.project_store.get_project(project_id) or {}
        upload["project_id"] = project_id
        upload["project"] = _project_summary_response(project)
        upload["project_sources"] = sources
        return to_json_ready(upload)

    def delete_project_source(self, project_id: str, source_id: str) -> dict[str, Any]:
        """Remove one project source reference."""

        record = self.project_store.delete_source(project_id, source_id)
        if record is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Project source not found: {source_id}",
                    failed_step="delete_project_source",
                    recoverable=True,
                    suggested_fix="Choose an existing source in the selected project.",
                )
            )
        return _project_response(record)

    def create_project_memory(
        self,
        project_id: str,
        *,
        content: str,
        memory_type: str = "pinned",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create project-only memory."""

        if self.project_store.get_project(project_id) is None:
            return _project_not_found_response(project_id, failed_step="create_project_memory")
        memory = self.project_store.add_memory(
            project_id,
            content=content,
            memory_type=memory_type,
            title=title,
            metadata=metadata,
        )
        if memory is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message="Project memory could not be created.",
                    failed_step="create_project_memory",
                    recoverable=True,
                    suggested_fix="Use non-empty memory content in an existing project.",
                )
            )
        return _project_memory_response(self.project_store.get_project(project_id), memory)

    def update_project_memory(
        self,
        project_id: str,
        memory_id: str,
        *,
        content: str | None = None,
        title: str | None = None,
        memory_type: str | None = None,
    ) -> dict[str, Any]:
        """Update project-only memory."""

        memory = self.project_store.update_memory(
            project_id,
            memory_id,
            content=content,
            title=title,
            memory_type=memory_type,
        )
        if memory is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Project memory not found: {memory_id}",
                    failed_step="update_project_memory",
                    recoverable=True,
                    suggested_fix="Choose an existing memory in the selected project.",
                )
            )
        return _project_memory_response(self.project_store.get_project(project_id), memory)

    def delete_project_memory(self, project_id: str, memory_id: str) -> dict[str, Any]:
        """Delete project-only memory."""

        record = self.project_store.delete_memory(project_id, memory_id)
        if record is None:
            return error_response(
                error=ErrorResult(
                    error_type=LOGIC_FORM_ERROR,
                    error_message=f"Project memory not found: {memory_id}",
                    failed_step="delete_project_memory",
                    recoverable=True,
                    suggested_fix="Choose an existing memory in the selected project.",
                )
            )
        return _project_response(record)

    def _record_conversation_turn(
        self,
        response: dict[str, Any],
        *,
        conversation_id: str,
        question: str,
        dataset_id: str,
        project_id: str,
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
            project_id=project_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            owner_context=owner_context,
        )
        if project_id:
            self.project_store.attach_conversation(project_id, record["conversation_id"])
        response["conversation_id"] = record["conversation_id"]
        response["conversation"] = {
            "conversation_id": record["conversation_id"],
            "title": record.get("title") or "",
            "dataset_id": record.get("dataset_id") or "",
            "project_id": record.get("project_id") or "",
            "updated_at": record.get("updated_at"),
            "message_count": len(record.get("messages") or []),
        }
        return to_json_ready(response)

    def chat_without_dataset(
        self,
        *,
        question: str,
        agent_mode: str = "multi_agent",
        monitor_run_id: str = "",
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
        response = to_json_ready(
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
                "process_view_v2": build_chat_process_view(cleaned_question, has_dataset=False),
                "warnings": [],
                "errors": [],
                "debug": {"agent_mode": "chat_without_dataset", "requires_dataset": False},
            }
        )
        emit_monitor_event(
            monitor_run_id,
            "workflow_completed",
            title="直接回复完成",
            summary="当前没有数据集，本次没有进入数据分析 agent 链路。",
            stage="chat",
            status="completed",
            payload=process_view_monitor_payload(response),
        )
        return response

    def chat_with_dataset(
        self,
        *,
        dataset_id: str,
        question: str,
        agent_mode: str = "multi_agent",
        monitor_run_id: str = "",
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
        response = to_json_ready(
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
                "process_view_v2": build_chat_process_view(cleaned_question, has_dataset=True),
                "warnings": [],
                "errors": [],
                "debug": {"agent_mode": "chat_with_dataset", "requires_dataset": False, "message_intent": "chat"},
            }
        )
        emit_monitor_event(
            monitor_run_id,
            "workflow_completed",
            title="直接回复完成",
            summary="本次是普通对话，保留数据集上下文但未进入完整分析链路。",
            stage="chat",
            status="completed",
            payload=process_view_monitor_payload(response),
        )
        return response

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
        response = dataset_profile_response(profile)
        bound = self.file_store.get_bound_rule_file_ids(dataset_id, rule_scope=USER_ANALYSIS_RULE_SCOPE)
        if bound:
            response["auto_bound_user_rule_file_ids"] = bound
        return response

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
        monitor_run_id: str = "",
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
            monitor_run_id=monitor_run_id,
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


def _normalize_file_role(file_role: str) -> str:
    role = (file_role or DATASET_FILE_ROLE).strip()
    if role not in VALID_FILE_ROLES:
        raise ValueError("file_role must be dataset or rule.")
    return role


def _validate_dataset_upload(file_path: str | Path, *, original_filename: str | None, rule_scope: str) -> None:
    if rule_scope:
        raise ValueError("dataset uploads must not include rule_scope.")
    suffix = Path(str(original_filename or Path(file_path).name)).suffix.lower() or Path(file_path).suffix.lower()
    if suffix not in DATASET_FILE_EXTENSIONS:
        raise ValueError(
            f"Unsupported dataset file type: {suffix or '(none)'}. "
            "Dataset files must use csv, xlsx, xls, json, parquet, arrow, or feather."
        )


def _split_dataset_and_auto_rule_files(
    file_paths: list[str | Path],
    original_filenames: list[str | None] | None,
) -> tuple[list[str | Path], list[str | None] | None, list[str | Path], list[str | None]]:
    """Split mixed Workbench uploads into dataset files and user knowledge files."""

    if _looks_like_complete_dab_context(file_paths, original_filenames):
        return file_paths, original_filenames, [], []
    dataset_paths: list[str | Path] = []
    dataset_names: list[str | None] = []
    rule_paths: list[str | Path] = []
    rule_names: list[str | None] = []
    for index, file_path in enumerate(file_paths):
        original_name = None if original_filenames is None else original_filenames[index]
        if _looks_like_auto_user_rule_file(file_path, original_name):
            rule_paths.append(file_path)
            rule_names.append(original_name)
        else:
            dataset_paths.append(file_path)
            dataset_names.append(original_name)
    return dataset_paths, dataset_names if original_filenames is not None else None, rule_paths, rule_names


def _looks_like_complete_dab_context(file_paths: list[str | Path], original_filenames: list[str | None] | None) -> bool:
    required = {"payments.csv", "merchant_category_codes.csv", "acquirer_countries.csv", "fees.json", "merchant_data.json", "manual.md"}
    names = {
        Path(str((None if original_filenames is None else original_filenames[index]) or Path(file_path).name)).name.lower()
        for index, file_path in enumerate(file_paths)
    }
    return required.issubset(names)


def _raise_if_rule_only_dabstep_partial(file_paths: list[str | Path], original_filenames: list[str | None] | None) -> None:
    """Keep DABstep rule-only partial uploads on the old clear error path."""

    required = {"payments.csv", "merchant_category_codes.csv", "acquirer_countries.csv", "fees.json", "merchant_data.json", "manual.md"}
    names = {
        Path(str((None if original_filenames is None else original_filenames[index]) or Path(file_path).name)).name.lower()
        for index, file_path in enumerate(file_paths)
    }
    if not names or required.issubset(names):
        return
    present = names & required
    if not present:
        return
    dataset_like = [
        name
        for name in names
        if Path(name).suffix.lower() in DATASET_FILE_EXTENSIONS and not _looks_like_auto_user_rule_file(name, name)
    ]
    if dataset_like:
        return
    missing = ", ".join(sorted(required - names))
    raise ValueError(
        "DABstep context package is incomplete. "
        "Upload these files together from the web workbench: "
        "payments.csv, merchant_category_codes.csv, acquirer_countries.csv, "
        f"fees.json, merchant_data.json, manual.md. Missing: {missing}."
    )


def _looks_like_auto_user_rule_file(file_path: str | Path, original_filename: str | None) -> bool:
    name = Path(str(original_filename or Path(file_path).name)).name
    lowered = name.lower()
    suffix = Path(name).suffix.lower() or Path(file_path).suffix.lower()
    if suffix in {".md", ".txt", ".yaml", ".yml"}:
        return True
    if suffix == ".json":
        return any(
            token in lowered
            for token in (
                "rule",
                "rules",
                "manual",
                "guideline",
                "guide",
                "schema",
                "metadata",
                "dictionary",
                "definition",
                "meaning",
                "fee",
                "说明",
                "字段",
                "口径",
                "规则",
                "计算",
            )
        )
    return False


def _is_project_text_source_upload(file_paths: list[str | Path], original_filenames: list[str | None] | None) -> bool:
    """Return true for project shared text files that should not enter DataFrame parsing."""

    if not file_paths:
        return False
    if original_filenames is not None and len(original_filenames) != len(file_paths):
        return False
    text_source_suffixes = {".md", ".txt", ".yaml", ".yml"}
    for index, file_path in enumerate(file_paths):
        original_name = None if original_filenames is None else original_filenames[index]
        suffix = Path(str(original_name or Path(file_path).name)).suffix.lower() or Path(file_path).suffix.lower()
        if suffix not in text_source_suffixes:
            return False
    return True


def _read_project_text_source(file_path: str | Path) -> str:
    path = Path(file_path)
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"Project source file is not valid text: {last_error}") from last_error


def _rule_file_response(record: StoredRuleFile) -> dict[str, Any]:
    return to_json_ready(
        {
            "response_version": RESPONSE_VERSION,
            "success": True,
            "file_id": record.file_id,
            "file_name": record.file_name,
            "file_role": record.file_role,
            "rule_scope": record.rule_scope,
            "dataset_id": record.dataset_id,
            "status": "ready",
            "rule_summary": _rule_summary(record),
            "warnings": list(record.warnings),
            "errors": [],
        }
    )


def _public_rule_record(record: StoredRuleFile) -> dict[str, Any]:
    return {
        "file_id": record.file_id,
        "file_name": record.file_name,
        "file_role": record.file_role,
        "rule_scope": record.rule_scope,
        "dataset_id": record.dataset_id,
        "warnings": list(record.warnings),
    }


def _rule_files_response(records: list[StoredRuleFile]) -> dict[str, Any]:
    return to_json_ready(
        {
            "response_version": RESPONSE_VERSION,
            "success": True,
            "file_role": RULE_FILE_ROLE,
            "files": [_rule_file_response(record) for record in records],
            "file_ids": [record.file_id for record in records],
            "warnings": [warning for record in records for warning in record.warnings],
            "errors": [],
        }
    )


def _rule_summary(record: StoredRuleFile) -> dict[str, Any]:
    parsed = record.parsed_rule if isinstance(record.parsed_rule, dict) else {}
    if record.rule_scope == BENCHMARK_RULE_SCOPE:
        return {
            "benchmark": _benchmark_name(parsed, record.file_name),
            "questions_count": len(_benchmark_questions(parsed)),
            "metrics": parsed.get("metrics") or [],
            "threshold": parsed.get("threshold"),
        }
    raw_text = record.raw_text or ""
    return {
        "line_count": len([line for line in raw_text.splitlines() if line.strip()]),
        "has_structured_fields": bool(parsed and "raw_text" not in parsed),
    }


def _public_rule_context(rule_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": True,
        "file_id": rule_context.get("file_id"),
        "file_name": rule_context.get("file_name"),
        "file_role": rule_context.get("file_role"),
        "rule_scope": rule_context.get("rule_scope"),
        "warnings": list(rule_context.get("warnings") or []),
    }


def _user_rule_guidelines(rule_context: dict[str, Any]) -> str:
    parsed = rule_context.get("parsed_rule")
    raw_text = str(rule_context.get("raw_text") or "").strip()
    if isinstance(parsed, dict) and "raw_text" not in parsed:
        return (
            "User analysis rules from uploaded rule file. These rules constrain this analysis only; "
            "do not treat the rule file as a dataset.\n"
            + json_dumps_compact(parsed)
        )
    return (
        "User analysis rules from uploaded rule file. These rules constrain this analysis only; "
        "do not treat the rule file as a dataset.\n"
        + raw_text
    )


def _combine_guidelines(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _benchmark_name(parsed_rule: dict[str, Any], fallback: str) -> str:
    return str(parsed_rule.get("benchmark_name") or parsed_rule.get("name") or Path(fallback).stem or "uploaded_benchmark")


def _benchmark_questions(parsed_rule: dict[str, Any]) -> list[dict[str, Any]]:
    raw_questions = parsed_rule.get("questions") or parsed_rule.get("test_questions") or parsed_rule.get("cases") or []
    questions: list[dict[str, Any]] = []
    for index, item in enumerate(raw_questions, start=1):
        if isinstance(item, str):
            questions.append({"id": f"case_{index}", "question": item, "guidelines": "", "expected_output": ""})
            continue
        if isinstance(item, dict):
            questions.append(
                {
                    "id": item.get("id") or item.get("case_id") or f"case_{index}",
                    "question": str(item.get("question") or ""),
                    "guidelines": str(item.get("guidelines") or item.get("rule") or ""),
                    "expected_output": item.get("expected_output", item.get("expected")),
                }
            )
    return [item for item in questions if str(item.get("question") or "").strip()]


def json_dumps_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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


def _attach_project_metadata(response: dict[str, Any], project_context: dict[str, Any]) -> None:
    """Attach trace-safe project metadata to a response payload."""

    if not project_context.get("enabled"):
        return
    project = {
        "project_id": project_context.get("project_id") or "",
        "name": project_context.get("name") or "",
        "memory_mode": project_context.get("memory_mode") or "project_only",
        "source_count": project_context.get("source_count") or 0,
        "memory_count": project_context.get("memory_count") or 0,
        "default_dataset_id": project_context.get("default_dataset_id") or "",
    }
    response["project_id"] = project["project_id"]
    response["project"] = project
    response.setdefault("debug", {})
    response["debug"]["project_context"] = project


def _project_response(record: dict[str, Any] | None) -> dict[str, Any]:
    """Build a stable project API response."""

    return to_json_ready(
        {
            "response_version": RESPONSE_VERSION,
            "success": bool(record),
            "project": record or {},
            "warnings": [],
            "errors": [],
        }
    )


def _project_source_response(project: dict[str, Any] | None, source: dict[str, Any]) -> dict[str, Any]:
    """Build a stable project source response."""

    return to_json_ready(
        {
            "response_version": RESPONSE_VERSION,
            "success": True,
            "project": _project_summary_response(project or {}),
            "source": source,
            "warnings": [],
            "errors": [],
        }
    )


def _project_memory_response(project: dict[str, Any] | None, memory: dict[str, Any]) -> dict[str, Any]:
    """Build a stable project memory response."""

    return to_json_ready(
        {
            "response_version": RESPONSE_VERSION,
            "success": True,
            "project": _project_summary_response(project or {}),
            "memory": memory,
            "warnings": [],
            "errors": [],
        }
    )


def _project_summary_response(record: dict[str, Any]) -> dict[str, Any]:
    """Return trace-safe project summary fields."""

    return {
        "project_id": record.get("project_id") or "",
        "name": record.get("name") or "",
        "description": record.get("description") or "",
        "memory_mode": record.get("memory_mode") or "project_only",
        "default_dataset_id": record.get("default_dataset_id") or "",
        "source_count": len(record.get("sources") or []),
        "memory_count": len(record.get("memories") or []),
        "conversation_count": len(record.get("conversation_ids") or []),
        "updated_at": record.get("updated_at"),
    }


def _project_not_found_response(project_id: str, *, failed_step: str) -> dict[str, Any]:
    return error_response(
        error=ErrorResult(
            error_type=LOGIC_FORM_ERROR,
            error_message=f"Project not found: {project_id}",
            failed_step=failed_step,
            recoverable=True,
            suggested_fix="Choose an existing project or create a new one.",
        )
    )


def _chat_answer(question: str, *, has_dataset: bool) -> str:
    lowered = question.lower()
    compact = lowered.replace(" ", "")
    if ("raw" in compact and any(token in compact for token in ("prompt", "trace", "sql"))) or any(token in question for token in ("标准答案", "trace", "后端审计")):
        return "不会展示 raw prompt、trace、SQL、标准答案、scorer 或后端审计 JSON。我只会给用户可读的问题理解、数据依据、计算口径和结果边界。"
    if any(token in question for token in ("外部维表", "真实名称", "直接说成真实名称")):
        return "不能把 ID 直接说成真实名称。没有外部维表或上传的映射表时，我只能说明这是 ID / 编号字段，并提示需要补充映射后再解释真实名称。"
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


def _suppress_raw_detail_answer(
    payload: dict[str, Any],
    *,
    question: str,
    tables: dict[str, Any],
    profile: Any,
    agent_mode: str,
) -> dict[str, Any]:
    answer = str(payload.get("answer") or "")
    if not _looks_like_raw_detail_dump(answer) or _allows_detail_answer(question):
        return payload
    try:
        replacement = build_dataset_overview_response(
            run_id=str(payload.get("run_id") or "run_guarded"),
            dataset_id=str(payload.get("dataset_id") or ""),
            question=question,
            tables=tables,
            profile=profile,
            agent_mode=agent_mode,
        )
        replacement.setdefault("debug", {})
        replacement["debug"]["raw_detail_answer_guard"] = {
            "applied": True,
            "reason": "final_answer_looked_like_raw_detail_dump",
            "original_answer_length": len(answer),
        }
        return to_json_ready(replacement)
    except Exception:  # noqa: BLE001 - last-resort UX guard.
        guarded = dict(payload)
        guarded["answer"] = (
            "本次执行返回了原始明细行，不适合直接作为答案；我已停止展示明细。"
            "请指定要汇总的指标、维度、时间范围或清洗规则后继续分析。"
        )
        guarded["answer_type"] = "clarification"
        guarded["result"] = {"columns": [], "rows": [], "value": None}
        guarded.setdefault("debug", {})
        guarded["debug"]["raw_detail_answer_guard"] = {"applied": True, "reason": "fallback_guard"}
        return guarded


def _looks_like_raw_detail_dump(answer: str) -> bool:
    text = " ".join(str(answer or "").split())
    if len(text) < 500:
        return False
    comma_count = text.count(",")
    if comma_count < 30:
        return False
    token_count = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff_.-]+", text))
    sentence_count = len(re.findall(r"[。！？；;]", text))
    return token_count >= 60 and sentence_count <= 6


def _allows_detail_answer(question: str) -> bool:
    compact = str(question or "").lower().replace(" ", "")
    return any(
        token in compact
        for token in (
            "列出明细",
            "展示明细",
            "查看明细",
            "给我明细",
            "原始明细",
            "明细行",
            "样例行",
            "样本行",
            "前10行",
            "前20行",
            "前十行",
            "前二十行",
            "samplerows",
            "rawrows",
        )
    )

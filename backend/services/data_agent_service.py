"""Backend service shell for calling data_agent_core."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import pandas as pd

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
from backend.storage.temp_file_store import StoredRuleFile, TempFileStore, _read_source_text
from backend.services.export_service import generate_export_artifacts
from data_agent_core.agent.single_agent import DataAnalysisAgent, UploadedDatasetAgent
from data_agent_core.benchmark.evaluator import question_scorer
from data_agent_core.contracts.analysis_contracts import UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import (
    action_questions,
    build_analysis_context,
    plan_followup_actions,
)
from data_agent_core.core.intent_parser import parse_question
from data_agent_core.core.message_intent import (
    classify_workbench_message,
    is_cleaning_guidance_question,
    is_dataset_overview_question,
    is_dataset_source_question,
)
from data_agent_core.core.file_parser import load_dabstep_context, parse_dataset_file, parse_dataset_files
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import FILE_PARSE_ERROR, LOGIC_FORM_ERROR
from data_agent_core.executors import pandas_executor
from data_agent_core.llm.client import LLMClient, MissingLLMConfigError, load_llm_client_from_env
from data_agent_core.llm.planner import complete_stage_with_llm
from data_agent_core.output.activity_trace import build_activity_trace_v2
from data_agent_core.output.cleaning_guidance import build_cleaning_guidance_response
from data_agent_core.output.dataset_overview import build_dataset_overview_response
from data_agent_core.output.process_narrative import build_chat_process_view, process_view_monitor_payload
from data_agent_core.output.response_builder import build_response
from data_agent_core.output.source_overview import build_dataset_source_overview_response
from data_agent_core.output.text_answer_framework import apply_text_answer_framework
from data_agent_core.task_execution_contracts import (
    build_task_execution_contract,
    semantic_status_from_report,
    verify_task_execution_contract,
)
from data_agent_core.task_contract_builder import referent_contract_guideline
from data_agent_core.tracing.live_monitor import emit_monitor_event
from data_agent_core.verifier.rule_checker import verify_execution
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
            role, rule_scope = _resolve_upload_file_role_and_scope(
                file_role=file_role,
                rule_scope=rule_scope,
                file_paths=[file_path],
                original_filenames=[original_filename],
            )
            if role == RULE_FILE_ROLE:
                record = self.file_store.save_rule_file(
                    file_path,
                    original_filename=original_filename,
                    rule_scope=rule_scope,
                    dataset_id=bind_dataset_id,
                )
                return _rule_file_response(record)
            if _is_source_only_upload([file_path], [original_filename]):
                stored = self.file_store.save_source_only_files(
                    [file_path],
                    original_filenames=[original_filename],
                )
                response = dataset_profile_response(stored.profile)
                response["dataset_kind"] = stored.dataset_kind
                response["source_file_count"] = 1
                _attach_uploaded_file_records(response, [file_path], [original_filename])
                return to_json_ready(response)
            _validate_dataset_upload(file_path, original_filename=original_filename, rule_scope=rule_scope)
            parsed = parse_dataset_file(file_path, source_name=original_filename)
            self.file_store.save_parsed_dataset(file_path, parsed)
            response = dataset_profile_response(parsed.profile)
            _attach_uploaded_file_records(response, [file_path], [original_filename])
            return response
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
            role, rule_scope = _resolve_upload_file_role_and_scope(
                file_role=file_role,
                rule_scope=rule_scope,
                file_paths=file_paths,
                original_filenames=original_filenames,
            )
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
            if bind_dataset_id and _looks_like_auto_user_rule_file_upload(file_paths, original_filenames):
                records = self.file_store.save_rule_files(
                    file_paths,
                    original_filenames=original_filenames,
                    rule_scope=USER_ANALYSIS_RULE_SCOPE,
                    dataset_id=bind_dataset_id,
                )
                response = _rule_files_response(records)
                response["bound_dataset_id"] = bind_dataset_id
                response["auto_bound_user_rule_file_ids"] = [record.file_id for record in records]
                response["auto_bound_rule_files"] = [_public_rule_record(record) for record in records]
                response.setdefault("warnings", [])
                response["warnings"].append(
                    "已自动识别并绑定用户分析规则文件：" + ", ".join(record.file_name for record in records)
                )
                return to_json_ready(response)
            if _is_source_only_upload(file_paths, original_filenames):
                stored = self.file_store.save_source_only_files(
                    file_paths,
                    original_filenames=original_filenames,
                )
                response = dataset_profile_response(stored.profile)
                response["dataset_kind"] = stored.dataset_kind
                response["source_file_count"] = len(file_paths)
                _attach_uploaded_file_records(response, file_paths, original_filenames)
                return to_json_ready(response)
            _raise_if_rule_only_dabstep_partial(file_paths, original_filenames)
            dataset_paths, dataset_names, rule_paths, rule_names = _split_dataset_and_auto_rule_files(
                file_paths,
                original_filenames,
            )
            if not dataset_paths:
                raise ValueError("Upload at least one dataset file together with optional rule files.")
            if rule_paths:
                parsed = parse_dataset_files(dataset_paths, source_names=dataset_names)
                stored = self.file_store.save_parsed_dataset_files(
                    dataset_paths,
                    parsed,
                    original_filenames=dataset_names,
                )
            else:
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
            response["dataset_kind"] = stored.dataset_kind
            _attach_uploaded_file_records(response, file_paths, original_filenames)
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
        project_context: dict[str, Any] | None = None,
        run_id: str | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Run the configured Data Agent workflow for an uploaded dataset."""

        run_id = run_id or "run_" + uuid.uuid4().hex[:16]
        _raise_if_cancelled(cancel_checker)
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
            user_rule_contexts, user_rule_context = self._user_rule_contexts(
                user_rule_file_id=user_rule_file_id,
                dataset_id=dataset_id,
            )
            if user_rule_contexts:
                guidelines = _combine_guidelines(
                    guidelines,
                    *[_user_rule_guidelines(context) for context in user_rule_contexts],
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
            tables, applied_project_metrics = _apply_project_derived_metrics_to_tables(
                tables,
                project_context=project_context or {},
            )
            profile = self.file_store.get_profile(dataset_id)
            dataset_kind = self.file_store.get_dataset_kind(dataset_id)
            analysis_context = self.file_store.get_analysis_context(dataset_id)
            rule_augmented_context = None
            if dataset_kind != "dabstep_context":
                rule_augmented_context = self._build_user_rule_fee_context(
                    dataset_id=dataset_id,
                    tables=tables,
                    user_rule_file_id=user_rule_file_id,
                )
                if rule_augmented_context is not None:
                    analysis_context = rule_augmented_context
            source_manifest = self.file_store.get_dataset_sources(dataset_id)
            emit_monitor_event(
                monitor_run_id,
                "data_scan_note",
                title="检查文件结构",
                summary=f"我先检查已上传数据结构：{len(tables)} 张表。",
                stage="service",
                status="completed",
                payload={"dataset_id": dataset_id, "table_count": len(tables)},
            )
            fee_rule_response = self._try_rule_backed_fee_id_analysis(
                run_id=run_id,
                dataset_id=dataset_id,
                question=question,
                guidelines=guidelines,
                execution_mode=execution_mode,
                agent_mode=agent_mode,
                tables=tables,
                profile=profile,
                user_rule_contexts=user_rule_contexts,
                user_rule_context=user_rule_context,
            )
            if fee_rule_response is not None:
                _raise_if_cancelled(cancel_checker)
                fee_rule_response = _apply_user_rule_output_constraints(fee_rule_response, user_rule_contexts)
                _ensure_activity_trace_v2(fee_rule_response)
                emit_monitor_event(
                    monitor_run_id,
                    "answer_outline_ready",
                    title="Fee ID 回答已生成",
                    summary="已用当前启用的费用规则文件和 payments 表执行 Fee ID 查询。",
                    stage="fee_rule",
                    status="completed" if fee_rule_response.get("success") else "failed",
                    payload={
                        "run_id": fee_rule_response.get("run_id"),
                        "dataset_id": dataset_id,
                        "answer_type": fee_rule_response.get("answer_type"),
                    },
                )
                emit_monitor_event(
                    monitor_run_id,
                    "workflow_completed",
                    title="Fee ID 查询完成",
                    summary="本次问题命中 rule-backed fee analysis 路径，未把规则文件当作普通数据表分析。",
                    stage="fee_rule",
                    status="completed" if fee_rule_response.get("success") else "failed",
                    payload=process_view_monitor_payload(fee_rule_response),
                )
                return to_json_ready(_ensure_semantic_response_fields(fee_rule_response))
            semantic_route = self._route_dataset_message(
                question=question,
                profile=profile,
                dataset_kind=dataset_kind,
                source_manifest=source_manifest,
            )
            if semantic_route["route"] == "dataset_source_overview":
                _raise_if_cancelled(cancel_checker)
                response = to_json_ready(
                    build_dataset_source_overview_response(
                        run_id=run_id,
                        dataset_id=dataset_id,
                        question=question.strip(),
                        source_manifest=source_manifest,
                        tables=tables,
                        agent_mode=agent_mode,
                    )
                )
                response.setdefault("debug", {})
                response["debug"]["semantic_route"] = semantic_route
                response = self._apply_fast_path_llm_presentation(
                    response,
                    question=question.strip(),
                    route="dataset_source_overview",
                    table_count=len(tables),
                )
                response = _apply_gpt_like_text_framework(response, question=question.strip())
                _ensure_activity_trace_v2(response)
                emit_monitor_event(
                    monitor_run_id,
                    "answer_outline_ready",
                    title="来源文件说明已整理",
                    summary="已读取上传来源清单，并区分表格、说明、规则和知识文件。",
                    stage="dataset_source_overview",
                    status="completed",
                    payload={"run_id": run_id, "dataset_id": dataset_id, "answer_type": response.get("answer_type")},
                )
                emit_monitor_event(
                    monitor_run_id,
                    "workflow_completed",
                    title="来源文件概览完成",
                    summary="本次问题命中来源文件概览路径，未进入完整 multi-agent 执行链。",
                    stage="dataset_source_overview",
                    status="completed",
                    payload=process_view_monitor_payload(response),
                )
                return _ensure_semantic_response_fields(response)
            if semantic_route["route"] == "cleaning_guidance":
                _raise_if_cancelled(cancel_checker)
                response = to_json_ready(
                    build_cleaning_guidance_response(
                        run_id=run_id,
                        dataset_id=dataset_id,
                        question=question.strip(),
                        tables=tables,
                        agent_mode=agent_mode,
                    )
                )
                response.setdefault("debug", {})
                response["debug"]["semantic_route"] = semantic_route
                response = self._apply_fast_path_llm_presentation(
                    response,
                    question=question.strip(),
                    route="cleaning_guidance",
                    table_count=len(tables),
                )
                _attach_source_references(response, profile=profile)
                response = _apply_gpt_like_text_framework(response, question=question.strip())
                _ensure_activity_trace_v2(response)
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
                return _ensure_semantic_response_fields(response)
            if semantic_route["route"] == "dataset_overview":
                _raise_if_cancelled(cancel_checker)
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
                response.setdefault("debug", {})
                response["debug"]["semantic_route"] = semantic_route
                response = self._apply_fast_path_llm_presentation(
                    response,
                    question=question.strip(),
                    route="dataset_overview",
                    table_count=len(tables),
                )
                _attach_fast_path_overview_contract_checks(response, question=question.strip())
                _attach_source_references(response, profile=profile)
                response = _apply_gpt_like_text_framework(response, question=question.strip())
                _ensure_activity_trace_v2(response)
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
                return _ensure_semantic_response_fields(response)
            if agent_mode == "single_agent":
                _raise_if_cancelled(cancel_checker)
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
                context_dir = analysis_context.get("context_dir") if isinstance(analysis_context, dict) else None
                if context_dir is not None and "payments" in (analysis_context or {}):
                    agent = DataAnalysisAgent(context_dir=context_dir, dataset_id=dataset_id, llm_client=self.llm_client)
                elif dataset_kind == "dabstep_context":
                    context_dir = self.file_store.get_context_dir(dataset_id)
                    if context_dir is None:
                        raise ValueError("DABstep context files are not available for single_agent analysis.")
                    agent = DataAnalysisAgent(context_dir=context_dir, dataset_id=dataset_id, llm_client=self.llm_client)
                else:
                    agent = UploadedDatasetAgent(tables=tables, dataset_id=dataset_id, llm_client=self.llm_client)
                response, trace = agent.analyze(question=question, guidelines=guidelines, execution_mode=execution_mode)
                response.run_id = run_id
                trace.run_id = run_id
                _raise_if_cancelled(cancel_checker)
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
            elif analysis_context is not None and "payments" in analysis_context and "context_dir" in analysis_context:
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
                    run_id=run_id,
                    cancel_checker=cancel_checker,
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
                    run_id=run_id,
                    cancel_checker=cancel_checker,
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
                    run_id=run_id,
                    cancel_checker=cancel_checker,
                )
            trace_path = self.file_store.write_run_trace(trace)
            payload = response.to_dict()
            payload.setdefault("debug", {})
            payload["debug"]["trace_path"] = str(trace_path)
            payload["debug"]["agent_mode"] = agent_mode
            payload["debug"]["dataset_kind"] = dataset_kind
            payload["debug"]["user_rule_context"] = user_rule_context
            if applied_project_metrics:
                payload["debug"]["project_derived_metrics_applied"] = applied_project_metrics
            if rule_augmented_context is not None:
                payload["debug"]["rule_augmented_fee_context"] = True
                payload["debug"]["effective_context_kind"] = "user_rule_fee_context"
            if monitor_run_id:
                payload["debug"]["monitor_run_id"] = monitor_run_id
            if dataset_kind == "dabstep_context" or rule_augmented_context is not None:
                payload["debug"]["knowledge_files"] = ["manual.md", "fees.json", "merchant_data.json"]
            formula_lineage = _formula_lineage_from_payload(payload)
            if formula_lineage:
                payload["debug"]["formula_lineage"] = formula_lineage
            payload = _suppress_raw_detail_answer(
                payload,
                question=question,
                tables=tables,
                profile=profile,
                agent_mode=agent_mode,
            )
            payload = self._rescue_unexpected_not_applicable(
                payload,
                question=question,
                tables=tables,
                profile=profile,
                source_manifest=source_manifest,
                agent_mode=agent_mode,
            )
            _attach_source_references(payload, profile=profile)
            payload = _apply_gpt_like_text_framework(payload, question=question)
            payload = _apply_user_rule_output_constraints(payload, user_rule_contexts)
            _ensure_activity_trace_v2(payload)
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
            return to_json_ready(_ensure_semantic_response_fields(payload))
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

    def _try_rule_backed_fee_id_analysis(
        self,
        *,
        run_id: str,
        dataset_id: str,
        question: str,
        guidelines: str,
        execution_mode: str,
        agent_mode: str,
        tables: dict[str, Any],
        profile: Any,
        user_rule_contexts: list[dict[str, Any]],
        user_rule_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Answer Fee ID questions from enabled rule files instead of the plain payments table."""

        if not _looks_like_fee_id_question(question):
            return None
        context_payload = _materialize_rule_backed_fee_context(
            self.file_store.root,
            dataset_id=dataset_id,
            tables=tables,
            user_rule_contexts=user_rule_contexts,
        )
        if context_payload is None:
            return None
        context = context_payload["context"]
        logic_form = parse_question(question, guidelines, context)
        if logic_form.operation not in FEE_ID_RULE_OPERATIONS:
            return None

        plan = build_analysis_plan(logic_form, question=question)
        execution_result = pandas_executor.execute_plan(plan, context)
        user_question = UserQuestion(
            dataset_id=dataset_id,
            question=question,
            execution_mode=execution_mode,
            guidelines=guidelines,
        )
        verification = verify_execution(execution_result, plan=plan, user_question=user_question)
        response = build_response(
            run_id=run_id,
            user_question=user_question,
            plan=plan,
            execution_result=execution_result,
            verification=verification,
            debug={
                "agent_mode": agent_mode,
                "dataset_kind": "uploaded_tables_with_user_fee_rules",
                "operation": logic_form.operation,
                "source_tables": [context_payload["payments_table"]],
                "logical_source_tables": list(logic_form.source_tables or ["payments"]),
                "knowledge_files": context_payload["knowledge_files"],
                "user_rule_context": user_rule_context,
                "rule_augmented_fee_context": True,
                "rule_backed_fee_analysis": {
                    "applied": True,
                    "payments_table": context_payload["payments_table"],
                    "rule_files": context_payload["knowledge_files"],
                    "context_dir": str(context_payload["context_dir"]),
                },
            },
        )
        payload = response.to_dict()
        payload["debug"]["user_rule_context"] = user_rule_context
        payload["debug"]["rule_backed_fee_analysis"]["answer_count"] = _fee_id_answer_count(execution_result.value)
        _shape_fee_id_result_table(payload, execution_result.value)
        _attach_source_references(payload, profile=profile)
        _append_rule_source_references(payload, user_rule_contexts, context_payload["knowledge_files"])
        payload["insight"] = _fee_id_insight(
            operation=logic_form.operation,
            value=execution_result.value,
            filters=logic_form.filters,
        )
        payload["reasoning_trace_view"] = _fee_id_reasoning_trace(
            operation=logic_form.operation,
            execution_success=execution_result.success,
            verification_passed=verification.passed,
            rule_files=context_payload["knowledge_files"],
        )
        payload["process_view_v2"] = _fee_id_process_view(
            operation=logic_form.operation,
            execution_success=execution_result.success,
            verification_passed=verification.passed,
            answer_count=_fee_id_answer_count(execution_result.value),
        )
        return _ensure_semantic_response_fields(payload)

    def _route_dataset_message(
        self,
        *,
        question: str,
        profile: Any,
        dataset_kind: str,
        source_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Choose fast-path route using semantic intent, not exact phrase patches."""

        deterministic_route = _semantic_dataset_route(question, source_manifest=source_manifest)
        compact_question = re.sub(r"\s+", "", str(question or "").strip().lower())
        semantics = _question_semantics(compact_question)
        fee_calculation = _looks_like_fee_calculation_question(compact_question)
        llm_route = self._try_llm_route_dataset_message(
            question=question,
            profile=profile,
            dataset_kind=dataset_kind,
            source_manifest=source_manifest,
        )
        route = deterministic_route
        if llm_route.get("route") in {"chat", "cleaning_guidance", "dataset_overview", "dataset_source_overview", "analysis"}:
            llm_confidence = float(llm_route.get("confidence") or 0.0)
            if llm_confidence >= 0.55:
                candidate_route = str(llm_route["route"])
                if not (deterministic_route == "analysis" and semantics["calculation"] and candidate_route != "analysis"):
                    route = candidate_route
        if route == "analysis" and not fee_calculation and not semantics["calculation"]:
            legacy_route = classify_workbench_message(question, has_dataset=True)
            if legacy_route in {"cleaning_guidance", "dataset_overview"}:
                route = legacy_route
            elif legacy_route == "dataset_source_overview":
                route = "dataset_source_overview"
        return {
            "route": route,
            "deterministic_route": deterministic_route,
            "llm_route": llm_route,
            "strategy": "semantic_router_with_not_applicable_rescue",
        }

    def _try_llm_route_dataset_message(
        self,
        *,
        question: str,
        profile: Any,
        dataset_kind: str,
        source_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Use the configured LLM as a semantic router when available."""

        client = self.llm_client
        if client is None:
            try:
                client = load_llm_client_from_env()
                self.llm_client = client
            except MissingLLMConfigError as exc:
                return {"used": False, "skipped_reason": str(exc)}
        try:
            stage = complete_stage_with_llm(
                llm_client=client,
                stage_name="workbench_semantic_router",
                stage_goal=(
                    "Classify the user message for a dataset-grounded data analysis product. "
                    "Choose chat for ordinary conversation, dataset_source_overview for questions asking what uploaded files, forms, manuals, rules, docs, JSON, or source materials contain or are used for, "
                    "dataset_overview for broad questions asking what the data/tables contain, mean, summarize, or can be used for, "
                    "cleaning_guidance for data-quality/cleaning-policy questions, and analysis only for concrete calculations, rankings, trends, filters, comparisons, charts, joins, or metric answers."
                ),
                question=question,
                guidelines=(
                    "Prefer overview/source_overview over analysis when the user asks a broad browse/explain question. "
                    "Do not send understandable broad content questions to Not Applicable."
                ),
                context_summary={
                    "dataset_kind": dataset_kind,
                    "dataset": _chat_dataset_context_for_llm(profile),
                    "source_counts": _source_counts_for_llm(source_manifest),
                },
                payload={
                    "source_preview": _source_preview_for_llm(source_manifest),
                },
                required_output={
                    "route": "one of chat, dataset_source_overview, dataset_overview, cleaning_guidance, analysis",
                    "confidence": "number between 0 and 1",
                    "reasoning_summary": "short safe explanation, not chain of thought",
                },
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001 - router must never block deterministic path.
            return {"used": False, "skipped_reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
        raw = stage.raw if isinstance(stage.raw, dict) else {}
        route = str(raw.get("route") or raw.get("intent") or "").strip()
        return {
            "used": True,
            "route": route,
            "confidence": stage.confidence,
            "reasoning_summary": _llm_text(stage.reasoning_summary),
        }

    def _rescue_unexpected_not_applicable(
        self,
        payload: dict[str, Any],
        *,
        question: str,
        tables: dict[str, Any],
        profile: Any,
        source_manifest: dict[str, Any],
        agent_mode: str,
    ) -> dict[str, Any]:
        """Replace broad browse-question N/A with a grounded overview response."""

        if not _is_not_applicable_payload(payload):
            return payload
        route = _semantic_dataset_route(question, source_manifest=source_manifest, allow_rescue=True)
        if route not in {"dataset_source_overview", "dataset_overview"}:
            return payload
        try:
            if route == "dataset_source_overview":
                replacement = build_dataset_source_overview_response(
                    run_id=str(payload.get("run_id") or "run_not_applicable_rescue"),
                    dataset_id=str(payload.get("dataset_id") or ""),
                    question=question.strip(),
                    source_manifest=source_manifest,
                    tables=tables,
                    agent_mode=agent_mode,
                )
            else:
                replacement = build_dataset_overview_response(
                    run_id=str(payload.get("run_id") or "run_not_applicable_rescue"),
                    dataset_id=str(payload.get("dataset_id") or ""),
                    question=question.strip(),
                    tables=tables,
                    profile=profile,
                    agent_mode=agent_mode,
                )
            replacement.setdefault("debug", {})
            replacement["debug"]["not_applicable_rescue"] = {
                "applied": True,
                "route": route,
                "reason": "broad_browse_question_must_not_surface_not_applicable",
                "original_operation": (payload.get("debug") or {}).get("operation")
                if isinstance(payload.get("debug"), dict)
                else "",
            }
            return to_json_ready(replacement)
        except Exception:
            return payload

    def _apply_fast_path_llm_presentation(
        self,
        response: dict[str, Any],
        *,
        question: str,
        route: str,
        table_count: int,
    ) -> dict[str, Any]:
        """Let an LLM shape fast deterministic answers without changing calculations."""

        debug = response.setdefault("debug", {})
        meta: dict[str, Any] = {
            "stage": "fast_path_presentation",
            "route": route,
            "used": False,
            "skipped_reason": "",
        }
        client = self.llm_client
        if client is None:
            try:
                client = load_llm_client_from_env()
                self.llm_client = client
            except MissingLLMConfigError as exc:
                meta["skipped_reason"] = str(exc)
                debug["llm_presentation"] = meta
                return response
        started = time.perf_counter()
        try:
            stage = complete_stage_with_llm(
                llm_client=client,
                stage_name="fast_path_presentation",
                stage_goal=(
                    "Act as the user-facing AI presentation layer for a verified deterministic data result. "
                    "Do not recalculate data, do not add new numbers, and do not change the answer. "
                    "Prefer a concise sectioned Chinese display answer using: 数据摘要（关键指标）, 分析洞察（发现了什么）, "
                    "业务建议（可以采取什么行动）, 口径与边界, 下一步可继续分析. "
                    "Produce one insight summary, one high-value next step, and up to two follow-up questions. "
                    "The display answer may rephrase and tailor the verified answer to the user's wording, but it must not change facts."
                ),
                question=question,
                guidelines=(
                    "All user-facing fields must be written in Chinese. Field names, country codes, and metric names may stay as-is, "
                    "but do not write English prose in display_answer, summary, next_step, or next_questions. "
                    "Keep Chinese concise and GPT-like. Be specific to the uploaded tables and verified result. "
                    "If the result shape is insufficient for the user's requested TopN, distinct entity, or grouping口径, say so in 口径与边界 "
                    "and do not turn it into unsupported business advice. Avoid introducing any number that is not present in the payload."
                ),
                context_summary={
                    "route": route,
                    "answer_type": response.get("answer_type"),
                    "operation": (response.get("debug") or {}).get("operation"),
                    "table_count": table_count,
                    "result_columns": (response.get("result") or {}).get("columns") if isinstance(response.get("result"), dict) else [],
                    "existing_insight_summary": (response.get("insight") or {}).get("summary") if isinstance(response.get("insight"), dict) else "",
                },
                payload={
                    "verified_answer_excerpt": _truncate_for_llm(response.get("answer"), 1200),
                    "result_preview": _result_preview_for_llm(response.get("result")),
                    "current_insight": _safe_dict_for_llm(response.get("insight"), limit=1200),
                    "overview_shape": _overview_shape_for_llm(response.get("overview_report")),
                    "quality_summary": _quality_summary_for_llm(response.get("quality_report")),
                },
                required_output={
                    "display_answer": "one concise Chinese answer, preferably with the five requested section headings, grounded only in verified payload evidence; no new numbers",
                    "summary": "one concise user-facing insight sentence grounded in the verified answer",
                    "next_step": "one concrete next analysis step; no generic advice",
                    "next_questions": "array of up to two useful follow-up questions",
                    "confidence": "number between 0 and 1",
                    "reasoning_summary": "short summary, not chain of thought",
                },
                temperature=0.35,
            )
        except Exception as exc:  # noqa: BLE001 - LLM presentation must never break verified answers.
            meta["skipped_reason"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            debug["llm_presentation"] = meta
            return response

        elapsed_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
        raw = stage.raw if isinstance(stage.raw, dict) else {}
        display_answer = _llm_text(raw.get("display_answer"), 1600)
        summary = _llm_text(raw.get("summary") or raw.get("display_summary"))
        next_step = _llm_text(raw.get("next_step") or raw.get("recommendation"))
        next_questions = _llm_text_list(raw.get("next_questions"), limit=2)
        rejected_language_fields: list[str] = []
        if display_answer and not _is_chinese_user_facing_text(display_answer):
            display_answer = ""
            rejected_language_fields.append("display_answer")
        if summary and not _is_chinese_user_facing_text(summary):
            summary = ""
            rejected_language_fields.append("summary")
        if next_step and (not _is_chinese_user_facing_text(next_step) or not _is_actionable_next_step_text(next_step)):
            next_step = ""
            rejected_language_fields.append("next_step")
        filtered_next_questions = [item for item in next_questions if _is_chinese_user_facing_text(item)]
        if len(filtered_next_questions) != len(next_questions):
            next_questions = filtered_next_questions
            rejected_language_fields.append("next_questions")
        answer_updated = False
        answer_update_source = ""
        if _is_safe_llm_display_answer(display_answer, response):
            response["answer"] = display_answer
            answer_updated = True
            answer_update_source = "display_answer"
        elif summary:
            summary_prefaced_answer = _compose_summary_prefaced_answer(response.get("answer"), summary)
            if _is_safe_llm_display_answer(summary_prefaced_answer, response):
                response["answer"] = summary_prefaced_answer
                answer_updated = True
                answer_update_source = "summary_preface"
        if summary or next_step or next_questions:
            insight = response.setdefault("insight", {})
            if isinstance(insight, dict):
                if summary:
                    insight["summary"] = summary
                if next_step:
                    insight["business_suggestions"] = [
                        f"观察：{summary or 'AI 已基于已验证结果复核表达'}；依据：后端已验证结果、表画像和当前问题；建议：{next_step}"
                    ]
                    insight["suggestions"] = list(insight["business_suggestions"])
                if next_questions:
                    insight["next_questions"] = next_questions
                insight["confidence"] = max(float(insight.get("confidence") or 0.0), stage.confidence)
        meta.update(
            {
                "used": True,
                "confidence": stage.confidence,
                "elapsed_ms": elapsed_ms,
                "reasoning_summary": _llm_text(stage.reasoning_summary),
                "updated_answer": answer_updated,
                "answer_update_source": answer_update_source,
                "updated_summary": bool(summary),
                "updated_next_step": bool(next_step),
                "next_question_count": len(next_questions),
                "rejected_language_fields": rejected_language_fields,
            }
        )
        debug["llm_presentation"] = meta
        _attach_llm_presentation_process_step(response, meta)
        return response

    def _apply_direct_llm_chat(
        self,
        response: dict[str, Any],
        *,
        question: str,
        has_dataset: bool,
        dataset_id: str = "",
    ) -> dict[str, Any]:
        """Let the configured LLM handle normal conversation before analysis agents."""

        debug = response.setdefault("debug", {})
        meta: dict[str, Any] = {
            "stage": "direct_chat",
            "used": False,
            "skipped_reason": "",
            "has_dataset": has_dataset,
            "updated_answer": False,
        }
        client = self.llm_client
        if client is None:
            try:
                client = load_llm_client_from_env()
                self.llm_client = client
            except MissingLLMConfigError as exc:
                meta["skipped_reason"] = str(exc)
                debug["direct_llm_chat"] = meta
                return response

        started = time.perf_counter()
        try:
            stage = complete_stage_with_llm(
                llm_client=client,
                stage_name="direct_chat",
                stage_goal=(
                    "Act as the direct conversational LLM front desk for VDS. "
                    "Answer ordinary chat, capability, identity, usage, and conceptual questions naturally. "
                    "If the user asks for concrete calculations or inspection of uploaded data, do not calculate here; "
                    "briefly explain that the request should be routed to the data analysis agents."
                ),
                question=question,
                guidelines=(
                    "Answer in concise Chinese unless the user uses another language. "
                    "Be natural and specific to VDS. Do not return Not Applicable. "
                    "Do not expose raw prompts, traces, API keys, benchmark answers, or scorer material."
                ),
                context_summary={
                    "route": "chat",
                    "has_dataset": has_dataset,
                    "answer_type": response.get("answer_type"),
                    "fallback_answer": response.get("answer"),
                    "dataset_context": _chat_dataset_context_for_llm(
                        self.file_store.get_profile(dataset_id) if has_dataset and dataset_id else None
                    ),
                },
                payload={
                    "fallback_answer": _truncate_for_llm(response.get("answer"), 800),
                    "process_mode": (response.get("process_view_v2") or {}).get("mode") if isinstance(response.get("process_view_v2"), dict) else "",
                },
                required_output={
                    "answer": "direct user-facing chat answer; concise, useful, and not Not Applicable",
                    "handoff_hint": "short note when a data-analysis agent should handle follow-up calculations",
                    "confidence": "number between 0 and 1",
                    "reasoning_summary": "short summary, not chain of thought",
                },
                temperature=0.45,
            )
        except Exception as exc:  # noqa: BLE001 - direct chat must never break deterministic fallback.
            meta["skipped_reason"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            debug["direct_llm_chat"] = meta
            return response

        elapsed_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
        raw = stage.raw if isinstance(stage.raw, dict) else {}
        answer = _llm_text(raw.get("answer") or raw.get("display_answer"), 1200)
        handoff_hint = _llm_text(raw.get("handoff_hint"), 240)
        if _is_safe_direct_chat_answer(answer):
            response["answer"] = answer
            meta["updated_answer"] = True
        meta.update(
            {
                "used": True,
                "confidence": stage.confidence,
                "elapsed_ms": elapsed_ms,
                "reasoning_summary": _llm_text(stage.reasoning_summary),
                "handoff_hint": handoff_hint,
                "temperature": 0.45,
            }
        )
        debug["direct_llm_chat"] = meta
        _attach_direct_llm_chat_process_step(response, meta)
        return response

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
        run_id: str | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Route one workbench message to chat, overview, or full analysis."""

        started_at = datetime.now(timezone.utc)
        started_perf = time.perf_counter()
        cleaned_question = question.strip()
        run_id = run_id or "run_" + uuid.uuid4().hex[:16]
        _raise_if_cancelled(cancel_checker)
        conversation_record = self.conversation_store.get_conversation(conversation_id) if conversation_id else None
        if conversation_record and not dataset_id:
            dataset_id = str(conversation_record.get("dataset_id") or "")
        project_context = {"enabled": False}
        if project_id:
            project = self.project_store.get_project(project_id)
            if project is None:
                return error_response(
                    run_id=run_id,
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
        correction_context = _build_turn_correction_context(
            conversation_record,
            question=cleaned_question,
            dataset_id=dataset_id,
        )
        if correction_context.get("needs_clarification"):
            response = _correction_clarification_response(
                run_id=run_id,
                dataset_id=dataset_id,
                question=cleaned_question,
                correction_context=correction_context,
                started_at=started_at,
                started_perf=started_perf,
            )
            _ensure_activity_trace_v2(response)
            _attach_project_metadata(response, project_context)
            _attach_export_artifacts(response, runs_root=self.file_store.runs_root)
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
        followup_context = (
            {"is_followup": False}
            if correction_context.get("is_correction")
            else _build_turn_followup_context(conversation_record, question=cleaned_question, dataset_id=dataset_id)
        )
        effective_question = str(
            correction_context.get("revised_question")
            or followup_context.get("revised_question")
            or cleaned_question
        )
        if correction_context.get("is_correction"):
            guidelines = _combine_guidelines(guidelines, str(correction_context.get("revised_guidelines") or ""))
        elif followup_context.get("is_followup") and not followup_context.get("self_contained"):
            guidelines = _combine_guidelines(
                guidelines,
                "用户本轮是在延续上一轮已验证分析。若本轮只给出拆分、复核、峰值、低点、波动或来源维度，"
                "应沿用上一轮的主事实表、指标和时间范围；如果请求维度在事实表中不存在，应说明缺口，不要强行跨表猜关联。",
            )
        pending_actions = followup_context.get("pending_actions") if isinstance(followup_context.get("pending_actions"), list) else []
        if len(pending_actions) == 1:
            guidelines = _combine_guidelines(guidelines, _referent_guideline_from_action(pending_actions[0]))
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
                "effective_question": effective_question,
                "execution_mode": execution_mode,
                "agent_mode": agent_mode,
            },
        )
        if not dataset_id:
            response = self.chat_without_dataset(
                question=effective_question,
                agent_mode=agent_mode,
                user_rule_file_id=user_rule_file_id,
                monitor_run_id=monitor_run_id,
                run_id=run_id,
                cancel_checker=cancel_checker,
            )
            _ensure_activity_trace_v2(response)
            _attach_project_metadata(response, project_context)
            _attach_message_timing(response, started_at=started_at, started_perf=started_perf)
            _attach_export_artifacts(response, runs_root=self.file_store.runs_root)
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
        intent = classify_workbench_message(effective_question, has_dataset=True)
        if not correction_context.get("is_correction") and (_is_rule_context_inspection_question(cleaned_question) or intent == "chat"):
            response = self.chat_with_dataset(
                dataset_id=dataset_id,
                question=effective_question,
                agent_mode=agent_mode,
                user_rule_file_id=user_rule_file_id,
                monitor_run_id=monitor_run_id,
                run_id=run_id,
                cancel_checker=cancel_checker,
            )
        elif intent == "cleaning_guidance":
            response = self.analyze_dataset(
                dataset_id=dataset_id,
                question=effective_question,
                execution_mode=execution_mode,
                guidelines=guidelines,
                agent_mode=agent_mode,
                user_rule_file_id=user_rule_file_id,
                monitor_run_id=monitor_run_id,
                project_context=project_context,
                run_id=run_id,
                cancel_checker=cancel_checker,
            )
        elif len(pending_actions) > 1:
            response = self._run_compound_followup_actions(
                run_id=run_id,
                dataset_id=dataset_id,
                original_question=cleaned_question,
                actions=pending_actions,
                execution_mode=execution_mode,
                guidelines=guidelines,
                agent_mode=agent_mode,
                user_rule_file_id=user_rule_file_id,
                monitor_run_id=monitor_run_id,
                project_context=project_context,
                cancel_checker=cancel_checker,
            )
        else:
            response = self.analyze_dataset(
                dataset_id=dataset_id,
                question=effective_question,
                execution_mode=execution_mode,
                guidelines=guidelines,
                agent_mode=agent_mode,
                user_rule_file_id=user_rule_file_id,
                monitor_run_id=monitor_run_id,
                project_context=project_context,
                run_id=run_id,
                cancel_checker=cancel_checker,
            )
        _ensure_activity_trace_v2(response)
        if correction_context.get("is_correction"):
            _attach_correction_context(response, correction_context, original_question=cleaned_question)
        if followup_context.get("is_followup"):
            _attach_followup_context(response, followup_context, original_question=cleaned_question)
        _attach_project_metadata(response, project_context)
        _attach_message_timing(response, started_at=started_at, started_perf=started_perf)
        _attach_export_artifacts(response, runs_root=self.file_store.runs_root)
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

    def _run_compound_followup_actions(
        self,
        *,
        run_id: str,
        dataset_id: str,
        original_question: str,
        actions: list[dict[str, Any]],
        execution_mode: str,
        guidelines: str,
        agent_mode: str,
        user_rule_file_id: str,
        monitor_run_id: str,
        project_context: dict[str, Any],
        cancel_checker: Callable[[], bool] | None,
    ) -> dict[str, Any]:
        """Execute a compound follow-up as ordered structured actions."""

        sub_results: list[dict[str, Any]] = []
        completed_actions: list[dict[str, Any]] = []
        for index, action in enumerate(actions, start=1):
            _raise_if_cancelled(cancel_checker)
            action_question = str(action.get("question") or "").strip()
            if not action_question:
                continue
            sub_run_id = f"{run_id}_a{index}"
            action_guidelines = _combine_guidelines(guidelines, _referent_guideline_from_action(action))
            sub_response = self.analyze_dataset(
                dataset_id=dataset_id,
                question=action_question,
                execution_mode=execution_mode,
                guidelines=action_guidelines,
                agent_mode=agent_mode,
                user_rule_file_id=user_rule_file_id,
                monitor_run_id=monitor_run_id,
                project_context=project_context,
                run_id=sub_run_id,
                cancel_checker=cancel_checker,
            )
            compact = _compact_compound_sub_response(sub_response, action=action, index=index)
            sub_results.append(compact)
            completed = dict(action)
            completed.update(
                {
                    "sequence": index,
                    "run_id": compact.get("run_id") or sub_run_id,
                    "status": "completed" if compact.get("success") else "failed",
                    "result_operation": ((compact.get("logic_form") or {}).get("operation") or ""),
                }
            )
            completed_actions.append(completed)

        success = bool(sub_results) and all(item.get("success") is not False for item in sub_results)
        last_successful = next((item for item in reversed(sub_results) if item.get("success") is not False), sub_results[-1] if sub_results else {})
        last_insight = last_successful.get("insight") if isinstance(last_successful.get("insight"), dict) else {}
        next_actions = list(last_insight.get("next_actions") or [])
        response = {
            "response_version": RESPONSE_VERSION,
            "success": success,
            "run_id": run_id,
            "dataset_id": dataset_id,
            "question": original_question,
            "answer_type": "compound_analysis",
            "execution_mode": execution_mode,
            "answer": _compound_followup_answer(sub_results),
            "logic_form": {
                "task_type": "compound_followup",
                "operation": "compound_followup",
                "parameters": {"action_count": len(completed_actions)},
                "source_tables": _source_tables_from_sub_results(sub_results),
                "output_format": {"answer_type": "compound_analysis"},
            },
            "result": {
                "columns": ["步骤", "动作", "状态", "分析类型", "问题"],
                "rows": [
                    {
                        "步骤": item.get("sequence"),
                        "动作": item.get("action_label") or item.get("action_id") or "",
                        "状态": "完成" if item.get("success") else "失败",
                        "分析类型": ((item.get("logic_form") or {}).get("operation") or ""),
                        "问题": item.get("question") or "",
                    }
                    for item in sub_results
                ],
                "sub_results": sub_results,
            },
            "verification": {"passed": success, "issues": [] if success else ["compound_followup_sub_action_failed"]},
            "insight": {
                "summary": f"已把复合追问拆成 {len(sub_results)} 个可执行动作，并按顺序完成。" if success else "复合追问已拆解，但至少一个动作未完成。",
                "business_suggestions": [],
                "suggestions": [],
                "next_questions": action_questions(next_actions)[:3],
                "next_actions": next_actions,
                "confidence": 0.82 if success else 0.4,
            },
            "chart": last_successful.get("chart") if isinstance(last_successful.get("chart"), dict) else {},
            "quality_report": last_successful.get("quality_report"),
            "reasoning_trace_view": [],
            "process_view_v2": {
                "mode": "compound_followup",
                "summary": f"已执行 {len(sub_results)} 个结构化后续动作。",
                "steps": [
                    {
                        "title": item.get("action_label") or f"动作 {item.get('sequence')}",
                        "source": "structured_followup_action",
                        "status": "completed" if item.get("success") else "failed",
                        "summary": str(item.get("answer") or "")[:180],
                    }
                    for item in sub_results
                ],
            },
            "activity_trace_v2": [],
            "execution_artifacts": [],
            "artifacts_manifest": {},
            "warnings": [],
            "errors": [error for item in sub_results for error in (item.get("errors") or [])],
            "debug": {
                "operation": "compound_followup",
                "compound_followup": {"action_count": len(completed_actions), "actions": completed_actions},
                "agent_mode": agent_mode,
            },
            "agent_actions": completed_actions,
        }
        compound_answer = response["answer"]
        response = _apply_gpt_like_text_framework(response, question=original_question)
        if response.get("answer_type") == "compound_analysis" and "结构化动作" not in str(response.get("answer") or ""):
            response["answer"] = compound_answer
        return to_json_ready(response)

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
            user_rule_file_ids = _split_rule_file_ids(user_rule_file_id)
            if user_rule_file_ids:
                user_contexts = [
                    self.file_store.get_rule_context(
                        file_id,
                        expected_scope=USER_ANALYSIS_RULE_SCOPE,
                    )
                    for file_id in user_rule_file_ids
                ]
                user_guidelines = _combine_guidelines(*[_user_rule_guidelines(context) for context in user_contexts])
                public_contexts = [_public_rule_context(context) for context in user_contexts]
                user_rule_context = {"enabled": True, "files": public_contexts}
                if public_contexts:
                    user_rule_context.update(public_contexts[0])
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

        contexts, context_payload = self._user_rule_contexts(
            user_rule_file_id=user_rule_file_id,
            dataset_id=dataset_id,
        )
        if not contexts:
            return guidelines, context_payload
        return (
            _combine_guidelines(guidelines, *[_user_rule_guidelines(context) for context in contexts]),
            context_payload,
        )

    def _user_rule_contexts(
        self,
        *,
        user_rule_file_id: str = "",
        dataset_id: str = "",
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Load explicit and auto-bound user rule contexts without treating them as datasets."""

        rule_ids: list[str] = _split_rule_file_ids(user_rule_file_id)
        if dataset_id:
            for file_id in self.file_store.get_bound_rule_file_ids(dataset_id, rule_scope=USER_ANALYSIS_RULE_SCOPE):
                if file_id not in rule_ids:
                    rule_ids.append(file_id)
        if not rule_ids:
            return [], {"enabled": False}
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
        return contexts, context_payload

    def _build_user_rule_fee_context(
        self,
        *,
        dataset_id: str,
        tables: dict[str, pd.DataFrame],
        user_rule_file_id: str = "",
    ) -> dict[str, Any] | None:
        """Promote bound fee-rule files plus a payments-like table into executable fee context."""

        contexts, _ = self._user_rule_contexts(user_rule_file_id=user_rule_file_id, dataset_id=dataset_id)
        if not contexts:
            return None
        fees_context = _rule_context_by_name(contexts).get("fees.json")
        if fees_context is None:
            return None
        payments_table = _select_fee_context_table(tables)
        if payments_table is None:
            return None

        payments_export = payments_table.copy()
        if "hour_of_day" not in payments_export.columns:
            payments_export["hour_of_day"] = 0
        if "minute_of_hour" not in payments_export.columns:
            payments_export["minute_of_hour"] = 0
        if "has_fraudulent_dispute" not in payments_export.columns:
            payments_export["has_fraudulent_dispute"] = False
        if "is_refused_by_adyen" not in payments_export.columns:
            payments_export["is_refused_by_adyen"] = False

        context_dir = self.file_store.datasets_root / dataset_id / "user_rule_fee_context"
        context_dir.mkdir(parents=True, exist_ok=True)
        payments_export.to_csv(context_dir / "payments.csv", index=False)
        _write_rule_context_json_file(fees_context, context_dir / "fees.json", fallback=[])
        _write_rule_context_json_file(_rule_context_by_name(contexts).get("merchant_data.json"), context_dir / "merchant_data.json", fallback=[])
        _write_rule_context_text_file(_rule_context_by_name(contexts).get("manual.md"), context_dir / "manual.md", fallback="Uploaded fee-rule context.")
        _write_merchant_category_codes_csv(_rule_context_by_name(contexts).get("merchant_data.json"), context_dir / "merchant_category_codes.csv")
        _write_acquirer_countries_csv(payments_export, context_dir / "acquirer_countries.csv")
        return load_dabstep_context(context_dir)

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
        offset: int = 0,
        owner_id: str = "",
        tenant_id: str = "",
        project_id: str | None = "",
    ) -> dict[str, Any]:
        """Return recent persistent workbench conversations."""

        conversations = self.conversation_store.list_conversations(
            limit=limit,
            offset=offset,
            owner_id=owner_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        total = self.conversation_store.count_conversations(
            owner_id=owner_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "conversations": conversations,
                "total": total,
                "limit": max(1, min(int(limit or 50), 200)),
                "offset": max(0, int(offset or 0)),
                "count": len(conversations),
                "has_more": max(0, int(offset or 0)) + len(conversations) < total,
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
        record = self._repair_stored_not_applicable_messages(record)
        return _conversation_response(record)

    def _repair_stored_not_applicable_messages(self, record: dict[str, Any]) -> dict[str, Any]:
        """Repair previously persisted broad-overview N/A answers on history load."""

        messages = record.get("messages") or []
        dataset_id = str(record.get("dataset_id") or "")
        if not dataset_id or not messages:
            return record
        try:
            tables = self.file_store.get_tables(dataset_id) or {}
            profile = self.file_store.get_profile(dataset_id)
            source_manifest = self.file_store.get_dataset_sources(dataset_id)
        except Exception:  # noqa: BLE001 - history loading must stay available.
            return record
        if not tables and not (source_manifest.get("sources") if isinstance(source_manifest, dict) else None):
            return record

        changed = False
        for index, message in enumerate(messages):
            if str(message.get("role") or "") != "assistant":
                continue
            payload = message.get("payload")
            if not isinstance(payload, dict):
                continue
            needs_repair = _is_not_applicable_payload(payload) or _is_stale_stored_overview_repair(payload)
            if not needs_repair:
                continue
            previous_user = next(
                (
                    candidate
                    for candidate in reversed(messages[:index])
                    if str(candidate.get("role") or "") == "user" and str(candidate.get("content") or "").strip()
                ),
                {},
            )
            question = str(previous_user.get("content") or payload.get("question") or "").strip()
            if not question:
                continue
            route = _semantic_dataset_route(question, source_manifest=source_manifest, allow_rescue=True)
            if route not in {"dataset_source_overview", "dataset_overview"}:
                continue
            try:
                payload_debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
                if route == "dataset_source_overview":
                    replacement = build_dataset_source_overview_response(
                        run_id=str(payload.get("run_id") or message.get("run_id") or "run_stored_not_applicable_repair"),
                        dataset_id=dataset_id,
                        question=question,
                        source_manifest=source_manifest,
                        tables=tables,
                        agent_mode=str(payload_debug.get("agent_mode") or "multi_agent"),
                    )
                else:
                    replacement = build_dataset_overview_response(
                        run_id=str(payload.get("run_id") or message.get("run_id") or "run_stored_not_applicable_repair"),
                        dataset_id=dataset_id,
                        question=question,
                        tables=tables,
                        profile=profile,
                        agent_mode=str(payload_debug.get("agent_mode") or "multi_agent"),
                    )
                replacement.setdefault("debug", {})
                replacement["debug"]["stored_not_applicable_repair"] = {
                    "applied": True,
                    "route": route,
                    "reason": "stored_broad_overview_answer_rebuilt_on_history_load",
                    "original_operation": payload_debug.get("operation") or "",
                }
                _attach_source_references(replacement, profile=profile)
                _ensure_activity_trace_v2(replacement)
            except Exception:  # noqa: BLE001 - keep original history if repair fails.
                continue
            message["payload"] = to_json_ready(replacement)
            message["content"] = str(replacement.get("answer") or "")
            message["answer_type"] = replacement.get("answer_type")
            message["success"] = bool(replacement.get("success"))
            message["run_id"] = replacement.get("run_id")
            changed = True
        if not changed:
            return record
        record["stored_not_applicable_repaired_at"] = datetime.now(timezone.utc).isoformat()
        try:
            return self.conversation_store.save_conversation(record)
        except Exception:  # noqa: BLE001 - repaired response can still be returned without persistence.
            return record

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
        pinned: bool | None = None,
    ) -> dict[str, Any]:
        """Update conversation title, project assignment, or pinned state."""

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
            pinned=pinned,
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

    def list_projects(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        owner_id: str = "",
        tenant_id: str = "",
    ) -> dict[str, Any]:
        """Return recent project workspaces."""

        projects = self.project_store.list_projects(
            limit=limit,
            offset=offset,
            owner_id=owner_id,
            tenant_id=tenant_id,
        )
        total = self.project_store.count_projects(owner_id=owner_id, tenant_id=tenant_id)
        return to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "projects": projects,
                "total": total,
                "limit": max(1, min(int(limit or 50), 200)),
                "offset": max(0, int(offset or 0)),
                "count": len(projects),
                "has_more": max(0, int(offset or 0)) + len(projects) < total,
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
            normalized_file_role, normalized_rule_scope = _resolve_upload_file_role_and_scope(
                file_role=file_role,
                rule_scope=rule_scope,
                file_paths=file_paths,
                original_filenames=original_filenames,
            )
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
        should_auto_bind_rules = bool(bind_dataset_id) and _looks_like_auto_user_rule_file_upload(file_paths, original_filenames)
        if normalized_file_role == DATASET_FILE_ROLE and _is_project_text_source_upload(file_paths, original_filenames) and not should_auto_bind_rules:
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
            rule_scope=normalized_rule_scope,
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
                dataset_id=str(rule.get("bound_dataset_id") or upload.get("dataset_id") or ""),
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
                dataset_id=str(rule.get("bound_dataset_id") or ""),
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
        assistant_message = next(
            (
                message
                for message in reversed(record.get("messages") or [])
                if message.get("role") == "assistant" and message.get("run_id") == response.get("run_id")
            ),
            {},
        )
        response["conversation_id"] = record["conversation_id"]
        response["message_id"] = assistant_message.get("message_id") or ""
        response["current_analysis_context"] = record.get("current_analysis_context") or {}
        response["conversation"] = {
            "conversation_id": record["conversation_id"],
            "title": record.get("title") or "",
            "dataset_id": record.get("dataset_id") or "",
            "project_id": record.get("project_id") or "",
            "pinned": bool(record.get("pinned")),
            "pinned_at": record.get("pinned_at") or "",
            "updated_at": record.get("updated_at"),
            "message_count": len(record.get("messages") or []),
            "current_analysis_context": record.get("current_analysis_context") or {},
        }
        return to_json_ready(response)

    def chat_without_dataset(
        self,
        *,
        question: str,
        agent_mode: str = "multi_agent",
        user_rule_file_id: str = "",
        monitor_run_id: str = "",
        run_id: str | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Return a VDS assistant reply when no dataset has been uploaded yet."""

        run_id = run_id or "run_" + uuid.uuid4().hex[:16]
        _raise_if_cancelled(cancel_checker)
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

        user_rule_contexts, user_rule_context = self._user_rule_contexts(user_rule_file_id=user_rule_file_id)
        response = to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "run_id": run_id,
                "dataset_id": "",
                "question": cleaned_question,
                "answer_type": "chat",
                "execution_mode": "chat",
                "answer": _chat_answer(cleaned_question, has_dataset=False),
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
                "debug": {"agent_mode": "chat_without_dataset", "requires_dataset": False, "user_rule_context": user_rule_context},
            }
        )
        if _is_rule_context_inspection_question(cleaned_question):
            response["answer"] = _user_rule_context_answer(user_rule_contexts)
            response["verification"]["notes"] = ["No dataset was required; answered from uploaded user analysis rule files."]
            response["reasoning_trace_view"] = [
                {
                    "step_id": "intent",
                    "name": "理解问题",
                    "status": "completed",
                    "summary": "用户在查看当前启用的规则文件，不需要上传数据集或进入数据计算链路。",
                },
                {
                    "step_id": "rule_context",
                    "name": "读取规则文件",
                    "status": "completed",
                    "summary": f"已读取 {len(user_rule_contexts)} 个 user_analysis 规则文件，只展示规则内容摘要，不把规则当作数据表分析。",
                },
            ]
            response["debug"]["answered_from_user_rule_context"] = bool(user_rule_contexts)
            _ensure_activity_trace_v2(response)
            emit_monitor_event(
                monitor_run_id,
                "workflow_completed",
                title="规则上下文回复完成",
                summary="已从当前启用的用户规则文件直接回复。",
                stage="chat",
                status="completed",
                payload=process_view_monitor_payload(response),
            )
            return response
        response = self._apply_direct_llm_chat(
            response,
            question=cleaned_question,
            has_dataset=False,
        )
        _raise_if_cancelled(cancel_checker)
        _ensure_activity_trace_v2(response)
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
        user_rule_file_id: str = "",
        monitor_run_id: str = "",
        run_id: str | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Return an ordinary assistant reply while keeping dataset context available."""

        run_id = run_id or "run_" + uuid.uuid4().hex[:16]
        _raise_if_cancelled(cancel_checker)
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

        user_rule_contexts, user_rule_context = self._user_rule_contexts(
            user_rule_file_id=user_rule_file_id,
            dataset_id=dataset_id,
        )
        response = to_json_ready(
            {
                "response_version": RESPONSE_VERSION,
                "success": True,
                "run_id": run_id,
                "dataset_id": dataset_id,
                "question": cleaned_question,
                "answer_type": "chat",
                "execution_mode": "chat",
                "answer": _chat_answer(cleaned_question, has_dataset=True),
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
                "debug": {
                    "agent_mode": "chat_with_dataset",
                    "requires_dataset": False,
                    "message_intent": "chat",
                    "user_rule_context": user_rule_context,
                },
            }
        )
        if _is_rule_context_inspection_question(cleaned_question):
            response["answer"] = _user_rule_context_answer(user_rule_contexts)
            response["verification"]["notes"] = ["No data calculation was required; answered from uploaded user analysis rule files."]
            response["reasoning_trace_view"] = [
                {
                    "step_id": "intent",
                    "name": "理解问题",
                    "status": "completed",
                    "summary": "用户在查看当前数据上下文绑定的规则文件，本次不需要执行数据计算。",
                },
                {
                    "step_id": "rule_context",
                    "name": "读取规则文件",
                    "status": "completed",
                    "summary": f"已读取 {len(user_rule_contexts)} 个 user_analysis 规则文件，并保留当前 dataset 上下文。",
                },
            ]
            response["debug"]["answered_from_user_rule_context"] = bool(user_rule_contexts)
            _ensure_activity_trace_v2(response)
            emit_monitor_event(
                monitor_run_id,
                "workflow_completed",
                title="规则上下文回复完成",
                summary="已从当前启用的用户规则文件直接回复。",
                stage="chat",
                status="completed",
                payload=process_view_monitor_payload(response),
            )
            return response
        response = self._apply_direct_llm_chat(
            response,
            question=cleaned_question,
            has_dataset=True,
            dataset_id=dataset_id,
        )
        _raise_if_cancelled(cancel_checker)
        _ensure_activity_trace_v2(response)
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

        was_in_memory = self.file_store.has_dataset_in_memory(dataset_id)
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
        restored_from_disk = False
        restore_error = ""
        if not was_in_memory:
            restored_ok, restore_error = self.file_store.restore_dataset_from_disk(dataset_id)
            restored_from_disk = restored_ok
        response = dataset_profile_response(profile)
        tables = self.file_store.get_tables(dataset_id) or {}
        dataset_kind = self.file_store.get_dataset_kind(dataset_id)
        source_manifest = self.file_store.get_dataset_sources(dataset_id)
        can_analyze = bool(tables) and not restore_error and dataset_kind != "uploaded_sources"
        response["can_analyze"] = can_analyze
        response["restored_from_disk"] = restored_from_disk
        response["restore_error"] = restore_error or ""
        response["dataset_kind"] = dataset_kind
        response["source_status"] = "available" if can_analyze or dataset_kind == "uploaded_sources" else "needs_reupload"
        response["source_files"] = source_manifest.get("sources") if isinstance(source_manifest, dict) else []
        bound = self.file_store.get_bound_rule_file_ids(dataset_id, rule_scope=USER_ANALYSIS_RULE_SCOPE)
        if bound:
            response["auto_bound_user_rule_file_ids"] = bound
            response["auto_bound_rule_files"] = [
                _public_rule_record(record)
                for file_id in bound
                if (record := self.file_store.get_rule_file(file_id)) is not None
            ]
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


_PROJECT_METRIC_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z_][\u4e00-\u9fffA-Za-z0-9_]*|\d+(?:\.\d+)?")


def _apply_project_derived_metrics_to_tables(
    tables: dict[str, pd.DataFrame],
    *,
    project_context: dict[str, Any],
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    specs = [spec for spec in (project_context.get("derived_metrics") or []) if isinstance(spec, dict)]
    if not specs:
        return tables, []
    copied_tables: dict[str, pd.DataFrame] | None = None
    applied: list[str] = []
    for spec in specs:
        metric_name = str(spec.get("name") or "").strip()
        expression = str(spec.get("expression") or "").strip()
        fields = [str(field) for field in spec.get("fields") or [] if str(field).strip()]
        if not metric_name or not expression or len(fields) < 2:
            continue
        for table_name, table in tables.items():
            if metric_name in table.columns or not all(field in table.columns for field in fields):
                continue
            computed = _evaluate_project_metric_expression(table, expression)
            if computed is None:
                continue
            if copied_tables is None:
                copied_tables = {name: frame.copy() for name, frame in tables.items()}
            copied_tables[table_name][metric_name] = computed
            if metric_name not in applied:
                applied.append(metric_name)
    return copied_tables or tables, applied


def _evaluate_project_metric_expression(table: pd.DataFrame, expression: str) -> pd.Series | None:
    tokens = _PROJECT_METRIC_TOKEN_PATTERN.findall(expression)
    if len(tokens) < 2:
        return None
    operators = re.findall(r"[+\-*/]", expression)
    if len(operators) != len(tokens) - 1:
        return None
    current = _project_metric_operand(table, tokens[0])
    if current is None:
        return None
    for operator, token in zip(operators, tokens[1:]):
        operand = _project_metric_operand(table, token)
        if operand is None:
            return None
        if operator == "+":
            current = current + operand
        elif operator == "-":
            current = current - operand
        elif operator == "*":
            current = current * operand
        elif operator == "/":
            divisor = operand.where(operand != 0)
            current = (current / divisor).replace([float("inf"), float("-inf")], pd.NA)
        else:
            return None
    return current


def _project_metric_operand(table: pd.DataFrame, token: str) -> pd.Series | None:
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return pd.Series(float(token), index=table.index, dtype="float64")
    if token not in table.columns:
        return None
    return pd.to_numeric(table[token], errors="coerce")


def _normalize_file_role(file_role: str) -> str:
    role = (file_role or DATASET_FILE_ROLE).strip().lower()
    if role not in VALID_FILE_ROLES:
        raise ValueError("file_role must be dataset or rule.")
    return role


def _resolve_upload_file_role_and_scope(
    *,
    file_role: str,
    rule_scope: str,
    file_paths: list[str | Path],
    original_filenames: list[str | None] | None,
) -> tuple[str, str]:
    """Resolve legacy upload payloads with missing/legacy metadata into one supported shape."""

    resolved_scope = (rule_scope or "").strip()
    provided_role = (file_role or "").strip().lower()
    explicit_rule_role = provided_role == RULE_FILE_ROLE
    if not provided_role:
        return DATASET_FILE_ROLE, resolved_scope
    try:
        resolved_role = _normalize_file_role(provided_role)
    except ValueError:
        if provided_role in {"none", "null", "undefined"}:
            if _looks_like_user_rule_file_upload(file_paths, original_filenames):
                resolved_role = RULE_FILE_ROLE
                if not resolved_scope:
                    resolved_scope = USER_ANALYSIS_RULE_SCOPE
            else:
                resolved_role = DATASET_FILE_ROLE
        else:
            raise
    if resolved_role == RULE_FILE_ROLE and not resolved_scope:
        if explicit_rule_role:
            raise ValueError("Rule files require rule_scope=user_analysis or rule_scope=benchmark.")
        if _looks_like_user_rule_file_upload(file_paths, original_filenames):
            resolved_scope = USER_ANALYSIS_RULE_SCOPE
    return resolved_role, resolved_scope


def _looks_like_user_rule_file_upload(
    file_paths: list[str | Path],
    original_filenames: list[str | None] | None,
) -> bool:
    """Return true when uploaded files are explicitly rule-like metadata files."""

    if not file_paths:
        return False
    for index, file_path in enumerate(file_paths):
        original_name = None if original_filenames is None else original_filenames[index]
        if not _looks_like_auto_user_rule_file(file_path, original_name):
            return False
        lowered_name = Path(str(original_name or Path(file_path).name)).name.lower()
        if not any(
            token in lowered_name
            for token in (
                "rule",
                "rules",
                "manual",
                "guide",
                "guideline",
                "schema",
                "metadata",
                "definition",
                "meaning",
                "fee",
                "口径",
                "规则",
                "计算",
            )
        ):
            return False
    return True


def _looks_like_auto_user_rule_file_upload(
    file_paths: list[str | Path],
    original_filenames: list[str | None] | None,
) -> bool:
    """Return true when every uploaded file should be bound as a user analysis rule."""

    if not file_paths:
        return False
    for index, file_path in enumerate(file_paths):
        original_name = None if original_filenames is None else original_filenames[index]
        if not _looks_like_auto_user_rule_file(file_path, original_name):
            return False
    return True


def _split_rule_file_ids(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


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
    if suffix in (RULE_FILE_EXTENSIONS - {".json"}):
        return True
    if suffix == ".json":
        if lowered in {"fees.json", "merchant_data.json"}:
            return True
        return any(
            token in lowered
            for token in (
                "rule",
                "rules",
                "merchant_data",
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


def _is_source_only_upload(file_paths: list[str | Path], original_filenames: list[str | None] | None) -> bool:
    """Return true when every uploaded file is a standalone readable source file."""

    if not file_paths:
        return False
    if original_filenames is not None and len(original_filenames) != len(file_paths):
        return False
    for index, file_path in enumerate(file_paths):
        original_name = None if original_filenames is None else original_filenames[index]
        suffix = Path(str(original_name or Path(file_path).name)).suffix.lower() or Path(file_path).suffix.lower()
        if suffix not in RULE_FILE_EXTENSIONS or suffix in DATASET_FILE_EXTENSIONS:
            return False
    return True


def _is_project_text_source_upload(file_paths: list[str | Path], original_filenames: list[str | None] | None) -> bool:
    """Return true for project shared text files that should not enter DataFrame parsing."""

    if not file_paths:
        return False
    if original_filenames is not None and len(original_filenames) != len(file_paths):
        return False
    text_source_suffixes = RULE_FILE_EXTENSIONS - {".json"}
    for index, file_path in enumerate(file_paths):
        original_name = None if original_filenames is None else original_filenames[index]
        suffix = Path(str(original_name or Path(file_path).name)).suffix.lower() or Path(file_path).suffix.lower()
        if suffix not in text_source_suffixes:
            return False
    return True


def _attach_uploaded_file_records(
    response: dict[str, Any],
    file_paths: list[str | Path],
    original_filenames: list[str | None] | None,
) -> None:
    records = _uploaded_file_records(file_paths, original_filenames)
    if not records:
        return
    response["uploaded_files"] = records
    response["uploaded_file_count"] = len(records)


def _uploaded_file_records(
    file_paths: list[str | Path],
    original_filenames: list[str | None] | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, file_path in enumerate(file_paths):
        original_name = None if original_filenames is None or index >= len(original_filenames) else original_filenames[index]
        path = Path(file_path)
        display_name = Path(str(original_name or path.name)).name
        if not display_name or display_name in seen:
            continue
        seen.add(display_name)
        suffix = Path(display_name).suffix.lower() or path.suffix.lower()
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        source_type = "table" if suffix in DATASET_FILE_EXTENSIONS else "source"
        records.append(
            {
                "file_name": display_name,
                "size_bytes": size_bytes,
                "file_ext": suffix,
                "file_role": DATASET_FILE_ROLE,
                "source_type": source_type,
                "status": "ready",
            }
        )
    return records


def _read_project_text_source(file_path: str | Path) -> str:
    path = Path(file_path)
    text = _read_source_text(path, suffix=path.suffix.lower())
    if text.strip():
        return text
    raise ValueError("Project source file content could not be extracted as text.")


def _rule_file_response(record: StoredRuleFile) -> dict[str, Any]:
    return to_json_ready(
        {
            "response_version": RESPONSE_VERSION,
            "success": True,
            "file_id": record.file_id,
            "file_name": record.file_name,
            "file_role": record.file_role,
            "rule_scope": record.rule_scope,
            "bound_dataset_id": record.dataset_id,
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
        "bound_dataset_id": record.dataset_id,
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


def _is_rule_context_inspection_question(question: str) -> bool:
    compact = str(question or "").lower().replace(" ", "")
    if "rule" in compact and any(token in compact for token in ("show", "list", "what", "content", "enabled", "uploaded")):
        return True
    if "规则" not in compact:
        return False
    return any(
        token in compact
        for token in (
            "规则是什么",
            "看规则",
            "查看规则",
            "规则内容",
            "规则文件",
            "已启用规则",
            "启用的规则",
            "上传的规则",
            "有哪些规则",
            "规则列表",
            "我要看",
        )
    )


def _user_rule_context_answer(rule_contexts: list[dict[str, Any]]) -> str:
    if not rule_contexts:
        return "当前没有启用用户分析规则文件。"
    lines = [f"当前启用了 {len(rule_contexts)} 个用户分析规则文件："]
    for index, context in enumerate(rule_contexts, start=1):
        file_name = str(context.get("file_name") or context.get("file_id") or f"规则文件 {index}")
        scope = str(context.get("rule_scope") or USER_ANALYSIS_RULE_SCOPE)
        excerpt = _rule_context_excerpt(context)
        lines.append(f"{index}. {file_name}（scope: {scope}）")
        if excerpt:
            lines.append(f"   内容摘要：{excerpt}")
        warnings = [str(item) for item in context.get("warnings") or [] if str(item).strip()]
        if warnings:
            lines.append("   解析提示：" + "；".join(warnings[:2]))
    lines.append("这些规则只作为本轮分析/回答的约束和口径上下文，不会被当成数据表参与字段画像或计算。")
    return "\n".join(lines)


def _rule_context_excerpt(rule_context: dict[str, Any]) -> str:
    parsed = rule_context.get("parsed_rule")
    raw_text = str(rule_context.get("raw_text") or "").strip()
    if isinstance(parsed, dict) and str(parsed.get("raw_text") or "").strip():
        text = str(parsed.get("raw_text") or "")
    elif raw_text:
        text = raw_text
    elif parsed:
        text = json_dumps_compact(parsed)
    else:
        text = ""
    text = " ".join(line.strip() for line in str(text).splitlines() if line.strip())
    return _truncate_for_llm(text, 500)


def _user_rule_guidelines(rule_context: dict[str, Any]) -> str:
    parsed = rule_context.get("parsed_rule")
    raw_text = str(rule_context.get("raw_text") or "").strip()
    prefix = (
        "User analysis rules from uploaded rule file. These rules constrain this analysis only; "
        "do not treat the rule file as a dataset. Treat explicit output-format rules as hard constraints "
        "for the final user-facing answer.\n"
    )
    if isinstance(parsed, dict) and "raw_text" not in parsed:
        return prefix + json_dumps_compact(parsed)
    return prefix + raw_text


def _apply_user_rule_output_constraints(
    payload: dict[str, Any],
    rule_contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    constraints = _collect_user_rule_output_constraints(rule_contexts)
    if not constraints["suppress_numbers"] and not constraints["entity_only"]:
        return payload
    original_answer = str(payload.get("answer") or "").strip()
    if not original_answer:
        return payload
    entity_answer = _entity_only_answer_from_payload(payload, preferred_label=str(constraints.get("entity_only_label") or ""))
    updated_answer = original_answer
    if constraints["entity_only"] and entity_answer:
        updated_answer = entity_answer
    elif constraints["suppress_numbers"] and _answer_contains_numeric_content(original_answer):
        if entity_answer:
            updated_answer = entity_answer
        else:
            sanitized = _remove_numeric_fragments(original_answer)
            if sanitized:
                updated_answer = sanitized
    if not updated_answer or updated_answer == original_answer:
        return payload
    payload["answer"] = updated_answer
    payload.setdefault("debug", {})["user_rule_output_constraints_applied"] = to_json_ready(constraints)
    verification = payload.get("verification")
    if isinstance(verification, dict):
        notes = verification.setdefault("notes", [])
        if isinstance(notes, list):
            note = "Applied uploaded user rule output constraints to the final answer."
            if note not in notes:
                notes.append(note)
    return payload


def _collect_user_rule_output_constraints(rule_contexts: list[dict[str, Any]]) -> dict[str, Any]:
    constraints: dict[str, Any] = {
        "suppress_numbers": False,
        "entity_only": False,
        "entity_only_label": "",
    }
    for context in rule_contexts:
        text = _rule_text_content(context)
        if not text:
            continue
        if _rule_requests_no_numeric_output(text):
            constraints["suppress_numbers"] = True
        entity_only_label = _rule_requests_entity_only_output(text)
        if entity_only_label and not constraints["entity_only"]:
            constraints["entity_only"] = True
            constraints["entity_only_label"] = entity_only_label
    return constraints


def _rule_text_content(rule_context: dict[str, Any]) -> str:
    parsed = rule_context.get("parsed_rule")
    raw_text = str(rule_context.get("raw_text") or "").strip()
    if isinstance(parsed, dict) and str(parsed.get("raw_text") or "").strip():
        return str(parsed.get("raw_text") or "")
    if raw_text:
        return raw_text
    if parsed:
        return json_dumps_compact(parsed)
    return ""


def _rule_requests_no_numeric_output(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "")).lower()
    return any(
        token in compact
        for token in (
            "不要返回数值",
            "不要返回数字",
            "不返回数值",
            "不返回数字",
            "不要带数值",
            "不要带数字",
            "不带数值",
            "不带数字",
            "不要返回任何数字",
            "donotreturnnumbers",
            "withoutnumbers",
            "nonumbers",
            "donotincludenumbers",
        )
    )


def _rule_requests_entity_only_output(text: str) -> str:
    chinese_match = re.search(r"(?:只|仅)(?:回答|返回|给出|保留)([^，。；,\n]{1,12})", str(text or ""))
    if chinese_match:
        candidate = chinese_match.group(1).strip()
        if candidate and candidate not in {"答案", "结果", "内容", "文本", "文字", "结论"}:
            return candidate
    english_match = re.search(r"(?:only|just)\s+(?:answer|return|give)\s+(?:the\s+)?([a-z][a-z _-]{0,20})", str(text or ""), re.IGNORECASE)
    if english_match:
        candidate = english_match.group(1).strip()
        if candidate and candidate.lower() not in {"answer", "result", "text", "content"}:
            return candidate
    return ""


def _entity_only_answer_from_payload(payload: dict[str, Any], *, preferred_label: str = "") -> str:
    result = payload.get("result")
    rows = result.get("rows") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not rows:
        value = result.get("value") if isinstance(result, dict) else None
        if isinstance(value, str) and value.strip() and not _answer_contains_numeric_content(value):
            return value.strip()
        return ""
    dict_rows = [row for row in rows if isinstance(row, dict)]
    if not dict_rows:
        return ""
    column = _pick_preferred_text_column(dict_rows, preferred_label=preferred_label)
    if not column:
        return ""
    values: list[str] = []
    for row in dict_rows:
        value = row.get(column)
        if value is None or _is_numeric_like_value(value):
            continue
        text = str(value).strip()
        if text and text not in values:
            values.append(text)
    if not values:
        return ""
    return values[0] if len(values) == 1 else ", ".join(values[:5])


def _pick_preferred_text_column(rows: list[dict[str, Any]], *, preferred_label: str = "") -> str:
    first_row = rows[0]
    candidate_columns = [column for column in first_row if any(not _is_numeric_like_value(row.get(column)) for row in rows)]
    if not candidate_columns:
        return ""
    if preferred_label:
        label_tokens = _output_label_tokens(preferred_label)
        for column in candidate_columns:
            normalized = _normalized_output_token(column)
            if any(token == normalized or token in normalized or normalized in token for token in label_tokens):
                return str(column)
    for column in candidate_columns:
        normalized = _normalized_output_token(column)
        if normalized and not any(token in normalized for token in ("id", "code", "date", "time", "编号", "编码", "日期", "时间")):
            return str(column)
    return str(candidate_columns[0])


def _output_label_tokens(label: str) -> set[str]:
    normalized = _normalized_output_token(label)
    if not normalized:
        return set()
    aliases = {
        "城市": {"city", "cities", "城市"},
        "地区": {"region", "area", "province", "state", "地区"},
        "国家": {"country", "nation", "国家"},
        "产品": {"product", "sku", "item", "产品"},
        "客户": {"customer", "client", "account", "客户"},
        "门店": {"store", "shop", "branch", "门店"},
        "品类": {"category", "segment", "class", "品类"},
        "品牌": {"brand", "品牌"},
        "商户": {"merchant", "商户"},
    }
    tokens = {normalized}
    for canonical, variants in aliases.items():
        canonical_token = _normalized_output_token(canonical)
        variant_tokens = {_normalized_output_token(value) for value in variants}
        if normalized == canonical_token or normalized in variant_tokens:
            tokens.update(token for token in variant_tokens | {canonical_token} if token)
    return tokens


def _normalized_output_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _is_numeric_like_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value or "").strip().replace(",", "")
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?%?", text))


def _answer_contains_numeric_content(text: str) -> bool:
    return bool(re.search(r"\d", str(text or "")))


def _remove_numeric_fragments(text: str) -> str:
    stripped = re.sub(r"[-+]?\d[\d,]*(?:\.\d+)?%?", "", str(text or ""))
    stripped = re.sub(r"\(\s*\)", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    stripped = re.sub(r"\s+([,.;:，；：。])", r"\1", stripped)
    return stripped.strip(" ,.;:，；：。")


def _rule_context_by_name(contexts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for context in contexts:
        name = Path(str(context.get("file_name") or "")).name.lower()
        if name and name not in mapping:
            mapping[name] = context
    return mapping


def _select_fee_context_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    preferred = tables.get("payments")
    if _looks_like_fee_context_table(preferred):
        return preferred.copy()
    for table in tables.values():
        if _looks_like_fee_context_table(table):
            return table.copy()
    return None


def _looks_like_fee_context_table(table: Any) -> bool:
    if not isinstance(table, pd.DataFrame) or table.empty:
        return False
    required = {
        "merchant",
        "year",
        "day_of_year",
        "eur_amount",
        "is_credit",
        "aci",
        "card_scheme",
        "issuing_country",
        "acquirer_country",
    }
    columns = {str(column) for column in table.columns}
    return required.issubset(columns)


def _write_rule_context_json_file(rule_context: dict[str, Any] | None, path: Path, *, fallback: Any) -> None:
    parsed = None if rule_context is None else rule_context.get("parsed_rule")
    payload = fallback if parsed is None else to_json_ready(parsed)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_rule_context_text_file(rule_context: dict[str, Any] | None, path: Path, *, fallback: str) -> None:
    text = str((rule_context or {}).get("raw_text") or fallback).strip() or fallback
    path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")


def _write_merchant_category_codes_csv(rule_context: dict[str, Any] | None, path: Path) -> None:
    rows = (rule_context or {}).get("parsed_rule")
    values: list[int] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("merchant_category_code"), int):
                values.append(int(row["merchant_category_code"]))
    lines = ["mcc,description"]
    lines.extend(f"{value},{value}" for value in sorted(set(values)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_acquirer_countries_csv(payments: pd.DataFrame, path: Path) -> None:
    values = sorted(
        {
            str(value)
            for value in payments.get("acquirer_country", pd.Series(dtype=str)).dropna().astype(str).tolist()
            if str(value)
        }
    )
    lines = ["country_code,country"]
    lines.extend(f"{value},{value}" for value in values)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


FEE_ID_RULE_OPERATIONS = {"fee_ids_for_filters", "applicable_fee_ids"}


def _looks_like_fee_id_question(question: str) -> bool:
    lowered = str(question or "").lower()
    if "fee id" not in lowered:
        return False
    return (
        ("account_type" in lowered and "aci" in lowered)
        or "applicable fee ids" in lowered
        or "fee ids applicable" in lowered
    )


def _materialize_rule_backed_fee_context(
    storage_root: str | Path,
    *,
    dataset_id: str,
    tables: dict[str, pd.DataFrame],
    user_rule_contexts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    payments = _select_fee_context_table(tables)
    if payments is None:
        return None
    contexts_by_name = _rule_context_by_name(user_rule_contexts)
    fees_context = contexts_by_name.get("fees.json")
    if fees_context is None:
        return None

    if "hour_of_day" not in payments.columns:
        payments["hour_of_day"] = 0
    if "minute_of_hour" not in payments.columns:
        payments["minute_of_hour"] = 0
    if "has_fraudulent_dispute" not in payments.columns:
        payments["has_fraudulent_dispute"] = False
    if "is_refused_by_adyen" not in payments.columns:
        payments["is_refused_by_adyen"] = False

    context_dir = Path(storage_root) / "datasets" / dataset_id / "rule_backed_fee_context"
    context_dir.mkdir(parents=True, exist_ok=True)
    payments.to_csv(context_dir / "payments.csv", index=False)
    _write_rule_context_json_file(fees_context, context_dir / "fees.json", fallback=[])
    _write_rule_context_json_file(contexts_by_name.get("merchant_data.json"), context_dir / "merchant_data.json", fallback=[])
    _write_rule_context_text_file(contexts_by_name.get("manual.md"), context_dir / "manual.md", fallback="Uploaded fee-rule context.")
    _write_merchant_category_codes_csv(contexts_by_name.get("merchant_data.json"), context_dir / "merchant_category_codes.csv")
    _write_acquirer_countries_csv(payments, context_dir / "acquirer_countries.csv")
    knowledge_files = [
        name
        for name in ("fees.json", "merchant_data.json", "manual.md")
        if contexts_by_name.get(name) is not None
    ]
    return {
        "context": load_dabstep_context(context_dir),
        "context_dir": context_dir,
        "payments_table": "payments",
        "knowledge_files": knowledge_files,
    }


def _fee_id_answer_count(value: Any) -> int:
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if value in (None, "", []):
        return 0
    return 1


def _shape_fee_id_result_table(payload: dict[str, Any], value: Any) -> None:
    items = list(value) if isinstance(value, (list, tuple, set)) else ([] if value in (None, "") else [value])
    payload["answer_type"] = "list"
    payload["result"] = {
        "columns": ["fee_id"],
        "rows": [{"fee_id": item} for item in items],
        "value": items,
    }


def _append_rule_source_references(payload: dict[str, Any], contexts: list[dict[str, Any]], knowledge_files: list[str]) -> None:
    source_references = payload.setdefault("source_references", [])
    existing_names = {str(item.get("file_name") or "") for item in source_references if isinstance(item, dict)}
    contexts_by_name = _rule_context_by_name(contexts)
    for name in knowledge_files:
        if name in existing_names:
            continue
        context = contexts_by_name.get(name)
        if context is None:
            continue
        source_references.append(
            {
                "file_name": name,
                "source_type": "rule",
                "source_role": "规则/知识来源",
                "read_status": "read",
                "purpose": "费用规则或商户规则上下文",
                "content_summary": _rule_context_excerpt(context),
            }
        )


def _fee_id_insight(*, operation: str, value: Any, filters: dict[str, Any]) -> dict[str, Any]:
    count = _fee_id_answer_count(value)
    if operation == "fee_ids_for_filters":
        account_type = filters.get("account_type")
        aci = filters.get("aci")
        scope = "、".join(f"{key}={value}" for key, value in (("account_type", account_type), ("aci", aci)) if value)
        summary = (
            f"当前筛选条件{('（' + scope + '）') if scope else ''}下没有匹配的 Fee ID。"
            if count == 0
            else f"当前筛选条件{('（' + scope + '）') if scope else ''}下匹配到 {count} 个 Fee ID。"
        )
        next_step = "查看这些 Fee ID 的具体规则条件，重点核对空列表通配、account_type、aci、card_scheme 和地区条件。"
        questions = ["这些 Fee ID 的规则条件分别是什么？", "如果再限定 card_scheme，Fee ID 会剩哪些？"]
    else:
        merchant = str(filters.get("merchant") or "目标商户")
        summary = f"{merchant} 在当前时间范围内没有匹配的 Fee ID。" if count == 0 else f"{merchant} 在当前时间范围内匹配到 {count} 个 Fee ID。"
        next_step = "展开这些 Fee ID 对应的规则条件，核对交易月份、商户属性、ACI、卡组织和月度门槛为什么命中。"
        questions = ["这些 Fee ID 分别对应哪些规则条件？", "这些 Fee ID 按 card_scheme 如何分布？"]
    return {
        "summary": summary,
        "next_step": next_step,
        "business_suggestions": [f"观察：{summary}；依据：后端已使用启用规则文件执行费用规则引擎；建议：{next_step}"],
        "suggestions": [next_step],
        "next_questions": questions,
        "caveats": [],
        "confidence": 0.9,
    }


def _fee_id_reasoning_trace(*, operation: str, execution_success: bool, verification_passed: bool, rule_files: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "step_id": "rule_context",
            "name": "读取规则上下文",
            "status": "completed",
            "summary": f"已读取规则文件：{', '.join(rule_files) if rule_files else '无'}。",
        },
        {
            "step_id": "fee_rule_execution",
            "name": "执行 Fee ID 查询",
            "status": "completed" if execution_success else "failed",
            "summary": f"操作={operation}，执行{'成功' if execution_success else '失败'}，校验{'通过' if verification_passed else '未通过'}。",
        },
    ]


def _fee_id_process_view(*, operation: str, execution_success: bool, verification_passed: bool, answer_count: int) -> dict[str, Any]:
    return {
        "mode": "rule_backed_fee_query",
        "summary": f"已使用费用规则路径执行 {operation}，返回 {answer_count} 个 Fee ID。",
        "steps": [
            {
                "title": "读取规则文件",
                "source": "rule_context",
                "status": "completed",
                "summary": "已把启用的费用规则文件与 payments 表组合成可执行上下文。",
            },
            {
                "title": "执行 Fee ID 查询",
                "source": "pandas_executor",
                "status": "completed" if execution_success else "failed",
                "summary": f"operation={operation}，命中 {answer_count} 个结果。",
            },
            {
                "title": "结果校验",
                "source": "verifier",
                "status": "completed" if verification_passed else "failed",
                "summary": "已检查执行成功状态和输出契约。",
            },
        ],
    }


def _build_turn_correction_context(record: dict[str, Any] | None, *, question: str, dataset_id: str) -> dict[str, Any]:
    if not record or not _looks_like_correction_request(question):
        return {"is_correction": False}
    previous = _latest_analysis_turn(record, dataset_id=dataset_id)
    if not previous:
        return {
            "is_correction": True,
            "needs_clarification": True,
            "reason": "no_previous_analysis_turn",
            "changed_scope": [],
        }
    formula_text = _extract_explicit_formula_text(question)
    if not formula_text:
        return {
            "is_correction": True,
            "needs_clarification": True,
            "reason": "missing_revised_formula",
            "previous_run_id": previous["payload"].get("run_id") or "",
            "changed_scope": [],
            "previous_formula": _formula_lineage_from_payload(previous["payload"]),
        }
    previous_question = str(previous.get("question") or previous["payload"].get("question") or "")
    revised_question = f"{previous_question}\n用户本轮修正口径：{question}\n请按修正口径重新计算，并解释和上一轮口径的差异。"
    return {
        "is_correction": True,
        "needs_clarification": False,
        "previous_run_id": previous["payload"].get("run_id") or "",
        "previous_question": previous_question,
        "previous_formula": _formula_lineage_from_payload(previous["payload"]),
        "previous_result_summary": _result_summary_for_correction(previous["payload"]),
        "revised_formula": formula_text,
        "changed_scope": ["metric_formula"],
        "revised_question": revised_question,
        "revised_guidelines": (
            "用户正在修正上一轮分析口径。必须重新计算，不得复用上一轮结果。"
            f" 本轮显式口径：{formula_text}。"
        ),
    }


def _looks_like_correction_request(question: str) -> bool:
    if _extract_explicit_formula_text(question):
        return True
    lowered = question.lower()
    if "口径" in question and any(token in lowered for token in ("不是", "不对", "改", "重新", "重算", "rerun", "recalculate")):
        return True
    if not _has_formula_like_expression(question):
        return False
    return any(
        token in lowered
        for token in (
            "不是这个口径",
            "口径不对",
            "改成",
            "用",
            "重新算",
            "重算",
            "重跑",
            "recalculate",
            "rerun",
            "use ",
            "instead",
        )
    )


def _has_formula_like_expression(question: str) -> bool:
    text = str(question or "")
    lowered = text.lower()
    if "sum" in lowered or "=" in text:
        return True
    if any(token in text for token in ("分子", "分母", "公式")):
        return True
    return bool(re.search(r"[\w\u4e00-\u9fff]{2,}\s*/\s*[\w\u4e00-\u9fff]{2,}", text))


def _build_turn_followup_context(record: dict[str, Any] | None, *, question: str, dataset_id: str) -> dict[str, Any]:
    if not record or not _looks_like_followup_analysis_request(question):
        return {"is_followup": False}
    self_contained = _looks_like_self_contained_analysis_request(question)
    previous = _latest_analysis_turn(record, dataset_id=dataset_id)
    if not previous:
        return {"is_followup": False}
    payload = previous["payload"]
    if not isinstance(payload, dict) or payload.get("success") is False:
        previous = _latest_successful_analysis_turn(record, dataset_id=dataset_id)
        if not previous:
            return {"is_followup": False}
        payload = previous["payload"]
        if not isinstance(payload, dict):
            return {"is_followup": False}
    analysis_context = _current_analysis_context_from_record(record, dataset_id=dataset_id) or build_analysis_context(
        payload,
        original_question=str(previous.get("question") or ""),
    )
    if _analysis_context_is_quality_only(analysis_context) and not _looks_like_quality_followup_request(question):
        prior = _latest_successful_analysis_turn(
            record,
            dataset_id=dataset_id,
            skip_operations={"quality_summary", "data_quality_report", "cleaning_policy", "anomaly_rules", "outlier_count", "null_check"},
        )
        if prior and isinstance(prior.get("payload"), dict):
            previous = prior
            payload = prior["payload"]
            analysis_context = build_analysis_context(payload, original_question=str(prior.get("question") or ""))
    if self_contained and _references_analysis_focus_set(question, analysis_context):
        self_contained = False
    contextual_extreme_rewrite = _rewrite_contextual_extreme_time_reference(
        record,
        question=question,
        dataset_id=dataset_id,
    )
    if contextual_extreme_rewrite:
        return {
            "is_followup": True,
            "reason": "contextual_extreme_reference",
            "previous_run_id": analysis_context.get("run_id") or payload.get("run_id") or "",
            "previous_question": analysis_context.get("question") or previous.get("question") or payload.get("question") or "",
            "revised_question": contextual_extreme_rewrite,
            "carried_operation": analysis_context.get("operation") or "",
            "pending_actions": [],
        }
    contextual_dimension_rewrite = _rewrite_contextual_extreme_dimension_reference(
        record,
        question=question,
        dataset_id=dataset_id,
    )
    if contextual_dimension_rewrite:
        return {
            "is_followup": True,
            "reason": "contextual_extreme_reference",
            "previous_run_id": analysis_context.get("run_id") or payload.get("run_id") or "",
            "previous_question": analysis_context.get("question") or previous.get("question") or payload.get("question") or "",
            "revised_question": contextual_dimension_rewrite,
            "carried_operation": analysis_context.get("operation") or "",
            "pending_actions": [],
        }
    if self_contained:
        return {
            "is_followup": True,
            "reason": "self_contained_followup",
            "previous_run_id": analysis_context.get("run_id") or payload.get("run_id") or "",
            "previous_question": analysis_context.get("question") or previous.get("question") or payload.get("question") or "",
            "revised_question": question,
            "carried_operation": "",
            "pending_actions": [],
            "self_contained": True,
        }
    planned_actions = plan_followup_actions(question, analysis_context)
    if planned_actions:
        rewritten_questions = action_questions(planned_actions)
        return {
            "is_followup": True,
            "reason": "compound_followup_actions" if len(planned_actions) > 1 else "structured_followup_action",
            "previous_run_id": analysis_context.get("run_id") or payload.get("run_id") or "",
            "previous_question": analysis_context.get("question") or previous.get("question") or payload.get("question") or "",
            "revised_question": rewritten_questions[0] if rewritten_questions else question,
            "carried_operation": analysis_context.get("operation") or "",
            "pending_actions": planned_actions,
        }
    logic = payload.get("logic_form") if isinstance(payload.get("logic_form"), dict) else {}
    rewritten = _rewrite_followup_question(question, previous_question=str(previous.get("question") or ""), logic=logic)
    if not rewritten or rewritten == question:
        return {
            "is_followup": True,
            "reason": "contextual_followup",
            "previous_run_id": analysis_context.get("run_id") or payload.get("run_id") or "",
            "previous_question": analysis_context.get("question") or previous.get("question") or payload.get("question") or "",
            "revised_question": question,
            "carried_operation": analysis_context.get("operation") or logic.get("operation") or logic.get("task_type") or "",
            "pending_actions": [],
        }
    return {
        "is_followup": True,
        "reason": "short_drilldown_followup",
        "previous_run_id": payload.get("run_id") or "",
        "previous_question": previous.get("question") or payload.get("question") or "",
        "revised_question": rewritten,
        "carried_operation": logic.get("operation") or logic.get("task_type") or "",
    }


def _current_analysis_context_from_record(record: dict[str, Any], *, dataset_id: str) -> dict[str, Any]:
    context = record.get("current_analysis_context") if isinstance(record.get("current_analysis_context"), dict) else {}
    if context and (not dataset_id or str(context.get("dataset_id") or "") in {"", dataset_id}):
        return dict(context)
    previous = _latest_analysis_turn(record, dataset_id=dataset_id)
    if not previous:
        return {}
    return build_analysis_context(previous.get("payload"), original_question=str(previous.get("question") or ""))


def _analysis_context_is_quality_only(context: dict[str, Any]) -> bool:
    operation = str(context.get("operation") or "")
    return operation in {"quality_summary", "data_quality_report", "cleaning_policy", "anomaly_rules", "outlier_count", "null_check"}


def _looks_like_quality_followup_request(question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    return any(token in compact for token in ("数据质量", "质量", "缺失", "重复", "异常", "清洗", "异常值", "质量问题"))


def _references_analysis_focus_set(question: str, context: dict[str, Any]) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    focus_sets = context.get("focus_sets") if isinstance(context, dict) else []
    if not isinstance(focus_sets, list):
        return False
    for focus_set in focus_sets:
        if not isinstance(focus_set, dict):
            continue
        label = _context_dimension_label(str(focus_set.get("dimension") or ""))
        if label and re.search(
            rf"(?:这|这些)?(?:排名|排行)?前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?{label}",
            compact,
        ):
            return True
        if label and any(
            token in compact
            for token in (
                f"这些{label}",
                f"这些Top{label}",
                f"这些top{label}",
                f"这些TOP{label}",
                f"Top{label}",
                f"top{label}",
                f"TOP{label}",
                f"这几个{label}",
                f"上述{label}",
                f"这3个{label}",
                f"这三个{label}",
                f"这前3个{label}",
                f"这前三个{label}",
                f"前3个{label}",
                f"前三个{label}",
                f"前3名{label}",
                f"这些前三{label}",
                f"这些前3{label}",
                f"这前三名{label}",
                f"这前3名{label}",
                f"排名前三的{label}",
                f"排名前3的{label}",
                f"前三的{label}",
                f"前3的{label}",
                f"前三{label}",
                f"前三名{label}",
                f"最高的{label}",
                f"最低的{label}",
                f"最多的{label}",
                f"最少的{label}",
                f"排名第一的{label}",
                f"排名第1的{label}",
                f"Top1{label}",
                f"top1{label}",
            )
        ):
            return True
        if label and re.search(rf"(?:最高|最低|最多|最少)[^，,。？?；;]{{0,8}}{label}", compact):
            return True
    return False


def _context_dimension_label(dimension: str) -> str:
    mapping = {
        "city": "城市",
        "product": "产品",
        "customer": "客户",
        "customer_id": "客户",
        "segment": "客群",
        "service_line": "服务线",
        "business_line": "业务线",
        "month": "月份",
    }
    return mapping.get(str(dimension or "").strip().lower(), "")


def _rewrite_contextual_extreme_time_reference(record: dict[str, Any], *, question: str, dataset_id: str) -> str:
    compact = re.sub(r"\s+", "", str(question or ""))
    if not compact or not re.search(r"(?:最高|最低)的(?:那?个)?月(?:份)?", compact):
        return ""
    metric_hint = _contextual_extreme_metric_hint(compact)
    month_value = _find_prior_extreme_month_value(record, dataset_id=dataset_id, metric_hint=metric_hint)
    month_text = _month_value_for_question(month_value)
    if not month_text:
        return ""
    tail = re.sub(r"^在?[^，,。；;]*?(?:最高|最低)的(?:那?个)?月(?:份)?[，,。；;]?", "", str(question).strip())
    if not tail or tail == str(question).strip():
        tail = re.sub(r"在?[^，,。；;]*?(?:最高|最低)的(?:那?个)?月(?:份)?", "", str(question)).strip(" ，,。；;")
    if not tail:
        return ""
    return f"在{month_text}，{tail}"


def _rewrite_contextual_extreme_dimension_reference(record: dict[str, Any], *, question: str, dataset_id: str) -> str:
    compact = re.sub(r"\s+", "", str(question or ""))
    match = re.search(
        r"(?P<prefix>[^，,。；;]*?(?:最高|最低|最多|最少|排名第一|排名第1|第一名|第1名|首位)的?)(?P<label>城市|客户|产品|商品|客群|客户细分)(?:中|里|，|,|。|；|;|$)",
        compact,
    )
    if not match:
        return ""
    label = match.group("label")
    dimension_hint = {
        "城市": "city",
        "客户": "customer",
        "产品": "product",
        "商品": "product",
        "客群": "segment",
        "客户细分": "segment",
    }.get(label, "")
    if not dimension_hint:
        return ""
    metric_hint = _contextual_extreme_metric_hint(match.group("prefix"))
    selected_context = _find_prior_extreme_dimension_context(
        record,
        dataset_id=dataset_id,
        dimension_hint=dimension_hint,
        metric_hint=metric_hint,
    )
    selected_value = selected_context.get("value") if isinstance(selected_context, dict) else None
    if selected_value in {None, ""}:
        return ""
    tail = re.sub(
        r"^在?[^，,。；;]*?(?:最高|最低|最多|最少|排名第一|排名第1|第一名|第1名|首位)的?(?:城市|客户|产品|商品|客群|客户细分)(?:中|里)?[，,。；;]?",
        "",
        str(question).strip(),
    )
    if not tail or tail == str(question).strip():
        tail = re.sub(
            r"在?[^，,。；;]*?(?:最高|最低|最多|最少|排名第一|排名第1|第一名|第1名|首位)的?(?:城市|客户|产品|商品|客群|客户细分)(?:中|里)?",
            "",
            str(question),
        ).strip(" ，,。；;")
    if not tail:
        return ""
    tail_compact = re.sub(r"\s+", "", tail)
    if _contextual_extreme_tail_should_use_structured_action(tail_compact):
        return ""
    if re.search(rf"(?:哪个|哪些|哪几个){label}", tail_compact):
        return ""
    time_prefix = _time_filter_question_prefix_from_filters(selected_context.get("filters") if isinstance(selected_context, dict) else {})
    return f"{time_prefix}在{selected_value}{label}中，{tail}"


def _contextual_extreme_tail_should_use_structured_action(tail_compact: str) -> bool:
    if any(token in tail_compact for token in ("趋势", "变化趋势", "如何变化", "怎么变化", "怎样变化", "走势", "每月", "每个月", "各月", "月度")):
        return True
    if any(token in tail_compact for token in ("占比", "比例", "份额", "贡献占比")):
        return True
    return False


def _contextual_extreme_metric_hint(compact: str) -> str:
    if "利润率" in compact or "毛利率" in compact:
        return "利润率"
    if any(token in compact for token in ("销售额", "销售金额", "订单总额", "订单金额", "订单额", "总金额", "总额")):
        return "amount"
    if "利润" in compact:
        return "profit"
    return ""


def _find_prior_extreme_dimension_context(record: dict[str, Any], *, dataset_id: str, dimension_hint: str, metric_hint: str = "") -> dict[str, Any]:
    messages = record.get("messages") if isinstance(record, dict) else []
    if not isinstance(messages, list):
        return {}
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict) or payload.get("success") is False:
            continue
        if dataset_id and str(payload.get("dataset_id") or "") not in {"", dataset_id}:
            continue
        logic = payload.get("logic_form") if isinstance(payload.get("logic_form"), dict) else {}
        params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
        dimension = str(params.get("dimension") or logic.get("group_by") or "")
        if not _dimension_hint_matches(dimension, dimension_hint):
            continue
        metric = str(params.get("metric") or logic.get("metric") or "")
        if metric_hint and not _metric_hint_matches(metric, metric_hint):
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        rows = result.get("rows") if isinstance(result.get("rows"), list) else []
        if rows and isinstance(rows[0], dict) and rows[0].get(dimension) not in {None, ""}:
            return {"value": rows[0].get(dimension), "filters": logic.get("filters") if isinstance(logic.get("filters"), dict) else {}}
    return {}


def _time_filter_question_prefix_from_filters(filters: Any) -> str:
    if not isinstance(filters, dict):
        return ""
    month_filter = filters.get("month")
    if not isinstance(month_filter, dict):
        return ""
    year = month_filter.get("year")
    month_range = month_filter.get("month_range")
    if isinstance(month_range, (list, tuple)) and len(month_range) >= 2:
        start, end = int(month_range[0]), int(month_range[1])
        return f"{year}年{start}月到{end}月，" if year else f"{start}月到{end}月，"
    month = month_filter.get("month")
    if month:
        return f"{year}年{int(month)}月，" if year else f"{int(month)}月，"
    return ""


def _dimension_hint_matches(column: str, hint: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(column or "").lower())
    aliases = {
        "city": ("city", "城市"),
        "customer": ("customer", "cust", "客户"),
        "product": ("product", "sku", "item", "产品", "商品"),
        "segment": ("segment", "客户细分", "客群"),
        "service_line": ("service_line", "business_line", "服务线", "业务线"),
    }.get(hint, (hint,))
    return any(alias and alias in normalized for alias in aliases)


def _metric_hint_matches(metric: str, hint: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(metric or "").lower())
    aliases = {
        "amount": ("amount", "sales", "revenue", "金额", "订单金额", "订单总额", "收入"),
        "profit": ("profit", "利润", "毛利"),
        "利润率": ("利润率", "毛利率", "profitmargin", "margin"),
    }.get(hint, (hint,))
    return any(alias and re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", alias.lower()) in normalized for alias in aliases)


def _find_prior_extreme_month_value(record: dict[str, Any], *, dataset_id: str, metric_hint: str = "") -> Any:
    messages = record.get("messages") if isinstance(record, dict) else []
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict) or payload.get("success") is False:
            continue
        if dataset_id and str(payload.get("dataset_id") or "") not in {"", dataset_id}:
            continue
        logic = payload.get("logic_form") if isinstance(payload.get("logic_form"), dict) else {}
        operation = str(logic.get("operation") or logic.get("task_type") or "")
        if "rank" not in operation and "top" not in operation:
            continue
        if metric_hint and not _payload_mentions_metric(payload, metric_hint):
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
        if not rows:
            continue
        params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
        dimension = str(logic.get("group_by") or params.get("dimension") or params.get("group_by") or "")
        month_column = _month_column_from_result(dimension, rows[0])
        if month_column:
            return rows[0].get(month_column)
    return None


def _payload_mentions_metric(payload: dict[str, Any], metric_hint: str) -> bool:
    needle = str(metric_hint or "").strip().lower()
    if not needle:
        return True
    logic = payload.get("logic_form") if isinstance(payload.get("logic_form"), dict) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    candidates: list[Any] = [
        logic.get("metric"),
        params.get("metric"),
        params.get("derived_metric", {}).get("name") if isinstance(params.get("derived_metric"), dict) else "",
        *(result.get("columns") or []),
    ]
    rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
    if rows:
        candidates.extend(rows[0].keys())
    return any(needle in str(candidate or "").lower() for candidate in candidates)


def _month_column_from_result(dimension: str, row: dict[str, Any]) -> str:
    if re.search(r"month|月份|月度", str(dimension or ""), re.I) and dimension in row:
        return dimension
    for column in row.keys():
        if re.search(r"month|月份|月度", str(column or ""), re.I):
            return str(column)
    return ""


def _month_value_for_question(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) and 1 <= int(value) <= 12:
        return f"{int(value)}月"
    text = str(value).strip()
    match = re.fullmatch(r"(20\d{2})[-/年](\d{1,2})月?", text)
    if match:
        return f"{int(match.group(1))}年{int(match.group(2))}月"
    match = re.fullmatch(r"(20\d{2})(\d{2})", text)
    if match:
        return f"{int(match.group(1))}年{int(match.group(2))}月"
    match = re.fullmatch(r"0?(\d{1,2})月?", text)
    if match:
        month = int(match.group(1))
        if 1 <= month <= 12:
            return f"{month}月"
    return text


def _looks_like_followup_analysis_request(question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    if not compact:
        return False
    if _extract_explicit_formula_text(compact):
        return False
    return any(
        token in compact
        for token in (
            "这些",
            "那",
            "那么",
            "它",
            "其",
            "这个",
            "那个",
            "该",
            "同一",
            "上一轮",
            "刚才",
            "继续",
            "为什么",
            "更高",
            "更大",
            "线路内",
            "线路外",
            "按业代",
            "拆开",
            "拆解",
            "贡献最大",
            "改看",
            "结论变不变",
            "不要看",
            "复核",
            "Top",
            "top",
            "前",
            "最高",
            "最低",
            "最多",
            "最少",
            "最大",
            "最小",
            "贡献",
            "数据质量",
            "质量",
            "缺失",
            "重复",
            "异常",
            "影响分析",
            "其中",
            "上述",
            "这几个",
            "这几",
            "这三个",
            "这3个",
            "这五个",
            "增长率",
            "增长最快",
            "增长最多",
            "增长",
            "相比",
            "相较",
            "利润率",
            "表现",
            "是多少",
            "多少",
            "趋势",
            "如何变化",
            "怎么变化",
            "怎样变化",
            "变化趋势",
            "按月份",
            "这个指标",
            "差距",
            "占比",
            "比例",
            "份额",
            "排名",
            "第二高",
            "第三高",
            "第",
            "继续看",
            "也看一下",
            "重新看",
            "峰值",
            "低点",
            "高点",
            "波动",
            "拆分",
            "下钻",
            "来源",
            "拉动",
            "驱动",
            "按客户",
            "按渠道",
            "按产品",
            "按品类",
        )
    )


def _looks_like_self_contained_analysis_request(question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    if not compact:
        return False
    if _looks_like_extreme_time_scoped_dimension_drilldown_request(compact):
        return False
    if _looks_like_personnel_growth_ranking_request(compact, str(question or "").lower()):
        return True
    if any(
        token in compact
        for token in (
            "这个城市",
            "那个城市",
            "该城市",
            "这个最高城市",
            "那个最高城市",
            "该最高城市",
            "最高城市",
            "最高的城市",
            "这些城市",
            "这3个城市",
            "这三个城市",
            "这五个城市",
            "这些前三城市",
            "这些前3城市",
            "前三城市",
            "这个客户",
            "该客户",
            "这些客户",
            "这个容量",
            "该容量",
            "这些容量",
            "这几个容量",
            "这个指标",
            "刚才排名",
            "排名第一",
            "最高的城市中",
            "最低的城市中",
            "增长最快的城市中",
            "增长最多的城市中",
            "增速最快的城市中",
            "增幅最大的城市中",
            "Top对象",
            "top对象",
            "继续",
        )
    ):
        return False
    if re.search(
        r"(?:这|这些)?(?:排名|排行)?前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?(?:城市|客户|产品|品类|区域|地区|服务线|业务线|团队|客群|客户群|客户群体|月份|容量|规格)",
        compact,
    ):
        return False
    has_metric = any(
        token in compact
        for token in (
            "销售额",
            "订单总金额",
            "订单总额",
            "订单金额",
            "总金额",
            "总额",
            "金额",
            "利润率",
            "利润",
            "收入",
            "营收",
            "订单数",
            "数量",
        )
    )
    has_dimension = any(
        token in compact
        for token in (
            "城市",
            "客户",
            "产品",
            "品类",
            "月份",
            "月度",
            "区域",
            "地区",
            "容量",
            "规格",
            "服务线",
            "团队",
        )
    )
    has_analysis_operator = any(
        token in compact
        for token in (
            "最高",
            "最低",
            "最多",
            "最少",
            "排名",
            "第二高",
            "第三高",
            "第",
            "Top",
            "top",
            "前",
            "趋势",
            "汇总",
            "分别",
        )
    )
    return has_metric and has_dimension and has_analysis_operator


def _looks_like_personnel_growth_ranking_request(compact: str, lowered: str) -> bool:
    personnel_signal = any(
        token in compact
        for token in (
            "销售员",
            "销售人员",
            "销售代表",
            "业务员",
            "业代",
            "员工",
            "人员",
        )
    ) or any(token in lowered for token in ("salesperson", "sales rep", "sales representative", "employee", "personnel"))
    if not personnel_signal:
        return False
    ranking_signal = any(token in compact for token in ("排名", "排行", "排序", "从高到低", "从低到高")) or any(
        token in lowered for token in ("ranking", "rank", "sort", "order by")
    )
    growth_signal = any(token in compact for token in ("增长率", "增速", "增幅")) or any(
        token in lowered for token in ("growth rate", "growth ranking")
    )
    fastest_growth_signal = any(
        token in compact
        for token in (
            "增长最快",
            "增长最多",
            "提升最快",
            "提升最多",
            "下降最快",
            "下降最多",
            "变化最大",
            "变化最多",
            "变动最大",
            "变动最多",
        )
    ) or any(
        token in lowered
        for token in ("fastest growth", "largest growth", "highest growth", "biggest increase", "largest increase", "fastest decline")
    )
    return (growth_signal and ranking_signal) or fastest_growth_signal


def _looks_like_extreme_time_scoped_dimension_drilldown_request(compact: str) -> bool:
    has_extreme_time = (
        any(token in compact for token in ("哪个月份", "哪个月", "哪月份", "哪月", "几月份", "几月"))
        and any(token in compact for token in ("最高", "最大", "最多", "最低", "最小", "最少"))
    )
    if not has_extreme_time:
        return False
    return bool(
        re.search(
            r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位|条)?(?:大)?的?(?:客户|城市|产品|商品|服务线|业务线|品类|门店|区域|地区)",
            compact,
        )
        or re.search(r"(?:哪个|哪些|哪几个)(?:客户|城市|产品|商品|服务线|业务线|品类|门店|区域|地区)", compact)
    )


def _rewrite_followup_question(question: str, *, previous_question: str, logic: dict[str, Any]) -> str:
    operation = str(logic.get("operation") or logic.get("task_type") or "")
    params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    route_rewrite = _rewrite_retail_route_scope_followup(question, previous_question=previous_question, operation=operation, params=params)
    if route_rewrite:
        return route_rewrite
    if operation in {"retail_category_distribution_monthly_trend", "retail_distribution_topn_chart"}:
        window = _retail_month_window_text(params.get("start_ym"), params.get("end_ym"))
        base = f"{window}历史分销金额" if window else "历史分销金额"
        dimension = _followup_dimension_text(question)
        compact = re.sub(r"\s+", "", question)
        if any(token in compact for token in ("拆分", "来源", "拉动", "驱动", "构成", "组成", "按客户", "按渠道", "按产品", "按品类")):
            return f"{base}按{dimension or '客户'}拆分来源，生成Top排名。"
        if any(token in compact for token in ("峰值", "低点", "高点", "波动", "复核")):
            return f"{base}分品类趋势，标出峰值、低点和最大波动期。"
    return ""


def _rewrite_retail_route_scope_followup(question: str, *, previous_question: str, operation: str, params: dict[str, Any]) -> str:
    if operation not in {
        "retail_route_scope_metric_summary",
        "retail_route_scope_difference_reason",
        "retail_route_scope_employee_ranking",
    } and "线路内" not in previous_question and "线路外" not in previous_question:
        return ""
    compact = re.sub(r"\s+", "", str(question or ""))
    ym_text = _ym_text(params.get("ym"))
    route_scope = _route_scope_text_from_question(question) or str(params.get("route_scope") or params.get("dominant_scope") or "")
    if not route_scope and "线路外" in previous_question:
        route_scope = "线路外"
    metric = _route_scope_metric_from_question(question) or str(params.get("metric") or params.get("primary_metric") or "sign_amt")
    metric_text = "签收箱数" if metric == "sign_box_cnt" else "签收金额"
    prefix = f"{ym_text}" if ym_text else ""
    if "为什么" in compact and any(token in compact for token in ("更高", "更大", "高", "大")):
        scope = route_scope or "线路外"
        return f"{prefix}解释为什么{scope}签收金额更高，并按业代拆解{scope}签收金额贡献Top3。"
    if any(token in compact for token in ("按业代", "业代拆", "拆开", "拆解")):
        scope = route_scope or "线路外"
        return f"{prefix}{scope}按业代拆开，按{metric_text}排名前三。"
    if "贡献最大" in compact or "最大的人" in compact:
        scope = route_scope or "线路外"
        return f"{prefix}{scope}按业代拆开，{metric_text}贡献最大的人是谁？"
    if any(token in compact for token in ("改看签收箱数", "签收箱数结论", "不要看签收金额")):
        scope = route_scope or "线路外"
        if operation == "retail_route_scope_employee_ranking" or "业代" in previous_question:
            return f"{prefix}{scope}按业代拆开，按签收箱数排名前三。"
        return f"{prefix}线路内/线路外的签收箱数分别是多少？"
    return ""


def _route_scope_text_from_question(question: str) -> str:
    if "线路外" in question:
        return "线路外"
    if "线路内" in question:
        return "线路内"
    return ""


def _route_scope_metric_from_question(question: str) -> str:
    if any(token in question for token in ("签收箱数", "分销箱数", "分销数量", "箱数", "数量")):
        return "sign_box_cnt"
    if any(token in question for token in ("签收金额", "分销金额", "金额")):
        return "sign_amt"
    return ""


def _retail_month_window_text(start_ym: Any, end_ym: Any) -> str:
    start_text = _ym_text(start_ym)
    end_text = _ym_text(end_ym)
    if start_text and end_text and start_text != end_text:
        return f"{start_text}至{end_text}"
    return start_text or end_text


def _ym_text(value: Any) -> str:
    try:
        ym_value = int(value)
    except (TypeError, ValueError):
        return ""
    year, month = divmod(ym_value, 100)
    if year <= 0 or month <= 0 or month > 12:
        return ""
    return f"{year}年{month}月"


def _followup_dimension_text(question: str) -> str:
    compact = re.sub(r"\s+", "", question)
    for token in ("客户", "渠道", "产品", "品类", "SKU", "业代", "主任"):
        if token in compact:
            return token
    return ""


def _latest_analysis_turn(record: dict[str, Any], *, dataset_id: str) -> dict[str, Any] | None:
    messages = record.get("messages") if isinstance(record, dict) else []
    if not isinstance(messages, list):
        return None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict) or not payload.get("logic_form"):
            continue
        if dataset_id and str(payload.get("dataset_id") or "") not in {"", dataset_id}:
            continue
        question = ""
        if index > 0 and isinstance(messages[index - 1], dict) and messages[index - 1].get("role") == "user":
            question = str(messages[index - 1].get("content") or "")
        return {"payload": payload, "question": question}
    return None


def _latest_successful_analysis_turn(
    record: dict[str, Any],
    *,
    dataset_id: str,
    skip_operations: set[str] | None = None,
) -> dict[str, Any] | None:
    messages = record.get("messages") if isinstance(record, dict) else []
    if not isinstance(messages, list):
        return None
    skip_operations = skip_operations or set()
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict) or not payload.get("logic_form") or payload.get("success") is False:
            continue
        logic = payload.get("logic_form") if isinstance(payload.get("logic_form"), dict) else {}
        operation = str(logic.get("operation") or logic.get("task_type") or "")
        if operation in skip_operations:
            continue
        if dataset_id and str(payload.get("dataset_id") or "") not in {"", dataset_id}:
            continue
        question = ""
        if index > 0 and isinstance(messages[index - 1], dict) and messages[index - 1].get("role") == "user":
            question = str(messages[index - 1].get("content") or "")
        return {"payload": payload, "question": question}
    return None


def _extract_explicit_formula_text(question: str) -> str:
    patterns = (
        r"[\w\u4e00-\u9fff]{1,20}\s*=\s*sum\s*\(?\s*[\w\u4e00-\u9fff_ -]{1,40}\s*\)?\s*/\s*sum\s*\(?\s*[\w\u4e00-\u9fff_ -]{1,40}\s*\)?",
        r"[\w\u4e00-\u9fff]{1,20}\s*=\s*[\w\u4e00-\u9fff_ -]{1,40}\s*/\s*[\w\u4e00-\u9fff_ -]{1,40}",
    )
    for pattern in patterns:
        match = re.search(pattern, question, re.I)
        if match:
            text = match.group(0).strip(" ，,。.;；")
            return re.sub(r"(重新计算|重新算|重算|再算|计算|这个口径|口径)$", "", text).strip(" ，,。.;；")
    return ""


def _formula_lineage_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    if isinstance(debug.get("formula_lineage"), dict) and debug["formula_lineage"]:
        return dict(debug["formula_lineage"])
    logic_form = payload.get("logic_form") if isinstance(payload.get("logic_form"), dict) else {}
    params = logic_form.get("parameters") if isinstance(logic_form.get("parameters"), dict) else {}
    derived = params.get("derived_metric") if isinstance(params.get("derived_metric"), dict) else {}
    if derived:
        return {key: derived.get(key) for key in ("name", "numerator", "denominator", "formula", "formula_source") if derived.get(key)}
    metric = params.get("metric") or logic_form.get("metric")
    aggregation = params.get("aggregation")
    return {"metric": metric, "aggregation": aggregation} if metric or aggregation else {}


def _result_summary_for_correction(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    return {
        "run_id": payload.get("run_id") or "",
        "answer": str(payload.get("answer") or "")[:240],
        "first_row": rows[0] if rows and isinstance(rows[0], dict) else {},
    }


def _correction_clarification_response(
    *,
    run_id: str,
    dataset_id: str,
    question: str,
    correction_context: dict[str, Any],
    started_at: datetime,
    started_perf: float,
) -> dict[str, Any]:
    previous_formula = correction_context.get("previous_formula") if isinstance(correction_context.get("previous_formula"), dict) else {}
    previous_text = ""
    if previous_formula:
        previous_text = "上一轮口径是：" + _short_json(previous_formula) + "。"
    response = {
        "response_version": RESPONSE_VERSION,
        "success": False,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "question": question,
        "answer_type": "clarification",
        "execution_mode": "correction_clarification",
        "answer": previous_text + "你正在修正上一轮口径，但还没有给出可执行的新公式或分子/分母。请明确类似“利润率=sum利润/sum销售”的口径后我再重跑。",
        "result": {"columns": [], "rows": []},
        "verification": {"passed": False, "issues": ["missing_revised_formula"]},
        "warnings": ["Correction request needs an explicit revised metric formula before rerun."],
        "errors": [],
        "debug": {"message_intent": "correction_clarification", "reason": correction_context.get("reason")},
        "correction_context": correction_context,
        "process_view_v2": build_chat_process_view(question, has_dataset=bool(dataset_id)),
    }
    _attach_message_timing(response, started_at=started_at, started_perf=started_perf)
    return response


def _attach_correction_context(response: dict[str, Any], correction_context: dict[str, Any], *, original_question: str) -> None:
    current_formula = _formula_lineage_from_payload(response)
    previous_summary = correction_context.get("previous_result_summary") if isinstance(correction_context.get("previous_result_summary"), dict) else {}
    context = {
        key: correction_context.get(key)
        for key in (
            "is_correction",
            "previous_run_id",
            "changed_scope",
            "previous_formula",
            "revised_formula",
            "previous_question",
        )
        if key in correction_context
    }
    context["current_formula"] = current_formula
    context["difference_summary"] = _correction_difference_summary(previous_summary, response, correction_context, current_formula)
    response["correction_context"] = to_json_ready(context)
    response["question"] = original_question
    debug = response.setdefault("debug", {})
    if isinstance(debug, dict):
        debug["correction_rerun"] = {
            "previous_run_id": correction_context.get("previous_run_id") or "",
            "changed_scope": correction_context.get("changed_scope") or [],
        }


def _attach_followup_context(response: dict[str, Any], followup_context: dict[str, Any], *, original_question: str) -> None:
    context = {
        key: followup_context.get(key)
        for key in ("is_followup", "reason", "previous_run_id", "previous_question", "revised_question", "carried_operation", "pending_actions")
        if key in followup_context
    }
    context["original_question"] = original_question
    response["followup_context"] = to_json_ready(context)
    response["question"] = original_question
    debug = response.setdefault("debug", {})
    if isinstance(debug, dict):
        debug["followup_context"] = to_json_ready(context)


def _compact_compound_sub_response(response: dict[str, Any], *, action: dict[str, Any], index: int) -> dict[str, Any]:
    keys = (
        "success",
        "run_id",
        "dataset_id",
        "question",
        "answer_type",
        "answer",
        "logic_form",
        "result",
        "verification",
        "insight",
        "chart",
        "quality_report",
        "warnings",
        "errors",
        "debug",
    )
    compact = {key: response.get(key) for key in keys if key in response}
    compact["sequence"] = index
    compact["action_id"] = action.get("action_id") or ""
    compact["action_label"] = action.get("label") or ""
    compact["planned_operation"] = action.get("operation") or ""
    return compact


def _compound_followup_answer(sub_results: list[dict[str, Any]]) -> str:
    if not sub_results:
        return "没有生成可执行的后续动作，请补充要复核、下钻或对比的维度。"
    lines = [f"已把这次追问拆成 {len(sub_results)} 个结构化动作执行："]
    for item in sub_results:
        status = "完成" if item.get("success") else "失败"
        operation = ((item.get("logic_form") or {}).get("operation") or item.get("planned_operation") or "analysis")
        answer = _short_plain_text(item.get("answer"), limit=180)
        lines.append(f"{item.get('sequence')}. {item.get('action_label') or operation}：{status}，operation={operation}。{answer}")
    return "\n".join(lines)


def _source_tables_from_sub_results(sub_results: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in sub_results:
        logic = item.get("logic_form") if isinstance(item.get("logic_form"), dict) else {}
        for source in logic.get("source_tables") or []:
            if source:
                names.append(str(source))
        params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
        table = params.get("table")
        if table:
            names.append(str(table))
    return list(dict.fromkeys(names))


def _short_plain_text(value: Any, *, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _correction_difference_summary(
    previous_summary: dict[str, Any],
    response: dict[str, Any],
    correction_context: dict[str, Any],
    current_formula: dict[str, Any],
) -> str:
    previous_formula = correction_context.get("previous_formula") or {}
    previous_row = previous_summary.get("first_row") if isinstance(previous_summary.get("first_row"), dict) else {}
    current_rows = ((response.get("result") or {}).get("rows") or []) if isinstance(response.get("result"), dict) else []
    current_row = current_rows[0] if current_rows and isinstance(current_rows[0], dict) else {}
    parts = []
    if previous_formula or current_formula:
        parts.append(f"口径已从 {_short_json(previous_formula) or '上一轮默认指标'} 改为 {_short_json(current_formula) or correction_context.get('revised_formula') or '新口径'}")
    if previous_row or current_row:
        parts.append(f"首行结果从 {_short_json(previous_row) or '无'} 更新为 {_short_json(current_row) or '无'}")
    return "；".join(parts) + "。" if parts else "已按用户修正口径重新计算。"


def _short_json(value: Any, limit: int = 180) -> str:
    if not value:
        return ""
    text = json.dumps(to_json_ready(value), ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _combine_guidelines(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _referent_guideline_from_action(action: Any) -> str:
    if not isinstance(action, dict):
        return ""
    contract = action.get("referent_contract")
    if not isinstance(contract, dict) or not contract:
        return ""
    return referent_contract_guideline(contract)


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
        "derived_metric_count": len(project_context.get("derived_metrics") or []),
    }
    response["project_id"] = project["project_id"]
    response["project"] = project
    response.setdefault("debug", {})
    response["debug"]["project_context"] = project


def _truncate_for_llm(value: Any, limit: int = 1000) -> str:
    text = value if isinstance(value, str) else json.dumps(to_json_ready(value), ensure_ascii=False, default=str)
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _attach_fast_path_overview_contract_checks(response: dict[str, Any], *, question: str) -> None:
    if not isinstance(response, dict):
        return
    if response.get("answer_type") != "overview":
        return
    logic_form = response.get("logic_form")
    if not isinstance(logic_form, dict):
        return
    debug = response.setdefault("debug", {}) if isinstance(response.get("debug"), dict) else {}
    response["debug"] = debug
    contract = build_task_execution_contract(logic_form, question=question)
    if contract is None or contract.task_family not in {"overview", "multi_file_overview"}:
        return
    result_payload = response.get("result")
    if not isinstance(result_payload, dict):
        return
    value_payload = result_payload.get("value")
    execution_value: dict[str, Any] = value_payload if isinstance(value_payload, dict) else {}
    execution_value["overview_report"] = response.get("overview_report") if response.get("overview_report") is not None else execution_value.get("overview_report")
    execution_result = ExecutionResult(
        backend="fast_path_overview",
        success=bool(response.get("success")),
        columns=list(result_payload.get("columns") or []),
        rows=list(result_payload.get("rows") or []) if isinstance(result_payload.get("rows"), list) else [],
        value=execution_value,
        summary=str(response.get("answer") or ""),
        debug={"path": "fast_path_overview", "operation": str((logic_form or {}).get("operation") or "dataset_overview")},
    )
    try:
        contract_report = verify_task_execution_contract(contract, execution_result)
        report_dict = asdict(contract_report)
        response["contract_report"] = report_dict
        response["contract_satisfied"] = bool(contract_report.passed)
        response["contract_family"] = contract_report.task_family
        response["semantic_status"] = semantic_status_from_report(contract=contract, report=contract_report)
        response["violations"] = list(report_dict.get("violations") or [])
        verification = response.get("verification") if isinstance(response.get("verification"), dict) else {}
        verification.setdefault("contract_report", report_dict)
        verification.setdefault("task_contract", asdict(contract))
        verification.setdefault("semantic_status", response["semantic_status"])
        verification.setdefault("notes", []).append("overview fast-path contract verified")
        response["verification"] = verification
        debug["contract_report"] = report_dict
        debug["task_contract"] = asdict(contract)
        debug["semantic_status"] = response["semantic_status"]
    except Exception as exc:  # noqa: BLE001 - overview fast-path contract should never block user answers.
        response["semantic_status"] = "legacy_unverified"
        response["unverified_reason"] = f"overview fast-path contract verification unavailable: {type(exc).__name__}: {str(exc)[:180]}"
        response["contract_satisfied"] = None
        response.setdefault("violations", [])
        response["contract_report"] = response.get("contract_report")
        debug["semantic_status"] = response["semantic_status"]
        debug["unverified_reason"] = response["unverified_reason"]


def _result_preview_for_llm(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    rows = result.get("rows")
    if not isinstance(rows, list):
        rows = []
    return {
        "columns": list(result.get("columns") or [])[:12],
        "rows": rows[:5],
        "value": result.get("value") if not rows else None,
    }


def _ensure_semantic_response_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Expose semantic-contract instrumentation without upgrading legacy paths to pass."""

    if not isinstance(payload, dict):
        return payload
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    verification = payload.get("verification") if isinstance(payload.get("verification"), dict) else {}
    contract_report = (
        payload.get("contract_report")
        if isinstance(payload.get("contract_report"), dict)
        else verification.get("contract_report")
        if isinstance(verification.get("contract_report"), dict)
        else debug.get("contract_report")
        if isinstance(debug.get("contract_report"), dict)
        else None
    )
    task_contract = (
        payload.get("task_contract")
        if isinstance(payload.get("task_contract"), dict)
        else verification.get("task_contract")
        if isinstance(verification.get("task_contract"), dict)
        else debug.get("task_contract")
        if isinstance(debug.get("task_contract"), dict)
        else None
    )
    oracle_result = (
        payload.get("oracle_result")
        if isinstance(payload.get("oracle_result"), dict)
        else verification.get("oracle_result")
        if isinstance(verification.get("oracle_result"), dict)
        else debug.get("oracle_result")
        if isinstance(debug.get("oracle_result"), dict)
        else None
    )
    semantic_status = (
        payload.get("semantic_status")
        or verification.get("semantic_status")
        or debug.get("semantic_status")
        or "legacy_unverified"
    )
    payload["semantic_status"] = str(semantic_status)
    payload["contract_satisfied"] = contract_report.get("passed") if isinstance(contract_report, dict) else payload.get("contract_satisfied")
    if payload["contract_satisfied"] is None and not isinstance(contract_report, dict):
        payload["contract_satisfied"] = None
    payload["contract_family"] = (
        payload.get("contract_family")
        or (task_contract or {}).get("task_family")
        or (contract_report or {}).get("task_family")
    )
    payload["violations"] = list((contract_report or {}).get("violations") or payload.get("violations") or [])
    payload["oracle_result"] = oracle_result if oracle_result is not None else payload.get("oracle_result")
    if payload["oracle_result"] is None:
        payload["oracle_result"] = {
            "oracle_available": False,
            "expected_result": None,
            "actual_result": None,
            "passed": None,
            "diff_summary": "No deterministic oracle result is attached to this legacy response path.",
            "issue_codes": ["oracle_not_instrumented"],
        }
    payload.setdefault("debug", {})
    if isinstance(payload["debug"], dict):
        payload["debug"].setdefault("semantic_status", payload["semantic_status"])
        payload["debug"].setdefault("task_contract", task_contract)
        payload["debug"].setdefault("contract_report", contract_report)
        payload["debug"].setdefault("oracle_result", payload["oracle_result"])
    return payload


def _safe_dict_for_llm(value: Any, *, limit: int = 1000) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe = to_json_ready(value)
    text = json.dumps(safe, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return safe
    return {"summary": _truncate_for_llm(value.get("summary") or text, limit)}


def _semantic_dataset_route(
    question: str,
    *,
    source_manifest: dict[str, Any],
    allow_rescue: bool = False,
) -> str:
    """Semantic fallback router for broad dataset/source browse questions."""

    text = str(question or "").strip().lower()
    if not text:
        return "chat"
    compact = re.sub(r"\s+", "", text)
    semantics = _question_semantics(compact)
    has_sources = _source_manifest_has_knowledge(source_manifest)
    has_table_sources = any(
        isinstance(item, dict) and str(item.get("source_type") or "") == "table"
        for item in source_manifest.get("sources") or []
    )
    if is_cleaning_guidance_question(question):
        return "cleaning_guidance"
    if _looks_like_fee_calculation_question(compact):
        return "analysis"
    if is_dataset_source_question(question):
        return "dataset_source_overview"
    if is_dataset_overview_question(question):
        if has_sources and semantics["content_or_purpose"] and semantics["dataset_subject"]:
            return "dataset_source_overview"
        return "dataset_overview"
    if semantics["quality_diagnostic"]:
        return "analysis"
    if semantics["calculation"]:
        return "analysis"
    if has_sources and not has_table_sources and (semantics["dataset_subject"] or semantics["source_subject"]):
        return "dataset_source_overview"
    if semantics["broad_browse"] and semantics["source_subject"]:
        return "dataset_source_overview"
    if semantics["broad_browse"] and semantics["dataset_subject"]:
        return "dataset_source_overview" if has_sources and semantics["content_or_purpose"] else "dataset_overview"
    if allow_rescue and semantics["broad_browse"]:
        return "dataset_source_overview" if has_sources else "dataset_overview"
    return "analysis"


def _question_semantics(compact: str) -> dict[str, bool]:
    """Return coarse semantics; this is a backstop, not a phrase router."""

    dataset_subject = bool(
        re.search(r"(数据|资料|表单?|文件|材料|dataset|table|file|form)", compact)
        or re.search(r"(这里面|这里边|这批|这份|当前上传|上传内容|这些里面|这个里面)", compact)
    )
    source_subject = bool(
        re.search(
            r"(文件|材料|文档|说明|规则|手册|口径|manual|readme|word|docx?|docm|rtf|odt|pdf|pages|html?|json|txt|md)",
            compact,
        )
    )
    browse_action = bool(re.search(r"(看|读|讲|介绍|总结|概览|解释|说明|浏览|overview|summary|summar)", compact))
    content_or_purpose = bool(
        re.search(
            r"(内容|含|包含|里面|里边|有什么|都有什|都有啥|装了啥|讲什么|是什么|是啥|什么文件|啥文件|干什么|做什么|用途|用处|作用|meaning|contain|include|purpose|about)",
            compact,
        )
    )
    quality_diagnostic = bool(re.search(r"(有什么问题|哪里有问题|质量问题|数据质量|异常|缺失|重复|坏数据|脏数据|problem|quality|anomal)", compact))
    calculation = bool(
        re.search(
            r"(计算|求|多少|数量|客户数|客户数量|总客户数|总金额|总订单金额|订单总金额|订单金额|总利润|总额|总收入|利润率|合计|几(?!个文件|张表|个表)|最高|最低|最大|最小|最好|最佳|最优|最差|表现|排名|top|占比|比例|趋势|环比|同比|增长|下降|筛选|过滤|按.+分组|生成图|图表|预测|关联分析|join)",
            compact,
        )
        or re.search(r"(?:各|每个|按).*(?:销售额|销售金额|总销售额|收入|金额|利润率|利润|工单量|工单数|指标)", compact)
        or re.search(r"(?:各|每个|按).*(?:销售数据|经营数据|业务数据|订单数据|工单数据)", compact)
        or re.search(r"(组成|构成|拆分|下钻|拉动|驱动|按.+拆分|拆分来源)", compact)
        or _looks_like_fee_calculation_question(compact)
    )
    return {
        "dataset_subject": dataset_subject,
        "source_subject": source_subject,
        "browse_action": browse_action,
        "content_or_purpose": content_or_purpose,
        "quality_diagnostic": quality_diagnostic,
        "calculation": calculation,
        "broad_browse": (dataset_subject or source_subject) and (browse_action or content_or_purpose),
    }


def _looks_like_fee_calculation_question(compact: str) -> bool:
    text = str(compact or "").lower()
    if "fee" not in text:
        return False
    return bool(
        re.search(
            r"(totalfees?|amount|delta|pay|paid|paying|changed(?:its)?mcc|mcccodeto|howmuch)",
            text,
        )
    )


def _source_manifest_has_knowledge(source_manifest: dict[str, Any]) -> bool:
    for item in source_manifest.get("sources") or []:
        if isinstance(item, dict) and str(item.get("source_type") or "") != "table":
            return True
    return False


def _source_counts_for_llm(source_manifest: dict[str, Any]) -> dict[str, int]:
    sources = [item for item in source_manifest.get("sources") or [] if isinstance(item, dict)]
    return {
        "source_count": len(sources),
        "table_count": sum(1 for item in sources if str(item.get("source_type") or "") == "table"),
        "knowledge_count": sum(1 for item in sources if str(item.get("source_type") or "") != "table"),
    }


def _source_preview_for_llm(source_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for item in source_manifest.get("sources") or []:
        if not isinstance(item, dict):
            continue
        preview.append(
            {
                "file_name": item.get("file_name"),
                "source_type": item.get("source_type"),
                "source_role": item.get("source_role"),
                "purpose": item.get("purpose"),
            }
        )
        if len(preview) >= 10:
            break
    return preview


def _is_not_applicable_payload(payload: dict[str, Any]) -> bool:
    answer = str(payload.get("answer") or "").strip().lower()
    if answer == "not applicable":
        return True
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    value = str(result.get("value") or "").strip().lower()
    if value == "not applicable":
        return True
    rows = result.get("rows") if isinstance(result, dict) else []
    return bool(rows) and all(
        isinstance(row, dict) and str(row.get("answer") or "").strip().lower() == "not applicable"
        for row in rows[:3]
    )


def _is_stale_stored_overview_repair(payload: dict[str, Any]) -> bool:
    """Return True for old repaired history payloads that still expose bad UX wording."""

    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    repair = debug.get("stored_not_applicable_repair") if isinstance(debug.get("stored_not_applicable_repair"), dict) else {}
    if not repair.get("applied"):
        return False
    answer = str(payload.get("answer") or "")
    return "刚才 N/A" in answer or "N/A 的问题" in answer or "Not Applicable" in answer


def _overview_shape_for_llm(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    tables = report.get("tables_summary")
    if isinstance(tables, list):
        return {
            "scope": report.get("overview_scope") or "multi_table",
            "table_count": report.get("table_count"),
            "tables": [
                {
                    "table": item.get("table"),
                    "rows": item.get("row_count"),
                    "columns": item.get("column_count"),
                    "table_type": item.get("table_type"),
                    "meaning": item.get("likely_meaning"),
                    "key_fields": list(item.get("key_fields") or [])[:6],
                }
                for item in tables[:6]
                if isinstance(item, dict)
            ],
        }
    return {
        "scope": "single_table",
        "table": report.get("table"),
        "rows": report.get("row_count"),
        "columns": report.get("column_count"),
        "metric_column": report.get("metric_column"),
        "dimension_column": report.get("dimension_column"),
        "period_column": report.get("period_column"),
    }


def _quality_summary_for_llm(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    return {
        "status": report.get("status"),
        "issue_count": report.get("issue_count"),
        "summary": report.get("summary"),
    }


def _chat_dataset_context_for_llm(profile: Any) -> dict[str, Any]:
    if not profile:
        return {"dataset_present": False}
    payload = to_json_ready(profile)
    if not isinstance(payload, dict):
        return {"dataset_present": True}
    tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    return {
        "dataset_present": True,
        "dataset_id": payload.get("dataset_id"),
        "file_name": payload.get("file_name"),
        "table_count": len(tables),
        "tables": [
            {
                "table_name": table.get("table_name"),
                "source_file": table.get("source_file"),
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count"),
            }
            for table in tables[:8]
            if isinstance(table, dict)
        ],
    }


def _blocked_marker(*parts: str, sep: str = "_") -> str:
    return sep.join(parts)


def _llm_text(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    blocked = (
        "chain_of_thought",
        "raw_prompt",
        _blocked_marker("standard", "answer"),
        _blocked_marker("hidden", "answer"),
        _blocked_marker("task", "id"),
        "scorer",
    )
    if any(token in text.lower() for token in blocked):
        return ""
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _is_chinese_user_facing_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if not re.search(r"[\u3400-\u9fff]", value):
        return False
    return not _looks_like_english_prose_leak(value)


def _is_actionable_next_step_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(
        re.search(
            r"下一步|继续|先|按|比较|查看|检查|复核|确认|拆分|下钻|分析|生成|列出|看|追踪|对比|补充|选择|找出",
            value,
        )
    )


def _looks_like_english_prose_leak(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    segments = [
        segment.strip()
        for segment in re.split(r"[；;。！？!?]\s*|(?:观察|风险|边界|依据|建议|下一步)[:：]", value)
        if segment.strip()
    ] or [value]
    return any(_segment_looks_like_english_prose_leak(segment) for segment in segments)


def _segment_looks_like_english_prose_leak(text: str) -> bool:
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", text))
    latin_words = re.findall(r"[A-Za-z][A-Za-z_'-]*", text)
    if not latin_words:
        return False
    prose_tokens = {
        "are",
        "based",
        "by",
        "compare",
        "countries",
        "country",
        "data",
        "followed",
        "full",
        "include",
        "includes",
        "is",
        "leading",
        "next",
        "not",
        "only",
        "present",
        "ranked",
        "ranking",
        "result",
        "results",
        "show",
        "shows",
        "step",
        "the",
        "this",
        "that",
    }
    prose_count = sum(1 for word in latin_words if word.lower().strip("_'") in prose_tokens)
    if cjk_count == 0:
        return prose_count >= 2 or (len(latin_words) >= 5 and prose_count >= 1)
    return prose_count >= 3 and cjk_count < 6


def _is_safe_direct_chat_answer(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    blocked = (
        "not applicable",
        "chain_of_thought",
        "chain of thought",
        "raw_prompt",
        "raw prompt",
        "raw trace",
        "trace json",
        _blocked_marker("standard", "answer"),
        _blocked_marker("standard", "answer", sep=" "),
        _blocked_marker("hidden", "answer"),
        _blocked_marker("task", "id"),
        "scorer",
        "api_key",
        "后端审计",
        "标准答案",
        "评分器",
    )
    if any(token in lowered for token in blocked):
        return False
    if any(token in lowered for token in ("```", "|---", "| ---", "select ", " from ", " where ", "group by", "order by")):
        return False
    return True


def _is_safe_llm_display_answer(text: str, response: dict[str, Any]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    blocked = (
        "chain_of_thought",
        "raw_prompt",
        "raw prompt",
        _blocked_marker("standard", "answer"),
        _blocked_marker("standard", "answer", sep=" "),
        _blocked_marker("hidden", "answer"),
        _blocked_marker("task", "id"),
        "scorer",
        "benchmark",
        "api_key",
        "trace json",
        "后端审计",
        "标准答案",
        "评分器",
    )
    if any(token in lowered for token in blocked):
        return False
    if "not applicable" in lowered and str(response.get("answer") or "").strip() != "Not Applicable":
        return False
    if any(token in lowered for token in ("```", "|---", "| ---", "select ", " from ", " where ", "group by", "order by")):
        return False
    if _looks_like_raw_detail_dump(text):
        return False
    if not _overview_table_types_preserved(text, response):
        return False
    return _display_answer_numbers_are_grounded(text, response)


def _overview_table_types_preserved(text: str, response: dict[str, Any]) -> bool:
    report = response.get("overview_report")
    if not isinstance(report, dict) or report.get("overview_scope") != "multi_table":
        return True
    table_types = {
        str(item.get("table_type") or "").strip()
        for item in report.get("tables_summary") or []
        if isinstance(item, dict) and str(item.get("table_type") or "").strip()
    }
    required = {label for label in table_types if label in {"可计算事实表", "维表", "说明或元数据表", "规则/知识来源"}}
    if len(required) <= 1:
        return True
    return all(label in text for label in required)


def _compose_summary_prefaced_answer(original_answer: Any, summary: str) -> str:
    original = str(original_answer or "").strip()
    preface = _llm_text(summary, 260)
    if not original or not preface or preface in original:
        return ""
    return f"{preface}\n\n{original}"


def _display_answer_numbers_are_grounded(text: str, response: dict[str, Any]) -> bool:
    display_numbers = _normalized_numbers(text)
    if not display_numbers:
        return True
    grounded_source = " ".join(
        [
            str(response.get("answer") or ""),
            json.dumps(to_json_ready(response.get("result") or {}), ensure_ascii=False, default=str),
            json.dumps(to_json_ready(response.get("insight") or {}), ensure_ascii=False, default=str),
            json.dumps(to_json_ready(response.get("chart") or {}), ensure_ascii=False, default=str),
            json.dumps(to_json_ready(response.get("quality_report") or {}), ensure_ascii=False, default=str),
            json.dumps(to_json_ready(response.get("overview_report") or {}), ensure_ascii=False, default=str),
        ]
    )
    grounded_numbers = _normalized_numbers(grounded_source)
    return display_numbers.issubset(grounded_numbers)


def _normalized_numbers(text: str) -> set[str]:
    result: set[str] = set()
    for raw in re.findall(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?%?", str(text or "")):
        normalized = raw.replace(",", "").rstrip("%")
        if normalized:
            result.add(normalized)
    return result


def _llm_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _llm_text(item, 120)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _attach_llm_presentation_process_step(response: dict[str, Any], meta: dict[str, Any]) -> None:
    process = response.get("process_view_v2")
    if not isinstance(process, dict) or not meta.get("used"):
        return
    process["summary"] = _append_once_to_summary(str(process.get("summary") or ""), "调用LLM整理表达")
    steps = process.setdefault("steps", [])
    if not isinstance(steps, list):
        return
    steps.append(
        {
            "title": "LLM 表达整理",
            "summary": "已调用 LLM 基于已验证结果整理五段式主回答、简要洞察和下一步建议；LLM 不重新计算数据，也不改变表格结果。",
            "status": "completed",
            "evidence": [
                f"stage={meta.get('stage')}",
                f"confidence={meta.get('confidence')}",
                f"elapsed_ms={meta.get('elapsed_ms')}",
                f"updated_answer={meta.get('updated_answer')}",
                f"answer_update_source={meta.get('answer_update_source')}",
            ],
            "source": "llm_summary",
            "confidence": meta.get("confidence"),
        }
    )


def _attach_direct_llm_chat_process_step(response: dict[str, Any], meta: dict[str, Any]) -> None:
    process = response.get("process_view_v2")
    if not isinstance(process, dict) or not meta.get("used"):
        return
    process["summary"] = _append_once_to_summary(str(process.get("summary") or ""), "调用LLM直接对话")
    steps = process.setdefault("steps", [])
    if not isinstance(steps, list):
        return
    steps.append(
        {
            "title": "LLM 直接对话",
            "summary": "已把普通聊天、能力说明或概念问题交给直连 LLM 回复；具体数据计算仍保留给分析 agent 链路。",
            "status": "completed",
            "evidence": [
                f"stage={meta.get('stage')}",
                f"confidence={meta.get('confidence')}",
                f"elapsed_ms={meta.get('elapsed_ms')}",
                f"updated_answer={meta.get('updated_answer')}",
                f"has_dataset={meta.get('has_dataset')}",
            ],
            "source": "llm_chat",
            "confidence": meta.get("confidence"),
        }
    )


def _ensure_activity_trace_v2(response: dict[str, Any]) -> None:
    """Attach GPT-like activity trace rows when a fast path skipped agents."""

    if not isinstance(response, dict) or response.get("activity_trace_v2"):
        return
    try:
        response["activity_trace_v2"] = build_activity_trace_v2(response_like=response)
    except Exception:
        response["activity_trace_v2"] = []


def _append_once_to_summary(summary: str, phrase: str) -> str:
    if not summary or phrase in summary:
        return summary
    if "输出用户回答" in summary:
        return summary.replace("输出用户回答", f"{phrase}、输出用户回答")
    return f"{summary} {phrase}。"


def _apply_gpt_like_text_framework(response: dict[str, Any], *, question: str) -> dict[str, Any]:
    """Normalize data-answer wording without risking the verified payload."""

    try:
        return apply_text_answer_framework(response, question=question)
    except Exception as exc:  # noqa: BLE001 - presentation shaping must never break an answer.
        response.setdefault("debug", {})
        if isinstance(response["debug"], dict):
            response["debug"]["text_answer_framework"] = {
                "applied": False,
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                "version": "bigcat_evidence_report_v2",
            }
        return response


def _attach_message_timing(response: dict[str, Any], *, started_at: datetime, started_perf: float) -> None:
    """Attach user-visible response timing before conversation persistence."""

    response.setdefault("started_at", started_at.isoformat())
    response["responded_at"] = datetime.now(timezone.utc).isoformat()
    response["thinking_elapsed_ms"] = max(0, int(round((time.perf_counter() - started_perf) * 1000)))


def _attach_export_artifacts(response: dict[str, Any], *, runs_root: Path) -> None:
    """Attach downloadable artifact manifest without exposing trace/debug payloads."""

    if not isinstance(response, dict) or response.get("success") is False:
        return
    try:
        response["artifacts_manifest"] = generate_export_artifacts(response, runs_root=runs_root)
    except Exception as exc:  # noqa: BLE001 - exports must not turn a valid answer into a failure.
        response["artifacts_manifest"] = {
            "version": "export_artifacts.v1",
            "source_run_id": str(response.get("run_id") or ""),
            "artifacts": [],
            "unavailable": [
                {
                    "artifact_type": "summary_report",
                    "format": "all",
                    "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                }
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def _raise_if_cancelled(cancel_checker: Callable[[], bool] | None) -> None:
    if cancel_checker is not None and cancel_checker():
        raise RuntimeError("Execution cancelled")


def _attach_source_references(response: dict[str, Any], *, profile: Any) -> None:
    """Attach user-facing uploaded-file references for the answer footer."""

    references = _build_source_references(response, profile)
    if references:
        response["source_references"] = references


def _build_source_references(response: dict[str, Any], profile: Any) -> list[dict[str, Any]]:
    data = to_json_ready(profile) if profile is not None else {}
    tables = data.get("tables") if isinstance(data, dict) else []
    if not isinstance(tables, list) or not tables:
        return []
    wanted = _response_source_table_names(response)
    selected = [
        table
        for table in tables
        if isinstance(table, dict) and (not wanted or _profile_table_matches_any_source(table, wanted))
    ]
    if wanted and not selected:
        return []
    if not selected and _should_reference_all_profile_tables(response, tables, wanted):
        selected = [table for table in tables if isinstance(table, dict)]
    if not selected:
        return []

    grouped: dict[str, dict[str, Any]] = {}
    fallback_file_name = str(data.get("file_name") or "").strip() if isinstance(data, dict) else ""
    for table in selected:
        table_name = str(table.get("table_name") or table.get("name") or "").strip()
        file_name = str(table.get("source_file") or table.get("file_name") or fallback_file_name or table_name or "uploaded dataset").strip()
        reference = grouped.setdefault(file_name, {"file_name": file_name, "tables": []})
        row_count = _safe_int(table.get("row_count"))
        column_count = _safe_int(table.get("column_count"))
        table_ref: dict[str, Any] = {
            "table_name": table_name or file_name,
            "sheet": str(table.get("sheet") or "").strip(),
        }
        if row_count is not None:
            table_ref["row_count"] = row_count
        if column_count is not None:
            table_ref["column_count"] = column_count
        reference["tables"].append(table_ref)

    references: list[dict[str, Any]] = []
    for reference in grouped.values():
        tables_for_file = reference["tables"]
        reference["table_count"] = len(tables_for_file)
        row_total = sum(int(table.get("row_count") or 0) for table in tables_for_file if table.get("row_count") is not None)
        if row_total:
            reference["row_count"] = row_total
        if len(tables_for_file) == 1 and tables_for_file[0].get("column_count") is not None:
            reference["column_count"] = int(tables_for_file[0]["column_count"])
        references.append(reference)
    return to_json_ready(references)


def _response_source_table_names(response: dict[str, Any]) -> list[str]:
    names: list[str] = []
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    logic_form = response.get("logic_form") if isinstance(response.get("logic_form"), dict) else {}
    parameters = logic_form.get("parameters") if isinstance(logic_form.get("parameters"), dict) else {}

    _append_source_names(names, debug.get("source_tables"))
    _append_source_names(names, logic_form.get("source_tables"))
    _append_source_names(names, parameters.get("source_tables"))
    _append_source_names(names, parameters.get("tables"))
    _append_source_names(names, parameters.get("table"))
    for join_plan in (
        debug.get("join_plan"),
        logic_form.get("join_plan"),
        parameters.get("join_plan"),
    ):
        if isinstance(join_plan, dict):
            _append_source_names(names, join_plan.get("left_table"))
            _append_source_names(names, join_plan.get("right_table"))
    deduped: list[str] = []
    for name in names:
        text = str(name or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _append_source_names(names: list[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        names.append(value)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _append_source_names(names, item)


def _profile_table_matches_any_source(table: dict[str, Any], source_names: list[str]) -> bool:
    source_keys = {_source_key(name) for name in source_names if _source_key(name)}
    if not source_keys:
        return False
    table_keys: set[str] = set()
    for key in ("table_name", "source_file", "file_name", "sheet"):
        value = str(table.get(key) or "").strip()
        if value:
            table_keys.add(_source_key(value))
            table_keys.add(_source_key(Path(value).stem))
    return bool(source_keys & table_keys)


def _source_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _should_reference_all_profile_tables(response: dict[str, Any], tables: list[Any], wanted: list[str]) -> bool:
    if wanted or response.get("success") is False or response.get("answer_type") == "chat":
        return False
    if len(tables) == 1:
        return True
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    return response.get("answer_type") in {"overview", "cleaning_simulation"} or debug.get("operation") == "multi_table_dataset_overview"


def _safe_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


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
        "instructions_version": record.get("instructions_version") or 1,
        "instructions_updated_at": record.get("instructions_updated_at") or "",
        "content_hash": record.get("content_hash") or "",
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
        return "你好，我是 VDS。当前没有上传文件，所以不能给出具体数据结论；你可以先和我讨论分析思路、指标口径、字段设计，上传文件后我再基于真实数据分析。"
    if any(token in question for token in ("你是什么模型", "你是哪个模型", "底层模型", "什么模型", "你是谁", "介绍一下你")):
        return "我是 VDS 数据分析助手，运行在当前 VDS 后端和可配置 LLM provider 之上。我的职责是理解数据问题、调用受控分析链路，并把结果整理成可核对的回答。"
    if any(
        token in compact
        for token in (
            "能做什么",
            "你能干什么",
            "你可以干什么",
            "你能帮我做什么",
            "你能帮我干什么",
            "你可以帮我做什么",
            "我能干什么",
            "我可以干什么",
            "我能问什么",
            "我可以问什么",
            "我该问什么",
            "我能让你做什么",
            "我可以让你做什么",
            "怎么用",
            "功能",
            "帮助",
        )
    ) or "help" in lowered:
        if has_dataset:
            return "当前数据已经上传。你可以问概览、排序、汇总、趋势、对比、多文件命中文件或多表关联问题；如果只是聊天或讨论口径，我也会直接回复。"
        return "上传文件后（上传数据后），我可以做通用数据概览、多文件字段对比、字段角色识别、数据质量扫描、异常规则说明、可分析性建议和清洗影响模拟；领域专项问题需要对应字段或配置支持。"
    if any(token in question for token in ("多文件", "多个文件", "多张表", "多表")) and any(token in question for token in ("对比", "支持", "join", "关联")):
        return "支持多文件对比。多文件场景必须分别读取每个文件的行列、字段、缺失和角色，再判断是否可以做对比或 join；不能默认只分析第一个文件。"
    if any(token in question for token in ("没有数据", "分析建议", "先给我建议")):
        return "没有数据时只能给方法建议：先上传文件，再确认行列、字段含义、时间字段、指标字段、维度字段、缺失和异常；不能编造任何真实数值。"
    if any(token in question for token in ("字段", "口径", "指标", "维度", "关联", "数据表")) or "join" in lowered:
        if any(token in question for token in ("多文件", "多个文件", "多张表", "多表", "对比")) or "join" in lowered:
            return "支持多文件对比。多文件场景必须分别读取每个文件的行列、字段、缺失和角色，再判断是否可以做对比或 join；不能默认只分析第一个文件。"
        return "没有数据时只能给方法建议：你把字段名、表结构或想看的指标告诉我，我可以帮你整理分析口径、推荐维度、判断是否需要多表关联；不能编造任何真实数值。"
    if any(token in lowered for token in ("sales", "revenue", "overall", "summary")) or any(token in question for token in ("销售", "收入", "整体", "概览", "情况")):
        return "没有数据时只能给方法建议，不能编造真实数值。真实结论需要上传相关销售或收入数据；上传后我会优先返回汇总指标、趋势和关键下钻方向，而不是直接展开明细行。"
    if has_dataset:
        return "可以继续聊。当前数据已就绪；你可以直接问概览、汇总、排序、趋势、对比、字段口径、数据质量或多表关联，我会按问题选择合适的分析链路。"
    return "可以继续聊。当前还没有上传数据，所以我不会编造业务结论；你可以描述分析目标、数据字段或上传文件后让我基于真实数据分析。"


def _ensure_activity_trace_v2(response: dict[str, Any]) -> dict[str, Any]:
    """Attach a safe activity trace for Workbench surfaces when missing."""

    if isinstance(response, dict) and not response.get("activity_trace_v2"):
        response["activity_trace_v2"] = build_activity_trace_v2(None, response)
    return response


def _suppress_raw_detail_answer(
    payload: dict[str, Any],
    *,
    question: str,
    tables: dict[str, Any],
    profile: Any,
    agent_mode: str,
) -> dict[str, Any]:
    answer = str(payload.get("answer") or "")
    if _is_non_detail_analysis_payload(payload, question=question):
        return payload
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


def _is_non_detail_analysis_payload(payload: dict[str, Any], *, question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or "").strip().lower())
    if not _question_semantics(compact)["calculation"]:
        return False
    logic = payload.get("logic_form") if isinstance(payload.get("logic_form"), dict) else {}
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    operation = str(logic.get("operation") or logic.get("task_type") or debug.get("operation") or "")
    if not operation or operation in {"detail_lookup", "filtering"}:
        return False
    return True


def _looks_like_raw_detail_dump(answer: str) -> bool:
    text = " ".join(str(answer or "").split())
    if _looks_like_compact_value_sequence(text):
        return True
    if len(text) < 500:
        return False
    comma_count = text.count(",")
    if comma_count < 30:
        return False
    token_count = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff_.-]+", text))
    sentence_count = len(re.findall(r"[。！？；;]", text))
    return token_count >= 60 and sentence_count <= 6


def _looks_like_compact_value_sequence(text: str) -> bool:
    parts = [part.strip() for part in re.split(r"[,，]", str(text or "")) if part.strip()]
    if len(parts) < 8:
        return False
    if len(re.findall(r"[。！？；;]", text)) > 1:
        return False
    if any(marker in text for marker in ("建议", "字段", "行", "列", "表", "文件", "数据", "不能", "不会", "可以", "需要", "结果")):
        return False
    structured_parts = sum(1 for part in parts if _looks_like_scalar_value(part))
    return structured_parts >= max(6, int(len(parts) * 0.6))


def _looks_like_scalar_value(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?%?", text):
        return True
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ tT]\d{1,2}:\d{2}(?::\d{2})?)?", text):
        return True
    if re.fullmatch(r"[A-Za-z]*\d[A-Za-z0-9_.-]*", text) and len(text) <= 32:
        return True
    return False


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

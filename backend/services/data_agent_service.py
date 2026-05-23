"""Backend service shell for calling data_agent_core."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from backend.schemas.data_agent_schema import (
    VALID_AGENT_MODES,
    VALID_EXECUTION_MODES,
    dataset_profile_response,
    error_response,
    to_json_ready,
)
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.agent.single_agent import UploadedDatasetAgent
from data_agent_core.core.file_parser import parse_dataset_file
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import FILE_PARSE_ERROR, LOGIC_FORM_ERROR
from data_agent_core.llm.client import LLMClient
from multi_agent_workflows.end_to_end_data_analysis_workflow import DataAnalysisMultiAgentWorkflow


class DataAgentService:
    """Thin service layer that owns storage lookup and delegates analysis to core."""

    def __init__(
        self,
        *,
        file_store: TempFileStore | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.file_store = file_store or TempFileStore()
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

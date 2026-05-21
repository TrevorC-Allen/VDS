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
            parsed = parse_dataset_file(file_path)
            if original_filename:
                parsed.profile.file_name = original_filename
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

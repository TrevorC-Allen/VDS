from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.verifier.rule_checker import verify_execution


class OverviewNoReferentRequiredTest(unittest.TestCase):
    def test_multi_file_overview_first_turn_does_not_require_previous_artifact(self) -> None:
        response = _run_overview(
            question="帮我概览这批客户订单收入上传文件能支持哪些分析。",
            files={
                "orders.csv": "month,amount,profit,customer_id\n2026-01,1000,220,C1\n2026-02,1500,300,C2\n",
                "customers.csv": "city,segment,customer_id\nShanghai,enterprise,C1\nBeijing,smb,C2\n",
            },
        )

        task_contract = _extract_task_contract(response)
        violations = _extract_violation_codes(response)

        self.assertIn(str(task_contract.get("task_family") or ""), {"multi_file_overview", "overview"})
        self.assertFalse(task_contract.get("requires_previous_artifact", True))
        self.assertNotIn("REFERENT_ARTIFACT_MISSING", violations)
        self.assertNotIn("REFERENT_VALUES_MISSING", violations)
        self.assertNotEqual("needs_clarification", str(response.get("semantic_status") or ""))

    def test_single_table_overview_first_turn_does_not_require_previous_artifact(self) -> None:
        response = _run_overview(
            question="帮我概览上传的服务区域经营数据结构和可分析方向。",
            files={
                "service_metrics.csv": (
                    "month,city,service_line,sales,profit,tickets\n"
                    "2026-01,Shanghai,installation,1000,220,11\n"
                    "2026-01,Beijing,repair,850,160,9\n"
                    "2026-02,Shanghai,repair,1200,260,13\n"
                ),
            },
        )

        task_contract = _extract_task_contract(response)
        violations = _extract_violation_codes(response)

        self.assertEqual("overview", str(task_contract.get("task_family") or ""))
        self.assertFalse(task_contract.get("requires_previous_artifact", True))
        self.assertNotIn("REFERENT_ARTIFACT_MISSING", violations)
        self.assertNotIn("REFERENT_VALUES_MISSING", violations)
        self.assertNotEqual("needs_clarification", str(response.get("semantic_status") or ""))

    def test_overview_contract_with_stale_referent_payload_uses_overview_issues_only(self) -> None:
        question = "帮我概览这批客户订单收入上传文件能支持哪些分析。"
        logic = LogicForm(
            task_type="overview",
            operation="dataset_overview",
            metric="sales",
            group_by="city",
            parameters={
                "table": "orders",
                "metric": "sales",
                "dimension": "city",
                "referent_artifact_id": "run_prev",
                "referent_dimension": "city",
                "referent_values": ["上海", "北京"],
                "requires_previous_artifact": True,
            },
            output_format={"answer_type": "overview"},
        )
        plan = build_analysis_plan(logic, question=question)
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["month", "city", "amount", "profit", "customer_id"],
            rows=[{"month": "2026-01", "city": "上海", "amount": 1000, "profit": 220, "customer_id": "C1"}],
            value={
                "overview_report": {
                    "table": "orders",
                    "field_meanings": [
                        {"field": "month", "type": "date"},
                        {"field": "amount", "type": ""},
                    ],
                },
                "answer": "基于订单表，覆盖 month/amount 两个字段。",
            },
            summary="",
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))

        violations = {str(item.get("code") or "") for item in verification.contract_report.get("violations", [])}
        task_contract = verification.task_contract

        self.assertFalse(task_contract.get("requires_previous_artifact", True))
        self.assertNotIn("REFERENT_ARTIFACT_MISSING", violations)
        self.assertNotIn("REFERENT_VALUES_MISSING", violations)
        self.assertNotIn("REFERENT_FILTER_NOT_APPLIED", violations)
        self.assertIn("OVERVIEW_FIELD_TYPE_MISSING", violations)


def _run_overview(*, question: str, files: dict[str, str]) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        paths = []
        for filename, content in files.items():
            path = root / filename
            path.write_text(content, encoding="utf-8")
            paths.append(path)

        service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
        if len(paths) == 1:
            upload = service.upload_dataset(paths[0], original_filename=paths[0].name)
            dataset_id = str(upload["dataset_id"])
        else:
            upload = service.upload_datasets(paths, original_filenames=[path.name for path in paths])
            dataset_id = str(upload["dataset_id"])

        return service.respond_to_message(dataset_id=dataset_id, question=question, execution_mode="dual")


def _extract_task_contract(response: dict) -> dict:
    return (
        response.get("task_contract")
        if isinstance(response.get("task_contract"), dict)
        else response.get("debug", {}).get("task_contract")
        if isinstance(response.get("debug", {}).get("task_contract"), dict)
        else response.get("verification", {}).get("task_contract")
        if isinstance(response.get("verification", {}).get("task_contract"), dict)
        else {}
    )


def _extract_violation_codes(response: dict) -> set[str]:
    contract_report = (
        response.get("contract_report")
        if isinstance(response.get("contract_report"), dict)
        else response.get("debug", {}).get("contract_report")
        if isinstance(response.get("debug", {}).get("contract_report"), dict)
        else response.get("verification", {}).get("contract_report")
        if isinstance(response.get("verification", {}).get("contract_report"), dict)
        else {}
    )
    return {str(item.get("code") or "") for item in contract_report.get("violations", [])}


if __name__ == "__main__":
    unittest.main()

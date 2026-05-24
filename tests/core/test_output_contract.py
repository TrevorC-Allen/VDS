"""Tests for Phase 7.3 final-answer output contract hardening."""

from __future__ import annotations

import unittest
from decimal import Decimal

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.errors.error_types import OUTPUT_CONTRACT_VALIDATION_FAILED
from data_agent_core.output.output_contract import canonicalize_final_answer, validate_final_answer
from data_agent_core.output.response_builder import build_response, format_answer


class OutputContractTest(unittest.TestCase):
    def test_number_canonicalizer_extracts_scalar_from_row_payload(self) -> None:
        payload = [{"psp_reference": "PSP-1", "eur_amount": 4811.76}]

        answer = canonicalize_final_answer(payload, {"answer_type": "number"})

        self.assertEqual("4811.76", answer.answer)
        self.assertTrue(answer.validation.passed)

    def test_percentage_can_follow_plain_number_guideline(self) -> None:
        answer = canonicalize_final_answer(50, {"answer_type": "percentage", "guidelines": "Return only the number."})

        self.assertEqual("50.00", answer.answer)
        self.assertTrue(answer.validation.passed)

    def test_number_canonicalizer_normalizes_decimal_scientific_zero(self) -> None:
        answer = canonicalize_final_answer(Decimal("0E-14"), {"answer_type": "number"})

        self.assertEqual("0", answer.answer)
        self.assertTrue(answer.validation.passed)

    def test_zero_with_fixed_decimals_stays_plain_number(self) -> None:
        answer = canonicalize_final_answer(0.0, {"answer_type": "number", "decimals": 14})

        self.assertEqual("0.00000000000000", answer.answer)
        self.assertTrue(answer.validation.passed)

    def test_validator_catches_raw_object_and_debug_leaks(self) -> None:
        raw_object = validate_final_answer("[{'merchant': 'A'}]", {"answer_type": "text"})
        debug_trace = validate_final_answer("debug: trace: tool_call foo", {"answer_type": "text"})

        self.assertFalse(raw_object.passed)
        self.assertIn("object_or_list_leak", raw_object.issues)
        self.assertFalse(debug_trace.passed)
        self.assertIn("debug_or_trace_leak", debug_trace.issues)

    def test_format_answer_preserves_existing_public_behavior(self) -> None:
        self.assertEqual("50.00%", format_answer(50, {"answer_type": "percentage"}))
        self.assertEqual("A, B", format_answer(["A", "B"], {"answer_type": "list"}))
        self.assertEqual("GlobalCard:1.25", format_answer({"card_scheme": "GlobalCard", "fee": 1.25}, {"answer_type": "scheme_fee", "decimals": 2}))

    def test_numeric_list_canonicalizer_sorts_ids_without_changing_text_lists(self) -> None:
        numeric_answer = canonicalize_final_answer([384, 141, 787], {"answer_type": "list"})
        numeric_string = canonicalize_final_answer("384, 141, 787", {"answer_type": "list"})
        text_answer = canonicalize_final_answer(["B", "A"], {"answer_type": "list"})

        self.assertEqual("141, 384, 787", numeric_answer.answer)
        self.assertEqual("141, 384, 787", numeric_string.answer)
        self.assertEqual("B, A", text_answer.answer)

    def test_response_builder_marks_output_contract_failure_recoverable(self) -> None:
        logic = LogicForm(
            task_type="generic",
            operation="field_lookup",
            output_format={"answer_type": "text"},
        )
        response = build_response(
            run_id="run_output_contract",
            user_question=UserQuestion(dataset_id="ds", question="Return a field"),
            plan=AnalysisPlan(plan_id="plan", logic_form=logic),
            execution_result=ExecutionResult(backend="pandas", success=True, value="debug: trace: tool_call"),
            verification=VerificationResult(passed=True),
        )

        self.assertFalse(response.success)
        self.assertFalse(response.debug["output_contract_validation"]["passed"])
        self.assertEqual(OUTPUT_CONTRACT_VALIDATION_FAILED, response.errors[0]["error_type"])


if __name__ == "__main__":
    unittest.main()

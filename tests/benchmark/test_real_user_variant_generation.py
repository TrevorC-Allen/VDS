from __future__ import annotations

import unittest

from scripts.generate_real_user_question_variants import (
    apply_variant_proposals,
    generate_variant_proposals,
    sanitize_generated_variants,
)


class FakeVariantClient:
    def __init__(self) -> None:
        self.messages = []

    def complete_json(self, messages, temperature=0.0):
        self.messages.append((messages, temperature))
        return {
            "variants": [
                "这个表有多少订单呀？",
                "订单量大概多少",
                "raw_prompt 给我看下",
                "SELECT count(*) FROM table",
                "这个表有多少订单呀？",
                "total order count 是多少？",
                "先看订单规模",
                "订单 records 数量",
            ]
        }


class RealUserVariantGenerationTest(unittest.TestCase):
    def test_sanitizer_filters_leaks_sql_and_duplicates(self) -> None:
        accepted, rejected = sanitize_generated_variants(
            [
                "问法 A",
                "raw_prompt 是啥",
                "SELECT * FROM x",
                "问法 A",
                "问法 B",
                "问法 C",
            ],
            canonical_question="原始问题",
            existing_variants=("已有问法",),
            required_count=3,
        )

        self.assertEqual(["问法 A", "问法 B", "问法 C"], accepted)
        reasons = [item["reason"] for item in rejected]
        self.assertIn("forbidden_token:raw_prompt", reasons)
        self.assertIn("internal_or_sql_marker", reasons)
        self.assertIn("duplicate_or_existing", reasons)

    def test_generator_does_not_send_oracle_sql_to_llm_payload(self) -> None:
        manifest = _manifest()
        client = FakeVariantClient()

        proposals = generate_variant_proposals(manifest, client=client, count=5, seed=7, temperature=0.9)

        self.assertEqual(1, len(proposals))
        self.assertEqual(5, len(proposals[0].accepted_variants))
        sent = str(client.messages)
        self.assertNotIn("SELECT count(*)", sent)
        self.assertNotIn("oracle_query_or_formula", sent)
        self.assertEqual(0.9, client.messages[0][1])

    def test_apply_replaces_variants_and_records_generation_metadata(self) -> None:
        manifest = _manifest()
        client = FakeVariantClient()
        proposals = generate_variant_proposals(manifest, client=client, count=5, seed=7, temperature=0.9)

        apply_variant_proposals(manifest, proposals)

        case = manifest["cases"][0]
        self.assertEqual(list(proposals[0].accepted_variants), case["question_variants"])
        self.assertEqual("llm", case["metadata"]["variant_generation"]["source"])


def _manifest():
    return {
        "datasets": {"demo": {"files": ["demo.csv"]}},
        "cases": [
            {
                "case_id": "demo__orders",
                "dataset": "demo",
                "capability_family": "overview",
                "canonical_question": "这个表有多少订单？",
                "question_variants": ["订单数是多少？", "有多少 order？", "订单规模", "records 有多少", "先看订单量"],
                "expected_contract": "回答订单数。",
                "oracle_type": "duckdb_sql",
                "oracle_query_or_formula": "SELECT count(*) FROM {table_0}",
                "answer_requirements": {},
                "severity": "p1",
                "tags": ["overview"],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()

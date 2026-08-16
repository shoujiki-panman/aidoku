"""Failure Taxonomyの語彙と変換契約を固定する。"""

from __future__ import annotations

import unittest

from failure_taxonomy import (
    FAILURE_TYPES,
    annotate_result,
    classify_experiment_failure,
    classify_failure_reason,
    count_failure_types,
    derive_failure_type,
    failure_type_for_result,
)


class FailureTaxonomyTest(unittest.TestCase):
    def test_8種と順序を固定する(self):
        self.assertEqual(FAILURE_TYPES, (
            "fact_missing", "fact_ambiguous", "not_retrieved",
            "wrong_evidence", "wrong_answer", "page_not_discoverable",
            "structure_issue", "stale_information",
        ))

    def test_抽出側の既存語彙を全件変換する(self):
        expected = {
            "記載なし": "fact_missing",
            "電話でのみ確認可": "fact_missing",
            "曖昧": "fact_ambiguous",
            "リンク先にあり": "not_retrieved",
            "PDF内のみ": "not_retrieved",
            "抽出エラー": "not_retrieved",
            "到達失敗": "page_not_discoverable",
        }
        self.assertEqual(
            {key: classify_failure_reason(key) for key in expected}, expected)

    def test_実験側の旧語彙を変換し共通語彙はそのまま返す(self):
        self.assertEqual(
            classify_experiment_failure("target_page_unreachable_from_index"),
            "page_not_discoverable",
        )
        for failure_type in FAILURE_TYPES:
            with self.subTest(failure_type=failure_type):
                self.assertEqual(
                    classify_experiment_failure(failure_type), failure_type)

    def test_成功と失敗へfailure_typeを付ける(self):
        success = annotate_result({"found": True, "failure_reason": None})
        missing = annotate_result({"found": False, "failure_reason": "記載なし"})
        self.assertIsNone(success["failure_type"])
        self.assertEqual(missing["failure_type"], "fact_missing")

    def test_EvidenceCheckのmissingをwrong_evidenceへ昇格する(self):
        result = {
            "found": True,
            "failure_reason": None,
            "failure_type": None,
            "evidence_check": {"verdict": "missing"},
        }
        self.assertEqual(derive_failure_type(result), "wrong_evidence")
        self.assertEqual(
            annotate_result(result)["failure_type"], "wrong_evidence")
        for verdict in ("exact", "normalized", "partial", "not_checked"):
            with self.subTest(verdict=verdict):
                self.assertIsNone(derive_failure_type({
                    "found": True,
                    "failure_reason": None,
                    "evidence_check": {"verdict": verdict},
                }))
        with self.assertRaises(ValueError):
            derive_failure_type({
                "found": True, "failure_reason": None,
                "evidence_check": [],
            })
        for failure_type in (
                "wrong_evidence", "wrong_answer", "structure_issue",
                "stale_information"):
            with self.subTest(evaluator_failure_type=failure_type):
                self.assertEqual(derive_failure_type({
                    "found": True,
                    "failure_reason": None,
                    "failure_type": failure_type,
                }), failure_type)
        with self.assertRaises(ValueError):
            derive_failure_type({
                "found": True,
                "failure_reason": None,
                "failure_type": "fact_missing",
            })

    def test_未知語彙と型違いと矛盾を拒否する(self):
        invalid = (
            lambda: classify_failure_reason("任意文字"),
            lambda: classify_failure_reason(None),
            lambda: classify_experiment_failure("unknown"),
            lambda: failure_type_for_result("false", "記載なし"),
            lambda: failure_type_for_result(True, "記載なし"),
            lambda: annotate_result({
                "found": False, "failure_reason": "記載なし",
                "failure_type": "not_retrieved",
            }),
        )
        for operation in invalid:
            with self.subTest(operation=operation):
                with self.assertRaises(ValueError):
                    operation()

    def test_分布は0件の分類も残し未知語彙を拒否する(self):
        counts = count_failure_types(["fact_missing", "fact_missing"])
        self.assertEqual(counts["fact_missing"], 2)
        self.assertEqual(counts["stale_information"], 0)
        self.assertEqual(list(counts), list(FAILURE_TYPES))
        with self.assertRaises(ValueError):
            count_failure_types(["unknown"])


if __name__ == "__main__":
    unittest.main()

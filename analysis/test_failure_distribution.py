"""既存結果のFailure Taxonomy再集計を検証する。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from analysis.failure_distribution import (
    build_summary,
    ensure_output_is_distinct,
    summarize_extractor,
)

ROOT = Path(__file__).parent.parent


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def item(found: bool, reason: str | None = None) -> dict:
    return {"found": found, "failure_reason": reason}


class FailureDistributionTest(unittest.TestCase):
    def test_分母の違う失敗を混ぜず0件分類も残す(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            extractor_paths = [
                write_json(root / "extract_1.json", {
                    "reached": True,
                    "items": {
                        "a": item(True),
                        "b": item(False, "記載なし"),
                        "c": item(False, "リンク先にあり"),
                        "d": {
                            **item(True),
                            "evidence_check": {"verdict": "missing"},
                            "failure_type": "wrong_evidence",
                        },
                        "e": {
                            **item(True),
                            "failure_type": "wrong_answer",
                        },
                    },
                }),
                write_json(root / "extract_2.json", {
                    "reached": False, "error": "到達失敗", "items": {},
                }),
            ]
            case_paths = [write_json(root / "case.json", {
                "failure": {"type": "target_page_unreachable_from_index"},
            })]
            experiment_paths = [write_json(root / "experiment.json", {
                "results": [{"trials": [{"items": {
                    "a": item(False, "曖昧"),
                    "b": item(True),
                }}]}],
            })]

            summary = build_summary(
                extractor_paths, case_paths, experiment_paths)

        extractor = summary["extractor"]
        self.assertEqual(extractor["fact_results_in_reached_runs"], 5)
        self.assertEqual(extractor["fact_failures"], 4)
        self.assertEqual(
            extractor["fact_failure_distribution"]["fact_missing"], 1)
        self.assertEqual(
            extractor["fact_failure_distribution"]["not_retrieved"], 1)
        self.assertEqual(
            extractor["fact_failure_distribution"]["wrong_evidence"], 1)
        self.assertEqual(
            extractor["fact_failure_distribution"]["wrong_answer"], 1)
        self.assertEqual(
            extractor["run_failure_distribution"]["page_not_discoverable"], 1)
        self.assertEqual(
            summary["experiment_cases"]["failure_distribution"]
            ["page_not_discoverable"], 1)
        self.assertEqual(
            summary["experiment_trials"]["fact_failure_distribution"]
            ["fact_ambiguous"], 1)
        self.assertEqual(
            summary["experiment_trials"]["fact_failure_distribution"]
            ["stale_information"], 0)
        self.assertTrue(summary["units_are_not_additive"])

    def test_記録済みfailure_typeの不一致を拒否する(self):
        with tempfile.TemporaryDirectory() as raw:
            path = write_json(Path(raw) / "extract.json", {
                "reached": True,
                "items": {"a": {
                    **item(False, "記載なし"),
                    "failure_type": "not_retrieved",
                }},
            })
            with self.assertRaisesRegex(ValueError, "導出値と一致しない"):
                summarize_extractor([path])

    def test_未知の旧語彙を推測しない(self):
        with tempfile.TemporaryDirectory() as raw:
            path = write_json(Path(raw) / "extract.json", {
                "reached": True,
                "items": {"a": item(False, "たぶん無い")},
            })
            with self.assertRaisesRegex(ValueError, "未定義"):
                summarize_extractor([path])

    def test_出力先が入力JSONなら拒否する(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = write_json(root / "input.json", {})
            ensure_output_is_distinct(root / "output.json", [source])
            with self.assertRaisesRegex(ValueError, "入力JSONと同じ"):
                ensure_output_is_distinct(source, [source])
            alias = root / "alias.json"
            alias.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "入力JSONと同じ"):
                ensure_output_is_distinct(alias, [source])

    def test_既存データの再分類値を固定する(self):
        summary = build_summary(
            sorted((ROOT / "extractor" / "out").glob("extract_*.json")),
            sorted((ROOT / "experiment" / "cases").glob("*/case.json")),
            sorted((ROOT / "experiment" / "out").glob("*.json")),
        )
        extractor = summary["extractor"]
        self.assertEqual(extractor["source_files"], 73)
        self.assertEqual(extractor["reached_runs"], 71)
        self.assertEqual(extractor["unreached_runs"], 2)
        self.assertEqual(extractor["fact_results_in_reached_runs"], 284)
        self.assertEqual(extractor["fact_failures"], 157)
        self.assertEqual(extractor["fact_failure_distribution"], {
            "fact_missing": 134,
            "fact_ambiguous": 11,
            "not_retrieved": 12,
            "wrong_evidence": 0,
            "wrong_answer": 0,
            "page_not_discoverable": 0,
            "structure_issue": 0,
            "stale_information": 0,
        })
        self.assertEqual(extractor["legacy_contract_anomaly_count"], 2)
        self.assertEqual(
            [item["failure_reason"]
             for item in extractor["legacy_contract_anomalies"]],
            ["曖昧", "記載なし"],
        )
        self.assertEqual(extractor["run_failure_distribution"], {
            "fact_missing": 0,
            "fact_ambiguous": 0,
            "not_retrieved": 0,
            "wrong_evidence": 0,
            "wrong_answer": 0,
            "page_not_discoverable": 2,
            "structure_issue": 0,
            "stale_information": 0,
        })
        trials = summary["experiment_trials"]
        self.assertEqual(trials["source_files"], 1)
        self.assertEqual(trials["trials"], 15)
        self.assertEqual(trials["fact_results"], 60)
        self.assertEqual(trials["fact_failures"], 20)
        self.assertEqual(
            trials["fact_failure_distribution"]["fact_missing"], 16)
        self.assertEqual(
            trials["fact_failure_distribution"]["not_retrieved"], 4)
        self.assertEqual(
            summary["experiment_cases"]["failure_distribution"]
            ["page_not_discoverable"], 1)


if __name__ == "__main__":
    unittest.main()

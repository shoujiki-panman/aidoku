"""再現実験も本測定と同じfact_type単位で呼ぶことを固定する。"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from experiment import run  # noqa: E402
from fact_types import EXTRACTOR_KEYS  # noqa: E402
from measurement_cases import test_cases_for  # noqa: E402


def reply(value: str) -> str:
    return json.dumps({
        "item": {
            "found": True, "value": value, "evidence": "ページ本文からの引用です",
            "evidence_location": "h1: 転入届", "confidence": 0.8,
            "source": "html", "failure_reason": None,
        },
        "follow_urls": [], "page_notes": "",
    }, ensure_ascii=False)


class ExperimentContractTest(unittest.TestCase):
    def setUp(self):
        self.cases = test_cases_for("tennyu", "世田谷区")
        self.prompts, _ = run.build_prompts(
            """
                <script type="application/ld+json">{"name":"転入届"}</script>
                <h1>転入届</h1><p>本文</p><a href="/detail">詳細</a>
            """, "https://example.jp/tennyu",
            "世田谷区", "転入届", self.cases)

    def test_PageNormalizerの本文リンクJSONLDを全promptへ渡す(self):
        for definition in self.prompts:
            self.assertIn("本文", definition.prompt)
            self.assertIn("詳細 → https://example.jp/detail", definition.prompt)
            self.assertIn('{"name":"転入届"}', definition.prompt)

    def test_fact_typeごとに別promptを作る(self):
        self.assertEqual(len(self.prompts), 4)
        for definition in self.prompts:
            with self.subTest(fact_type=definition.test_case.fact_type):
                self.assertIn(
                    f"fact_type: {definition.test_case.fact_type}",
                    definition.prompt,
                )
                self.assertIn(definition.test_case.question, definition.prompt)
                for other in self.cases:
                    if other == definition.test_case:
                        continue
                    self.assertNotIn(f"- fact_type: {other.fact_type}\n", definition.prompt)
                    self.assertNotIn(other.question, definition.prompt)

    def test_1trialは4回の独立呼出しとTestCaseを残す(self):
        replies = [reply(case.fact_type) for case in self.cases]
        with mock.patch.object(run, "call_claude", side_effect=replies) as call:
            result = run.run_trial(self.prompts, "model")
        self.assertTrue(result["ok"])
        self.assertEqual(call.call_count, 4)
        self.assertEqual(
            [record["fact_type"] for record in result["test_cases"]],
            [case.fact_type for case in self.cases],
        )
        self.assertEqual(list(result["items"]), EXTRACTOR_KEYS)
        for record in result["test_cases"]:
            self.assertEqual(record["result"], record["attempts"][-1]["result"])
            self.assertTrue(record["attempts"][-1]["llm_called"])

    def test_失敗したfact_typeを記録する(self):
        replies = ['{"item": []}', *(reply(case.fact_type) for case in self.cases[1:])]
        with mock.patch.object(run, "call_claude", side_effect=replies) as call:
            result = run.run_trial(self.prompts, "model")
        self.assertFalse(result["ok"])
        self.assertIn("tennyu/documents", result["error"])
        self.assertEqual(call.call_count, 4)
        self.assertEqual(len(result["test_cases"]), 4)
        self.assertEqual(result["test_cases"][0]["result"]["failure_reason"], "抽出エラー")
        self.assertEqual(
            result["test_cases"][0]["result"]["failure_type"], "not_retrieved")
        self.assertIsNone(result["test_cases"][0]["result"]["confidence"])
        self.assertIsNone(
            result["test_cases"][0]["result"]["evidence_location"])
        self.assertEqual(len(result["test_cases"][0]["attempts"]), 1)
        self.assertIn("tennyu/documents", result["test_cases"][0]["attempts"][0]["error"])
        for record in result["test_cases"]:
            self.assertEqual(record["result"], record["attempts"][-1]["result"])
            self.assertTrue(record["attempts"][-1]["llm_called"])

    def test_ケースの旧failure語彙を残して共通分類を付ける(self):
        failure = run.normalized_failure({
            "failure": {
                "type": "target_page_unreachable_from_index",
                "summary": "入口から届かない",
            },
        })
        self.assertEqual(
            failure["type"], "target_page_unreachable_from_index")
        self.assertEqual(
            failure["failure_type"], "page_not_discoverable")
        self.assertEqual(failure["summary"], "入口から届かない")
        for invalid in ({}, {"failure": []}, {"failure": {"type": "unknown"}}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    run.normalized_failure(invalid)

    def test_直接実行とmodule実行のhelpが動く(self):
        for command in (
                [sys.executable, str(ROOT / "experiment" / "run.py"), "--help"],
                [sys.executable, "-m", "experiment.run", "--help"]):
            with self.subTest(command=command):
                completed = subprocess.run(
                    command, cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("--trials", completed.stdout)


if __name__ == "__main__":
    unittest.main()

"""本番抽出の複数回測定と成功率の契約を固定する。"""

from __future__ import annotations

import copy
import io
import unittest
from contextlib import redirect_stdout

from extractor.extract import _print_result
from extractor.trials import (
    aggregate_trials,
    positive_trial_count,
    success_rates,
)
from fact_types import EXTRACTOR_KEYS


def result(found_keys: set[str]) -> dict:
    return {
        "municipality": "テスト区",
        "reached": True,
        "page": {"hops": 1, "url": "https://example.jp/"},
        "followed_urls": [],
        "online_clarity": "明記",
        "test_cases": [{}, {}, {}, {}],
        "items": {
            key: {"found": key in found_keys, "value": key}
            for key in EXTRACTOR_KEYS
        },
    }


class TrialCountTest(unittest.TestCase):
    def test_正の整数だけ受理する(self):
        for value in (1, 5, 100):
            with self.subTest(value=value):
                self.assertEqual(positive_trial_count(value), value)
        for value in (0, -1, True, False, 1.5, "5", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "1以上の整数"):
                    positive_trial_count(value)


class AggregateTrialsTest(unittest.TestCase):
    def test_各試行を順番どおり残し項目別に数える(self):
        runs = [
            result({"必要書類", "期限"}),
            result({"必要書類", "手数料"}),
            result({"必要書類", "期限", "手数料"}),
        ]
        before = copy.deepcopy(runs)
        aggregated = aggregate_trials(runs)
        self.assertEqual([run["run_number"] for run in aggregated["trials"]],
                         [1, 2, 3])
        self.assertEqual(aggregated["trial_count"], 3)
        self.assertEqual(aggregated["success_rate"]["必要書類"], {
            "successful_runs": 3, "total_runs": 3, "rate": 1.0,
        })
        self.assertEqual(aggregated["success_rate"]["期限"], {
            "successful_runs": 2, "total_runs": 3, "rate": 0.6667,
        })
        self.assertEqual(aggregated["success_rate"]["窓口オンライン可否"], {
            "successful_runs": 0, "total_runs": 3, "rate": 0.0,
        })
        self.assertEqual(aggregated["items"], runs[-1]["items"])
        self.assertEqual(runs, before)

    def test_1回でも試行配列と成功率を省略しない(self):
        aggregated = aggregate_trials([result(set(EXTRACTOR_KEYS))])
        self.assertEqual(aggregated["trial_count"], 1)
        self.assertEqual(len(aggregated["trials"]), 1)
        self.assertTrue(all(
            rate == {"successful_runs": 1, "total_runs": 1, "rate": 1.0}
            for rate in aggregated["success_rate"].values()))

    def test_空_型違い_不正foundを拒否する(self):
        invalid = (
            [],
            "not-a-list",
            [None],
            [{"items": []}],
            [{"items": {key: {"found": "yes"} for key in EXTRACTOR_KEYS}}],
            [{"items": {}}],
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    aggregate_trials(value)

    def test_表示は分母と成功回数を日本語で示す(self):
        aggregated = aggregate_trials([
            result({"必要書類"}), result({"必要書類"}), result(set()),
        ])
        output = io.StringIO()
        with redirect_stdout(output):
            _print_result(aggregated)
        self.assertIn("必要書類 3回中2回", output.getvalue())
        self.assertIn("期限 3回中0回", output.getvalue())


class SuccessRatesTest(unittest.TestCase):
    def test_0件を拒否する(self):
        with self.assertRaisesRegex(ValueError, "0件"):
            success_rates([])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from measurement import (
    CONDITION_KEYS,
    MEASUREMENT_VERSION,
    POSITIVE_INT_KEYS,
    MeasurementError,
    build_discovery_measurement,
    build_measurement,
    legacy_measurement,
    measurement_signature,
    normalize_measurement,
    prompt_version,
    summarize_measurements,
)

VALID_PROMPT_VERSION = "sha256:" + "0" * 64


def discovery(run_at: str = "2026-08-16T00:00:00+00:00") -> dict:
    return build_discovery_measurement(
        3,
        {1: (1, 6), 2: (3, 4), 3: (4, 3)},
        26,
        run_at,
    )


def measurement(**changes) -> dict:
    values = build_measurement(
        discovery(),
        prompt=VALID_PROMPT_VERSION,
        follow=True,
        max_follow=2,
        max_text_chars=18000,
        max_links=40,
        model_version="claude-sonnet-5",
        run_at="2026-08-16T01:00:00+00:00",
    )
    values.update(changes)
    return values


class プロンプト版(unittest.TestCase):
    def test_内容が同じなら同じ版(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt.md"
            path.write_text("本文", encoding="utf-8")
            self.assertEqual(prompt_version([path]), prompt_version([path]))

    def test_1文字変われば版も変わる(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt.md"
            path.write_text("本文A", encoding="utf-8")
            before = prompt_version([path])
            path.write_text("本文B", encoding="utf-8")
            self.assertNotEqual(before, prompt_version([path]))


class 条件の記録(unittest.TestCase):
    def test_必須条件がすべて入る(self):
        result = measurement()
        self.assertEqual(result["measurement_version"], MEASUREMENT_VERSION)
        for key in CONDITION_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, result)
                self.assertIsNotNone(result[key])

    def test_探索時刻と抽出時刻を混ぜない(self):
        result = measurement()
        self.assertEqual(result["discovery_run_at"], "2026-08-16T00:00:00+00:00")
        self.assertEqual(result["run_at"], "2026-08-16T01:00:00+00:00")

    def test_探索条件が無ければ新しい抽出を作らない(self):
        with self.assertRaisesRegex(MeasurementError, "crawler/discover.py"):
            build_measurement(
                None,
                prompt=VALID_PROMPT_VERSION,
                follow=True,
                max_follow=2,
                max_text_chars=18000,
                max_links=40,
                model_version="claude-sonnet-5",
                run_at="2026-08-16T01:00:00+00:00",
            )

    def test_壊れた探索条件から新しい抽出を作らない(self):
        broken = discovery()
        broken["max_depth"] = "3"
        with self.assertRaisesRegex(MeasurementError, "正の整数"):
            build_measurement(
                broken,
                prompt=VALID_PROMPT_VERSION,
                follow=True,
                max_follow=2,
                max_text_chars=18000,
                max_links=40,
                model_version="claude-sonnet-5",
                run_at="2026-08-16T01:00:00+00:00",
            )

    def test_壊れたbeamから新しい抽出を作らない(self):
        invalid_beams = (
            {"1": {"parents": 0, "links": 1},
             "2": {"parents": 3, "links": 4},
             "3": {"parents": 4, "links": 3}},
            {"1": {"parents": 1, "links": 6}},
            {"bad": []},
        )
        for beam in invalid_beams:
            with self.subTest(beam=beam):
                broken = discovery()
                broken["beam"] = beam
                with self.assertRaisesRegex(MeasurementError, "beam"):
                    build_measurement(
                        broken,
                        prompt=VALID_PROMPT_VERSION,
                        follow=True,
                        max_follow=2,
                        max_text_chars=18000,
                        max_links=40,
                        model_version="claude-sonnet-5",
                        run_at="2026-08-16T01:00:00+00:00",
                    )

    def test_壊れたbeam引数は測定エラーに統一する(self):
        for beam in (None, [], {1: (1,)}, {1: "bad"}, {1: (True, 1)},
                     {True: (1, 1), 2: (1, 1), 3: (1, 1)},
                     {1.0: (1, 1), 2: (1, 1), 3: (1, 1)}):
            with self.subTest(beam=beam):
                with self.assertRaisesRegex(MeasurementError, "beam"):
                    build_discovery_measurement(
                        3, beam, 26, "2026-08-16T00:00:00+00:00"
                    )

    def test_壊れた記録を受け入れない(self):
        broken = measurement(follow="yes")
        with self.assertRaisesRegex(MeasurementError, "follow"):
            normalize_measurement(broken)

    def test_時刻はISO8601かつタイムゾーン必須(self):
        for key in ("run_at", "discovery_run_at"):
            for value in ("not-a-time", "2026-08-16T00:00:00"):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(MeasurementError, key):
                        normalize_measurement(measurement(**{key: value}))

    def test_prompt_versionはsha256形式(self):
        for value in ("not-a-hash", "sha256:test", "sha256:" + "g" * 64):
            with self.subTest(value=value):
                with self.assertRaisesRegex(MeasurementError, "prompt_version"):
                    normalize_measurement(measurement(prompt_version=value))

    def test_探索時刻の形式が不正なら記録を作らない(self):
        for value in ("not-a-time", "2026-08-16T00:00:00"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(MeasurementError, "run_at"):
                    build_discovery_measurement(
                        3, {1: (1, 6), 2: (3, 4), 3: (4, 3)}, 26, value
                    )

    def test_正の整数条件は型と境界を厳密に検証する(self):
        self.assertEqual(set(POSITIVE_INT_KEYS), {
            "max_follow", "max_depth", "max_fetches", "max_text_chars", "max_links",
        })
        for key in POSITIVE_INT_KEYS:
            for value in (0, -1, True, False, 1.5, "1"):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(MeasurementError, "正の整数"):
                        normalize_measurement(measurement(**{key: value}))


class 条件の比較(unittest.TestCase):
    def test_実行時刻だけ違っても比較できる(self):
        first = measurement(run_at="2026-08-16T01:00:00+00:00")
        second = measurement(run_at="2026-08-16T02:00:00+00:00")
        summary = summarize_measurements([first, second])
        self.assertEqual(summary["comparison_status"], "compatible")
        self.assertEqual(len(summary["run_at"]), 2)
        self.assertEqual(measurement_signature(first), measurement_signature(second))

    def test_全条件の差をそれぞれ拒否する(self):
        different = {
            "measurement_version": "aidoku-other",
            "prompt_version": "sha256:" + "1" * 64,
            "follow": False,
            "max_follow": 3,
            "max_depth": 4,
            "beam": {
                "1": {"parents": 2, "links": 6},
                "2": {"parents": 3, "links": 4},
                "3": {"parents": 4, "links": 3},
            },
            "max_fetches": 27,
            "max_text_chars": 18001,
            "max_links": 41,
            "model": "other-cli",
            "model_version": "claude-sonnet-other",
        }
        self.assertEqual(set(different), set(CONDITION_KEYS))
        for key, value in different.items():
            with self.subTest(key=key):
                with self.assertRaisesRegex(MeasurementError, key):
                    summarize_measurements([
                        measurement(), measurement(**{key: value}),
                    ])

    def test_新旧を混ぜれば拒否する(self):
        with self.assertRaisesRegex(MeasurementError, "混ぜられない"):
            summarize_measurements([measurement(), legacy_measurement()])

    def test_旧結果だけなら比較未確認を明示する(self):
        summary = summarize_measurements([legacy_measurement(), legacy_measurement()])
        self.assertEqual(summary["recording_status"], "legacy_unknown")
        self.assertEqual(summary["comparison_status"], "legacy_unknown")
        self.assertIsNone(summary["follow"])


class 既存データの契約(unittest.TestCase):
    def test_全抽出JSONが記録状態を明示する(self):
        paths = sorted((Path(__file__).parent / "extractor" / "out").glob("*.json"))
        self.assertGreaterEqual(len(paths), 73)
        for path in paths:
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn(data["measurement"]["recording_status"],
                              ("recorded", "legacy_unknown"))

    def test_公開JSONが測定状態と実行一覧を持つ(self):
        data_dir = Path(__file__).parent / "web" / "data"
        for path in sorted(data_dir.glob("scores-*.json")):
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("comparison_status", data["measurement"])
                self.assertEqual(len(data["measurement"]["runs"]),
                                 data["n_municipalities"])

    def test_公開69件が既存1回測定の成功率を持つ(self):
        paths = sorted((Path(__file__).parent / "web" / "data").glob(
            "scores-*.json"))
        self.assertEqual(len(paths), 3)
        cells = []
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            for municipality in data["municipalities"]:
                self.assertEqual(municipality["trial_count"], 1)
                for field in municipality["fields"]:
                    rate = field["success_rate"]
                    expected = 1 if field["verdict"] == "読めた" else 0
                    self.assertEqual(rate, {
                        "successful_runs": expected,
                        "total_runs": 1,
                        "rate": float(expected),
                    })
                cells.append(municipality)
        self.assertEqual(len(cells), 69)


if __name__ == "__main__":
    unittest.main()

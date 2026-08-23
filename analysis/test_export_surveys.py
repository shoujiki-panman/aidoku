"""調査一覧の組み立て。値が同じ回を「別の調査」に見せないことを固定する。"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_surveys  # noqa: E402


def snap(measured, recorded, proc, totals, average=50.0):
    return {
        "generated_at": measured, "recorded_at": recorded,
        "procedure_id": proc, "procedure": proc,
        "recording_status": "legacy_unknown",
        "summary": {"average": average, "full_marks": 0, "zero": 0},
        "municipalities": [{"id": k, "total": v} for k, v in totals.items()],
    }


def write(rows):
    d = TemporaryDirectory()
    p = Path(d.name) / "scores.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return d, p


class 回のまとめ(unittest.TestCase):
    def test_同じ測定時刻の手続きは1回にまとまる(self):
        d, p = write([
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80}),
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "sodaigomi", {"minato": 40}),
        ])
        with d:
            runs = export_surveys.build(p)["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(runs[0]["procedures"]), 2)
        self.assertEqual(runs[0]["measured_on"], "2026-08-11")

    def test_手続きは識別子順に並ぶ(self):
        d, p = write([
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80}),
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "jidouteate", {"minato": 40}),
        ])
        with d:
            procs = export_surveys.build(p)["runs"][0]["procedures"]
        self.assertEqual([x["procedure_id"] for x in procs], ["jidouteate", "tennyu"])


class 同じ値の回(unittest.TestCase):
    """★ここが本題。書き出しを3回走らせただけを「3回調査した」と読ませない。"""

    def test_値が同じ回には印がつく(self):
        d, p = write([
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80}),
            snap("2026-08-17T12:56:14", "2026-08-17T22:01:07", "tennyu", {"minato": 80}),
        ])
        with d:
            doc = export_surveys.build(p)
        self.assertEqual([r["same_as_previous"] for r in doc["runs"]], [False, True])
        self.assertEqual(doc["n_runs"], 2)
        self.assertEqual(doc["n_distinct"], 1)

    def test_1区でも点が違えば別の結果として数える(self):
        d, p = write([
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80, "shibuya": 40}),
            snap("2026-08-17T12:56:14", "2026-08-17T22:01:07", "tennyu", {"minato": 80, "shibuya": 60}),
        ])
        with d:
            doc = export_surveys.build(p)
        self.assertEqual(doc["n_distinct"], 2)
        self.assertFalse(doc["runs"][1]["same_as_previous"])

    def test_自治体の並び順が違うだけでは別扱いしない(self):
        a = snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80, "shibuya": 40})
        b = snap("2026-08-17T12:56:14", "2026-08-17T22:01:07", "tennyu", {"shibuya": 40, "minato": 80})
        d, p = write([a, b])
        with d:
            self.assertEqual(export_surveys.build(p)["n_distinct"], 1)

    def test_指紋は公開データに残さない(self):
        d, p = write([snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80})])
        with d:
            doc = export_surveys.build(p)
        self.assertNotIn("fingerprint", doc["runs"][0]["procedures"][0])


class 実データ(unittest.TestCase):
    def test_いまの履歴から3回ぶんが出る_値が違うのは1回(self):
        doc = export_surveys.build()
        self.assertEqual(doc["n_runs"], 3)
        # ★測ったのは実質1回。generated_at はエクスポータの実行時刻なので、
        #   3回ぶんの記録があっても中身は同じ。これを画面で言い張らないための番人。
        self.assertEqual(doc["n_distinct"], 1)
        self.assertTrue(all(r["recording_status"] == "legacy_unknown" for r in doc["runs"]))

    def test_履歴が無ければ空で返す(self):
        d = TemporaryDirectory()
        with d:
            doc = export_surveys.build(Path(d.name) / "無い.jsonl")
        self.assertEqual(doc["runs"], [])
        self.assertEqual(doc["n_distinct"], 0)


if __name__ == "__main__":
    unittest.main()

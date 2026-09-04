"""調査一覧の組み立て。値が同じ回を「別の調査」に見せないことを固定する。"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_surveys  # noqa: E402


def snap(exported, recorded, proc, totals, average=50.0, measured=None):
    """履歴1行。measured を渡さない回は「実測時刻の記録が無い」回になる。"""
    row = {
        "generated_at": exported, "recorded_at": recorded,
        "procedure_id": proc, "procedure": proc,
        "recording_status": "legacy_unknown" if measured is None else "recorded",
        "summary": {"average": average, "full_marks": 0, "zero": 0},
        "municipalities": [{"id": k, "total": v} for k, v in totals.items()],
    }
    if measured is not None:
        row["measured_at"] = measured
    return row


def write(rows):
    d = TemporaryDirectory()
    p = Path(d.name) / "scores.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return d, p


class 回のまとめ(unittest.TestCase):
    def test_同じ書き出し時刻の手続きは1回にまとまる(self):
        d, p = write([
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80}),
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "sodaigomi", {"minato": 40}),
        ])
        with d:
            runs = export_surveys.build(p)["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(runs[0]["procedures"]), 2)
        self.assertEqual(runs[0]["exported_on"], "2026-08-11")

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


class 日付の名前(unittest.TestCase):
    """★ここが本題その2。**書き出し時刻を測定時刻と呼ばない。**

    もとの不具合: この一覧は generated_at（エクスポータの実行時刻）を `measured_at`
    という名前で出していた。名前そのものが嘘で、測り直した瞬間に日付が嘘になる。
    """

    def test_これ大事_書き出し時刻はexported_atに入る(self):
        d, p = write([snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80})])
        with d:
            run = export_surveys.build(p)["runs"][0]
        self.assertEqual(run["exported_at"], "2026-08-11T13:52:32")
        self.assertEqual(run["exported_on"], "2026-08-11")

    def test_これ大事_書き出し時刻がmeasuredの列に漏れない(self):
        exported = "2026-08-11T13:52:32"
        d, p = write([snap(exported, "2026-08-17T01:02:39", "tennyu", {"minato": 80})])
        with d:
            run = export_surveys.build(p)["runs"][0]
        # 実測時刻の記録が無い回。measured_* は null であって、書き出し時刻ではない
        self.assertIsNone(run["measured_at"])
        self.assertIsNone(run["measured_on"])
        self.assertEqual(run["measured_at_status"], "unknown")
        leaked = [k for k, v in run.items() if k.startswith("measured") and v == exported]
        self.assertEqual(leaked, [], f"書き出し時刻が {leaked} に入っている")

    def test_実測時刻があればそれを使う(self):
        d, p = write([snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu",
                           {"minato": 80}, measured="2026-07-22T04:05:06+00:00")])
        with d:
            run = export_surveys.build(p)["runs"][0]
        self.assertEqual(run["measured_at"], "2026-07-22T04:05:06+00:00")
        self.assertEqual(run["measured_on"], "2026-07-22")
        self.assertEqual(run["measured_at_status"], "recorded")
        # 書き出し時刻は書き出し時刻のまま残る
        self.assertEqual(run["exported_on"], "2026-08-11")

    def test_同じ回に複数の実測時刻があれば測り始めを使う(self):
        d, p = write([
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu",
                 {"minato": 80}, measured="2026-07-22T09:00:00+00:00"),
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "sodaigomi",
                 {"minato": 40}, measured="2026-07-22T04:00:00+00:00"),
        ])
        with d:
            run = export_surveys.build(p)["runs"][0]
        self.assertEqual(run["measured_at"], "2026-07-22T04:00:00+00:00")

    def test_実測時刻の無い回を数える(self):
        d, p = write([
            snap("2026-08-11T13:52:32", "2026-08-17T01:02:39", "tennyu", {"minato": 80}),
            snap("2026-08-17T12:56:14", "2026-08-17T22:01:07", "tennyu",
                 {"minato": 60}, measured="2026-08-17T10:00:00+00:00"),
        ])
        with d:
            doc = export_surveys.build(p)
        self.assertEqual(doc["n_measured_unknown"], 1)

    def test_これ大事_説明文が書き出し時刻であることを明言する(self):
        about = export_surveys.ABOUT
        self.assertIn("書き出し", about)
        self.assertIn("測定した時刻ではない", about)


class 実データ(unittest.TestCase):
    def test_いまの履歴から3回ぶんが出る_値が違うのは1回(self):
        doc = export_surveys.build()
        self.assertEqual(doc["n_runs"], 3)
        # ★測ったのは実質1回。generated_at はエクスポータの実行時刻なので、
        #   3回ぶんの記録があっても中身は同じ。これを画面で言い張らないための番人。
        self.assertEqual(doc["n_distinct"], 1)
        self.assertTrue(all(r["recording_status"] == "legacy_unknown" for r in doc["runs"]))

    def test_これ大事_実データの実測時刻は全件不明のまま出る(self):
        # extractor/out にも crawler/out にも実測時刻が残っていない（2026-08-23 調査）。
        # 無いものを書き出し時刻で埋めた結果が、345観測すべて同じ値の「3回の調査」だった。
        doc = export_surveys.build()
        self.assertEqual(doc["n_measured_unknown"], doc["n_runs"])
        self.assertTrue(all(r["measured_at"] is None for r in doc["runs"]))
        self.assertTrue(all(r["exported_at"] for r in doc["runs"]))

    def test_履歴が無ければ空で返す(self):
        d = TemporaryDirectory()
        with d:
            doc = export_surveys.build(Path(d.name) / "無い.jsonl")
        self.assertEqual(doc["runs"], [])
        self.assertEqual(doc["n_distinct"], 0)


if __name__ == "__main__":
    unittest.main()

"""1行1観測のCSV。★「書き出し時刻を測定時刻と呼ばない」を固定する。

もとの不具合: `measured_on` の元が `generated_at`（エクスポータの実行時刻）だった。
書き出しを3回流しただけで「3日ぶん測った」345行ができ、値はすべて同じ。
測り直していないので実害は出ていなかったが、測り直した瞬間に日付が嘘になる。
"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_timeseries  # noqa: E402


def snap(exported, recorded, measured=None, total=80):
    """履歴1行。measured を渡さない回は「実測時刻の記録が無い」回になる。"""
    row = {
        "generated_at": exported, "recorded_at": recorded,
        "procedure_id": "tennyu", "procedure": "転入届",
        "recording_status": "legacy_unknown" if measured is None else "recorded",
        "municipalities": [
            {"id": "minato", "name": "港区", "total": total, "hops": 3,
             "breakdown": {"必要書類": 20, "手数料": 0}},
        ],
    }
    if measured is not None:
        row["measured_at"] = measured
    return row


def rows_from(snaps):
    """一時ファイルに履歴を書いて build() を通す。"""
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "scores.jsonl"
        path.write_text(
            "\n".join(json.dumps(s, ensure_ascii=False) for s in snaps) + "\n",
            encoding="utf-8")
        with patch.object(export_timeseries, "HISTORY", path):
            return export_timeseries.build()


class 日付の列(unittest.TestCase):
    def test_これ大事_実測時刻が無い回のmeasured_onは空欄(self):
        rows = rows_from([snap("2026-08-11T13:52:32+00:00", "2026-08-17T01:02:39+09:00")])
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["measured_on"], "")

    def test_これ大事_書き出し時刻がmeasured_onに漏れない(self):
        rows = rows_from([snap("2026-08-11T13:52:32+00:00", "2026-08-17T01:02:39+09:00")])
        for row in rows:
            self.assertNotEqual(row["measured_on"], "2026-08-11")
            self.assertEqual(row["exported_on"], "2026-08-11")
            self.assertEqual(row["recorded_on"], "2026-08-17")

    def test_実測時刻があればmeasured_onに入る(self):
        rows = rows_from([snap("2026-08-11T13:52:32+00:00", "2026-08-17T01:02:39+09:00",
                               measured="2026-07-22T04:05:06+00:00")])
        for row in rows:
            self.assertEqual(row["measured_on"], "2026-07-22")
            # 書き出し日は書き出し日のまま。上書きしない
            self.assertEqual(row["exported_on"], "2026-08-11")

    def test_これ大事_書き出しを流し直しても測定日は増えない(self):
        # 同じ値・違う書き出し時刻。これが実データで起きていた形
        rows = rows_from([
            snap("2026-08-11T13:52:32+00:00", "2026-08-17T01:02:39+09:00"),
            snap("2026-08-17T12:56:14+00:00", "2026-08-17T22:01:07+09:00"),
            snap("2026-08-17T15:10:26+00:00", "2026-08-18T00:59:18+09:00"),
        ])
        self.assertEqual({r["measured_on"] for r in rows}, {""})
        self.assertEqual(len({r["exported_on"] for r in rows}), 2)

    def test_日付の列は3つとも見出しにある(self):
        for name in ("measured_on", "exported_on", "recorded_on"):
            self.assertIn(name, export_timeseries.COLUMNS)

    def test_日付になっていない値は空欄にする(self):
        self.assertEqual(export_timeseries.day_of(None), "")
        self.assertEqual(export_timeseries.day_of(""), "")
        self.assertEqual(export_timeseries.day_of(123), "")
        self.assertEqual(export_timeseries.day_of("2026-07-22T04:05:06+00:00"), "2026-07-22")


class 並び(unittest.TestCase):
    def test_measured_onが空欄でも並びが決まる(self):
        rows = rows_from([
            snap("2026-08-17T15:10:26+00:00", "2026-08-18T00:59:18+09:00"),
            snap("2026-08-11T13:52:32+00:00", "2026-08-17T01:02:39+09:00"),
        ])
        exported = [r["exported_on"] for r in rows]
        self.assertEqual(exported, sorted(exported))


class 実データ(unittest.TestCase):
    """★2026-09-04 に書き直した。

    元は「全行の measured_on が空欄」と固定していた（2026-08-23 時点の実データ）。
    条件を記録して測り直したので、記録のある行には実測日が入るようになり落ちた。

    守りたかったのは**無い実測日を書き出し日で埋めないこと**。そこを固定し直す。
    """

    def test_これ大事_記録の無い行だけが空欄になる(self):
        rows = export_timeseries.build()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(muni=row["municipality"], field=row["field"]):
                self.assertEqual(row["measured_on"] == "",
                                 row["recording_status"] != "recorded")
        self.assertTrue(all(r["exported_on"] for r in rows))

    def test_記録前の行は残っている(self):
        # ★§4-8。既存の観測は条件を復元できない。消して揃えたりしない。
        rows = export_timeseries.build()
        self.assertTrue(any(r["measured_on"] == "" for r in rows))

    def test_書き出し済みCSVの見出しがCOLUMNSと一致する(self):
        head = export_timeseries.OUT.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(head.split(","), export_timeseries.COLUMNS)


if __name__ == "__main__":
    unittest.main()

"""1区の測り直し。ネットワークにも LLM にも触らない。前回との並べ方と報告の書き方だけを見る。"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remeasure_one  # noqa: E402

# 公開データ（web/data/scores-sodaigomi.json）の実物と同じ形
SCORES_DOC = {
    "procedure": "粗大ごみ",
    "measurement": {"runs": [{"municipality_id": "kita", "run_at": "2026-08-31T14:00:31+00:00"}]},
    "municipalities": [
        {"id": "nerima", "name": "練馬区", "total": 100, "breakdown": {}},
        {"id": "kita", "name": "北区", "total": 60, "page_url": "https://example.jp/kita",
         "breakdown": {"必要書類": 20, "窓口/オンライン可否": 20, "期限": 0, "手数料": 0, "オンライン明示": 20}},
    ],
}
CUR = {"total": 80, "page_url": "https://example.jp/kita",
       "breakdown": {"必要書類": 20, "窓口/オンライン可否": 20, "期限": 0, "手数料": 20, "オンライン明示": 20}}
SCORED = {"total": 60, "breakdown": {"情報到達": 20, "抽出正確性": 0, "機械可読性": 10, "オンライン明示": 20},
          "fields": [{"field": "必要書類", "verdict": "未採点"}, {"field": "手数料", "verdict": "未採点"}]}


def render(**kw):
    base = {"municipality": "北区", "procedure": "粗大ごみ", "when": "2026-09-28 10:00 JST",
            "page_url": "https://example.jp/kita", "fetch_note": "取り直した・200",
            "prev": remeasure_one.previous_entry(SCORES_DOC, "kita"), "cur": CUR,
            "scored": SCORED, "out_dir": "analysis/out/daily/remeasure/x"}
    return remeasure_one.render(**{**base, **kw})


class PreviousEntryTest(unittest.TestCase):
    def test_picks_the_municipality_and_its_run_time(self):
        prev = remeasure_one.previous_entry(SCORES_DOC, "kita")
        self.assertEqual(prev["total"], 60)
        self.assertEqual(prev["run_at"], "2026-08-31T14:00:31+00:00")

    def test_unknown_municipality_is_none(self):
        self.assertIsNone(remeasure_one.previous_entry(SCORES_DOC, "nowhere"))

    def test_missing_run_record_is_not_an_error(self):
        prev = remeasure_one.previous_entry({**SCORES_DOC, "measurement": {}}, "kita")
        self.assertIsNone(prev["run_at"])


class PointRowsTest(unittest.TestCase):
    def test_rows_follow_public_breakdown_order_then_total(self):
        rows = remeasure_one.point_rows(remeasure_one.previous_entry(SCORES_DOC, "kita"), CUR)
        self.assertEqual([r[0] for r in rows],
                         ["必要書類", "窓口/オンライン可否", "期限", "手数料", "オンライン明示", "合計"])
        self.assertEqual(rows[3], ("手数料", 0, 20, 20))
        self.assertEqual(rows[-1], ("合計", 60, 80, 20))

    def test_no_previous_is_not_called_zero(self):
        # 前回が無いのを 0点と並べると、差が「上がった」に見える
        rows = remeasure_one.point_rows(None, CUR)
        self.assertTrue(all(before is None and diff is None for _, before, _, diff in rows))

    def test_label_missing_in_previous_is_none(self):
        prev = {"total": 40, "breakdown": {"必要書類": 20, "オンライン明示": 20}}
        rows = {r[0]: r for r in remeasure_one.point_rows(prev, CUR)}
        self.assertEqual(rows["手数料"], ("手数料", None, 20, None))


class RenderTest(unittest.TestCase):
    def test_condition_note_is_always_there(self):
        # 前回は道具が開いた条件。これが無いと差を改善と読んでしまう
        self.assertIn("前回は #236 以前の条件（道具が開いていた）で測った値", render())
        self.assertIn("前回は #236 以前の条件", render(prev=None))

    def test_table_shows_before_after_and_signed_diff(self):
        text = render()
        self.assertIn("| 手数料 | 0 | 20 | +20 |", text)
        self.assertIn("| 合計 | 60 | 80 | +20 |", text)
        self.assertIn("| 期限 | 0 | 0 | +0 |", text)

    def test_no_previous_uses_dash(self):
        text = render(prev=None)
        self.assertIn("| 合計 | — | 80 | — |", text)
        self.assertIn("前回の記録が公開データに無い", text)

    def test_scorer_unscored_fields_are_named(self):
        text = render()
        self.assertIn("合計 60点（到達20 正確0 可読10 オンライン20）", text)
        self.assertIn("未採点: 必要書類・手数料", text)

    def test_missing_scorer_output_is_said(self):
        self.assertIn("採点結果なし", render(scored=None))

    def test_different_start_page_is_flagged(self):
        text = render(cur={**CUR, "page_url": "https://example.jp/other"})
        self.assertIn("★抽出が読んだ起点は別のページ", text)
        self.assertNotIn("★抽出が読んだ起点は別のページ", render())


class RunDirTest(unittest.TestCase):
    def test_name_has_time_and_ids(self):
        path = remeasure_one.run_dir(Path("/x"), datetime(2026, 9, 28, 10, 5, 7), "kita", "sodaigomi")
        self.assertEqual(path, Path("/x/20260928-100507-kita-sodaigomi"))

    def test_output_is_under_ignored_daily_dir(self):
        # analysis/out/daily/ は .gitignore 済み。区の文を含むので外に出さない
        rel = remeasure_one.OUT_BASE.relative_to(remeasure_one.ROOT)
        self.assertEqual(rel.parts[:3], ("analysis", "out", "daily"))


if __name__ == "__main__":
    unittest.main()

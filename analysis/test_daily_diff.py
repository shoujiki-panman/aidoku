"""毎朝の差分。ネットワークにも LLM にも触らない。比べ方と1通の書き方だけを見る。"""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_diff  # noqa: E402

TARGET = {"municipality": "北区", "procedure": "粗大ごみ", "url": "https://example.jp/a"}


class ChangedLinesTest(unittest.TestCase):
    def test_blank_lines_and_surrounding_spaces_do_not_count(self):
        self.assertEqual(daily_diff.changed_lines("a\n\n b \n", "a\nb\n\n"), ([], []))

    def test_added_and_removed_are_separated(self):
        added, removed = daily_diff.changed_lines("a\n旧\nc", "a\n新\nc\nd")
        self.assertEqual(added, ["新", "d"])
        self.assertEqual(removed, ["旧"])


class TouchedFieldsTest(unittest.TestCase):
    def test_fee_change_is_marked(self):
        lines = ["粗大ごみ処理手数料の電子決済（キャッシュレス決済）サービスが始まります"]
        self.assertEqual(daily_diff.touched_fields(lines), ["手数料"])

    def test_decoration_is_not_marked(self):
        # 2026-09-23 に実際に出た飾りの差
        self.assertEqual(daily_diff.touched_fields(["チャットを閉じる", "Foreign Languages"]), [])


class CompareTest(unittest.TestCase):
    def test_same_text_is_same(self):
        self.assertEqual(daily_diff.compare(TARGET, "a", "a").status, "同じ")

    def test_missing_text_is_not_called_same(self):
        # 取れなかったものを「変化なし」と言わない
        self.assertEqual(daily_diff.compare(TARGET, None, "a").status, "比べられない")
        self.assertEqual(daily_diff.compare(TARGET, "a", None).status, "比べられない")


class RenderTest(unittest.TestCase):
    def test_quiet_day_still_says_so(self):
        # 届かないのか、変化が無いのかを区別するため、変化なしでも1行出す
        text = daily_diff.render("2026-09-24", [daily_diff.compare(TARGET, "a", "a")])
        self.assertIn("変化なし", text)

    def test_field_hits_come_before_other_changes(self):
        fee = daily_diff.compare(TARGET, "a", "a\n手数料は無料です")
        deco = daily_diff.compare({**TARGET, "municipality": "目黒区"}, "a", "a\nForeign Languages")
        text = daily_diff.render("2026-09-24", [deco, fee])
        self.assertLess(text.index("北区"), text.index("目黒区"))
        self.assertIn("［手数料］", text)
        self.assertNotIn("変化なし", text)

    def test_failed_pages_are_listed_not_dropped(self):
        text = daily_diff.render("2026-09-24", [daily_diff.compare(TARGET, None, "a")])
        self.assertIn("比べられなかった", text)
        self.assertIn("北区", text)


class OutPathTest(unittest.TestCase):
    def test_second_run_of_the_day_does_not_overwrite_the_first(self):
        now = datetime(2026, 9, 24, 8, 30, 0)
        with TemporaryDirectory() as d:
            first = daily_diff.out_path(Path(d), now)
            self.assertEqual(first.name, "2026-09-24.md")
            first.write_text("1回目", encoding="utf-8")
            second = daily_diff.out_path(Path(d), now)
            self.assertNotEqual(second, first)
            self.assertTrue(second.name.startswith("2026-09-24-"))


if __name__ == "__main__":
    unittest.main()

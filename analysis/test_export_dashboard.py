"""ダッシュボード生成のテスト — 公開している点数の作り方を固定する。

web/data/scores.json は 2026-07-30 に生成されたが生成スクリプトがコミットされて
おらず、1区を測り直すだけでも手で JSON を書き換えるしかない状態だった。
export_dashboard.py はその欠けを埋めたもので、ここでは配点・処方箋・集計を固定する。

LLM は呼ばない。標準ライブラリのみ。

実行: python3 -m unittest discover -s analysis -p 'test_*.py'
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from export_dashboard import MAX_VALUE_CHARS, build_entry, summarize  # noqa: E402


def extract(items: dict, clarity: str = "明記", **kw) -> dict:
    base = {
        "municipality": "テスト区", "municipality_id": "test",
        "page": {"url": "https://example.jp/a.html", "hops": 2},
        "followed_urls": [], "online_clarity": clarity, "items": items,
        "page_notes": "",
    }
    base.update(kw)
    return base


def item(found: bool, value: str = "") -> dict:
    return {"found": found, "value": value}


ALL_FOUND = {k: item(True, "あり") for k in
             ("必要書類", "窓口オンライン可否", "期限", "手数料")}


class ScoringTest(unittest.TestCase):
    def test_full_marks(self):
        e = build_entry(extract(ALL_FOUND, "明記"))
        self.assertEqual(e["total"], 100)
        self.assertEqual(e["improvements"], [])

    def test_each_item_is_all_or_nothing(self):
        """4項目に部分点は無い。20点か0点しか出ない。"""
        items = dict(ALL_FOUND, 手数料=item(False))
        e = build_entry(extract(items, "明記"))
        self.assertEqual(e["breakdown"]["手数料"], 0)
        self.assertEqual(e["total"], 80)

    def test_clarity_has_three_levels(self):
        for clarity, pt in (("明記", 20), ("曖昧", 10), ("記載なし", 0)):
            with self.subTest(clarity=clarity):
                e = build_entry(extract(ALL_FOUND, clarity))
                self.assertEqual(e["breakdown"]["オンライン明示"], pt)
                self.assertEqual(e["total"], 80 + pt)

    def test_unknown_clarity_scores_zero(self):
        self.assertEqual(build_entry(extract(ALL_FOUND, "?"))["breakdown"]["オンライン明示"], 0)

    def test_missing_items_become_improvements(self):
        items = dict(ALL_FOUND, 期限=item(False), 手数料=item(False))
        e = build_entry(extract(items, "曖昧"))
        self.assertEqual([i["field"] for i in e["improvements"]],
                         ["期限", "手数料", "オンライン明示"])
        # オンライン明示は満点までの差分だけを足せる
        self.assertEqual([i["gain"] for i in e["improvements"]], [20, 20, 10])

    def test_agent_value_is_truncated(self):
        items = dict(ALL_FOUND, 必要書類=item(True, "あ" * 500))
        e = build_entry(extract(items))
        self.assertEqual(len(e["fields"][0]["agent_value"]), MAX_VALUE_CHARS)

    def test_field_label_is_renamed_for_display(self):
        e = build_entry(extract(ALL_FOUND))
        self.assertIn("窓口/オンライン可否", e["breakdown"])
        self.assertNotIn("窓口オンライン可否", e["breakdown"])


class SummaryTest(unittest.TestCase):
    def test_counts(self):
        full = build_entry(extract(ALL_FOUND, "明記"))
        no_fee = build_entry(extract(dict(ALL_FOUND, 手数料=item(False)), "明記"))
        zero = build_entry(extract({k: item(False) for k in ALL_FOUND}, "記載なし"))
        s = summarize([full, no_fee, zero])
        self.assertEqual(s["max"], 100)
        self.assertEqual(s["min"], 0)
        self.assertEqual(s["full_marks"], 1)
        self.assertEqual(s["zero"], 1)
        self.assertEqual(s["fee_missing"], 2)
        self.assertEqual(s["average"], round((100 + 80 + 0) / 3, 1))

    def test_full_marks_ignores_online_clarity(self):
        """「4項目すべて読めた」はオンライン明示を含まない（港区=1区の定義）。"""
        e = build_entry(extract(ALL_FOUND, "記載なし"))
        self.assertEqual(e["total"], 80)
        self.assertEqual(summarize([e])["full_marks"], 1)


if __name__ == "__main__":
    unittest.main()

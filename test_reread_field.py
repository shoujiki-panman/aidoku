from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from reread_field import ASK, HINTS, NOT_THIS, summarize  # noqa: E402


def published_fields() -> set[str]:
    doc = json.loads((ROOT / "web/data/scores-tennyu.json").read_text(encoding="utf-8"))
    return {f["field"] for m in doc["municipalities"] for f in m.get("fields", [])}


class 項目名(unittest.TestCase):
    """★同じ取り違えを2回やっている。

    公開データの項目は `窓口/オンライン可否`（スラッシュ入り）だが、
    1回目は `窓口とオンライン可否`、2回目は `窓口オンライン可否` と書いた。
    名前が違うと突き合わせが黙って全件外れ、**全部「不明」になったまま気づかない。**
    """

    def test_公開データの項目名と一致する(self):
        self.assertEqual(set(HINTS), published_fields())

    def test_語の表と除外の表がずれていない(self):
        self.assertEqual(set(HINTS), set(NOT_THIS))

    def test_除外がどれも空でない(self):
        # 空だと隣の手続きの答えを拾う。手数料で実証済み。
        for field, text in NOT_THIS.items():
            with self.subTest(field=field):
                self.assertGreater(len(text.strip()), 40)


class 語の選び方(unittest.TestCase):
    def test_答えそのものの形は入れない(self):
        # 金額や日付の形を入れると、隣の手続きの数字まで拾う
        # （plans/decisions/table-reading.md：見積12セル→実際4セル）。
        for field, pattern in HINTS.items():
            with self.subTest(field=field):
                self.assertIsNone(pattern.search("300円"))
                self.assertIsNone(pattern.search("2026年8月27日"))

    def test_必要書類の語が当たる(self):
        self.assertTrue(HINTS["必要書類"].search("次のものをお持ちください"))

    def test_期限の語が当たる(self):
        self.assertTrue(HINTS["期限"].search("転入した日から14日以内に届け出てください"))

    def test_窓口の語が当たる(self):
        self.assertTrue(HINTS["窓口/オンライン可否"].search("区民課の窓口で受け付けます"))

    def test_手数料の語が当たる(self):
        self.assertTrue(HINTS["手数料"].search("手数料はかかりません"))


class 質問文(unittest.TestCase):
    def test_全項目で組み立てられる(self):
        for field in HINTS:
            with self.subTest(field=field):
                text = ASK.format(muni="港区", proc="転入届", field=field,
                                  not_this=NOT_THIS[field], url="https://x.example/a", text="本文")
                self.assertIn(field, text)
                self.assertIn("港区", text)
                # JSONの見本が壊れていないこと（{{ }} のエスケープ漏れ検出）
                self.assertIn('{"found": true', text)

    def test_引き写しを求めている(self):
        # 言い換えられると evidence_check が missing になり、正しい根拠まで落ちる。
        self.assertIn("引き写して", ASK)


def row(mid: str, name: str, found: bool, pages: list[dict] | None = None) -> dict:
    return {"municipality_id": mid, "municipality": name,
            "now_found": found, "pages": pages or []}


class 集計(unittest.TestCase):
    def test_読み落としだった区だけ数える(self):
        rows = [row("a", "A区", True), row("b", "B区", True), row("c", "C区", False)]
        got = summarize(rows, {"a": "読めない", "b": "読めた", "c": "読めない"})
        self.assertEqual(got["newly_found"], 1)
        self.assertEqual(got["newly_found_names"], ["A区"])
        self.assertEqual(got["already_readable"], 1)

    def test_引用が本文に無い主張を別に数える(self):
        pages = [{"found": True, "verified": False}, {"found": True, "verified": True}]
        got = summarize([row("a", "A区", True, pages)], {"a": "読めない"})
        self.assertEqual(got["unverified_claims"], 1)

    def test_公開判定に無い区でも落ちない(self):
        self.assertEqual(summarize([row("x", "X区", True)], {})["newly_found"], 1)


if __name__ == "__main__":
    unittest.main()

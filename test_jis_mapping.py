from __future__ import annotations

import unittest
from pathlib import Path

from jis_mapping import CRITERIA, MAPPING, criterion_for, describe, summary

ROOT = Path(__file__).resolve().parent


class 対応づけ(unittest.TestCase):
    def test_画像PDFはレベルAの非テキストコンテンツ(self):
        got = criterion_for("image_pdf")
        self.assertEqual(got.number, "1.1.1")
        self.assertEqual(got.level, "A")

    def test_表の見出しは情報及び関係性(self):
        self.assertEqual(criterion_for("table_only").number, "1.3.1")

    def test_見出しはレベルAA(self):
        self.assertEqual(criterion_for("buried_heading").level, "AA")


class 範囲外(unittest.TestCase):
    """★ここがAI読の固有部分。無理にJISへ寄せると、見えなくなる。"""

    def test_書かれていないことは違反ではない(self):
        self.assertIsNone(criterion_for("not_written"))

    def test_リンク先1階層は違反ではない(self):
        self.assertIsNone(criterion_for("one_hop_away"))

    def test_情報の古さをJISは扱わない(self):
        self.assertIsNone(criterion_for("stale"))

    def test_AIの推測はサイト側の問題ですらない(self):
        self.assertIsNone(criterion_for("ai_guesses"))

    def test_範囲外が1つ以上ある(self):
        # 全部が対応づいたら、それは寄せすぎている。
        self.assertGreater(summary()["out_of_scope"], 0)


class 出力(unittest.TestCase):
    def test_対応づくものは番号とレベルと出典を出す(self):
        got = describe("image_pdf")
        self.assertTrue(got["in_scope"])
        self.assertIn("1.1.1", got["criterion"])
        self.assertEqual(got["level"], "A")
        self.assertIn("適合レベルAA", got["guideline"])

    def test_対応づかないものはレベルを出さない(self):
        got = describe("not_written")
        self.assertFalse(got["in_scope"])
        self.assertIsNone(got["criterion"])
        self.assertIsNone(got["level"])
        self.assertIsNone(got["guideline"])
        self.assertTrue(got["why"])          # 代わりに理由を必ず出す

    def test_全件に理由と根拠がある(self):
        for key in MAPPING:
            with self.subTest(finding=key):
                got = describe(key)
                self.assertTrue(got["why"].strip())
                self.assertTrue(got["evidence"].strip())


class 規格の書き方(unittest.TestCase):
    def test_番号と名称を言い換えない(self):
        # ★規格の名称は規格のとおりに書く。言い換えると照合できなくなる。
        self.assertEqual(CRITERIA["2.4.4"].name, "文脈におけるリンクの目的")
        self.assertEqual(CRITERIA["1.3.1"].name, "情報及び関係性")

    def test_レベルはAかAAだけ(self):
        # AAA は自治体に求められていないので持たない。
        for number, c in CRITERIA.items():
            with self.subTest(number=number):
                self.assertIn(c.level, ("A", "AA"))

    def test_番号とキーが一致する(self):
        for number, c in CRITERIA.items():
            self.assertEqual(number, c.number)


class 根拠のファイル(unittest.TestCase):
    def test_挙げた根拠が実在する(self):
        # ★存在しないファイルを根拠に挙げると、職員が確かめられない。
        for key, entry in MAPPING.items():
            with self.subTest(finding=key):
                self.assertTrue((ROOT / entry["evidence"]).exists(),
                                f"{entry['evidence']} が無い")


if __name__ == "__main__":
    unittest.main()

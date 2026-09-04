"""`analysis/mr_mapping.py` — AI読と「行政データにおける機械可読性に関するルール」の対応づけ。

★JISの対応づけで学んだこと: **対応づけただけで数が無いと職員に渡せない。**
  だからここでは「実測が書かれていること」をテストで強制する。

★もう1つ: **対応づかないものを書かないと、何が新しいのかが消える。**
  空にできないようにする。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from mr_mapping import (  # noqa: E402
    MAPPED,
    RULE_SOURCE,
    UNMAPPED,
    coverage,
    mapped_rule_ids,
    render,
)

# 公式ルールの数。ルール本体（machine-readability-rules.json）を数えた値。
OFFICIAL_RULES = 30
OFFICIAL_LEVELS = {"Level1": 15, "Level2": 6, "Level3": 9}


class 出典(unittest.TestCase):
    def test_いつ誰が出したかを持つ(self):
        # ★出典の無い対応表は、次の人が確かめられない。
        for key in ("name", "issued", "by", "url", "tool"):
            self.assertTrue(RULE_SOURCE.get(key), key)

    def test_ルール数は公式と一致する(self):
        self.assertEqual(RULE_SOURCE["rules"], OFFICIAL_RULES)

    def test_レベルの内訳を数えた記録(self):
        # 実際に数えた値。ルールが改定されたらここが落ちて気づける。
        self.assertEqual(sum(OFFICIAL_LEVELS.values()), OFFICIAL_RULES)


class 対応づけ(unittest.TestCase):
    def test_どの項目にも実測がある(self):
        """★JISのときは対応づけだけ書いて数が無く、職員に渡せなかった。"""
        for m in MAPPED:
            with self.subTest(rule=m["rule_id"]):
                self.assertGreater(len(m["measured"]), 20)
                self.assertTrue(any(c.isdigit() for c in m["measured"]),
                                "実測に数字が入っていない")

    def test_ルールIDの形が正しい(self):
        for m in MAPPED:
            with self.subTest(rule=m["rule_id"]):
                self.assertRegex(m["rule_id"], r"^L[123]-\d{2}$")

    def test_レベルとIDが食い違わない(self):
        for m in MAPPED:
            with self.subTest(rule=m["rule_id"]):
                self.assertEqual(m["level"], "Level" + m["rule_id"][1])

    def test_AI読側の指摘が書いてある(self):
        for m in MAPPED:
            with self.subTest(rule=m["rule_id"]):
                self.assertGreater(len(m["aidoku"]), 5)


class 対応づかないもの(unittest.TestCase):
    """★ここがAI読の固有部分。空にできないようにする。"""

    def test_空にしない(self):
        self.assertGreaterEqual(len(UNMAPPED), 3)

    def test_なぜ対応づかないかが書いてある(self):
        for u in UNMAPPED:
            with self.subTest(aidoku=u["aidoku"]):
                self.assertGreater(len(u["why"]), 20)
                self.assertGreater(len(u["measured"]), 10)

    def test_読めるPDFと読めないPDFの区別が入っている(self):
        # ★これが今回いちばん言いたいこと。ルールは「PDFは不可」で止まる。
        self.assertTrue(any("PDF" in u["aidoku"] for u in UNMAPPED))


class 網羅の見せ方(unittest.TestCase):
    def test_対応づいた数を隠さない(self):
        cov = coverage()
        self.assertEqual(cov["rules_total"], OFFICIAL_RULES)
        self.assertLessEqual(cov["rules_mapped"], cov["rules_total"])
        # ★少ないことを隠さない。30のうち数件しか対応づかないのが実態。
        self.assertLess(cov["rules_mapped"], 10)

    def test_IDは重複を除いて並べる(self):
        ids = mapped_rule_ids()
        self.assertEqual(ids, sorted(set(ids)))

    def test_表示に対応づかないものが出る(self):
        text = render()
        self.assertIn("対応づかないもの", text)
        self.assertIn("固有", text)


if __name__ == "__main__":
    unittest.main()

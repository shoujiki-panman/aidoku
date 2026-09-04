"""`analysis/probes/check_pick.py` — 起点ページの選び方と本文量の食い違い。

**なぜ要るか**: 最初の版は「選ばれたページより桁違いに長い候補があるか」だけを見て
27組と答えたが、**長い候補の多くは手続きと無関係なページ**だった
（施設一覧・はてなブックマーク・読み上げ代行サービス）。

**長い＝正しい、ではない。** 手続きらしさの点を見ないと数を水増しする。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis" / "probes"))
from check_pick import KINDS, classify, eligible, passed_over, summarize  # noqa: E402


def cand(url: str, length: int, score: int = 10, **extra) -> dict:
    base = {"url": url, "text_len": length, "score": score,
            "status": 200, "is_pdf": False}
    base.update(extra)
    return base


def discovery(*candidates: dict) -> dict:
    return {"candidates": list(candidates)}


class 採りうる候補(unittest.TestCase):
    def test_並び順のまま返す(self):
        got = eligible(discovery(cand("a", 500), cand("b", 900)))
        self.assertEqual([c["url"] for c in got], ["a", "b"])

    def test_200字未満は捨てる(self):
        # ★pick_page の足切りと同じ。ずれると別のものを測ることになる。
        self.assertEqual(eligible(discovery(cand("a", 199))), [])

    def test_PDFは捨てる(self):
        self.assertEqual(eligible(discovery(cand("a", 900, is_pdf=True))), [])

    def test_200番以外は捨てる(self):
        self.assertEqual(eligible(discovery(cand("a", 900, status=404))), [])

    def test_pick_pageと先頭が一致する(self):
        """★`pick_page` と食い違ったら、測っている対象がずれる。"""
        sys.path.insert(0, str(ROOT))
        from extractor.extract import pick_page
        doc = discovery(cand("https://x/a", 199), cand("https://x/b", 900))
        self.assertEqual(eligible(doc)[0], pick_page(doc))


class 飛ばされた候補(unittest.TestCase):
    def test_最も長い1本を返す(self):
        got = passed_over(discovery(cand("a", 300), cand("b", 900), cand("c", 5000)))
        self.assertEqual(got["longest_skipped"]["url"], "c")

    def test_選ばれたものが最長なら無し(self):
        got = passed_over(discovery(cand("a", 9000), cand("b", 300)))
        self.assertIsNone(got["longest_skipped"])

    def test_候補が無ければNone(self):
        self.assertIsNone(passed_over(discovery()))


class 食い違いの分類(unittest.TestCase):
    def row(self, picked_len: int, skipped_len: int,
            picked_score: int = 10, skipped_score: int = 10) -> dict:
        return passed_over(discovery(
            cand("picked", picked_len, picked_score),
            cand("skipped", skipped_len, skipped_score)))

    def test_最長なら食い違いなし(self):
        self.assertEqual(classify(self.row(9000, 300)), "選ばれたものが最長")

    def test_同点で桁が違えば本物(self):
        self.assertEqual(classify(self.row(775, 9800)), "同点以上で桁が違う")

    def test_点が低ければ別の話題とみなす(self):
        """★これを入れないと、無関係な長いページを選び損ねに数える（27組→4組）。"""
        self.assertEqual(classify(self.row(775, 16654, 25, 7)),
                         "長いが手続きの語が弱い")

    def test_点が高ければ本物に数える(self):
        self.assertEqual(classify(self.row(775, 9800, 10, 25)), "同点以上で桁が違う")

    def test_倍率が足りなければ少し長い(self):
        self.assertEqual(classify(self.row(3000, 6000)), "少し長い")

    def test_字数が足りなければ少し長い(self):
        """★倍率だけだと 210字 vs 700字 を「桁が違う」に数える。"""
        self.assertEqual(classify(self.row(210, 700)), "少し長い")


class 集計(unittest.TestCase):
    def items(self, kinds: list[str]) -> list[dict]:
        return [{"municipality": f"{i}区", "procedure": "tennyu", "kind": k}
                for i, k in enumerate(kinds)]

    def test_確実に言えるのは同点以上だけ(self):
        got = summarize(self.items(["同点以上で桁が違う", "長いが手続きの語が弱い"]))
        self.assertEqual(got["confirmed_lower_bound"], 1)

    def test_名前も出す(self):
        got = summarize(self.items(["同点以上で桁が違う"]))
        self.assertEqual(got["confirmed_names"], ["0区 tennyu"])

    def test_印は全種類出す(self):
        self.assertEqual(set(summarize(self.items(["少し長い"]))["by_kind"]), set(KINDS))


class 実データ(unittest.TestCase):
    def test_無関係な長いページを本物に数えていない(self):
        """★27組と答えた誤りの再発防止。下限は27よりずっと小さいはず。"""
        import json
        path = ROOT / "analysis" / "out" / "pick_vs_length.json"
        if not path.exists():
            self.skipTest("未生成")
        got = json.loads(path.read_text(encoding="utf-8"))["summary"]
        self.assertLess(got["confirmed_lower_bound"], 27)
        self.assertGreater(got["by_kind"]["長いが手続きの語が弱い"], 0)


if __name__ == "__main__":
    unittest.main()

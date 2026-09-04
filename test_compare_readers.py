"""`analysis/compare_readers.py` — 自作リーダーと外部の変換器を突き合わせる検算道具。

**作品本体ではない。** 外部の変換器（anydoc）は開発時にだけ使う
（CLAUDE.md「作品本体は Python 標準ライブラリのみ」）。ruff / jscpd と同じ立場。
なので anydoc が入っていない環境でも、ここの判定の作りはテストできる。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from compare_readers import (  # noqa: E402
    SAME_RATIO,
    kind_of,
    normalize,
    similarity,
    summarize,
    verdict,
)


def side(ok: bool) -> dict:
    return {"ok": ok, "chars": 100 if ok else 0, "text": "本文" if ok else "", "reason": ""}


class 種類(unittest.TestCase):
    def test_先頭バイトで見分ける(self):
        self.assertEqual(kind_of(b"%PDF-1.4"), "pdf")
        self.assertIn("zip", kind_of(b"PK\x03\x04") or "")
        self.assertIn("古い", kind_of(b"\xd0\xcf\x11\xe0") or "")

    def test_添付でなければNone(self):
        # ★None のものは数から外す。HTMLを混ぜると分母が変わる。
        self.assertIsNone(kind_of(b"<html>"))
        self.assertIsNone(kind_of(b""))


class 突き合わせの下ごしらえ(unittest.TestCase):
    def test_書式を落とす(self):
        # anydoc は Markdown を返す。記号を残すと「中身が違う」ではなく
        # 「書式が違う」を数えてしまう。
        self.assertEqual(normalize("| **手数料** | 400円 |"), "手数料400円")

    def test_改行と空白も落とす(self):
        self.assertEqual(normalize("手数料\n\n  は  無料"), "手数料は無料")

    def test_同じ本文なら1(self):
        self.assertEqual(similarity("手数料は無料", "手数料は無料"), 1.0)

    def test_片方が空なら0(self):
        self.assertEqual(similarity("手数料", ""), 0.0)
        self.assertEqual(similarity("", "手数料"), 0.0)

    def test_両方空なら1(self):
        # ★「どちらも読めない」を一致率0にすると、読めた組と見分けがつかなくなる。
        #   印は verdict で分ける。ここは素直に1を返す。
        self.assertEqual(similarity("", ""), 1.0)

    def test_長い本文でも頭だけ見る(self):
        # 二乗に膨らむので cap で切る。切っても落ちないことを固定する。
        self.assertGreater(similarity("あ" * 100000, "あ" * 100000), 0.9)


class 判定(unittest.TestCase):
    def test_両方読めて似ていれば同じ(self):
        self.assertEqual(verdict(side(True), side(True), 0.9), "同じ")

    def test_両方読めても似ていなければ別扱い(self):
        self.assertEqual(verdict(side(True), side(True), 0.2), "両方読めたが中身が違う")

    def test_境目は同じ側に倒す(self):
        self.assertEqual(verdict(side(True), side(True), SAME_RATIO), "同じ")

    def test_片方だけ読めた場合を分ける(self):
        self.assertEqual(verdict(side(False), side(True), 0.0), "★anydocだけ読めた")
        self.assertEqual(verdict(side(True), side(False), 0.0), "★うちだけ読めた")

    def test_どちらも読めないを一致に混ぜない(self):
        # ★一致率は1.0（どちらも空）になる。印で必ず分ける。
        self.assertEqual(verdict(side(False), side(False), 1.0), "どちらも読めない")


class 集計(unittest.TestCase):
    def row(self, mark: str, url: str) -> dict:
        return {"url": url, "verdict": mark}

    def test_印ごとに数える(self):
        got = summarize([self.row("同じ", "a"), self.row("同じ", "b"),
                         self.row("★うちだけ読めた", "c")])
        self.assertEqual(got["files"], 3)
        self.assertEqual(got["by_verdict"]["同じ"], 2)

    def test_片方だけ読めたものは名前を出す(self):
        # 数だけだと、どのファイルを直せばよいか追えない。
        got = summarize([self.row("★anydocだけ読めた", "x.pdf"),
                         self.row("★うちだけ読めた", "y.pdf")])
        self.assertEqual(got["anydoc_only"], ["x.pdf"])
        self.assertEqual(got["ours_only"], ["y.pdf"])

    def test_空でも落ちない(self):
        self.assertEqual(summarize([])["files"], 0)


if __name__ == "__main__":
    unittest.main()

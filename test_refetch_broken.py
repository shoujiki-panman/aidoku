"""`crawler/refetch_broken.py` — 壊れているキャッシュを見つけて取り直す。

**壊れていた実物**: 13MBのPDFに置換文字が3,029,888個（23%）。
`polite_fetch` が全応答を `write_text` で保存していた頃のもので、
修正後も**取り直すまで壊れたまま残る**。この判定を間違えると、
「その区が書いていない」が壊れたファイルを根拠にした主張になる。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "crawler"))
from officedoc import looks_like_document  # noqa: E402
from refetch_broken import (  # noqa: E402
    BROKEN_RATIO,
    REPLACEMENT,
    broken_entries,
    broken_ratio,
    is_broken,
)

PDF = b"%PDF-1.4\n"


def corrupted(size: int = 300) -> bytes:
    """壊れたPDFの形。置換文字が本文の大半を占める。"""
    return PDF + REPLACEMENT * size


class 添付かどうか(unittest.TestCase):
    def test_先頭バイトで判断する(self):
        # ★キャッシュは拡張子 .html で保存されるので、名前では分からない。
        self.assertTrue(looks_like_document(b"%PDF-1.7 ..."))
        self.assertTrue(looks_like_document(b"PK\x03\x04zip"))
        self.assertTrue(looks_like_document(b"\xd0\xcf\x11\xe0old office"))

    def test_HTMLは添付ではない(self):
        self.assertFalse(looks_like_document(b"<!DOCTYPE html><html>"))
        self.assertFalse(looks_like_document(b""))


class 壊れている割合(unittest.TestCase):
    def test_置換文字の占める割合を返す(self):
        self.assertAlmostEqual(broken_ratio(REPLACEMENT * 10), 1.0)
        self.assertAlmostEqual(broken_ratio(b"x" * 97 + REPLACEMENT), 0.03)

    def test_空なら0(self):
        self.assertEqual(broken_ratio(b""), 0.0)

    def test_置換文字が無ければ0(self):
        self.assertEqual(broken_ratio(b"%PDF-1.4 clean"), 0.0)


class 壊れている判定(unittest.TestCase):
    def test_置換文字だらけの添付は壊れている(self):
        self.assertTrue(is_broken(corrupted()))

    def test_偶然1個混じっただけの添付は壊れていない(self):
        """★閾値が無いと誤検出する。**実測で踏んだ。**

        取り直して直った7.5MBのPDFに、置換文字がちょうど1個残っていた。
        3バイトの並びは偶然も起きる。閾値が無いと永久に取り直し続ける。
        """
        big = PDF + b"x" * 7_500_000 + REPLACEMENT
        self.assertFalse(is_broken(big))
        self.assertLess(broken_ratio(big), BROKEN_RATIO)

    def test_HTMLは対象にしない(self):
        # 元から化けているページはありうる。取り直しても直らないので触らない。
        self.assertFalse(is_broken(b"<html>" + REPLACEMENT * 300))

    def test_空でも落ちない(self):
        self.assertFalse(is_broken(b""))

    def test_閾値ちょうどは壊れていない側(self):
        # 境目をどちらに倒したかを固定する（超えたときだけ壊れている）。
        exact = REPLACEMENT + b"x" * (len(REPLACEMENT) * 100 - len(REPLACEMENT))
        self.assertAlmostEqual(broken_ratio(PDF + exact), 0.0097, places=3)
        self.assertFalse(is_broken(PDF + exact))


class 一覧(unittest.TestCase):
    def cache(self, tmp: Path, name: str, raw: bytes, url: str) -> None:
        host = tmp / "example.lg.jp"
        host.mkdir(exist_ok=True)
        (host / f"{name}.html").write_bytes(raw)
        (host / f"{name}.meta.json").write_text(
            json.dumps({"url": url}, ensure_ascii=False), encoding="utf-8")

    def entries(self, files: list[tuple[str, bytes, str]]) -> list[dict]:
        import refetch_broken as mod
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, raw, url in files:
                self.cache(root, name, raw, url)
            original, mod.CACHE = mod.CACHE, root
            try:
                return broken_entries()
            finally:
                mod.CACHE = original

    def test_壊れているものだけ挙げる(self):
        got = self.entries([("a", corrupted(), "https://x/a.pdf"),
                            ("b", PDF + b"clean body", "https://x/b.pdf")])
        self.assertEqual([e["url"] for e in got], ["https://x/a.pdf"])

    def test_URLはメタから取る(self):
        # 本体のファイル名はハッシュなので、名前からURLは復元できない。
        got = self.entries([("deadbeef", corrupted(), "https://x/長い名前.pdf")])
        self.assertEqual(got[0]["url"], "https://x/長い名前.pdf")
        self.assertGreater(got[0]["ratio"], BROKEN_RATIO)

    def test_本体が無いメタは飛ばす(self):
        import refetch_broken as mod
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "example.lg.jp"
            root.mkdir(parents=True)
            (root / "x.meta.json").write_text("{}", encoding="utf-8")
            original, mod.CACHE = mod.CACHE, Path(tmp)
            try:
                self.assertEqual(broken_entries(), [])
            finally:
                mod.CACHE = original


if __name__ == "__main__":
    unittest.main()

"""`crawler/ocr.py` — 絵として入っている文字を読む。

**住民のAIができることは、こちらもできる。** 住民の ChatGPT / Claude は絵を読む。
こちらが字しか扱えないまま「その区は書いていない」と言うのは、
**住民の側で読めているものを区の落ち度にする**ことになる。

★2026-08-31 の朝は「OCRは開発時の道具。測定条件に混ぜない」としていた。本人の指摘で改めた。
  再現性は「使わない」ではなく **`non_html_reading` に記録する**ことで担保する。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "crawler"))
import ocr  # noqa: E402
from officedoc import read_document  # noqa: E402


class 測定条件への記録(unittest.TestCase):
    """★ここが要。使ったかどうかが後から分からないと、条件が混ざる。"""

    def test_使えるときは印が付く(self):
        original, ocr._READY = ocr._READY, True
        try:
            self.assertEqual(ocr.condition("cmap_text"), "cmap_text+ocr")
        finally:
            ocr._READY = original

    def test_使えないときは元のまま(self):
        # ★環境にOCRが無ければ条件が変わる。条件が違う記録は比較を拒否されるので、
        #   「使ったのに使っていないことにする」は起きない。
        original, ocr._READY = ocr._READY, False
        try:
            self.assertEqual(ocr.condition("cmap_text"), "cmap_text")
        finally:
            ocr._READY = original

    def test_抽出器が同じ値を記録している(self):
        sys.path.insert(0, str(ROOT))
        from extractor.fact_extract import NON_HTML_READING
        self.assertEqual(NON_HTML_READING, ocr.condition("cmap_text"))


class 読めないときの振る舞い(unittest.TestCase):
    def test_PDFでなければ何もしない(self):
        self.assertEqual(ocr.read_pdf_text(b"<html>"), "")
        self.assertEqual(ocr.read_pdf_text(b""), "")

    def test_使えない環境では空を返す(self):
        # ★読めたふりをしない。呼ぶ側が「読めない」と記録できるようにする。
        original, ocr._READY = ocr._READY, False
        try:
            self.assertEqual(ocr.read_pdf_text(b"%PDF-1.4 ..."), "")
        finally:
            ocr._READY = original

    def test_壊れたPDFでも落ちない(self):
        self.assertIsInstance(ocr.read_pdf_text(b"%PDF-1.4 broken"), str)


class 読み取りへの効き方(unittest.TestCase):
    """★実物で確かめる。作った入力だけでは思い込みが素通りする。"""

    def pdf(self, url: str) -> bytes | None:
        import hashlib
        import urllib.parse
        host = urllib.parse.urlparse(url).netloc
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        path = ROOT / "crawler" / "cache" / host / f"{key}.html"
        return path.read_bytes() if path.exists() else None

    def test_本文のストリームが無いPDFが読める(self):
        """中野区の委任状。字ではなく絵として入っている。"""
        url = ("https://www.city.tokyo-nakano.lg.jp/kurashi/koseki/mynumber/"
               "tennyutodoke.files/ininjyou.pdf")
        raw = self.pdf(url)
        if raw is None or not ocr.available():
            self.skipTest("キャッシュかOCRが無い")
        got = read_document(raw, url)
        self.assertTrue(got.ok, got.reason)
        self.assertIn("委任状", got.text)

    def test_読めなければ理由が残る(self):
        # ★OCRでも読めないものはある。そのときは理由を返す（空にしない）。
        got = read_document(b"%PDF-1.4\nnothing here\n", "https://x/a.pdf")
        self.assertFalse(got.ok)
        self.assertTrue(got.reason)


if __name__ == "__main__":
    unittest.main()

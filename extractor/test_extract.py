"""読解層のテスト — 「どのページを採点するか」を固定する。

台東区が Word 文書（.docx）を診断ページに選び、ZIP/XML のバイナリを採点していた
（2026-08-05 実測・0点 → 本来のHTMLページで80点）。pick_page の docstring は
「スコア最上位のHTMLページ」と書いてあるのに、実装は PDF しか除外していなかった。
バイナリは text_len が大きくなるので「本文200字以上」の条件もすり抜ける。

LLM（`claude -p`）は呼ばない。呼ばずに決まる経路だけを対象にしている。
標準ライブラリのみ。

実行: python3 -m unittest discover -s extractor -p 'test_*.py'
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import is_non_html, pick_page  # noqa: E402


def candidate(url: str, **kw) -> dict:
    base = {"url": url, "status": 200, "is_pdf": False, "text_len": 5000, "score": 10}
    base.update(kw)
    return base


class IsNonHtmlTest(unittest.TestCase):
    def test_office_documents_are_not_html(self):
        for ext in ("docx", "doc", "xlsx", "xls", "pptx", "ppt", "pdf", "zip", "csv", "rtf"):
            with self.subTest(ext=ext):
                self.assertTrue(is_non_html(f"https://example.jp/a/b.{ext}"))

    def test_case_is_ignored(self):
        self.assertTrue(is_non_html("https://example.jp/A/TENNYU.DOCX"))

    def test_html_pages_pass(self):
        for url in ("https://example.jp/a.html", "https://example.jp/a.htm",
                    "https://example.jp/a/", "https://example.jp/a"):
            with self.subTest(url=url):
                self.assertFalse(is_non_html(url))

    def test_query_string_is_not_the_path(self):
        """?file=x.docx は HTML ページ。拡張子はパス側だけを見る。"""
        self.assertFalse(is_non_html("https://example.jp/view.html?file=x.docx"))


class PickPageTest(unittest.TestCase):
    def test_skips_binary_attachment_even_when_top_scored(self):
        """台東区で起きた事象。1位が .docx なら飛ばして次のHTMLを選ぶ。"""
        picked = pick_page({"candidates": [
            candidate("https://example.jp/x.files/tennyu-inin.docx", score=46, text_len=21992),
            candidate("https://example.jp/tennyu.html", score=39, text_len=1635),
        ]})
        self.assertEqual(picked["url"], "https://example.jp/tennyu.html")

    def test_binary_does_not_pass_via_text_len(self):
        """バイナリは text_len が大きいので、長さの条件では止められない。"""
        picked = pick_page({"candidates": [
            candidate("https://example.jp/a.docx", text_len=99999)]})
        self.assertIsNone(picked)

    def test_skips_pdf_and_non_200_and_short_pages(self):
        picked = pick_page({"candidates": [
            candidate("https://example.jp/a.html", is_pdf=True),
            candidate("https://example.jp/b.html", status=404),
            candidate("https://example.jp/c.html", text_len=199),
            candidate("https://example.jp/d.html"),
        ]})
        self.assertEqual(picked["url"], "https://example.jp/d.html")

    def test_returns_none_when_nothing_usable(self):
        self.assertIsNone(pick_page({"candidates": []}))


if __name__ == "__main__":
    unittest.main()

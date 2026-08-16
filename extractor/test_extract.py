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
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from extract import (  # noqa: E402
    MAX_TEXT_CHARS,
    build_evidence_pages,
    is_non_html,
    measurement_for,
    main,
    pick_page,
)
from measurement import MeasurementError, build_discovery_measurement  # noqa: E402

VALID_PROMPT_VERSION = "sha256:" + "0" * 64


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


class FakeCachedPage:
    body_path = "cached.html"

    def __init__(self, body: str):
        self._body = body

    def body(self) -> str:
        return f"<html><body>{self._body}</body></html>"


class FakeFetcher:
    def __init__(self, body: str):
        self._body = body

    def cached(self, _url: str) -> FakeCachedPage:
        return FakeCachedPage(self._body)


class EvidenceScopeTest(unittest.TestCase):
    def test_本体と追跡ページを各18000字まで照合対象にする(self):
        pages = build_evidence_pages(
            {"url": "https://example.jp/base"},
            FakeFetcher("本" * (MAX_TEXT_CHARS + 10)),
            extra_pages=[("https://example.jp/detail", "追" * (MAX_TEXT_CHARS + 10))],
        )
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].count("本"), MAX_TEXT_CHARS)
        self.assertEqual(pages[1].count("追"), MAX_TEXT_CHARS)

    def test_基点ページのキャッシュが無ければ明示的に失敗する(self):
        class MissingFetcher:
            def cached(self, _url: str):
                return None

        with self.assertRaises(SystemExit):
            build_evidence_pages({"url": "https://example.jp/base"}, MissingFetcher())


class MeasurementRecordTest(unittest.TestCase):
    def test_探索条件と抽出条件をまとめる(self):
        discovery = {
            "measurement": build_discovery_measurement(
                3, {1: (1, 6), 2: (3, 4), 3: (4, 3)}, 26,
                "2026-08-16T00:00:00+00:00",
            )
        }
        result = measurement_for(
            discovery,
            follow=True,
            model="claude-sonnet-5",
            prompt=VALID_PROMPT_VERSION,
            run_at="2026-08-16T01:00:00+00:00",
        )
        self.assertTrue(result["follow"])
        self.assertEqual(result["max_depth"], 3)
        self.assertEqual(result["max_text_chars"], MAX_TEXT_CHARS)

    def test_探索条件の無い旧結果は拒否する(self):
        with self.assertRaises(MeasurementError):
            measurement_for(
                {},
                follow=True,
                model="claude-sonnet-5",
                prompt=VALID_PROMPT_VERSION,
                run_at="2026-08-16T01:00:00+00:00",
            )

    def test_後半の旧探索結果で失敗しても前半の出力を書かない(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery_dir = root / "discovery"
            out_dir = root / "out"
            discovery_dir.mkdir()
            valid = {
                "municipality": "A市", "municipality_id": "a",
                "procedure": "転入届", "procedure_id": "tennyu",
                "candidates": [],
                "measurement": build_discovery_measurement(
                    3, {1: (1, 6), 2: (3, 4), 3: (4, 3)}, 26,
                    "2026-08-16T00:00:00+00:00",
                ),
            }
            legacy = {**valid, "municipality": "B市", "municipality_id": "b"}
            legacy.pop("measurement")
            (discovery_dir / "discovery_a_tennyu.json").write_text(
                json.dumps(valid), encoding="utf-8"
            )
            (discovery_dir / "discovery_b_tennyu.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )

            with patch("extract.DISCOVERY_DIR", discovery_dir), \
                    patch("extract.OUT_DIR", out_dir), \
                    patch.object(sys, "argv", ["extract.py"]):
                with self.assertRaises(SystemExit):
                    main()

            self.assertFalse(list(out_dir.glob("*.json")))


if __name__ == "__main__":
    unittest.main()

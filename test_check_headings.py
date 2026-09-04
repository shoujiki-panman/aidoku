"""`analysis/check_headings.py` — 見出しで中身にたどれるか（2.4.6 の対応づけ）。

**適合試験ではない。** 2.4.6 は「主題又は目的を説明している」であって、
説明できているかは人が読んで決める。ここで数えるのは機械で確実に言える2つだけ。

★リンク題（2.4.4）で同じことをやって間違えている。「相談窓口」「印鑑登録」を
  欠陥として73本数えたが、中身を見たら十分わかるものだった。
  **語の一般性で意味は測れない。**
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from check_headings import GENERIC, marks, page_headings, read_pages, summarize  # noqa: E402


def h(level: int, text: str) -> dict:
    return {"level": level, "text": text}


def row(**kw) -> dict:
    base = {"municipality": "A区", "url": "https://x/a", "unreadable": False,
            "headings": 1, "no_headings": False, "empty": 0,
            "has_h1": True, "generic_not_counted": 0}
    return {**base, **kw}


class 見出しの取り出し(unittest.TestCase):
    def test_HTMLから見出しを拾う(self):
        html = "<html><body><h1>転入届</h1><h2>必要なもの</h2></body></html>"
        got = page_headings(html, "https://x/a")
        self.assertEqual([g["text"] for g in got], ["転入届", "必要なもの"])
        self.assertEqual(got[0]["level"], 1)

    def test_見出しが無ければ空(self):
        self.assertEqual(page_headings("<html><body><p>本文</p></body></html>", "u"), [])

    def test_壊れたHTMLでも落ちない(self):
        self.assertIsInstance(page_headings("<h1>途中で切れ", "u"), list)


class ページの印(unittest.TestCase):
    def test_見出しが1つも無ければ印を立てる(self):
        got = marks([])
        self.assertTrue(got["no_headings"])
        self.assertEqual(got["headings"], 0)

    def test_空の見出しを数える(self):
        got = marks([h(1, "転入届"), h(2, "")])
        self.assertEqual(got["empty"], 1)
        self.assertFalse(got["no_headings"])

    def test_h1の有無を見る(self):
        self.assertTrue(marks([h(1, "題")])["has_h1"])
        self.assertFalse(marks([h(2, "題")])["has_h1"])

    def test_一般的な見出しは欠陥として数えない(self):
        """★ここを欠陥にすると、リンク題で踏んだ間違いを繰り返す。"""
        got = marks([h(2, GENERIC[0]), h(2, "手数料")])
        self.assertEqual(got["generic_not_counted"], 1)
        self.assertEqual(got["empty"], 0)
        self.assertFalse(got["no_headings"])


class 集計(unittest.TestCase):
    def test_見出しが無いページを数える(self):
        got = summarize([row(no_headings=True, headings=0), row()])
        self.assertEqual(got["pages_without_headings"], 1)
        self.assertEqual(got["pages_without_headings_ratio"], 0.5)

    def test_空の見出しをページ数と本数で数える(self):
        got = summarize([row(empty=2), row(empty=0)])
        self.assertEqual(got["empty_headings"], 2)
        self.assertEqual(got["pages_with_empty_heading"], 1)

    def test_取得できていないページは別に数える(self):
        # ★「見出しが無い」に混ぜない。混ぜると、こちらの取りこぼしが区の欠陥に見える。
        got = summarize([row(unreadable=True, no_headings=False)])
        self.assertEqual(got["unreadable_pages"], 1)
        self.assertEqual(got["pages_without_headings"], 0)

    def test_自治体数は重複を除く(self):
        got = summarize([row(), row(url="https://x/b")])
        self.assertEqual(got["municipalities"], 1)
        self.assertEqual(got["pages"], 2)

    def test_ページが無くても割合で落ちない(self):
        self.assertEqual(summarize([])["pages_without_headings_ratio"], 0.0)


class 対象ページ(unittest.TestCase):
    def pages(self, doc: dict) -> list[tuple[str, str]]:
        import check_headings as mod
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "extractor" / "out"
            out.mkdir(parents=True)
            (out / "extract_a_tennyu.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            original, mod.ROOT = mod.ROOT, Path(tmp)
            try:
                return read_pages("tennyu")
            finally:
                mod.ROOT = original

    def test_起点と追従の両方を見る(self):
        got = self.pages({"municipality": "A区", "page": {"url": "u0"},
                          "followed_urls": ["u1"]})
        self.assertEqual(got, [("A区", "u0"), ("A区", "u1")])

    def test_起点に到達していない区は対象外(self):
        # ★読んでいないページの見出しを数えても、つまずいた証拠にはならない。
        self.assertEqual(self.pages({"municipality": "B区", "page": None}), [])


class 実データ(unittest.TestCase):
    """★対応づけただけで数が無いと職員に渡せない。3手続きぶん固定する。"""

    def summary(self, procedure: str) -> dict:
        path = ROOT / "analysis" / "out" / f"headings_{procedure}.json"
        if not path.exists():
            self.skipTest(f"未生成: {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))["summary"]

    def test_空の見出しは3手続きとも0(self):
        for proc in ("tennyu", "jidouteate", "sodaigomi"):
            with self.subTest(proc=proc):
                self.assertEqual(self.summary(proc)["empty_headings"], 0)

    def test_見出しが無いページはごくわずか(self):
        # 2.4.4 と同じく、AI読が見ている問題の主因ではない。
        for proc in ("tennyu", "jidouteate", "sodaigomi"):
            with self.subTest(proc=proc):
                self.assertLess(self.summary(proc)["pages_without_headings_ratio"], 0.05)


if __name__ == "__main__":
    unittest.main()

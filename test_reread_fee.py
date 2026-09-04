from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "analysis"))
from reread_fee import FEE_WORDS, cache_text, read_urls, summarize  # noqa: E402

HTML = "https://example.lg.jp/tennyu.html"
OTHER = "https://example.lg.jp/kokugai.html"


class FeeWords(unittest.TestCase):
    def test_手数料を表す語を拾う(self):
        for text in ("手数料は無料です", "費用はかかりません", "無料", "かかりません"):
            with self.subTest(text=text):
                self.assertTrue(FEE_WORDS.search(text))

    def test_金額の形は入れていない(self):
        # ★\d+円 を入れると児童手当の支給額の表まで拾って数が3倍になった。
        #   金額の形は答えの形ではない（plans/decisions/table-reading.md）。
        self.assertIsNone(FEE_WORDS.search("300円"))

    def test_無関係な文には当たらない(self):
        self.assertIsNone(FEE_WORDS.search("本人確認書類をお持ちください"))


class CacheText(unittest.TestCase):
    """★添付（PDF/Word/Excel）もここを通る。**中身を見て振り分ける。**

    以前はすべてHTMLとして読もうとしていたので、添付は文字化けした本文になり、
    手がかりの語に当たらず静かに落ちていた。実測で、虱潰し321ページのうち
    添付は0本だった。「その区が書いていない」と言う前に、添付も読む必要がある。
    """

    def put(self, tmp: Path, url: str, raw: bytes) -> None:
        import hashlib
        import urllib.parse
        host = tmp / urllib.parse.urlparse(url).netloc
        host.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        (host / f"{key}.html").write_bytes(raw)

    def read(self, url: str, raw: bytes) -> str | None:
        import reread_fee as mod
        with tempfile.TemporaryDirectory() as tmp:
            self.put(Path(tmp), url, raw)
            original, mod.CACHE = mod.CACHE, Path(tmp)
            try:
                return cache_text(url)
            finally:
                mod.CACHE = original

    def test_HTMLは本文を返す(self):
        got = self.read(HTML, b"<html><body><p>\xe6\x89\x8b\xe6\x95\xb0\xe6\x96\x99</p></body></html>")
        self.assertIn("手数料", got or "")

    def test_取得していないURLはNone(self):
        import reread_fee as mod
        with tempfile.TemporaryDirectory() as tmp:
            original, mod.CACHE = mod.CACHE, Path(tmp)
            try:
                self.assertIsNone(cache_text(HTML))
            finally:
                mod.CACHE = original

    def test_読めない添付はNoneを返す(self):
        # ★空文字ではなく None。「本文が空のページ」と「読めなかった」を混ぜない。
        self.assertIsNone(self.read("https://example.lg.jp/a.pdf", b"%PDF-1.4 broken"))

    def test_添付をHTMLとして読まない(self):
        # 中身がPDFなら、HTMLパーサには渡さない（渡すと化けた文字列が本文になる）。
        got = self.read("https://example.lg.jp/b.pdf", b"%PDF-1.4\n" + b"\xef\xbf\xbd" * 200)
        self.assertIsNone(got)


class ReadUrls(unittest.TestCase):
    def test_起点とリンク先を合わせる(self):
        self.assertEqual(
            read_urls({"page": {"url": HTML}, "followed_urls": [OTHER]}), {HTML, OTHER})

    def test_リンク先がnullでも落ちない(self):
        self.assertEqual(read_urls({"page": {"url": HTML}, "followed_urls": None}), {HTML})


def row(mid: str, name: str, found: bool, pages: list[dict] | None = None) -> dict:
    return {"municipality_id": mid, "municipality": name,
            "now_found": found, "pages": pages if pages is not None else []}


class Summarize(unittest.TestCase):
    def test_読み落としだった区を数える(self):
        rows = [row("a", "A区", True), row("b", "B区", False)]
        got = summarize(rows, {"a": "読めない", "b": "読めない"})
        self.assertEqual(got["newly_found"], 1)
        self.assertEqual(got["newly_found_names"], ["A区"])
        self.assertEqual(got["still_not_found"], 1)

    def test_もともと読めていた区は読み落としに数えない(self):
        # ★港区は唯一「読めた」区。ここを数えると増えたように見えて嘘になる。
        rows = [row("minato", "港区", True)]
        got = summarize(rows, {"minato": "読めた"})
        self.assertEqual(got["newly_found"], 0)
        self.assertEqual(got["already_readable"], 1)

    def test_公開判定に無い区も落ちない(self):
        got = summarize([row("x", "X区", True)], {})
        self.assertEqual(got["newly_found"], 1)

    def test_引用が本文に無い主張を別に数える(self):
        pages = [{"found": True, "verified": False}, {"found": True, "verified": True},
                 {"found": False, "verified": False}]
        got = summarize([row("a", "A区", True, pages)], {"a": "読めない"})
        self.assertEqual(got["unverified_claims"], 1)

    def test_読んだページ数を合算する(self):
        rows = [row("a", "A区", False, [{"found": False, "verified": False}] * 3),
                row("b", "B区", False, [{"found": False, "verified": False}] * 2)]
        self.assertEqual(summarize(rows, {})["pages_read"], 5)

    def test_1本も読まなかった区も自治体数に入る(self):
        # 0本の区（品川・豊島）を落とすと、母数が変わって割合が狂う。
        self.assertEqual(summarize([row("a", "A区", False)], {})["municipalities"], 1)


if __name__ == "__main__":
    unittest.main()

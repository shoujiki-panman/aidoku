"""`crawler/discover.py` の `link_filter` — どのリンクを辿ってよいか。

**なぜ要るか**: 以前は `page_host in href` と書いていた。**URL全体への部分一致**なので、
区のホスト名を中に含むだけの別ホスト（はてなブックマーク・翻訳サービス・SNSの共有リンク）を
「同一ホスト」として通していた。**同一ホスト制限がそもそも効いていなかった。**

METHOD §4-3 は「同一ホストしか選べないのだから、除外された側は見えない」と書いていたが、
除外されていなかった。候補 2,102本中 154本が別ホストだった。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "crawler"))
from discover import link_filter  # noqa: E402

TOP = "https://www.city.adachi.tokyo.jp/"
HOST = "www.city.adachi.tokyo.jp"


class 同一ホストだけ(unittest.TestCase):
    def setUp(self):
        self.allowed = link_filter(TOP, False)

    def test_同じホストは通す(self):
        self.assertTrue(self.allowed(HOST, "https://www.city.adachi.tokyo.jp/gomi/a.html"))

    def test_別ホストは弾く(self):
        self.assertFalse(self.allowed(HOST, "https://example.com/a.html"))

    def test_ホスト名を中に含む別ホストを弾く(self):
        """★これが通っていた。はてなブックマークが候補に9本入っていた。"""
        for href in (
            "https://b.hatena.ne.jp/entry/https://www.city.adachi.tokyo.jp/gomi/a.html",
            "https://translation2.j-server.com/ns/tl.cgi?url=https://www.city.adachi.tokyo.jp/",
            "https://twitter.com/share?url=https://www.city.adachi.tokyo.jp/gomi/",
            "https://evil.example.com/?x=www.city.adachi.tokyo.jp",
        ):
            with self.subTest(href=href[:40]):
                self.assertFalse(self.allowed(HOST, href))

    def test_似た名前のホストを弾く(self):
        # ★前方一致にすると通ってしまう形。
        self.assertFalse(self.allowed(HOST, "https://www.city.adachi.tokyo.jp.evil.com/a"))

    def test_サブドメインは既定では弾く(self):
        self.assertFalse(self.allowed(HOST, "https://kyoiku.city.adachi.tokyo.jp/a.html"))


class サブドメインを許すとき(unittest.TestCase):
    """東京都は局ごとにホストが分かれていて、同一ホストだと1歩も進めない。"""

    def setUp(self):
        self.allowed = link_filter("https://www.metro.tokyo.lg.jp/", True)

    def test_親ドメイン配下を通す(self):
        self.assertTrue(self.allowed("www.metro.tokyo.lg.jp",
                                     "https://seikatubunka.metro.tokyo.lg.jp/a.html"))

    def test_親ドメインそのものを通す(self):
        self.assertTrue(self.allowed("www.metro.tokyo.lg.jp",
                                     "https://metro.tokyo.lg.jp/a.html"))

    def test_外は弾く(self):
        self.assertFalse(self.allowed("www.metro.tokyo.lg.jp", "https://example.com/a"))

    def test_親ドメインを中に含む別ホストを弾く(self):
        self.assertFalse(self.allowed(
            "www.metro.tokyo.lg.jp",
            "https://b.hatena.ne.jp/entry/https://www.metro.tokyo.lg.jp/a.html"))

    def test_親ドメインで終わる別ドメインを弾く(self):
        # ★endswith だけだと "evilmetro.tokyo.lg.jp" が通る形。点を必ず付ける。
        self.assertFalse(self.allowed("www.metro.tokyo.lg.jp",
                                      "https://evilmetro.tokyo.lg.jp/a.html"))


if __name__ == "__main__":
    unittest.main()

"""リンクを辿ってよいかの判定（link_filter）のテスト。

なぜテストを置くか: この判定を緩めると、**測る対象そのものが変わる。**
うっかり全ドメインを辿れるようにすると、自治体サイトを測っているつもりで
外部サイトを測ることになり、点数の意味が壊れる。
"""

from __future__ import annotations

import unittest

from discover import link_filter


class 既定は同一ホストのみ(unittest.TestCase):
    """23区はこれ。2026-08-13 時点、採点した69ページすべてがトップと同じホスト。"""

    def setUp(self) -> None:
        self.f = link_filter("https://www.city.setagaya.tokyo.jp/", False)
        self.host = "www.city.setagaya.tokyo.jp"

    def test_同じホストは辿る(self):
        self.assertTrue(self.f(self.host, "https://www.city.setagaya.tokyo.jp/kurashi/a.html"))

    def test_外部サイトは辿らない(self):
        self.assertFalse(self.f(self.host, "https://sodai-uketsuke.example.jp/x"))

    def test_サブドメインも辿らない(self):
        # 既定では親ドメイン配下でも辿らない。ここを変えると23区の結果が変わる
        self.assertFalse(self.f(self.host, "https://www.tax.city.setagaya.tokyo.jp/a"))


class 東京都はサブドメインを辿る(unittest.TestCase):
    """東京都は局ごとにホストが分かれているので、同一ホストだと1歩も進めない。

    これはサイトの性質ではなくこちらの制限なので、targets.json 側で
    allow_subdomains を立てて親ドメイン配下だけ辿れるようにしている。
    """

    def setUp(self) -> None:
        self.f = link_filter("https://www.metro.tokyo.lg.jp/", True)
        self.host = "www.metro.tokyo.lg.jp"

    def test_局のサイトを辿る(self):
        for url in [
            "https://www.tax.metro.tokyo.lg.jp/tozei_nouzei",
            "https://www.kyoiku.metro.tokyo.lg.jp/admission/tuition",
            "https://www.seikatubunka.metro.tokyo.lg.jp/passport/guide",
            "https://www.juutakuseisaku.metro.tokyo.lg.jp/toei_online",
        ]:
            with self.subTest(url=url):
                self.assertTrue(self.f(self.host, url))

    def test_親ドメインそのものも辿る(self):
        self.assertTrue(self.f(self.host, "https://metro.tokyo.lg.jp/a"))

    def test_外郭団体は辿らない(self):
        # 東京都中小企業振興公社。都のページからリンクされているが別法人・別ドメイン
        self.assertFalse(self.f(self.host, "https://www.tokyo-kosha.or.jp/support/josei/"))

    def test_区市町村は辿らない(self):
        self.assertFalse(self.f(self.host, "https://www.city.nerima.tokyo.jp/z"))

    def test_接尾辞を装った別ドメインは辿らない(self):
        # metro.tokyo.lg.jp で終わっているように見えるが別ドメイン。
        # 単純な endswith だとここを通してしまう
        self.assertFalse(self.f(self.host, "https://evil-metro.tokyo.lg.jp.attacker.example/"))

    def test_名前が似ているだけのドメインは辿らない(self):
        self.assertFalse(self.f(self.host, "https://notmetro.tokyo.lg.jp/a"))


if __name__ == "__main__":
    unittest.main()

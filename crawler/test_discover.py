"""リンクを辿ってよいかの判定（link_filter）のテスト。

なぜテストを置くか: この判定を緩めると、**測る対象そのものが変わる。**
うっかり全ドメインを辿れるようにすると、自治体サイトを測っているつもりで
外部サイトを測ることになり、点数の意味が壊れる。
"""

from __future__ import annotations

import unittest

from discover import discover, link_filter

from measurement import build_discovery_measurement


def measurement() -> dict:
    return build_discovery_measurement(
        3, {1: (1, 6), 2: (3, 4), 3: (4, 3)}, 26,
        "2026-08-16T00:00:00+00:00",
    )


class FailedResult:
    status = 0
    from_cache = False
    blocked_by_robots = False
    body_path = None
    last_modified = None
    etag = None
    error = "取得失敗"


class FailedFetcher:
    def fetch(self, _url: str) -> FailedResult:
        return FailedResult()


class FakeResult:
    status = 200
    from_cache = True
    blocked_by_robots = False
    body_path = "cached.html"
    content_type = "text/html"
    error = None

    def __init__(self, body: str, *, last_modified: str | None = None,
                 etag: str | None = None):
        self._body = body
        self.last_modified = last_modified
        self.etag = etag

    def body(self) -> str:
        return self._body


class SuccessFetcher:
    def fetch(self, _url: str) -> FakeResult:
        return FakeResult("<html><body>トップページ</body></html>")


class 測定条件の出力(unittest.TestCase):
    def setUp(self) -> None:
        self.measurement = measurement()
        self.municipality = {
            "name": "テスト区", "id": "test", "top_url": "https://example.jp"
        }
        self.procedure = {
            "name": "転入届", "id": "tennyu", "keywords": {}
        }

    def test_到達失敗でも探索条件とIDを残す(self):
        result = discover(
            self.municipality,
            self.procedure,
            FailedFetcher(),
            self.measurement,
        )
        self.assertEqual(result["municipality_id"], "test")
        self.assertEqual(result["procedure_id"], "tennyu")
        self.assertEqual(result["measurement"], self.measurement)

    def test_到達成功でも探索条件を残す(self):
        result = discover(
            self.municipality,
            self.procedure,
            SuccessFetcher(),
            self.measurement,
        )
        self.assertNotIn("error", result)
        self.assertEqual(result["measurement"], self.measurement)


class PageFetcher:
    def fetch(self, url: str) -> FakeResult:
        if url == "https://example.jp/":
            return FakeResult('<a href="/tennyu">転入届</a>')
        return FakeResult("""
            <head>
              <title>転入届</title>
              <meta name="description" content="転入届の案内">
              <meta property="og:type" content="article">
              <script type="application/ld+json">
                {"dateModified":"2026-08-16", "datePublished":"2026-08-01"}
              </script>
            </head>
            <body><h1>転入届</h1><h2>必要書類</h2><p>本文です。</p></body>
        """, last_modified="Sun, 16 Aug 2026 00:00:00 GMT", etag='"v2"')


class 正規化結果の出力(unittest.TestCase):
    def test_候補へページ構造と更新情報を残す(self):
        result = discover(
            {"name": "テスト区", "id": "test", "top_url": "https://example.jp/"},
            {"name": "転入届", "id": "tennyu", "keywords": {
                "strong": ["転入届"], "weak": [], "url_hints": [],
            }},
            PageFetcher(),
            measurement(),
        )
        candidate = result["candidates"][0]
        self.assertEqual(candidate["title"], "転入届")
        self.assertEqual(candidate["meta"], {
            "description": "転入届の案内", "og:type": "article",
        })
        self.assertEqual(candidate["headings"], [
            {"level": 1, "text": "転入届"},
            {"level": 2, "text": "必要書類"},
        ])
        self.assertEqual(candidate["date_modified"], ["2026-08-16"])
        self.assertEqual(candidate["date_published"], ["2026-08-01"])
        self.assertEqual(candidate["last_modified"], "Sun, 16 Aug 2026 00:00:00 GMT")
        self.assertEqual(candidate["etag"], '"v2"')


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

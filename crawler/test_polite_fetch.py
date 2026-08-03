"""取得層のテスト — 対外的に約束している「行儀」が本当に守られているかを確かめる。

ここで守りたいのは README とフォーム提出内容に書いた4つ:
  1. robots.txt を読み、Disallow なら取得しない
  2. robots.txt が読めないときは、取得しない側に倒す
  3. 同一ドメインへの間隔は3秒以上（Crawl-delay がそれより長ければ従う）
  4. 一度取得したページは再取得しない

ネットワークには一切出ない。urlopen を差し替えて確かめる。
標準ライブラリのみ（外部依存を増やさない方針のため）。

実行: python3 -m unittest discover -s crawler -p 'test_*.py'
"""

from __future__ import annotations

import io
import sys
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import polite_fetch  # noqa: E402
from polite_fetch import CONTACT, USER_AGENT, PoliteFetcher  # noqa: E402


def _resp(body: str, *, status: int = 200, content_type: str = "text/html; charset=utf-8"):
    """urlopen が返すコンテキストマネージャの最小の偽物。"""
    headers = Message()
    headers["Content-Type"] = content_type

    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    r = _R(body.encode("utf-8"))
    r.headers = headers
    r.status = status
    r.geturl = lambda: "https://example.lg.jp/page.html"
    return r


def _http_error(code: int):
    return urllib.error.HTTPError("https://example.lg.jp/robots.txt", code, "err", None, None)


class RobotsTest(unittest.TestCase):
    """1・2: robots.txt の読み方。取れないときに取得へ倒さないこと。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        # 間隔0にして待ち時間を消す。待ちの検証は IntervalTest で別に行う
        self.f = PoliteFetcher(cache_dir=Path(self.tmp.name), min_interval=0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_disallowは取得しない(self):
        robots = "User-agent: *\nDisallow: /kurashi/\n"
        with mock.patch.object(urllib.request, "urlopen", return_value=_resp(robots)):
            self.assertFalse(self.f.allowed("https://example.lg.jp/kurashi/tennyu.html"))
            self.assertTrue(self.f.allowed("https://example.lg.jp/other/page.html"))

    def test_robotsが404なら全許可(self):
        with mock.patch.object(urllib.request, "urlopen", side_effect=_http_error(404)):
            self.assertTrue(self.f.allowed("https://example.lg.jp/kurashi/tennyu.html"))

    def test_robotsが403なら取得しない(self):
        with mock.patch.object(urllib.request, "urlopen", side_effect=_http_error(403)):
            self.assertFalse(self.f.allowed("https://example.lg.jp/kurashi/tennyu.html"))

    def test_robotsが500なら取得しない(self):
        """サーバ側の不調で robots.txt が読めないとき、許可へ倒してはいけない。

        polite_fetch.py のコメントは「404 は全許可、それ以外のエラーは保守的に全禁止」
        と宣言している。robots.txt の仕様（RFC 9309）でも 5xx は取得を控える扱い。
        """
        with mock.patch.object(urllib.request, "urlopen", side_effect=_http_error(500)):
            self.assertFalse(self.f.allowed("https://example.lg.jp/kurashi/tennyu.html"))

    def test_robotsが503なら取得しない(self):
        with mock.patch.object(urllib.request, "urlopen", side_effect=_http_error(503)):
            self.assertFalse(self.f.allowed("https://example.lg.jp/kurashi/tennyu.html"))

    def test_通信そのものが失敗したら取得しない(self):
        with mock.patch.object(urllib.request, "urlopen", side_effect=OSError("timeout")):
            self.assertFalse(self.f.allowed("https://example.lg.jp/kurashi/tennyu.html"))

    def test_robotsは一度だけ読む(self):
        robots = "User-agent: *\nDisallow:\n"
        with mock.patch.object(urllib.request, "urlopen", return_value=_resp(robots)) as m:
            self.f.allowed("https://example.lg.jp/a.html")
            self.f.allowed("https://example.lg.jp/b.html")
            self.assertEqual(m.call_count, 1, "同じオリジンの robots.txt を2回取りに行っている")

    def test_disallowなら本文を保存しない(self):
        robots = "User-agent: *\nDisallow: /\n"
        with mock.patch.object(urllib.request, "urlopen", return_value=_resp(robots)):
            r = self.f.fetch("https://example.lg.jp/kurashi/tennyu.html")
        self.assertTrue(r.blocked_by_robots)
        self.assertIsNone(r.body_path)
        self.assertEqual(r.body(), "")


class IntervalTest(unittest.TestCase):
    """3: 間隔。3秒未満で連続して叩かないこと。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_既定の間隔は3秒(self):
        self.assertEqual(polite_fetch.MIN_INTERVAL_SEC, 3.0)

    def test_同一ドメインへの2回目は3秒待つ(self):
        f = PoliteFetcher(cache_dir=Path(self.tmp.name))
        robots = "User-agent: *\nDisallow:\n"
        slept: list[float] = []
        with mock.patch.object(urllib.request, "urlopen", return_value=_resp(robots)), \
             mock.patch.object(polite_fetch.time, "sleep", side_effect=slept.append):
            f.allowed("https://example.lg.jp/a.html")
            f._wait("example.lg.jp")
        self.assertTrue(slept, "2回目のリクエストで一度も待っていない")
        self.assertGreater(sum(slept), 0)

    def test_crawl_delayが長ければそちらに従う(self):
        f = PoliteFetcher(cache_dir=Path(self.tmp.name))
        robots = "User-agent: *\nCrawl-delay: 10\nDisallow:\n"
        with mock.patch.object(urllib.request, "urlopen", return_value=_resp(robots)):
            self.assertEqual(f.crawl_delay("https://example.lg.jp/a.html"), 10.0)

    def test_crawl_delayが短くても3秒は下回らない(self):
        f = PoliteFetcher(cache_dir=Path(self.tmp.name))
        robots = "User-agent: *\nCrawl-delay: 1\nDisallow:\n"
        with mock.patch.object(urllib.request, "urlopen", return_value=_resp(robots)):
            self.assertEqual(f.crawl_delay("https://example.lg.jp/a.html"), 3.0)


class CacheTest(unittest.TestCase):
    """4: 一度取ったら再取得しない。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.f = PoliteFetcher(cache_dir=Path(self.tmp.name), min_interval=0)

    def tearDown(self):
        self.tmp.cleanup()

    def _fetch_once(self, body="<html>本文</html>"):
        robots = "User-agent: *\nDisallow:\n"

        def _side_effect(req, *a, **kw):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            return _resp(robots if url.endswith("/robots.txt") else body)

        with mock.patch.object(urllib.request, "urlopen", side_effect=_side_effect) as m:
            r = self.f.fetch("https://example.lg.jp/page.html")
        return r, m

    def test_2回目はキャッシュから返り通信しない(self):
        first, _ = self._fetch_once()
        self.assertFalse(first.from_cache)
        self.assertEqual(first.body(), "<html>本文</html>")

        with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("再取得した")) as m:
            second = self.f.fetch("https://example.lg.jp/page.html")
        self.assertTrue(second.from_cache)
        self.assertEqual(m.call_count, 0)

    def test_refreshを付けたときだけ取り直す(self):
        self._fetch_once()
        _, m = self.f, None
        robots = "User-agent: *\nDisallow:\n"

        def _side_effect(req, *a, **kw):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            return _resp(robots if url.endswith("/robots.txt") else "<html>新しい</html>")

        with mock.patch.object(urllib.request, "urlopen", side_effect=_side_effect):
            r = self.f.fetch("https://example.lg.jp/page.html", refresh=True)
        self.assertFalse(r.from_cache)
        self.assertEqual(r.body(), "<html>新しい</html>")


class UserAgentTest(unittest.TestCase):
    """User-Agent に連絡先を明記する、という約束。"""

    def test_連絡先が空でない(self):
        self.assertTrue(CONTACT.strip(), "CONTACT が空のまま。本番クロールしてはいけない")

    def test_UAにプロジェクト名と連絡先が入っている(self):
        self.assertIn("TokyoAgentReadinessBot", USER_AGENT)
        self.assertIn(CONTACT, USER_AGENT)


if __name__ == "__main__":
    unittest.main(verbosity=2)

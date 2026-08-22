"""見張り（条件付きGET）のテスト。ネットワークには触らない。

実行: python3 -m unittest discover -s crawler -p 'test_*.py'
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import check_pages  # noqa: E402
import polite_fetch  # noqa: E402
from polite_fetch import CheckResult, FetchResult, PoliteFetcher  # noqa: E402

URL = "https://example.lg.jp/tennyu.html"


# テストはネットワークに出ない。SSRFガードの名前解決だけ偽物を渡す
# （example.lg.jp は実在しないので、素で通すとガードに弾かれる）。
def _fake_resolve(host):
    return ["93.184.216.34"]


def cached(etag: str | None = '"v1"', last_modified: str | None = None) -> FetchResult:
    return FetchResult(
        url=URL, final_url=URL, status=200, content_type="text/html",
        fetched_at="2026-08-01T00:00:00+00:00", from_cache=True,
        blocked_by_robots=False, body_path=None,
        last_modified=last_modified, etag=etag)


class _Resp:
    def __init__(self, status=200, headers=None):
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = PoliteFetcher(cache_dir=Path(self.tmp.name), min_interval=0, resolve=_fake_resolve)
        self.addCleanup(self.tmp.cleanup)

    def check(self, *, prev, opener=None, allowed=True):
        with mock.patch.object(PoliteFetcher, "cached", return_value=prev), \
             mock.patch.object(PoliteFetcher, "allowed", return_value=allowed), \
             mock.patch.object(polite_fetch.urllib.request, "urlopen",
                               side_effect=opener or (lambda *a, **k: _Resp())):
            return self.f.check(URL)

    def test_304なら変わっていない(self):
        def raise304(*a, **k):
            raise urllib.error.HTTPError(URL, 304, "Not Modified", {}, None)
        r = self.check(prev=cached(), opener=raise304)
        self.assertEqual((r.status, r.changed), (304, False))
        self.assertIn("変わっていない", r.reason)

    def test_200なら変わった(self):
        r = self.check(prev=cached(), opener=lambda *a, **k: _Resp(200, {"ETag": '"v2"'}))
        self.assertEqual((r.status, r.changed), (200, True))
        self.assertEqual(r.etag, '"v2"')

    def test_前回の記録が無ければ判定しない(self):
        r = self.check(prev=None)
        self.assertIsNone(r.changed)
        self.assertIn("前回の記録が無い", r.reason)

    def test_ETagもLast_Modifiedも無ければ判定しない(self):
        r = self.check(prev=cached(etag=None, last_modified=None))
        self.assertIsNone(r.changed)
        self.assertIn("比べられない", r.reason)

    def test_Last_Modifiedだけでも確認する(self):
        def raise304(*a, **k):
            raise urllib.error.HTTPError(URL, 304, "Not Modified", {}, None)
        r = self.check(prev=cached(etag=None, last_modified="Fri, 01 Aug 2026 00:00:00 GMT"),
                       opener=raise304)
        self.assertIs(r.changed, False)

    def test_robotsで許可されていなければ確認しない(self):
        def fail(*a, **k):
            raise AssertionError("robots不許可なのに通信した")
        r = self.check(prev=cached(), opener=fail, allowed=False)
        self.assertIsNone(r.changed)
        self.assertIn("robots", r.reason)

    def test_404はページが消えた変化として扱う(self):
        """『判定できない』に混ぜると通知されず、根拠URLが切れたまま気づけない。"""
        def raise404(*a, **k):
            raise urllib.error.HTTPError(URL, 404, "Not Found", {}, None)
        r = self.check(prev=cached(), opener=raise404)
        self.assertIs(r.changed, True)
        self.assertIs(r.gone, True)
        self.assertEqual(r.status, 404)
        self.assertIn("無くなった", r.reason)

    def test_410も消えた扱い(self):
        def raise410(*a, **k):
            raise urllib.error.HTTPError(URL, 410, "Gone", {}, None)
        r = self.check(prev=cached(), opener=raise410)
        self.assertIs(r.gone, True)

    def test_5xxは消えたと決めつけない(self):
        """相手側の一時的な事情のことが多い。"""
        for code in (500, 502, 503):
            def raise5xx(*a, _c=code, **k):
                raise urllib.error.HTTPError(URL, _c, "Server Error", {}, None)
            r = self.check(prev=cached(), opener=raise5xx)
            self.assertIsNone(r.changed, code)
            self.assertIs(r.gone, False, code)

    def test_403も消えた扱いにしない(self):
        """見せてもらえないだけで、ページが無いとは限らない。"""
        def raise403(*a, **k):
            raise urllib.error.HTTPError(URL, 403, "Forbidden", {}, None)
        r = self.check(prev=cached(), opener=raise403)
        self.assertIsNone(r.changed)
        self.assertIs(r.gone, False)

    def test_変化なしのときgoneは立たない(self):
        def raise304(*a, **k):
            raise urllib.error.HTTPError(URL, 304, "Not Modified", {}, None)
        r = self.check(prev=cached(), opener=raise304)
        self.assertIs(r.gone, False)

    def test_通信失敗でも落ちない(self):
        def boom(*a, **k):
            raise OSError("接続できない")
        r = self.check(prev=cached(), opener=boom)
        self.assertIsNone(r.changed)
        self.assertIn("OSError", r.error)

    def test_条件付きヘッダを実際に送る(self):
        sent = {}

        def capture(req, *a, **k):
            sent.update({k.lower(): v for k, v in req.header_items()})
            raise urllib.error.HTTPError(URL, 304, "Not Modified", {}, None)
        self.check(prev=cached(etag='"v1"', last_modified="Fri, 01 Aug 2026 00:00:00 GMT"),
                   opener=capture)
        self.assertEqual(sent.get("If-none-match".lower()), '"v1"')
        self.assertEqual(sent.get("If-modified-since".lower()),
                         "Fri, 01 Aug 2026 00:00:00 GMT")

    def test_確認ではキャッシュを書き換えない(self):
        def raise304(*a, **k):
            raise urllib.error.HTTPError(URL, 304, "Not Modified", {}, None)
        before = sorted(p.name for p in Path(self.tmp.name).rglob("*"))
        self.check(prev=cached(), opener=raise304)
        after = sorted(p.name for p in Path(self.tmp.name).rglob("*"))
        self.assertEqual(before, after)


class HashFallbackTest(unittest.TestCase):
    """ETag も Last-Modified も返さないサイト（動的生成ページ）の判定。

    2026-08-17に渋谷区・品川区で実測: どちらもCloudFront配下の動的生成で
    ヘッダを返さないが、本文は2回取っても**バイト単位で同一**だった。
    """

    BODY = "<html>転入届は14日以内</html>"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.f = PoliteFetcher(cache_dir=self.dir, min_interval=0, resolve=_fake_resolve)
        self.addCleanup(self.tmp.cleanup)

    def prev_with_body(self, body: str, stored_hash: str | None = None):
        p = self.dir / "prev.html"
        p.write_text(body, encoding="utf-8")
        return FetchResult(
            url=URL, final_url=URL, status=200, content_type="text/html",
            fetched_at="2026-08-01T00:00:00+00:00", from_cache=True,
            blocked_by_robots=False, body_path=str(p),
            last_modified=None, etag=None, content_hash=stored_hash)

    def check(self, prev, served: str):
        class Resp(_Resp):
            def read(self_inner):
                return served.encode("utf-8")

            def get_content_charset(self_inner):
                return "utf-8"
        resp = Resp(200, {})
        resp.headers = {}
        with mock.patch.object(PoliteFetcher, "cached", return_value=prev), \
             mock.patch.object(PoliteFetcher, "allowed", return_value=True), \
             mock.patch.object(polite_fetch, "_decode", return_value=served), \
             mock.patch.object(polite_fetch.urllib.request, "urlopen",
                               side_effect=lambda *a, **k: resp):
            return self.f.check(URL)

    def test_本文が同じなら変わっていない(self):
        r = self.check(self.prev_with_body(self.BODY), self.BODY)
        self.assertIs(r.changed, False)
        self.assertIn("ハッシュが前回と同じ", r.reason)

    def test_本文が違えば変わった(self):
        r = self.check(self.prev_with_body(self.BODY), self.BODY + "追記")
        self.assertIs(r.changed, True)
        self.assertIn("ハッシュが前回と違う", r.reason)

    def test_記録済みハッシュがあればそれを使う(self):
        """キャッシュ本文から計算し直さず、記録された指紋をそのまま使う。"""
        fingerprint = polite_fetch.content_fingerprint(self.BODY, URL)
        prev = self.prev_with_body("別の本文", stored_hash=fingerprint)
        r = self.check(prev, self.BODY)
        self.assertIs(r.changed, False)

    def test_生HTMLだけが違っても本文が同じなら変わっていない(self):
        """リクエストごとに変わるIDで偽陽性を出さない（2026-08-17 渋谷区の実測）。"""
        old = '<html><script src="x.js" targetId="search-input-31748057"></script>'\
              '<body><p>転入届は14日以内</p></body></html>'
        new = old.replace("31748057", "31964550")
        self.assertNotEqual(polite_fetch.sha256_of(old), polite_fetch.sha256_of(new))
        r = self.check(self.prev_with_body(old), new)
        self.assertIs(r.changed, False)

    def test_本文もハッシュも無ければ判定しない(self):
        prev = FetchResult(
            url=URL, final_url=URL, status=200, content_type="", fetched_at="t",
            from_cache=True, blocked_by_robots=False, body_path=None)
        with mock.patch.object(PoliteFetcher, "cached", return_value=prev), \
             mock.patch.object(PoliteFetcher, "allowed", return_value=True), \
             mock.patch.object(polite_fetch.urllib.request, "urlopen",
                               side_effect=AssertionError("通信してはいけない")):
            r = self.f.check(URL)
        self.assertIsNone(r.changed)
        self.assertIn("どれも残っていない", r.reason)

    def test_ヘッダがあるサイトではハッシュ経路に入らない(self):
        """ETagがあるなら条件付きGETのまま。本文を落としに行かない。"""
        prev = FetchResult(
            url=URL, final_url=URL, status=200, content_type="", fetched_at="t",
            from_cache=True, blocked_by_robots=False, body_path=None, etag='"v1"')

        def raise304(*a, **k):
            raise urllib.error.HTTPError(URL, 304, "Not Modified", {}, None)
        with mock.patch.object(PoliteFetcher, "cached", return_value=prev), \
             mock.patch.object(PoliteFetcher, "allowed", return_value=True), \
             mock.patch.object(polite_fetch.urllib.request, "urlopen", side_effect=raise304):
            r = self.f.check(URL)
        self.assertEqual(r.status, 304)


class BodyHashTest(unittest.TestCase):
    def test_記録が無くてもキャッシュ本文から計算できる(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.html"
            p.write_text("本文", encoding="utf-8")
            r = FetchResult(url=URL, final_url=URL, status=200, content_type="",
                            fetched_at="t", from_cache=True, blocked_by_robots=False,
                            body_path=str(p))
            self.assertEqual(r.body_hash(), polite_fetch.sha256_of("本文"))

    def test_ファイルが無ければNone(self):
        r = FetchResult(url=URL, final_url=URL, status=200, content_type="",
                        fetched_at="t", from_cache=True, blocked_by_robots=False,
                        body_path="/存在しない/a.html")
        self.assertIsNone(r.body_hash())


class SummarizeTest(unittest.TestCase):
    def items(self, *changed):
        return [{"changed": c, "gone": False} for c in changed]

    def test_3種類を数え分ける(self):
        s = check_pages.summarize(self.items(True, False, False, None))
        self.assertEqual((s["total"], s["changed"], s["unchanged"], s["unknown"]),
                         (4, 1, 2, 1))

    def test_見出しに件数が入る(self):
        s = check_pages.summarize(self.items(True, False))
        self.assertIn("2ページを確認", s["headline"])
        self.assertIn("1件", s["headline"])

    def test_空でも落ちない(self):
        s = check_pages.summarize([])
        self.assertEqual(s["total"], 0)
        self.assertIn("0ページ", s["headline"])

    def test_消えたページは内数として別に数える(self):
        s = check_pages.summarize([
            {"changed": True, "gone": True},
            {"changed": True, "gone": False},
            {"changed": False, "gone": False},
        ])
        self.assertEqual((s["changed"], s["gone"], s["edited"]), (2, 1, 1))

    def test_消えたページがあれば見出しの先頭で言う(self):
        s = check_pages.summarize([{"changed": True, "gone": True}])
        self.assertIn("1件が消えました", s["headline"])

    def test_消えたページが無ければ見出しに出さない(self):
        s = check_pages.summarize(self.items(True, False))
        self.assertNotIn("消えました", s["headline"])


class PrimeTest(unittest.TestCase):
    """比較材料が無いページの土台作り。既定では走らない（--prime のときだけ）。"""

    TARGET = {"municipality_id": "x", "municipality": "X区",
              "procedure_id": "tennyu", "procedure": "転入届", "url": URL}
    NO_BASE = CheckResult(url=URL, status=0, changed=None, checked_at="t",
                          reason="前回のETagもLast-Modifiedも記録が無いので比べられない")

    def run_with(self, prime_missing):
        fetched = []
        with mock.patch.object(check_pages, "targets", return_value=[self.TARGET]), \
             mock.patch.object(PoliteFetcher, "check", return_value=self.NO_BASE), \
             mock.patch.object(PoliteFetcher, "fetch",
                               side_effect=lambda u, **k: fetched.append((u, k))):
            report = check_pages.run(["tennyu"], PoliteFetcher(cache_dir=Path("/tmp/none"), resolve=_fake_resolve),
                                     prime_missing=prime_missing)
        return report, fetched

    def test_既定では取り直さない(self):
        _, fetched = self.run_with(False)
        self.assertEqual(fetched, [])

    def test_primeを付けたときだけ取り直す(self):
        report, fetched = self.run_with(True)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0][0], URL)
        self.assertTrue(fetched[0][1]["refresh"])
        self.assertIn("土台作り", report["items"][0]["reason"])

    def test_土台作りの回は変化を断定しない(self):
        report, _ = self.run_with(True)
        self.assertIsNone(report["items"][0]["changed"])

    def test_判定できた回はprimeしない(self):
        ok = CheckResult(url=URL, status=304, changed=False, checked_at="t", reason="304")
        fetched = []
        with mock.patch.object(check_pages, "targets", return_value=[self.TARGET]), \
             mock.patch.object(PoliteFetcher, "check", return_value=ok), \
             mock.patch.object(PoliteFetcher, "fetch",
                               side_effect=lambda u, **k: fetched.append(u)):
            check_pages.run(["tennyu"], PoliteFetcher(cache_dir=Path("/tmp/none"), resolve=_fake_resolve),
                            prime_missing=True)
        self.assertEqual(fetched, [])


class ReportTest(unittest.TestCase):
    """出力JSONの形を固定する。画面はこれを読む。"""

    def test_失敗しても必ずJSONを書く(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site-status.json"
            with mock.patch.object(check_pages, "run", side_effect=RuntimeError("こわれた")):
                check_pages.main(["--out", str(out)])
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("checked_at", report)
            self.assertEqual(report["items"], [])
            self.assertIn("RuntimeError", report["error"])
            self.assertIn("確認できませんでした", report["summary"]["headline"])

    def test_出力に確認時刻と要約と明細がある(self):
        fake = CheckResult(url=URL, status=304, changed=False,
                           checked_at="2026-08-17T00:00:00+00:00", reason="304")
        with mock.patch.object(check_pages, "targets",
                               return_value=[{"municipality_id": "x", "municipality": "X区",
                                              "procedure_id": "tennyu", "procedure": "転入届",
                                              "url": URL}]), \
             mock.patch.object(PoliteFetcher, "check", return_value=fake):
            report = check_pages.run(["tennyu"], PoliteFetcher(cache_dir=Path("/tmp/none"), resolve=_fake_resolve))
        self.assertEqual(set(report) >= {"checked_at", "summary", "items", "_about"}, True)
        self.assertEqual(report["items"][0]["municipality"], "X区")
        self.assertIs(report["items"][0]["changed"], False)

    def test_changedはtrueでも悪化を意味しないと書いてある(self):
        with mock.patch.object(check_pages, "targets", return_value=[]):
            report = check_pages.run([], PoliteFetcher(cache_dir=Path("/tmp/none"), resolve=_fake_resolve))
        self.assertIn("悪くなったという意味ではない", report["_about"])


if __name__ == "__main__":
    unittest.main()


class HistoryDoesNotEscape(unittest.TestCase):
    """履歴の既定が実ファイルを指していて、テストが本物を汚した回帰。

    main() を --out だけで呼んだとき、履歴が --out の隣に出ること。
    リポジトリの web/data/history/ に書かないこと。
    """

    def test_履歴はoutの隣に出る(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site-status.json"
            with mock.patch.object(check_pages, "run", side_effect=RuntimeError("boom")):
                check_pages.main(["--out", str(out)])
            hist = out.parent / "history" / "site-status.jsonl"
            self.assertTrue(hist.exists(), "--out の隣に履歴が出ていない")
            self.assertEqual(len(hist.read_text(encoding="utf-8").strip().splitlines()), 1)

    def test_空文字なら履歴を残さない(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site-status.json"
            with mock.patch.object(check_pages, "run", side_effect=RuntimeError("boom")):
                check_pages.main(["--out", str(out), "--history", ""])
            self.assertFalse((out.parent / "history").exists())

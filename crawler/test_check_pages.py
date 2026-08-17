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
        self.f = PoliteFetcher(cache_dir=Path(self.tmp.name), min_interval=0)
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

    def test_404は変化と断定しない(self):
        def raise404(*a, **k):
            raise urllib.error.HTTPError(URL, 404, "Not Found", {}, None)
        r = self.check(prev=cached(), opener=raise404)
        self.assertIsNone(r.changed)
        self.assertEqual(r.status, 404)

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


class SummarizeTest(unittest.TestCase):
    def items(self, *changed):
        return [{"changed": c} for c in changed]

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
            report = check_pages.run(["tennyu"], PoliteFetcher(cache_dir=Path("/tmp/none")),
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
            check_pages.run(["tennyu"], PoliteFetcher(cache_dir=Path("/tmp/none")),
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
            report = check_pages.run(["tennyu"], PoliteFetcher(cache_dir=Path("/tmp/none")))
        self.assertEqual(set(report) >= {"checked_at", "summary", "items", "_about"}, True)
        self.assertEqual(report["items"][0]["municipality"], "X区")
        self.assertIs(report["items"][0]["changed"], False)

    def test_changedはtrueでも悪化を意味しないと書いてある(self):
        with mock.patch.object(check_pages, "targets", return_value=[]):
            report = check_pages.run([], PoliteFetcher(cache_dir=Path("/tmp/none")))
        self.assertIn("悪くなったという意味ではない", report["_about"])


if __name__ == "__main__":
    unittest.main()

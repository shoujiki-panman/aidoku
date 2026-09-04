"""採点しなかった候補の走査のテスト。

ネットワークにもキャッシュにも触らない。`cached_text` を差し替えて純粋に判定だけを見る。

実行: python3 -m unittest discover -s analysis -p 'test_*.py'
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import scan_unpicked_candidates as scan  # noqa: E402

MARKERS = ["14日以内", "手数料", "無料", "本人確認書類"]
SCORED = "https://example.lg.jp/wrong.html"


def candidate(url: str, link_text: str = "候補", is_pdf: bool = False) -> dict:
    return {"url": url, "link_text": link_text, "is_pdf": is_pdf}


class MarkersInTest(unittest.TestCase):
    def test_見つかった語だけ返す(self):
        self.assertEqual(scan.markers_in("14日以内に届出。無料です。", MARKERS),
                         {"14日以内", "無料"})

    def test_無ければ空(self):
        self.assertEqual(scan.markers_in("関係のない文章", MARKERS), set())

    def test_空文字でも落ちない(self):
        self.assertEqual(scan.markers_in("", MARKERS), set())


class ScanMunicipalityTest(unittest.TestCase):
    """cached_text を差し替えて、URL→本文の対応を固定する。"""

    def run_scan(self, texts: dict[str, str | None], candidates: list[dict]):
        def fake(_fetcher, url):
            return texts.get(url)
        with mock.patch.object(scan, "cached_text", fake):
            return scan.scan_municipality(None, candidates, SCORED, MARKERS)

    def test_採点したページに無い語を持つ候補を見つける(self):
        best, gained, checked = self.run_scan(
            {SCORED: "案内のページです", "https://example.lg.jp/right.html": "14日以内に届出。手数料は無料。"},
            [candidate(SCORED), candidate("https://example.lg.jp/right.html", "住民登録の届出")])
        self.assertIsNotNone(best)
        self.assertEqual(best["link_text"], "住民登録の届出")
        self.assertEqual(gained, {"14日以内", "手数料", "無料"})
        self.assertEqual(checked, 1)

    def test_採点したページに既にある語は数えない(self):
        """同じ語があっても「新たに見つかった」ことにしない。"""
        best, gained, _ = self.run_scan(
            {SCORED: "手数料は無料です", "https://example.lg.jp/b.html": "手数料は無料です"},
            [candidate(SCORED), candidate("https://example.lg.jp/b.html")])
        self.assertIsNone(best)
        self.assertEqual(gained, set())

    def test_語の多い候補を選ぶ(self):
        best, gained, _ = self.run_scan(
            {SCORED: "", "https://example.lg.jp/a.html": "無料",
             "https://example.lg.jp/b.html": "14日以内 手数料 無料"},
            [candidate(SCORED), candidate("https://example.lg.jp/a.html", "A"),
             candidate("https://example.lg.jp/b.html", "B")])
        self.assertEqual(best["link_text"], "B")
        self.assertEqual(len(gained), 3)

    def test_PDFは調べない(self):
        _, _, checked = self.run_scan(
            {SCORED: "", "https://example.lg.jp/a.pdf": "14日以内"},
            [candidate(SCORED), candidate("https://example.lg.jp/a.pdf", "A", is_pdf=True)])
        self.assertEqual(checked, 0)

    def test_キャッシュに無いURLは飛ばす(self):
        """取りに行かない。None が返るものは調べた数に入れない。"""
        _, _, checked = self.run_scan(
            {SCORED: "", "https://example.lg.jp/a.html": None},
            [candidate(SCORED), candidate("https://example.lg.jp/a.html")])
        self.assertEqual(checked, 0)

    def test_採点したページ自身は除く(self):
        _, _, checked = self.run_scan({SCORED: "14日以内"}, [candidate(SCORED)])
        self.assertEqual(checked, 0)

    def test_採点したページがキャッシュに無くても動く(self):
        """比較元が取れないときは、候補側の語をそのまま新語として扱う。"""
        best, gained, _ = self.run_scan(
            {SCORED: None, "https://example.lg.jp/a.html": "14日以内"},
            [candidate(SCORED), candidate("https://example.lg.jp/a.html")])
        self.assertIsNotNone(best)
        self.assertEqual(gained, {"14日以内"})

    def test_候補が空でも落ちない(self):
        best, gained, checked = self.run_scan({SCORED: ""}, [])
        self.assertIsNone(best)
        self.assertEqual((gained, checked), (set(), 0))

    def test_urlが無い候補は飛ばす(self):
        _, _, checked = self.run_scan({SCORED: ""}, [{"link_text": "URLなし"}])
        self.assertEqual(checked, 0)


class MarkersTableTest(unittest.TestCase):
    def test_公開している3手続きすべてに語がある(self):
        self.assertEqual(set(scan.MARKERS), {"tennyu", "jidouteate", "sodaigomi"})
        for markers in scan.MARKERS.values():
            self.assertTrue(markers)


if __name__ == "__main__":
    unittest.main()

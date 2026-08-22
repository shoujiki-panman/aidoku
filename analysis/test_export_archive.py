"""アーカイブ記録の書き出しのテスト。ネットワークには一切出ない。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import export_archive  # noqa: E402


class Summarize(unittest.TestCase):
    def test_版を古い順に並べる(self):
        r = export_archive.summarize("https://a.jp/x", [
            {"timestamp": "20260525000000", "digest": "B"},
            {"timestamp": "20240902000000", "digest": "A"},
        ])
        self.assertEqual(r["first"], "20240902000000")
        self.assertEqual(r["last"], "20260525000000")
        self.assertEqual(r["snapshots"], 2)

    def test_実物へのリンクを持つ(self):
        # ★コピーは持たない（#99）。実物は Internet Archive へ渡す
        r = export_archive.summarize("https://a.jp/x", [])
        self.assertIn("web.archive.org", r["wayback"])
        self.assertIn("https://a.jp/x", r["wayback"])

    def test_版が無くても落ちない(self):
        r = export_archive.summarize("https://a.jp/x", [])
        self.assertEqual(r["snapshots"], 0)
        self.assertIsNone(r["first"])
        self.assertIsNone(r["last"])

    def test_timestampの無い行は数えない(self):
        r = export_archive.summarize("https://a.jp/x", [{"digest": "A"}, {"timestamp": "20200101000000"}])
        self.assertEqual(r["snapshots"], 1)

    def test_HTMLそのものは持たない(self):
        # 保存量を増やさないための約束。中身を持ったら意味が無い
        r = export_archive.summarize("https://a.jp/x", [{"timestamp": "20200101000000", "digest": "A"}])
        self.assertNotIn("body", r)
        self.assertNotIn("html", r)
        self.assertNotIn("content", r)


class FetchFailure(unittest.TestCase):
    def test_引けなければNoneで推測しない(self):
        # 相手が落ちているときに「0版」と言ってはいけない。「引けなかった」と言う
        orig = export_archive.urllib.request.urlopen

        def boom(*a, **k):
            raise OSError("network down")
        export_archive.urllib.request.urlopen = boom
        try:
            self.assertIsNone(export_archive.fetch_snapshots("https://a.jp/x"))
        finally:
            export_archive.urllib.request.urlopen = orig


class Politeness(unittest.TestCase):
    def test_間隔をあける設定がある(self):
        # archive.org は非営利。こちらのクロールと同じ間隔をあける
        self.assertGreaterEqual(export_archive.MIN_INTERVAL_SEC, 3.0)

    def test_連絡先つきのUserAgent(self):
        self.assertIn("github.com", export_archive.UA)


if __name__ == "__main__":
    unittest.main()

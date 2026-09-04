"""`analysis/probes/check_host.py` — 区の外のホストがどれだけ混ざっていたか。

**なぜ要るか**: 同一ホスト判定が部分一致だったため、区のホスト名を中に含むだけの
別ホストが通っていた。**どれだけ通っていたかを数え直せるようにする。**
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis" / "probes"))
from check_host import host_of, off_host  # noqa: E402

TOP = "https://www.city.adachi.tokyo.jp/"


class ホストを取る(unittest.TestCase):
    def test_ホスト名を返す(self):
        self.assertEqual(host_of("https://www.city.adachi.tokyo.jp/a"),
                         "www.city.adachi.tokyo.jp")

    def test_空文字でも落ちない(self):
        self.assertEqual(host_of(""), "")


class 別ホストを拾う(unittest.TestCase):
    def test_同じホストは拾わない(self):
        self.assertEqual(off_host(TOP, ["https://www.city.adachi.tokyo.jp/a"]), [])

    def test_別ホストを拾う(self):
        self.assertEqual(off_host(TOP, ["https://example.com/a"]),
                         ["https://example.com/a"])

    def test_ホスト名を中に含むだけのものを拾う(self):
        """★ここが要点。部分一致だと「同じホスト」に見えてしまう。"""
        url = "https://b.hatena.ne.jp/entry/https://www.city.adachi.tokyo.jp/gomi/a"
        self.assertEqual(off_host(TOP, [url]), [url])

    def test_ホストが無いものは拾わない(self):
        # ★相対URLを「別ホスト」に数えると件数が水増しされる。
        self.assertEqual(off_host(TOP, ["/kurashi/a.html", ""]), [])


class 実データ(unittest.TestCase):
    def test_粗大ごみの外部申込サイトを実際に読んでいる(self):
        """★METHOD §4-3 の「可能性は残る」は、可能性ではなく事実だった。"""
        import json
        path = ROOT / "analysis" / "out" / "off_host.json"
        if not path.exists():
            self.skipTest("未生成")
        doc = json.loads(path.read_text(encoding="utf-8"))
        followed = [r for r in doc["read_rows"] if r["how"] == "追従"]
        self.assertGreater(len(followed), 0)
        self.assertTrue(any(r["procedure"] == "sodaigomi" for r in followed))


if __name__ == "__main__":
    unittest.main()

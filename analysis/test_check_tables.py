"""表読みの効果を数える道具のテスト。

数え方そのものが主張の根拠なので、「表を取り除いた本文」の作り方と
「表の中にしかない項目」の判定を、ここで止める。
LLMもネットワークも使わない。標準ライブラリのみ。

実行: python3 -m unittest discover -s analysis -p 'test_*.py'
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from check_tables import inspect, strip_tables, table_only_facts  # noqa: E402


class 表を除いた本文Test(unittest.TestCase):
    def test_表の中身を落とす(self):
        html = "<p>案内</p><table><tr><td>手数料 無料</td></tr></table><p>末尾</p>"
        stripped = strip_tables(html)
        self.assertNotIn("無料", stripped)
        self.assertIn("案内", stripped)
        self.assertIn("末尾", stripped)

    def test_入れ子の表も残さない(self):
        html = ("<table><tr><td>外"
                "<table><tr><td>手数料 無料</td></tr></table>"
                "</td></tr></table><p>案内</p>")
        stripped = strip_tables(html)
        self.assertNotIn("無料", stripped)
        self.assertNotIn("外", stripped)
        self.assertIn("案内", stripped)


class 表の中にしかない項目Test(unittest.TestCase):
    def test_本文にも出る語は数えない(self):
        self.assertEqual(
            table_only_facts("手数料 無料", "手数料は無料です"), [])

    def test_表にしか出ない語を項目として返す(self):
        self.assertEqual(
            table_only_facts("手数料 無料", "案内文だけ"), ["手数料"])

    def test_複数の項目をまとめて返す(self):
        self.assertEqual(
            table_only_facts("本人確認書類 14日以内", "案内文だけ"),
            ["必要書類", "期限"])


class ページ1枚の集計Test(unittest.TestCase):
    def test_表の中にしかない手数料を見つける(self):
        html = ("<p>転入届の案内です。</p><table>"
                "<tr><th>区分</th><th>費用</th></tr>"
                "<tr><th>国内転入</th><td>手数料は無料</td></tr></table>")
        row = inspect(html, "https://example.jp/")
        self.assertEqual(row["table_only"], ["手数料"])
        self.assertEqual(row["n_tables"], 1)
        self.assertGreater(row["passed_len"], 0)
        self.assertEqual(row["body_lost"], 0)

    def test_表が無ければ渡すものも無い(self):
        row = inspect("<p>転入届の案内です。</p>", "https://example.jp/")
        self.assertEqual(row["table_only"], [])
        self.assertEqual(row["passed_len"], 0)
        self.assertFalse(row["blocked"])


if __name__ == "__main__":
    unittest.main()

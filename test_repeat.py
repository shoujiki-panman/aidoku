"""`analysis/repeat.py` — 同じ条件で何度測ると答えが割れるか。

**なぜ要るか**: 1組を1回しか測っていないのに、点の上下を語っていた。
揺れの幅を知らなければ、点が動いた理由を条件差だと言えない。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from repeat import observations, spread  # noqa: E402


def run(url: str, clarity: str, **fields: bool) -> dict:
    return {"page": {"url": url}, "online_clarity": clarity,
            "items": {k: {"found": v} for k, v in fields.items()}}


class 観測を並べる(unittest.TestCase):
    def test_項目ごとに回数ぶん並ぶ(self):
        got = observations([run("u", "あり", 手数料=True), run("u", "あり", 手数料=False)])
        self.assertEqual(got["手数料"], ["読めた", "読めない"])

    def test_選んだページも記録する(self):
        # ★どのページを起点に選ぶかも揺れる。項目だけ見ると気づけない。
        got = observations([run("a", "あり", 期限=True), run("b", "あり", 期限=True)])
        self.assertEqual(got["_選んだページ"], ["a", "b"])

    def test_オンライン明示も記録する(self):
        got = observations([run("u", "あり", 期限=True), run("u", "記載なし", 期限=True)])
        self.assertEqual(got["_オンライン明示"], ["あり", "記載なし"])


class 割れを数える(unittest.TestCase):
    def test_全部同じなら割れは0(self):
        got = spread(observations([run("u", "あり", 期限=True), run("u", "あり", 期限=True)]))
        self.assertEqual(got["split_fields"], [])
        self.assertEqual(got["split_ratio"], 0.0)

    def test_割れた項目を名前で返す(self):
        got = spread(observations([run("u", "あり", 期限=True, 手数料=True),
                                   run("u", "あり", 期限=True, 手数料=False)]))
        self.assertEqual(got["split_fields"], ["手数料"])
        self.assertEqual(got["split_ratio"], 0.5)

    def test_分母に下線つきを混ぜない(self):
        """★ページ選択を項目に混ぜると、割れの割合が水増しされる。"""
        got = spread(observations([run("a", "あり", 期限=True), run("b", "あり", 期限=True)]))
        self.assertEqual(got["fields"], 1)
        self.assertEqual(got["split_ratio"], 0.0)

    def test_ページが揺れたら別枠で言う(self):
        got = spread(observations([run("a", "あり", 期限=True), run("b", "あり", 期限=True)]))
        self.assertFalse(got["page_stable"])

    def test_オンライン明示の揺れも別枠(self):
        got = spread(observations([run("u", "あり", 期限=True), run("u", "記載なし", 期限=True)]))
        self.assertFalse(got["clarity_stable"])

    def test_回数を返す(self):
        got = spread(observations([run("u", "あり", 期限=True)] * 3))
        self.assertEqual(got["runs"], 3)


class 落ちた回の扱い(unittest.TestCase):
    def test_2回そろわなければ揺れは言えない(self):
        import repeat
        original = repeat.run_once
        repeat.run_once = lambda *a, **k: None
        try:
            with self.assertRaises(SystemExit):
                repeat.measure("nakano", "jidouteate", 3)
        finally:
            repeat.run_once = original


if __name__ == "__main__":
    unittest.main()

"""`analysis/probes/crosscheck_exhausted.py` — 「書いていない」の突き合わせ。

**なぜ要るか**: 読めなかったものを「無かった」に混ぜると、比較そのものが嘘になる。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis" / "probes"))
from crosscheck_exhausted import MIN_CONTROL_FOUND, classify, judge, summarize, target_key, targets  # noqa: E402


def row(*fields):
    return {"municipality_id": "m", "municipality": "M区", "fields": list(fields)}


def item(group, field="期限", url="u", codex=None, again=None):
    return {"procedure": "p", "municipality_id": "m", "municipality": "M区", "field": field, "url": url,
            "group": group, "codex": codex, "claude_again": again}


class 対象を選ぶ(unittest.TestCase):
    def test_exhaustedは読んだ全ページ(self):
        got = targets({"p": [row({"field": "期限", "stopped": "exhausted", "looked": [{"url": "a"}, {"url": "b"}]})]})
        self.assertEqual([t["url"] for t in got], ["a", "b"])
        self.assertEqual({t["group"] for t in got}, {"exhausted"})

    def test_foundは見つけた1ページだけ陽性対照にする(self):
        got = targets({"p": [row({"field": "期限", "stopped": "found", "url": "c",
                                  "looked": [{"url": "a"}, {"url": "c"}]})]})
        self.assertEqual([(t["url"], t["group"]) for t in got], [("c", "control")])

    def test_結論にできない行は入れない(self):
        for stopped in ("unreadable", "error", "budget", "no_candidates"):
            self.assertEqual(targets({"p": [row({"field": "期限", "stopped": stopped, "looked": []})]}), [])

    def test_読めなかったページは比べない(self):
        got = targets({"p": [row({"field": "期限", "stopped": "exhausted",
                                  "looked": [{"url": "a", "error": "x"}, {"url": "b"}]})]})
        self.assertEqual([t["url"] for t in got], ["b"])

    def test_同じページでも項目が違えば別の判定(self):
        self.assertNotEqual(target_key(item("exhausted", field="期限")), target_key(item("exhausted", field="手数料")))


class 判定する(unittest.TestCase):
    def test_根拠が本文にあれば見つけた(self):
        self.assertTrue(judge({"found": True, "evidence": "14日以内に届け出てください"},
                              "転入後14日以内に届け出てください。")["verified"])

    def test_根拠が本文に無ければ見つけたと数えない(self):
        self.assertFalse(judge({"found": True, "evidence": "30日以内に届け出てください"},
                               "転入後14日以内に届け出てください。")["verified"])

    def test_無いという返答は根拠があっても見つけたにしない(self):
        self.assertFalse(judge({"found": False, "evidence": "14日以内"}, "14日以内")["verified"])


class 分ける(unittest.TestCase):
    def test_再度見つければぶれ(self):
        self.assertEqual(classify({"verified": True}), "1回ごとのぶれ")

    def test_また見つけなければ食い違い(self):
        self.assertEqual(classify({"verified": False}), "系統の食い違い")

    def test_聞けていなければ未確認(self):
        self.assertEqual(classify(None), "未確認")
        self.assertEqual(classify({"error": "x"}), "未確認")


class 集計する(unittest.TestCase):
    def test_自治体と項目の単位で数える(self):
        got = summarize([item("exhausted", url="a", codex={"verified": True}, again={"verified": False}),
                         item("exhausted", url="b", codex={"verified": True}, again={"verified": True}),
                         item("exhausted", url="c", codex={"verified": False})])
        self.assertEqual((got["exhausted_judgments"], got["exhausted_pairs"]), (3, 1))
        self.assertEqual((got["codex_found_judgments"], got["codex_found_pairs"]), (2, 1))
        self.assertEqual(got["by_label"], {"系統の食い違い": 1, "1回ごとのぶれ": 1})

    def test_エラーと未実施は無かったに混ぜない(self):
        got = summarize([item("exhausted", url="a", codex={"error": "x"}), item("exhausted", url="b")])
        self.assertEqual((got["codex_errors"], got["unjudged"], got["codex_found_judgments"]), (1, 1, 0))

    def test_陽性対照の合格線(self):
        hits = [item("control", url=str(i), codex={"verified": True}) for i in range(MIN_CONTROL_FOUND)]
        self.assertTrue(summarize(hits)["control_passed"])
        self.assertFalse(summarize(hits[:-1])["control_passed"])


if __name__ == "__main__":
    unittest.main()

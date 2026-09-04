"""`analysis/compare_runs.py` — 2回の測定を突き合わせて、変わったセルを数える。

**この数え方に、AI読でいちばん重い主張（再現性は手続きによって何倍違うか）が乗る。**
手で数えていたときに一度間違えている（粗大ごみ 29/96 → 実際は 21/96）ので、
数え方そのものをここで固定する。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from compare_runs import FIELDS, compare_one, reached, tally  # noqa: E402


def doc(found: dict, *, unreached: bool = False) -> dict:
    """抽出結果の形。`unreached=True` で、起点ページに到達できなかった区と同じ形になる。"""
    return {"municipality": "A区",
            "page": None if unreached else {"url": "https://x.example/a"},
            "items": {f: {"found": found.get(f, False)} for f in FIELDS}}


def rows(cells: list[dict], name: str = "A区") -> list[dict]:
    return [{"municipality": name, "cells": cells}]


class 到達判定(unittest.TestCase):
    def test_URLがあれば到達(self):
        self.assertTrue(reached({"page": {"url": "u"}}))

    def test_pageがnullなら未到達(self):
        self.assertFalse(reached({"page": None}))
        self.assertFalse(reached({}))


class セルの印(unittest.TestCase):
    def test_取れるようになったら_up(self):
        got = compare_one(doc({}), doc({"手数料": True}))
        self.assertEqual([c["mark"] for c in got if c["field"] == "手数料"], ["up"])

    def test_取れなくなったら_down(self):
        got = compare_one(doc({"手数料": True}), doc({}))
        self.assertEqual([c["mark"] for c in got if c["field"] == "手数料"], ["down"])

    def test_変わらなければ_same(self):
        got = compare_one(doc({"手数料": True}), doc({"手数料": True}))
        self.assertTrue(all(c["mark"] == "same" for c in got))

    def test_4項目ぶん必ず返す(self):
        self.assertEqual([c["field"] for c in compare_one(doc({}), doc({}))], list(FIELDS))

    def test_どちらかが未到達なら4項目とも_unreached(self):
        """★これを same に混ぜていた。

        混ぜると分母が水増しされ、再現性が実際より高く見える。
        逆に「4項目とも変化した」と数えた誤りも実際に起きている
        （粗大ごみの江戸川区・八王子市。旧・新どちらも未到達で、変化は0）。
        """
        got = compare_one(doc({}, unreached=True), doc({"手数料": True}))
        self.assertTrue(all(c["mark"] == "unreached" for c in got))
        got = compare_one(doc({"手数料": True}), doc({}, unreached=True))
        self.assertTrue(all(c["mark"] == "unreached" for c in got))


class 集計(unittest.TestCase):
    def cells(self, marks: list[str]) -> list[dict]:
        return [{"field": f, "mark": m, "before": None, "after": None}
                for f, m in zip(FIELDS, marks, strict=True)]

    def test_上昇と下降を分けて数える(self):
        got = tally(rows(self.cells(["up", "down", "same", "same"])))
        self.assertEqual((got["up"], got["down"], got["changed"]), (1, 1, 2))

    def test_未到達は分母から外した割合も出す(self):
        # ★全セル分母だけだと、測定が成立していないセルで薄まる。
        got = tally(rows(self.cells(["up", "unreached", "unreached", "same"])))
        self.assertEqual(got["cells"], 4)
        self.assertEqual(got["measured_cells"], 2)
        self.assertEqual(got["changed_ratio"], 0.25)
        self.assertEqual(got["changed_ratio_measured"], 0.5)

    def test_未到達しかない区は名前を出す(self):
        # 黙って消えると、その区が「変わらなかった」ように見える。
        got = tally(rows(self.cells(["unreached"] * 4), name="江戸川区"))
        self.assertEqual(got["unreached_municipalities"], ["江戸川区"])
        self.assertEqual(got["changed"], 0)

    def test_一部だけ未到達の区は名前を出さない(self):
        got = tally(rows(self.cells(["up", "unreached", "same", "same"])))
        self.assertEqual(got["unreached_municipalities"], [])

    def test_変わったセルの名前を向き付きで出す(self):
        got = tally(rows(self.cells(["up", "down", "same", "same"])))
        self.assertEqual(got["changed_names"], ["↑A区/必要書類", "↓A区/期限"])

    def test_項目別に数える(self):
        got = tally(rows(self.cells(["up", "same", "down", "same"])))
        self.assertEqual(got["by_field"]["必要書類"], 1)
        self.assertEqual(got["by_field"]["手数料"], 1)
        self.assertEqual(got["by_field"]["期限"], 0)

    def test_セルが無くても割合で落ちない(self):
        got = tally([])
        self.assertEqual(got["changed_ratio"], 0.0)
        self.assertEqual(got["changed_ratio_measured"], 0.0)


class 実データ(unittest.TestCase):
    """★手で数えた値と食い違ったのは粗大ごみだけ。3手続きとも道具で固定する。"""

    def summary(self, procedure: str) -> dict:
        path = ROOT / "analysis" / "out" / f"compare_{procedure}.json"
        return json.loads(path.read_text(encoding="utf-8"))["summary"]

    def test_転入届は3セル(self):
        self.assertEqual(self.summary("tennyu")["changed"], 3)

    def test_児童手当は12セル(self):
        self.assertEqual(self.summary("jidouteate")["changed"], 12)

    def test_粗大ごみは21セル(self):
        # 手で数えたときは29と書いていた（上昇17＋下降2＝19で、それ自体合っていない）。
        got = self.summary("sodaigomi")
        self.assertEqual((got["changed"], got["up"], got["down"]), (21, 18, 3))

    def test_粗大ごみの未到達2区は分けて数えてある(self):
        got = self.summary("sodaigomi")
        self.assertEqual(got["unreached_municipalities"], ["江戸川区", "八王子市"])

    def test_再現性の差は約7倍(self):
        # 「10倍違う」と書いていた。結論の向きは変わらないが、倍率を大きく言っていた。
        low = self.summary("tennyu")["changed_ratio"]
        high = self.summary("sodaigomi")["changed_ratio"]
        self.assertAlmostEqual(high / low, 7.0, delta=0.5)


class 出力の作り(unittest.TestCase):
    def test_書いて読み戻せる(self):
        import compare_runs as mod
        with tempfile.TemporaryDirectory() as tmp:
            before = Path(tmp) / "before"
            after = Path(tmp) / "after"
            before.mkdir()
            after.mkdir()
            for d in (before, after):
                (d / "extract_a_tennyu.json").write_text(
                    json.dumps(doc({}), ensure_ascii=False), encoding="utf-8")
            original, mod.OUT_DIR = mod.OUT_DIR, Path(tmp) / "out"
            try:
                mod.main(["-p", "tennyu", "--before", str(before), "--after", str(after)])
                got = json.loads((mod.OUT_DIR / "compare_tennyu.json")
                                 .read_text(encoding="utf-8"))
            finally:
                mod.OUT_DIR = original
        self.assertEqual(got["summary"]["changed"], 0)
        self.assertEqual(got["summary"]["cells"], 4)


if __name__ == "__main__":
    unittest.main()

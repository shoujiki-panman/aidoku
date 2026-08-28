from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from sweep import (  # noqa: E402
    BUDGET,
    ITEM_TO_FIELD,
    key,
    load_visits,
    missing_fields,
    summarize,
)


def cand(url: str, score: int = 20) -> dict:
    return {"url": url, "link_text": "転入届", "score": score, "text": "本文"}


class 足りない項目(unittest.TestCase):
    def test_取れていない項目だけ返す(self):
        extract = {"items": {"必要書類": {"found": True}, "手数料": {"found": False}}}
        self.assertEqual(missing_fields(extract), ["手数料"])

    def test_公開データの項目名に直す(self):
        # ★抽出結果は「窓口オンライン可否」、公開データは「窓口/オンライン可否」。
        #   この取り違えを3回やっている。
        extract = {"items": {"窓口オンライン可否": {"found": False}}}
        self.assertEqual(missing_fields(extract), ["窓口/オンライン可否"])

    def test_対応表に無いキーは無視する(self):
        extract = {"items": {"謎の項目": {"found": False}}}
        self.assertEqual(missing_fields(extract), [])

    def test_itemsが無くても落ちない(self):
        self.assertEqual(missing_fields({}), [])

    def test_対応表は公開データの項目名を持つ(self):
        doc = json.loads((ROOT / "web/data/scores-tennyu.json").read_text(encoding="utf-8"))
        real = {f["field"] for m in doc["municipalities"] for f in m.get("fields", [])}
        self.assertEqual(set(ITEM_TO_FIELD.values()), real)


class 虱潰し(unittest.TestCase):
    """★止まった理由を必ず分ける。混ぜると「書いていない」が嘘になる。"""

    def ask(self, hits: dict[str, bool]):
        def fake(target, muni, proc, field, model):
            ok = hits.get(target["url"], False)
            return {"found": ok, "verified": ok, "value": "無料" if ok else "",
                    "evidence": "本文", "why_not": ""}
        return fake

    def run_sweep(self, cands, hits, visits=None):
        import sweep as mod
        original, mod.ask_page = mod.ask_page, self.ask(hits)
        try:
            # ★`visits or {}` と書くと、空の辞書が偽と見なされて捨てられる。
            #   渡した辞書に記録が入らず、テストが通らなかった。
            return mod.sweep_field(cands, "A区", "転入届", "手数料", "m",
                                   visits if visits is not None else {})
        finally:
            mod.ask_page = original

    def test_見つかったら止める(self):
        cands = [cand("u1"), cand("u2"), cand("u3")]
        got = self.run_sweep(cands, {"u2": True})
        self.assertTrue(got["found"])
        self.assertEqual(got["stopped"], "found")
        self.assertEqual(len(got["looked"]), 2)      # u3 は読まない

    def test_全部見て無ければ_exhausted(self):
        got = self.run_sweep([cand("u1"), cand("u2")], {})
        self.assertFalse(got["found"])
        self.assertEqual(got["stopped"], "exhausted")

    def test_上限で止まったら_budget(self):
        # ★ここを exhausted と混ぜると「読み切った上で無い」が嘘になる。
        cands = [cand(f"u{i}") for i in range(BUDGET + 3)]
        got = self.run_sweep(cands, {})
        self.assertEqual(got["stopped"], "budget")
        self.assertEqual(len(got["looked"]), BUDGET)

    def test_ちょうど上限なら_exhausted(self):
        cands = [cand(f"u{i}") for i in range(BUDGET)]
        self.assertEqual(self.run_sweep(cands, {})["stopped"], "exhausted")

    def test_点数の高い順に読む(self):
        # 呼ぶ側が並べる。ここは渡された順に読む。
        got = self.run_sweep([cand("hi", 30), cand("lo", 5)], {"lo": True})
        self.assertEqual([x["url"] for x in got["looked"]], ["hi", "lo"])

    def test_記録済みは読み直さない(self):
        visits = {key("u1", "手数料"): {"found": False, "verified": False, "value": ""}}
        got = self.run_sweep([cand("u1"), cand("u2")], {"u1": True}, visits)
        # u1 は記録があるので呼ばない。記録は「見つからなかった」なので u2 へ進む
        self.assertTrue(got["looked"][0]["from_cache"])
        self.assertFalse(got["found"])

    def test_読んだものは必ず記録に残る(self):
        visits: dict = {}
        self.run_sweep([cand("u1"), cand("u2")], {}, visits)
        self.assertEqual(set(visits), {key("u1", "手数料"), key("u2", "手数料")})


class 記録(unittest.TestCase):
    def test_記録が無ければ空(self):
        self.assertEqual(load_visits("__nonexistent__"), {})

    def test_キーはURLと項目の組(self):
        # 同じURLでも項目が違えば別に数える。
        self.assertNotEqual(key("u", "手数料"), key("u", "期限"))


def row(name: str, fields: list[dict]) -> dict:
    return {"municipality": name, "municipality_id": name, "fields": fields}


def result(field: str, *, found: bool, stopped: str, looked: int = 1) -> dict:
    return {"field": field, "found": found, "stopped": stopped,
            "looked": [{"url": f"u{i}"} for i in range(looked)]}


class 集計(unittest.TestCase):
    def test_見つけた項目を数える(self):
        rows = [row("A区", [result("手数料", found=True, stopped="found")])]
        got = summarize(rows)
        self.assertEqual(got["found"], 1)
        self.assertEqual(got["found_names"], ["A区/手数料"])

    def test_上限で止まったものを別に数える(self):
        # ★これを exhausted と混ぜてはいけない。
        rows = [row("A区", [result("手数料", found=False, stopped="budget")]),
                row("B区", [result("期限", found=False, stopped="exhausted")])]
        got = summarize(rows)
        self.assertEqual(got["budget_hit"], 1)
        self.assertEqual(got["budget_names"], ["A区/手数料"])
        self.assertEqual(got["exhausted"], 1)

    def test_候補が無い項目はどちらにも数えない(self):
        rows = [row("A区", [result("手数料", found=False, stopped="no_candidates", looked=0)])]
        got = summarize(rows)
        self.assertEqual(got["budget_hit"], 0)
        self.assertEqual(got["exhausted"], 0)
        self.assertEqual(got["pages_read"], 0)

    def test_読んだページ数を合算する(self):
        rows = [row("A区", [result("手数料", found=False, stopped="exhausted", looked=3)])]
        self.assertEqual(summarize(rows)["pages_read"], 3)


class 保存(unittest.TestCase):
    def test_書いて読み戻せる(self):
        import sweep as mod
        with tempfile.TemporaryDirectory() as d:
            original, mod.OUT_DIR = mod.OUT_DIR, Path(d)
            try:
                mod.save_visits("t", {key("u", "手数料"): {"found": True}})
                self.assertEqual(set(mod.load_visits("t")), {key("u", "手数料")})
            finally:
                mod.OUT_DIR = original


if __name__ == "__main__":
    unittest.main()

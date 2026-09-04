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
    merge_rows,
    missing_fields,
    reached,
    summarize,
    unwrap,
)

PAGE = {"url": "https://x.example/service"}


def extract(items: dict, *, page=PAGE) -> dict:
    """抽出結果の形。★`page` を省くと、到達できなかった区と同じ形になる。"""
    return {"page": page, "items": items}


def cand(url: str, score: int = 20) -> dict:
    return {"url": url, "link_text": "転入届", "score": score, "text": "本文"}


class 足りない項目(unittest.TestCase):
    def test_取れていない項目だけ返す(self):
        got = extract({"必要書類": {"found": True}, "手数料": {"found": False}})
        self.assertEqual(missing_fields(got), ["手数料"])

    def test_公開データの項目名に直す(self):
        # ★抽出結果は「窓口オンライン可否」、公開データは「窓口/オンライン可否」。
        #   この取り違えを3回やっている。
        got = extract({"窓口オンライン可否": {"found": False}})
        self.assertEqual(missing_fields(got), ["窓口/オンライン可否"])

    def test_対応表に無いキーは無視する(self):
        self.assertEqual(missing_fields(extract({"謎の項目": {"found": False}})), [])

    def test_itemsが無くても落ちない(self):
        self.assertEqual(missing_fields({}), [])
        self.assertEqual(missing_fields(extract({})), [])

    def test_到達できなかった区は対象外(self):
        """★`reached: false` の区は page が null で、読むページが1本も無い。

        実測で2区あった（粗大ごみ・江戸川区/八王子市）。ここで落ちていた。
        「書いていない」ではなく「探索が届かなかった」。混ぜてはいけない。
        """
        self.assertEqual(missing_fields({"page": None, "reached": False,
                                         "items": {"手数料": {"found": False}}}), [])

    def test_到達判定(self):
        self.assertTrue(reached({"page": {"url": "https://x.example/a"}}))
        self.assertFalse(reached({"page": None}))
        self.assertFalse(reached({"page": {}}))
        self.assertFalse(reached({}))

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

    def test_1件壊れても止まらない(self):
        """★1件のAI応答が壊れただけで全体が止まっていた（JSONDecodeError）。

        reread_field では拾っていた失敗を、ここで拾っていなかった。
        """
        import sweep as mod
        calls = []

        def flaky(target, muni, proc, field, model):
            calls.append(target["url"])
            if target["url"] == "u1":
                raise ValueError("Extra data")
            return {"found": True, "verified": True, "value": "無料",
                    "evidence": "本文", "why_not": ""}

        original, mod.ask_page = mod.ask_page, flaky
        try:
            got = mod.sweep_field([cand("u1"), cand("u2")], "A区", "転入届",
                                  "手数料", "m", {})
        finally:
            mod.ask_page = original
        self.assertEqual(calls, ["u1", "u2"])       # 止まらず次へ進む
        self.assertTrue(got["found"])
        self.assertEqual(got["errors"], 1)
        self.assertIn("error", got["looked"][0])

    def test_壊れた応答は記録に残さない(self):
        # ★次回もう一度読ませるため。記録すると永久に読まれない。
        import sweep as mod
        visits: dict = {}

        def always_fail(*_a, **_k):
            raise ValueError("Extra data")

        original, mod.ask_page = mod.ask_page, always_fail
        try:
            got = mod.sweep_field([cand("u1")], "A区", "転入届", "手数料", "m", visits)
        finally:
            mod.ask_page = original
        self.assertEqual(visits, {})
        # ★全部見たとは言えない。exhausted にしない
        self.assertEqual(got["stopped"], "error")

    def test_読んだものは必ず記録に残る(self):
        visits: dict = {}
        self.run_sweep([cand("u1"), cand("u2")], {}, visits)
        self.assertEqual(set(visits), {key("u1", "手数料"), key("u2", "手数料")})


class 部分実行(unittest.TestCase):
    """★`-m` で数区だけ回すと、出力が今回の数区だけになっていた。

    実測で36項目の記録が3項目に減り、git から戻して気づいた。
    部分実行は「一部を測り直す」であって「他を無かったことにする」ではない。
    """

    def row(self, mid: str, mark: str) -> dict:
        return {"municipality_id": mid, "municipality": mid,
                "fields": [{"field": "手数料", "stopped": mark, "found": False,
                            "looked": []}]}

    def test_回さなかった自治体の記録を残す(self):
        got = merge_rows([self.row("a", "exhausted"), self.row("b", "exhausted")],
                         [self.row("b", "found")])
        self.assertEqual([r["municipality_id"] for r in got], ["a", "b"])

    def test_回した自治体は新しい方で置き換える(self):
        got = merge_rows([self.row("b", "exhausted")], [self.row("b", "found")])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["fields"][0]["stopped"], "found")

    def test_前回が空でも落ちない(self):
        self.assertEqual(len(merge_rows([], [self.row("a", "found")])), 1)

    def test_自治体の順を保つ(self):
        got = merge_rows([self.row("c", "exhausted")], [self.row("a", "found")])
        self.assertEqual([r["municipality_id"] for r in got], ["a", "c"])


class 読めない候補(unittest.TestCase):
    """★本文が取れない候補を黙って落として「全部見た」と言っていた。

    実測で9項目が該当（画像PDF・404・古い .xls）。落とした候補があるまま
    exhausted にすると、**読めなかったものが「無かった」に化ける。**
    """

    def ok_ask(self, target, muni, proc, field, model):
        return {"found": False, "verified": False, "value": "",
                "evidence": "", "why_not": ""}

    def run_sweep(self, cands, unreadable):
        import sweep as mod
        original, mod.ask_page = mod.ask_page, self.ok_ask
        try:
            return mod.sweep_field(cands, "A区", "転入届", "手数料", "m", {}, unreadable)
        finally:
            mod.ask_page = original

    def test_読めない候補が残っていれば_exhausted_にしない(self):
        got = self.run_sweep([cand("u1")], ["https://x/scan.pdf"])
        self.assertEqual(got["stopped"], "unreadable")
        self.assertEqual(got["unreadable"], ["https://x/scan.pdf"])

    def test_読めない候補が無ければ_exhausted(self):
        self.assertEqual(self.run_sweep([cand("u1")], [])["stopped"], "exhausted")

    def test_省略しても落ちない(self):
        # 既存の呼び出し（第7引数なし）を壊さない。
        import sweep as mod
        original, mod.ask_page = mod.ask_page, self.ok_ask
        try:
            got = mod.sweep_field([cand("u1")], "A区", "転入届", "手数料", "m", {})
        finally:
            mod.ask_page = original
        self.assertEqual(got["stopped"], "exhausted")

    def test_エラーの方を優先する(self):
        # ★どちらも「結論にできない」だが、原因の違いを残す。
        import sweep as mod

        def fail(*_a, **_k):
            raise ValueError("Extra data")

        original, mod.ask_page = mod.ask_page, fail
        try:
            got = mod.sweep_field([cand("u1")], "A区", "転入届", "手数料", "m", {}, ["u2"])
        finally:
            mod.ask_page = original
        self.assertEqual(got["stopped"], "error")

    def test_集計が読めない候補を別に数える(self):
        rows = [row("A区", [result("手数料", found=False, stopped="unreadable")]),
                row("B区", [result("期限", found=False, stopped="exhausted")])]
        got = summarize(rows)
        self.assertEqual(got["unreadable"], 1)
        self.assertEqual(got["unreadable_names"], ["A区/手数料"])
        self.assertEqual(got["exhausted"], 1)


class 包まれたURL(unittest.TestCase):
    """★翻訳サービス経由のURL（`https://…/https://本来のURL`）。

    実測では目黒区のごみのページが j-server 経由で6本並んでいた。
    包みは robots.txt で拒否されるが、**中身のページは取得済み**だった。
    包みを「読めない候補」と数えると、同じページを読んでいるのに
    「読み切っていない」ことになり、穴の数が実態より多く出る。
    """

    def test_中身のURLを取り出す(self):
        got = unwrap("https://www15.j-server.com/LUC/ns/w0/jazh/"
                     "https://www.city.meguro.tokyo.jp/gomi/funen.html")
        self.assertEqual(got, "https://www.city.meguro.tokyo.jp/gomi/funen.html")

    def test_包みでなければそのまま(self):
        url = "https://www.city.meguro.tokyo.jp/gomi/funen.html"
        self.assertEqual(unwrap(url), url)

    def test_クエリに入っていても取り出す(self):
        got = unwrap("https://tr.example/go?url=https://www.city.ota.tokyo.jp/a.html")
        self.assertEqual(got, "https://www.city.ota.tokyo.jp/a.html")

    def test_httpも扱う(self):
        self.assertEqual(unwrap("https://w.example/x/http://a.example/b"),
                         "http://a.example/b")


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

    def test_読めなかった項目を別に数える(self):
        # ★exhausted と混ぜると「読み切った上で無い」が嘘になる。
        rows = [row("A区", [result("手数料", found=False, stopped="error")])]
        got = summarize(rows)
        self.assertEqual(got["errored"], 1)
        self.assertEqual(got["errored_names"], ["A区/手数料"])
        self.assertEqual(got["exhausted"], 0)

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

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from reread_field import (  # noqa: E402
    ASK,
    HINTS,
    NOT_THIS,
    PROC_DESC,
    already_done,
    proc_rules,
    safe_name,
    summarize,
)


def published_fields() -> set[str]:
    doc = json.loads((ROOT / "web/data/scores-tennyu.json").read_text(encoding="utf-8"))
    return {f["field"] for m in doc["municipalities"] for f in m.get("fields", [])}


class 項目名(unittest.TestCase):
    """★同じ取り違えを2回やっている。

    公開データの項目は `窓口/オンライン可否`（スラッシュ入り）だが、
    1回目は `窓口とオンライン可否`、2回目は `窓口オンライン可否` と書いた。
    名前が違うと突き合わせが黙って全件外れ、**全部「不明」になったまま気づかない。**
    """

    def test_公開データの項目名と一致する(self):
        self.assertEqual(set(HINTS), published_fields())

    def test_語の表と除外の表がずれていない(self):
        for proc, table in NOT_THIS.items():
            with self.subTest(proc=proc):
                self.assertEqual(set(HINTS), set(table))

    def test_除外がどれも空でない(self):
        # 空だと隣の手続きの答えを拾う。手数料で実証済み。
        for proc, table in NOT_THIS.items():
            for field, text in table.items():
                with self.subTest(proc=proc, field=field):
                    self.assertGreater(len(text.strip()), 40)


class 語の選び方(unittest.TestCase):
    def test_答えそのものの形は入れない(self):
        # 金額や日付の形を入れると、隣の手続きの数字まで拾う
        # （plans/decisions/table-reading.md：見積12セル→実際4セル）。
        for field, pattern in HINTS.items():
            with self.subTest(field=field):
                self.assertIsNone(pattern.search("300円"))
                self.assertIsNone(pattern.search("2026年8月27日"))

    def test_必要書類の語が当たる(self):
        self.assertTrue(HINTS["必要書類"].search("次のものをお持ちください"))

    def test_期限の語が当たる(self):
        self.assertTrue(HINTS["期限"].search("転入した日から14日以内に届け出てください"))

    def test_窓口の語が当たる(self):
        self.assertTrue(HINTS["窓口/オンライン可否"].search("区民課の窓口で受け付けます"))

    def test_手数料の語が当たる(self):
        self.assertTrue(HINTS["手数料"].search("手数料はかかりません"))


class 質問文(unittest.TestCase):
    def test_全項目で組み立てられる(self):
        for field in HINTS:
            with self.subTest(field=field):
                desc, not_this = proc_rules("転入届", field, "港区")
                text = ASK.format(muni="港区", proc="転入届", field=field,
                                  proc_desc=desc, not_this=not_this,
                                  url="https://x.example/a", text="本文")
                self.assertIn(field, text)
                self.assertIn("港区", text)
                # JSONの見本が壊れていないこと（{{ }} のエスケープ漏れ検出）
                self.assertIn('{"found": true', text)

    def test_引き写しを求めている(self):
        # 言い換えられると evidence_check が missing になり、正しい根拠まで落ちる。
        self.assertIn("引き写して", ASK)


class 手続きごとの説明(unittest.TestCase):
    """★転入届の説明を全手続きに使っていた。

    「粗大ごみ収集の申込とは、他の市区町村から引っ越してきたときに出す届出です」と
    AIに教えていた。実測（墨田区）で、AIは粗大ごみ処理手数料一覧表を**正しく読んだ上で**
    「転入時の届出の手数料ではない」と却下した。**読めても、聞き方が違えば取れない。**
    """

    def test_3手続きぶんある(self):
        self.assertEqual(set(PROC_DESC), set(NOT_THIS))
        self.assertEqual(set(PROC_DESC),
                         {"転入届", "児童手当の申請", "粗大ごみ収集の申込"})

    def test_粗大ごみを引っ越しの届出と説明しない(self):
        desc, _ = proc_rules("粗大ごみ収集の申込", "手数料", "墨田区")
        self.assertNotIn("引っ越してきた", desc)
        self.assertIn("粗大ごみ", desc)

    def test_児童手当を引っ越しの届出と説明しない(self):
        desc, _ = proc_rules("児童手当の申請", "手数料", "港区")
        self.assertNotIn("引っ越してきた", desc)

    def test_品目ごとの料金表を手数料として認める(self):
        # ★これを却下していたのが、墨田区/手数料 を「書いていない」にした原因。
        _, not_this = proc_rules("粗大ごみ収集の申込", "手数料", "墨田区")
        self.assertIn("品目ごとの料金表", not_this)

    def test_児童手当の支給額を手数料と混ぜない(self):
        _, not_this = proc_rules("児童手当の申請", "手数料", "港区")
        self.assertIn("支給額", not_this)

    def test_区名が説明に入る(self):
        desc, _ = proc_rules("転入届", "期限", "世田谷区")
        self.assertIn("世田谷区", desc)

    def test_知らない手続きは黙って通さない(self):
        # ★転入届の説明を使い回して、実測で判定を1件落としている。
        with self.assertRaises(SystemExit):
            proc_rules("パスポートの申請", "手数料", "港区")


def row(mid: str, name: str, found: bool, pages: list[dict] | None = None) -> dict:
    return {"municipality_id": mid, "municipality": name,
            "now_found": found, "pages": pages or []}


class 集計(unittest.TestCase):
    def test_読み落としだった区だけ数える(self):
        rows = [row("a", "A区", True), row("b", "B区", True), row("c", "C区", False)]
        got = summarize(rows, {"a": "読めない", "b": "読めた", "c": "読めない"})
        self.assertEqual(got["newly_found"], 1)
        self.assertEqual(got["newly_found_names"], ["A区"])
        self.assertEqual(got["already_readable"], 1)

    def test_引用が本文に無い主張を別に数える(self):
        pages = [{"found": True, "verified": False}, {"found": True, "verified": True}]
        got = summarize([row("a", "A区", True, pages)], {"a": "読めない"})
        self.assertEqual(got["unverified_claims"], 1)

    def test_公開判定に無い区でも落ちない(self):
        self.assertEqual(summarize([row("x", "X区", True)], {})["newly_found"], 1)



class ファイル名(unittest.TestCase):
    """★項目名を公開データに合わせて `窓口/オンライン可否` にしたら、
    スラッシュがパスの区切りになって **284回ぶんのLLM呼び出しが捨てられた。**
    名前をデータに合わせるのは正しかったが、そのままファイル名にしたのが誤り。
    """

    def test_全項目がファイル名に使える(self):
        for field in HINTS:
            with self.subTest(field=field):
                name = safe_name(field)
                self.assertNotIn("/", name)
                self.assertEqual(Path(name).name, name)   # パスにならないこと
                self.assertTrue(name)

    def test_スラッシュを潰す(self):
        self.assertEqual(safe_name("窓口/オンライン可否"), "窓口-オンライン可否")

    def test_他の禁止文字も潰す(self):
        self.assertEqual(safe_name('a\\b:c*d?e"f<g>h|i'), "a-b-c-d-e-f-g-h-i")

    def test_空白も潰す(self):
        self.assertEqual(safe_name("窓口 と オンライン"), "窓口-と-オンライン")

    def test_端のハイフンは残さない(self):
        self.assertEqual(safe_name("/窓口/"), "窓口")

    def test_普通の名前は変えない(self):
        self.assertEqual(safe_name("必要書類"), "必要書類")


def page(url: str, *, error: str | None = None, found: bool = False,
         verified: bool = False) -> dict:
    p = {"url": url, "found": found, "verified": verified}
    if error:
        p["error"] = error
    return p


class 失敗を成功に混ぜない(unittest.TestCase):
    """★利用上限で71ページが落ち、7区の「見つからない」が嘘になった。

    墨田区は11本すべて失敗していたのに「見つからない」と出ていた。
    1ページでも読めていない区の「見つからない」は結論にならない。
    """

    def test_読めなかったページを別に数える(self):
        rows = [{"municipality_id": "a", "municipality": "A区", "now_found": False,
                 "pages": [page("u1"), page("u2", error="rc=1")]}]
        got = summarize(rows, {"a": "読めない"})
        self.assertEqual(got["pages_read"], 1)
        self.assertEqual(got["pages_failed"], 1)

    def test_全部失敗した区は結論を出せない扱い(self):
        rows = [{"municipality_id": "a", "municipality": "A区", "now_found": False,
                 "pages": [page("u1", error="rc=1"), page("u2", error="rc=1")]}]
        got = summarize(rows, {"a": "読めない"})
        self.assertEqual(got["inconclusive"], 1)
        self.assertEqual(got["inconclusive_names"], ["A区"])
        self.assertEqual(got["newly_found"], 0)

    def test_見つかった区は失敗があっても結論扱い(self):
        # 1本でも verified があれば「書いてある」は言える。失敗は残りの話。
        rows = [{"municipality_id": "a", "municipality": "A区", "now_found": True,
                 "pages": [page("u1", found=True, verified=True), page("u2", error="rc=1")]}]
        got = summarize(rows, {"a": "読めない"})
        self.assertEqual(got["inconclusive"], 0)
        self.assertEqual(got["newly_found"], 1)

    def test_全部読めた区は結論を出せる(self):
        rows = [{"municipality_id": "a", "municipality": "A区", "now_found": False,
                 "pages": [page("u1"), page("u2")]}]
        self.assertEqual(summarize(rows, {"a": "読めない"})["inconclusive"], 0)

    def test_1本も対象が無い区は結論を出せる(self):
        rows = [{"municipality_id": "a", "municipality": "A区", "now_found": False, "pages": []}]
        self.assertEqual(summarize(rows, {"a": "読めない"})["inconclusive"], 0)


class 再開(unittest.TestCase):
    def test_エラー無しのページだけ引き継ぐ(self):
        import json as _json
        import tempfile as _tf
        doc = {"rows": [{"municipality_id": "a", "pages": [
            page("ok", found=True, verified=True), page("ng", error="rc=1")]}]}
        with _tf.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(_json.dumps(doc), encoding="utf-8")
            got = already_done(p)
        self.assertEqual(set(got["a"]), {"ok"})     # 失敗した ng は呼び直す

    def test_出力がまだ無ければ空(self):
        self.assertEqual(already_done(Path("/nonexistent/x.json")), {})


if __name__ == "__main__":
    unittest.main()

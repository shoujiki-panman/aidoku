"""`analysis/check_search.py` — 区の検索窓が、ブラウザを持たないAIから使えるか。

**なぜ要るか**: 住民のAIが最初にやることの一つが「サイト内検索に語を入れる」。
だが AI読はリンクしか辿っていない。**検索窓を一度も使っていない。**

使えるなら使うべきだが、**使えるかどうかを先に測った。** 実測で
「区自身のURLで叩ける検索」は24自治体中**0**だった。

★判定には使わない。次に何を作るかを決めるための材料。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from check_search import (  # noqa: E402
    KINDS,
    LABEL,
    classify,
    entry_pages,
    search_form,
    summarize,
)

CSE = '<form action="/search_result.html"><input name="q"><input name="cx" value="123"></form>'
JS = '<form action="/#" id="s"><input name="q"></form>'
EXTERNAL = '<form action="https://search-hachioji.dga.jp/"><input name="q"></form>'
SERVER = '<form action="/search/result.html"><input name="kw"></form>'
NOT_SEARCH = '<form action="/apply.php"><input name="name"></form>'


class 検索窓を見つける(unittest.TestCase):
    def test_入力欄の名前で見つける(self):
        self.assertIsNotNone(search_form(SERVER))

    def test_type_search_でも見つける(self):
        self.assertIsNotNone(search_form('<form action="/a.html"><input type="search"></form>'))

    def test_検索でないformは拾わない(self):
        # ★申込フォームを検索窓と数えると、使える区が水増しされる。
        self.assertIsNone(search_form(NOT_SEARCH))

    def test_formが無ければNone(self):
        self.assertIsNone(search_form("<html><body>本文</body></html>"))


class 分類(unittest.TestCase):
    def test_Googleカスタム検索を見分ける(self):
        kind, evidence = classify(CSE)
        self.assertEqual(kind, "google_cse")
        self.assertIn("cx", evidence)

    def test_CSEを先に見る(self):
        """★CSE の action も .html なので、順番を逆にすると「URLで叩ける」になる。"""
        self.assertEqual(classify(CSE)[0], "google_cse")

    def test_送り先がシャープだけならJS頼み(self):
        self.assertEqual(classify(JS)[0], "js_only")

    def test_外の検索サービスを見分ける(self):
        self.assertEqual(classify(EXTERNAL)[0], "external")

    def test_区自身のURL検索を見分ける(self):
        self.assertEqual(classify(SERVER)[0], "url_search")

    def test_検索窓が無ければそう言う(self):
        kind, evidence = classify("<html></html>")
        self.assertEqual(kind, "no_search")
        self.assertEqual(evidence, "")

    def test_根拠を必ず返す(self):
        # ★人が見て確かめられるように。分類だけ返すと誰も検算できない。
        for html in (CSE, JS, EXTERNAL, SERVER):
            with self.subTest(html=html[:24]):
                self.assertTrue(classify(html)[1])


class 集計(unittest.TestCase):
    def rows(self, kinds: list[str]) -> list[dict]:
        return [{"municipality": f"{i}区", "url": "u", "kind": k, "evidence": ""}
                for i, k in enumerate(kinds)]

    def test_印ごとに数える(self):
        got = summarize(self.rows(["google_cse", "google_cse", "url_search"]))
        self.assertEqual(got["by_kind"]["google_cse"], 2)
        self.assertEqual(got["municipalities"], 3)

    def test_使えるのはURL検索だけ(self):
        # ★JS頼みや外部サービスを「使える」に混ぜない。
        got = summarize(self.rows(["js_only", "external", "google_cse"]))
        self.assertEqual(got["usable_without_browser"], 0)
        self.assertEqual(got["needs_browser"], 1)

    def test_印は全種類出す(self):
        got = summarize(self.rows(["no_search"]))
        self.assertEqual(set(got["by_kind"]), set(KINDS))

    def test_名前も出す(self):
        got = summarize(self.rows(["url_search"]))
        self.assertEqual(got["names"]["url_search"], ["0区"])

    def test_全部の印に日本語の説明がある(self):
        self.assertEqual(set(LABEL), set(KINDS))


class 対象の集め方(unittest.TestCase):
    def test_1自治体1本にする(self):
        """★手続きごとに数えると、同じ区の検索窓を3回数えてしまう。"""
        import check_search as mod
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "extractor" / "out"
            out.mkdir(parents=True)
            for proc in ("tennyu", "sodaigomi"):
                (out / f"extract_a_{proc}.json").write_text(json.dumps(
                    {"municipality": "A区", "page": {"url": f"https://x/{proc}"}},
                    ensure_ascii=False), encoding="utf-8")
            original, mod.ROOT = mod.ROOT, Path(tmp)
            try:
                got = entry_pages()
            finally:
                mod.ROOT = original
        self.assertEqual(list(got), ["A区"])

    def test_起点に到達していない区は入れない(self):
        import check_search as mod
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "extractor" / "out"
            out.mkdir(parents=True)
            (out / "extract_b_tennyu.json").write_text(json.dumps(
                {"municipality": "B区", "page": None}, ensure_ascii=False), encoding="utf-8")
            original, mod.ROOT = mod.ROOT, Path(tmp)
            try:
                self.assertEqual(entry_pages(), {})
            finally:
                mod.ROOT = original


class 実データ(unittest.TestCase):
    def test_区自身のURL検索は無い(self):
        """★実測。ここが変わったら「検索窓を使う」を実装する価値が出る。"""
        path = ROOT / "analysis" / "out" / "search_forms.json"
        if not path.exists():
            self.skipTest("未生成")
        got = json.loads(path.read_text(encoding="utf-8"))["summary"]
        self.assertEqual(got["usable_without_browser"], 0)
        self.assertGreater(got["needs_browser"], 0)


if __name__ == "__main__":
    unittest.main()

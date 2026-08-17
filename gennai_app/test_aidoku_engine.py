"""判定エンジンのテスト — 回答観測と検証済み点数を混ぜないことを固定する。

このエンジンは源内の画面から呼ばれる作品本体。2026-07-26 にスタブから差し替えたが、
差し替えの正しさを機械で確かめていなかった。

LLM（`claude -p`）とネットワークには出ない。呼ぶ経路は差し替える。
標準ライブラリのみ。

実行: python3 -m unittest discover -s gennai_app -p 'test_*.py'
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import aidoku_engine as eng  # noqa: E402


class LivePage:
    body_path = "cached.html"

    def body(self) -> str:
        return """
            <script type="application/ld+json">{"name":"転入届"}</script>
            <h1>転入届</h1><p>必要書類の本文</p>
        """


class LiveFetcher:
    def fetch(self, _url: str) -> LivePage:
        return LivePage()


class JudgeLivePageNormalizerTest(unittest.TestCase):
    def test_正規化後も未知URLをライブ判定できる(self):
        polite_fetch = types.ModuleType("polite_fetch")
        polite_fetch.PoliteFetcher = LiveFetcher
        extracted = {"items": {
            jp: {"found": True, "value": "値", "failure_reason": None}
            for jp in eng.ITEM_KEYS.values()
        }, "page_notes": ""}
        replies = [json.dumps(extracted), json.dumps({
            "online_clarity": "明記", "evidence": "本文",
        })]
        with mock.patch.dict(sys.modules, {"polite_fetch": polite_fetch}), \
                mock.patch.object(eng, "_call_claude", side_effect=replies) as call:
            result = eng.judge_live("https://example.jp/tennyu")

        self.assertTrue(all(result["found"].values()))
        self.assertEqual(result["clarity"], "明記")
        self.assertIn("必要書類の本文", call.call_args_list[0].args[0])
        self.assertIn('{"name":"転入届"}', call.call_args_list[0].args[0])


def measured_row(**over) -> dict:
    base = {
        "municipality": "港区",
        "found": {"documents": True, "online": True, "deadline": True, "fee": True},
        "values": {k: "値" for k in eng.ITEM_KEYS},
        "reasons": {k: "" for k in eng.ITEM_KEYS},
        "page_notes": "",
        "clarity": "明記",
        "hops": 3,
        "measured_at": "2026-07-21〜2026-08-05",
        "followed": [],
    }
    base.update(over)
    return base


class RepoPathTest(unittest.TestCase):
    """このリポジトリは公開している。他の人がクローンしても動く場所を指すこと。"""

    def test_REPOはこのファイルから導く(self):
        """絶対パスを直書きすると、書いた本人のマシンでしか動かない。

        README では「触ってみたい方は START-HERE.md の『動かす』から」と
        呼びかけている。クローンした人の手元で MEASURED が空になると、
        23区の実測が即答できず「動かない」ように見える。
        """
        expected = Path(__file__).resolve().parent.parent
        self.assertEqual(Path(eng.REPO).resolve(), expected)

    def test_実測データの置き場が実在する(self):
        self.assertTrue(Path(eng.EXTRACT_DIR).exists(),
                        f"実測データの置き場が無い: {eng.EXTRACT_DIR}")


class NormUrlTest(unittest.TestCase):
    """URLの正規化。ここが緩いと実測にあるページを「未知」と誤判定してライブ判定に落ちる。"""

    def test_スキームとwwwと末尾スラッシュを吸収する(self):
        forms = [
            "https://www.city.minato.tokyo.jp/a/b.html",
            "http://city.minato.tokyo.jp/a/b.html",
            "https://city.minato.tokyo.jp/a/b.html/",
            "  https://WWW.City.Minato.Tokyo.JP/a/b.html  ",
        ]
        normalized = {eng._norm_url(u) for u in forms}
        self.assertEqual(len(normalized), 1, f"揃わなかった: {normalized}")

    def test_クエリとフラグメントを落とす(self):
        self.assertEqual(eng._norm_url("https://a.lg.jp/x.html?utm=1#sec"),
                         eng._norm_url("https://a.lg.jp/x.html"))

    def test_空でも落ちない(self):
        self.assertEqual(eng._norm_url(""), "")
        self.assertEqual(eng._norm_url(None), "")


class ParseJsonTest(unittest.TestCase):
    """LLMの返事からJSONを取り出す。前後の説明文やコードフェンスに耐えること。"""

    def test_素のJSON(self):
        self.assertEqual(eng._parse_json('{"a": 1}'), {"a": 1})

    def test_コードフェンス付き(self):
        self.assertEqual(eng._parse_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_前後に説明文があっても取れる(self):
        self.assertEqual(eng._parse_json('はい。\n{"a": 1}\n以上です。'), {"a": 1})

    def test_JSONが無ければ例外(self):
        with self.assertRaises(ValueError):
            eng._parse_json("JSONはありません")


class ScoreTest(unittest.TestCase):
    """回答があっても4条件が揃うまで点にしない。"""

    URL = "https://www.city.minato.tokyo.jp/a/b.html"

    def setUp(self):
        self.table = {eng._norm_url(self.URL): measured_row()}
        p = mock.patch.object(eng, "MEASURED", self.table)
        p.start(); self.addCleanup(p.stop)

    def test_実測にあれば実測を返す(self):
        r = eng.score(self.URL, None)
        self.assertEqual(r["source"], "measured")
        self.assertEqual(r["municipality"], "港区")
        self.assertEqual(r["measured_at"], "2026-07-21〜2026-08-05")

    def test_4項目すべて回答ありでも未検証(self):
        r = eng.score(self.URL, None)
        self.assertIsNone(r["item_pt"])
        self.assertEqual(r["clarity_pt"], 20)
        self.assertIsNone(r["total"])
        self.assertEqual(r["evaluation_status"], "not_checked")
        self.assertTrue(all(point is None for point in r["field_points"].values()))

    def test_オンライン明示の配点(self):
        self.assertEqual(eng.CLARITY_POINTS, {"明記": 20, "曖昧": 10, "記載なし": 0})
        for clarity, pt in eng.CLARITY_POINTS.items():
            with self.subTest(clarity=clarity):
                self.table[eng._norm_url(self.URL)] = measured_row(clarity=clarity)
                r = eng.score(self.URL, None)
                self.assertEqual(r["clarity_pt"], pt)

    def test_回答なしも検証前に0点と決めない(self):
        self.table[eng._norm_url(self.URL)] = measured_row(
            found={"documents": True, "online": True, "deadline": True, "fee": False})
        r = eng.score(self.URL, None)
        self.assertIsNone(r["item_pt"])
        self.assertFalse(r["found"]["fee"])

    def test_checksで絞っても未検証は点にならない(self):
        r = eng.score(self.URL, ["fee"])
        self.assertIsNone(r["item_pt"])

    def test_絞った外の項目はNoneで返る(self):
        """False（読めなかった）と None（そもそも見ていない）を混ぜない。"""
        r = eng.score(self.URL, ["fee"])
        self.assertIsNone(r["found"]["documents"])
        self.assertTrue(r["found"]["fee"])
        self.assertIsNone(r["evaluations"]["documents"])

    def test_4条件を通った項目だけ20点(self):
        passed = eng.evaluate_item(
            {"found": True, "evidence_check": {"verdict": "exact"}},
            expected_found=True,
            support="yes",
            elements=[{"id": 1, "covered": "yes"}],
            required_count=1,
        )
        self.table[eng._norm_url(self.URL)] = measured_row(
            evaluations={key: passed for key in eng.ITEM_KEYS})
        r = eng.score(self.URL, None)
        self.assertEqual(r["item_pt"], 80)
        self.assertEqual(r["total"], 100)
        self.assertEqual(r["evaluation_status"], "pass")

    def test_未知のURLはライブ判定に回る(self):
        with mock.patch.object(eng, "judge_live", return_value=measured_row(
                municipality="", measured_at=None)) as m:
            r = eng.score("https://unknown.lg.jp/x.html", None)
        self.assertEqual(r["source"], "live")
        m.assert_called_once()

    def test_ライブ禁止なら未知URLは例外(self):
        with self.assertRaises(RuntimeError):
            eng.score("https://unknown.lg.jp/x.html", None, allow_live=False)

    def test_読めない理由を画面まで運ぶ(self):
        self.table[eng._norm_url(self.URL)] = measured_row(
            found={"documents": True, "online": True, "deadline": True, "fee": False},
            reasons={"documents": "", "online": "", "deadline": "", "fee": "記載なし"})
        r = eng.score(self.URL, None)
        self.assertEqual(r["reasons"]["fee"], "記載なし")


class TemplateTest(unittest.TestCase):
    """処方箋。実測で「そのまま貼っても点は上がらない／埋めれば上がる」と分かっている。

    だから型は空欄つきで出す。空欄を消して「そのまま貼れる完成文」にしてはいけない。
    AIが役所の情報を作り出さないための設計。
    """

    def test_4項目ぶんある(self):
        self.assertEqual(set(eng.TEMPLATES), set(eng.ITEM_KEYS))

    def test_空欄を残している項目がある(self):
        blanks = [k for k, v in eng.TEMPLATES.items() if "（" in v and "）" in v]
        self.assertTrue(blanks, "空欄が1つも無い。埋めるのは職員、という設計が消えている")

    def test_窓口の型は窓口名と受付時間の両方を空欄で残す(self):
        """片方でも埋めて出すと、AIが役所の運用を決めたことになる。

        窓口名も受付時間も自治体ごとに違う。ここを「区民課」などと書いて出すのは、
        サイトに書かれていないことをAIが作り出すのと同じ。
        """
        online = eng.TEMPLATES["online"]
        for label in ("受付窓口", "受付時間"):
            with self.subTest(label=label):
                line = next((ln for ln in online.splitlines() if label in ln), None)
                self.assertIsNotNone(line, f"{label} の行が無い")
                self.assertIn("（", line, f"{label} が空欄になっていない: {line}")

    def test_型が空文字でない(self):
        for k, v in eng.TEMPLATES.items():
            with self.subTest(key=k):
                self.assertTrue(v.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)

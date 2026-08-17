"""採点層のテスト — 公開している数字が、どう作られているかを固定する。

デッキ・公開ダッシュボード・提出フォームに出している点数は全部ここから出ている。
だからここは「たまたま今そう動いている」ではなく「こう決めた」を書き残す必要がある。

LLM（`claude -p`）は呼ばない。呼ばずに決まる経路だけを対象にしている。
標準ライブラリのみ。

実行: python3 -m unittest discover -s scorer -p 'test_*.py'
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import score  # noqa: E402
from score import (  # noqa: E402
    FIELDS,
    ONLINE_CLARITY_POINTS,
    GoldenRow,
    judge,
    parse_elements,
    parse_judgment_reply,
    score_one,
)


def golden(field: str, *, expected_found: bool = True, elements: str = "スロット=内容") -> GoldenRow:
    return GoldenRow(
        municipality_id="minato", procedure_id="tennyu", field=field,
        expected_found=expected_found, expected_value="値", note="", source_url="",
        required_elements=parse_elements(elements),
    )


def item(*, found: bool, value: str = "答え", failure_reason: str = "",
         evidence_verdict: str | None = "exact") -> dict:
    result = {
        "found": found,
        "value": value,
        "evidence": "根拠の引用文です",
        "failure_reason": failure_reason,
        "source": "html" if found else None,
    }
    if evidence_verdict is not None:
        result["evidence_check"] = {"verdict": evidence_verdict}
    return result


def extraction(**over) -> dict:
    base = {
        "municipality": "港区", "municipality_id": "minato",
        "procedure": "転入届", "procedure_id": "tennyu",
        "reached": True,
        "online_clarity": "明記",
        "page": {"url": "https://example.lg.jp/a.html", "hops": 3,
                 "is_pdf": False, "has_jsonld": True},
        "items": {f: item(found=True) for f in FIELDS},
    }
    base.update(over)
    return base


class ParseElementsTest(unittest.TestCase):
    """必須要素の読み方。分母が変わると点の意味が変わるので、ここは厳密に。"""

    def test_区切りで読む(self):
        self.assertEqual(parse_elements("a=あ|b=い"), [("a", "あ"), ("b", "い")])

    def test_ハイフンは分母から外す(self):
        """`-` は「そのサイトがその要求を課していない」。分母に入れると不当に減点される。"""
        self.assertEqual(parse_elements("a=あ|b=-|c=う"), [("a", "あ"), ("c", "う")])

    def test_空は無視する(self):
        self.assertEqual(parse_elements("a=あ||b=い"), [("a", "あ"), ("b", "い")])

    def test_空文字なら要素なし(self):
        self.assertEqual(parse_elements(""), [])
        self.assertEqual(parse_elements(None), [])


class JudgeRuleTest(unittest.TestCase):
    """LLMを呼ばずに決まる判定。ここが崩れると全部の点が崩れる。"""

    def test_記載が無く見つからないと答えたら満点(self):
        v = judge(golden("手数料", expected_found=False), item(found=False), "港区", "転入届", "m")
        self.assertEqual(v["points"], 10.0)
        self.assertEqual(v["judged_by"], "rule")

    def test_記載が無いのに答えたら0点_幻覚(self):
        """サイトに書いていないことを答えるのは、正解ではなく幻覚。ここを甘くしない。"""
        v = judge(golden("手数料", expected_found=False), item(found=True), "港区", "転入届", "m")
        self.assertEqual(v["points"], 0.0)
        self.assertEqual(v["verdict"], "不正解(幻覚)")

    def test_記載があるのに見つけられなければ0点(self):
        v = judge(golden("手数料"), item(found=False, failure_reason="本文になし"),
                  "港区", "転入届", "m")
        self.assertEqual(v["points"], 0.0)
        self.assertEqual(v["verdict"], "不正解")

    def test_必須要素が無ければ未採点(self):
        """LLMに投げず「未採点」で止める。ここを0点と混同すると点の意味が壊れる。"""
        v = judge(golden("手数料", elements=""), item(found=True), "港区", "転入届", "m")
        self.assertEqual(v["verdict"], "未採点")
        self.assertEqual(v["points"], 0.0)


class ParseJudgmentReplyTest(unittest.TestCase):
    VALID = (
        '{"elements": [{"id": 1, "covered": "yes", "why": "明記"}], '
        '"evidence_supports_answer": "yes", "support_reason": "根拠にある"}'
    )

    def test_厳格なJSONを読む(self):
        parsed = parse_judgment_reply(self.VALID, 1)
        self.assertEqual(parsed["elements"][0]["id"], 1)
        self.assertEqual(parsed["evidence_supports_answer"], "yes")
        self.assertEqual(
            parse_judgment_reply(f"```json\n{self.VALID}\n```", 1), parsed)

    def test_前置きや後置きを許さない(self):
        for raw in ("前置き" + self.VALID, self.VALID + "後置き", "", None):
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                parse_judgment_reply(raw, 1)

    def test_rootとキーを厳格にする(self):
        for raw in (
            "[]",
            '{"elements": [], "evidence_supports_answer": "yes"}',
            self.VALID[:-1] + ', "extra": true}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_judgment_reply(raw, 1)

    def test_要素数_順序_ID_yesno_理由を厳格にする(self):
        import json
        bad_elements = (
            [],
            [{"id": 2, "covered": "yes", "why": "明記"}],
            [{"id": 1, "covered": True, "why": "明記"}],
            [{"id": 1, "covered": "maybe", "why": "明記"}],
            [{"id": 1, "covered": "yes", "why": ""}],
            [{"id": 1, "covered": "yes", "why": "明記", "extra": 1}],
            ["yes"],
        )
        for elements in bad_elements:
            raw = json.dumps({
                "elements": elements,
                "evidence_supports_answer": "yes",
                "support_reason": "根拠にある",
            }, ensure_ascii=False)
            with self.subTest(elements=elements), self.assertRaises(ValueError):
                parse_judgment_reply(raw, 1)

    def test_Evidence支持値と理由を厳格にする(self):
        import json
        for support, reason in ((True, "理由"), ("pass", "理由"),
                                ("yes", ""), ("no", None)):
            raw = json.dumps({
                "elements": [{"id": 1, "covered": "yes", "why": "明記"}],
                "evidence_supports_answer": support,
                "support_reason": reason,
            }, ensure_ascii=False)
            with self.subTest(support=support, reason=reason), self.assertRaises(ValueError):
                parse_judgment_reply(raw, 1)

    def test_required_countは正整数だけ(self):
        for value in (0, -1, True, 1.0, "1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_judgment_reply(self.VALID, value)


class ScoreOneTest(unittest.TestCase):
    """合計点の作り方。配点は 情報到達20＋抽出正確性40＋機械可読性20＋オンライン明示20。

    judge() は差し替える。ここで確かめたいのは「点の足し方」であって判定の中身ではない。
    差し替えないと `claude -p` を呼びに行き、テストがネットワークとログイン状態に依存する。
    """

    def setUp(self):
        # 4項目とも満点(10点)を返す判定に固定する
        self._patch = mock.patch.object(
            score, "judge",
            return_value={"verdict": "正解", "points": 10.0, "reason": "",
                          "judged_by": "stub", "missing": [],
                          "elements": [{"id": 1, "covered": "yes", "why": "明記"}],
                          "evidence_support": "yes"})
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _all_golden(self, **kw):
        return {("minato", f): golden(f, **kw) for f in FIELDS}

    def test_到達できなければ情報到達は0点(self):
        r = score_one(extraction(reached=False), self._all_golden(), "m")
        self.assertEqual(r["breakdown"]["情報到達"], 0)
        self.assertEqual(r["breakdown"]["抽出正確性"], 0.0)

    def test_到達できなければオンライン明示も0点(self):
        """到達していないのに online_clarity を点にしてはいけない。"""
        r = score_one(extraction(reached=False, online_clarity="明記"), self._all_golden(), "m")
        self.assertEqual(r["online_clarity"], "記載なし")
        self.assertEqual(r["breakdown"]["オンライン明示"], 0)

    def test_オンライン明示の配点(self):
        self.assertEqual(ONLINE_CLARITY_POINTS, {"明記": 20, "曖昧": 10, "記載なし": 0})
        for clarity, pts in ONLINE_CLARITY_POINTS.items():
            with self.subTest(clarity=clarity):
                r = score_one(extraction(online_clarity=clarity), self._all_golden(), "m")
                self.assertEqual(r["breakdown"]["オンライン明示"], pts)

    def test_PDFは機械可読性のHTML分を取れない(self):
        r = score_one(extraction(page={"url": "u", "hops": 1, "is_pdf": True, "has_jsonld": False}),
                      self._all_golden(), "m")
        self.assertEqual(r["breakdown"]["機械可読性"], 0)

    def test_構造化データがあれば機械可読性10点(self):
        r = score_one(extraction(page={"url": "u", "hops": 1, "is_pdf": False, "has_jsonld": True}),
                      self._all_golden(), "m")
        self.assertEqual(r["breakdown"]["機械可読性"], 20)

    def test_合計は内訳の和(self):
        r = score_one(extraction(), self._all_golden(expected_found=False), "m")
        self.assertEqual(r["total"], round(sum(r["breakdown"].values()), 1))

    def test_満点は100(self):
        """記載なしを正しく報告した場合、4項目×10点＝40点満点。

        ここだけ judge() の差し替えを外し、本物のルール経路を通す。
        """
        self._patch.stop()
        self.addCleanup(self._patch.start)
        r = score_one(extraction(items={f: item(found=False) for f in FIELDS}),
                      self._all_golden(expected_found=False), "m")
        self.assertEqual(r["breakdown"]["抽出正確性"], 40.0)
        self.assertEqual(r["total"], 100.0)

    def test_ゴールデン行が無いと未採点になる(self):
        """⚠️ これを「点が低い」と読み違えないための固定。

        ゴールデンセットに行が無い自治体は、抽出正確性が丸ごと0になる。
        だが情報到達・機械可読性・オンライン明示は付くので、合計は50点などになる。
        これは「そのページが50点」ではなく「採点していない」。
        公開している scores.csv とは別物なので、並べて比較してはいけない。
        """
        r = score_one(extraction(), golden_missing := {}, "m")
        self.assertEqual(golden_missing, {})
        for f in r["fields"]:
            self.assertEqual(f["verdict"], "未採点")
        self.assertEqual(r["breakdown"]["抽出正確性"], 0.0)
        # 到達20 + 機械可読20 + オンライン明示20 = 60。採点していないのに点が付く
        self.assertEqual(r["total"], 60.0)

    def test_項目は常に4つ返る(self):
        r = score_one(extraction(), self._all_golden(), "m")
        self.assertEqual([f["field"] for f in r["fields"]], FIELDS)

    def test_各項目に4判定を保存する(self):
        r = score_one(extraction(), self._all_golden(), "m")
        for field in r["fields"]:
            self.assertEqual(field["evaluation"]["overall"], "pass")
            self.assertEqual(field["evaluation"]["points"], 20)

    def test_found_trueだけでは検証済みにならない(self):
        items = {f: item(found=True, evidence_verdict=None) for f in FIELDS}
        r = score_one(extraction(items=items), self._all_golden(), "m")
        for field in r["fields"]:
            self.assertEqual(field["evaluation"]["overall"], "not_checked")
            self.assertIsNone(field["evaluation"]["points"])

    def test_ページ未到達なら記載なし正解でも評価fail(self):
        r = score_one(
            extraction(reached=False, items={f: item(found=False) for f in FIELDS}),
            self._all_golden(expected_found=False), "m")
        for field in r["fields"]:
            self.assertEqual(field["evaluation"]["overall"], "fail")
            self.assertEqual(field["evaluation"]["points"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

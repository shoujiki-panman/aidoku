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
    score_one,
)


def golden(field: str, *, expected_found: bool = True, elements: str = "スロット=内容") -> GoldenRow:
    return GoldenRow(
        municipality_id="minato", procedure_id="tennyu", field=field,
        expected_found=expected_found, expected_value="値", note="", source_url="",
        required_elements=parse_elements(elements),
    )


def item(*, found: bool, value: str = "答え", failure_reason: str = "") -> dict:
    return {"found": found, "value": value, "evidence": "", "failure_reason": failure_reason,
            "source": None}


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

    def test_confidenceは採点に使わない(self):
        base = item(found=False)
        low = judge(
            golden("手数料", expected_found=False),
            {**base, "confidence": 0.0}, "港区", "転入届", "m")
        high = judge(
            golden("手数料", expected_found=False),
            {**base, "confidence": 1.0}, "港区", "転入届", "m")
        self.assertEqual(low, high)


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
                          "judged_by": "stub", "missing": [], "elements": []})
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


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""4判定Evaluatorの契約テスト。"""

from __future__ import annotations

import unittest

from evaluator import (
    CHECK_NAMES,
    CHECK_STATUSES,
    EVALUATOR_VERSION,
    answer_correct,
    check,
    evaluate_item,
    evaluation_from_item,
    evidence_exists,
    evidence_supports_answer,
    ground_truth_matches,
    overall_status,
    points_for,
)


def item(found=True, verdict="exact"):
    result = {"found": found, "value": "答え", "evidence": "根拠"}
    if verdict is not None:
        result["evidence_check"] = {"verdict": verdict}
    return result


class VocabularyTest(unittest.TestCase):
    def test_語彙と順序を固定する(self):
        self.assertEqual(EVALUATOR_VERSION, "1.0")
        self.assertEqual(CHECK_NAMES, (
            "answer_correct", "evidence_exists",
            "evidence_supports_answer", "ground_truth_matches"))
        self.assertEqual(CHECK_STATUSES,
                         ("pass", "fail", "not_checked", "not_applicable"))

    def test_判定契約は未知値と空欄を拒否する(self):
        with self.assertRaisesRegex(ValueError, "未定義"):
            check("unknown", "理由", "rule")
        for reason, method in (("", "rule"), (None, "rule"), ("理由", "")):
            with self.subTest(reason=reason, method=method), self.assertRaises(ValueError):
                check("pass", reason, method)


class AnswerCorrectTest(unittest.TestCase):
    def test_GroundTruthなしは未検証(self):
        self.assertEqual(answer_correct(True)["status"], "not_checked")

    def test_情報有無の一致だけを見る(self):
        for found, expected, status in (
                (True, True, "pass"), (False, False, "pass"),
                (True, False, "fail"), (False, True, "fail")):
            with self.subTest(found=found, expected=expected):
                self.assertEqual(answer_correct(found, expected)["status"], status)

    def test_bool以外を拒否する(self):
        for value in (1, 0, "true", None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                answer_correct(value, True)

    def test_ページ未到達は記載なし正解でもfail(self):
        self.assertEqual(answer_correct(False, False, False)["status"], "fail")
        for value in (0, 1, None, "false"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                answer_correct(False, False, value)


class EvidenceExistsTest(unittest.TestCase):
    def test_found_falseは対象外(self):
        self.assertEqual(evidence_exists(False)["status"], "not_applicable")

    def test_全文確認だけpass(self):
        for verdict, status in (
                ("exact", "pass"), ("normalized", "pass"),
                ("partial", "not_checked"), ("too_short", "not_checked"),
                ("not_checked", "not_checked"), ("missing", "fail")):
            with self.subTest(verdict=verdict):
                self.assertEqual(
                    evidence_exists(True, {"verdict": verdict})["status"], status)

    def test_未実施は未検証(self):
        self.assertEqual(evidence_exists(True)["status"], "not_checked")

    def test_矛盾と未知値を拒否する(self):
        for value in ({"verdict": "not_applicable"}, {"verdict": "maybe"}, [], "exact"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evidence_exists(True, value)


class EvidenceSupportsTest(unittest.TestCase):
    def test_found_falseは対象外(self):
        self.assertEqual(evidence_supports_answer(False, "yes")["status"],
                         "not_applicable")

    def test_yes_noと未実施(self):
        self.assertEqual(evidence_supports_answer(True, "yes")["status"], "pass")
        self.assertEqual(evidence_supports_answer(True, "no")["status"], "fail")
        self.assertEqual(evidence_supports_answer(True)["status"], "not_checked")

    def test_boolや未知値を受理しない(self):
        for value in (True, False, "pass", "", 1, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evidence_supports_answer(True, value)


class GroundTruthTest(unittest.TestCase):
    def test_GroundTruthなしは未検証(self):
        self.assertEqual(ground_truth_matches(True)["status"], "not_checked")

    def test_記載なしが正解ならpass(self):
        self.assertEqual(ground_truth_matches(False, False)["status"], "pass")

    def test_found不一致はfail(self):
        self.assertEqual(ground_truth_matches(False, True)["status"], "fail")
        self.assertEqual(ground_truth_matches(True, False)["status"], "fail")

    def test_必須要素の全件一致だけpass(self):
        yes = [{"id": 1, "covered": "yes"}, {"id": 2, "covered": "yes"}]
        partial = [{"id": 1, "covered": "yes"}, {"id": 2, "covered": "no"}]
        self.assertEqual(ground_truth_matches(True, True, yes, 2)["status"], "pass")
        self.assertEqual(ground_truth_matches(True, True, partial, 2)["status"], "fail")

    def test_必須要素なしと未実施を分ける(self):
        self.assertEqual(ground_truth_matches(True, True)["status"], "not_checked")
        self.assertEqual(ground_truth_matches(True, True, None, 2)["status"],
                         "not_checked")

    def test_要素数_順序_ID_yesnoを厳格にする(self):
        bad = (
            ([{"id": 1, "covered": "yes"}], 2),
            ([{"id": 2, "covered": "yes"}], 1),
            ([{"id": 1, "covered": True}], 1),
            ([{"id": 1, "covered": "maybe"}], 1),
            (["yes"], 1),
        )
        for elements, count in bad:
            with self.subTest(elements=elements), self.assertRaises(ValueError):
                ground_truth_matches(True, True, elements, count)


class OverallTest(unittest.TestCase):
    @staticmethod
    def checks(*statuses):
        return {name: check(status, "理由", "rule")
                for name, status in zip(CHECK_NAMES, statuses)}

    def test_failを優先する(self):
        self.assertEqual(overall_status(self.checks(
            "pass", "not_checked", "fail", "pass")), "fail")

    def test_未検証をpassへ丸めない(self):
        self.assertEqual(overall_status(self.checks(
            "pass", "pass", "not_checked", "pass")), "not_checked")

    def test_対象外を除いた全件pass(self):
        self.assertEqual(overall_status(self.checks(
            "pass", "not_applicable", "not_applicable", "pass")), "pass")

    def test_全件対象外は未検証(self):
        self.assertEqual(overall_status(self.checks(*(["not_applicable"] * 4))),
                         "not_checked")

    def test_キー欠落_余分_型違いを拒否する(self):
        with self.assertRaises(ValueError):
            overall_status({})
        with self.assertRaises(ValueError):
            overall_status({**self.checks(*(["pass"] * 4)), "extra": {}})
        with self.assertRaises(ValueError):
            overall_status({name: "pass" for name in CHECK_NAMES})

    def test_判定理由と方法の欠落_余分なキーを拒否する(self):
        values = self.checks(*(["pass"] * 4))
        del values["answer_correct"]["reason"]
        with self.assertRaisesRegex(ValueError, "キー"):
            overall_status(values)
        values = self.checks(*(["pass"] * 4))
        values["answer_correct"]["extra"] = True
        with self.assertRaisesRegex(ValueError, "キー"):
            overall_status(values)

    def test_配点はpass20_fail0_未検証null(self):
        self.assertEqual(points_for("pass"), 20)
        self.assertEqual(points_for("fail"), 0)
        self.assertIsNone(points_for("not_checked"))
        for value in ("not_applicable", "unknown", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                points_for(value)


class EvaluateItemTest(unittest.TestCase):
    def test_4判定がpassなら20点(self):
        result = evaluate_item(
            item(), expected_found=True, support="yes",
            elements=[{"id": 1, "covered": "yes"}], required_count=1)
        self.assertEqual(result["overall"], "pass")
        self.assertEqual(result["points"], 20)

    def test_found_trueだけでは点を付けない(self):
        result = evaluate_item(item(verdict=None))
        self.assertEqual(result["overall"], "not_checked")
        self.assertIsNone(result["points"])

    def test_記載なしが正解ならEvidenceなしでpass(self):
        result = evaluate_item(item(found=False, verdict=None), expected_found=False)
        self.assertEqual(result["overall"], "pass")
        self.assertEqual(result["points"], 20)

    def test_ページ未到達なら記載なし正解でもfail(self):
        result = evaluate_item(
            item(found=False, verdict=None), expected_found=False, reached=False)
        self.assertEqual(result["overall"], "fail")
        self.assertEqual(result["points"], 0)

    def test_記録済みevaluationの改ざんを拒否する(self):
        value = item()
        value["evaluation"] = evaluate_item(
            value, expected_found=True, support="yes",
            elements=[{"id": 1, "covered": "yes"}], required_count=1)
        self.assertEqual(evaluation_from_item(value)["overall"], "pass")
        value["evaluation"]["points"] = 0
        with self.assertRaisesRegex(ValueError, "points"):
            evaluation_from_item(value)

    def test_記録済みevaluationのrootとfound整合を厳格にする(self):
        value = item()
        value["evaluation"] = evaluate_item(
            value, expected_found=True, support="yes",
            elements=[{"id": 1, "covered": "yes"}], required_count=1)
        value["evaluation"]["extra"] = True
        with self.assertRaisesRegex(ValueError, "キー"):
            evaluation_from_item(value)

        value = item(found=False, verdict=None)
        value["evaluation"] = evaluate_item(value, expected_found=False)
        value["evaluation"]["checks"]["evidence_exists"] = check(
            "pass", "不正な記録", "fixture")
        value["evaluation"]["overall"] = "pass"
        value["evaluation"]["points"] = 20
        with self.assertRaisesRegex(ValueError, "found=false"):
            evaluation_from_item(value)

        value = item()
        value["found"] = 1
        value["evaluation"] = evaluate_item(item(), expected_found=True, support="yes",
                                             elements=[{"id": 1, "covered": "yes"}],
                                             required_count=1)
        with self.assertRaisesRegex(ValueError, "found"):
            evaluation_from_item(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)

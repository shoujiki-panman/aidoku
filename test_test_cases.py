"""Test Caseの単位とtargets/fact_typesの接続を固定する。"""

from __future__ import annotations

import json
import unittest

from measurement_cases import (
    TARGETS_PATH,
    TestCaseError,
    build_test_cases,
    test_cases_for,
)


class TestCaseContractTest(unittest.TestCase):
    def test_転入届はfact_typeごとの4件になる(self):
        cases = test_cases_for("tennyu", "練馬区")
        self.assertEqual(
            [case.fact_type for case in cases],
            ["documents", "channel", "deadline", "fee"],
        )
        for case in cases:
            with self.subTest(fact_type=case.fact_type):
                self.assertEqual(case.service, "tennyu")
                self.assertIn("練馬区", case.question)
                self.assertIn("転入届", case.question)
                self.assertEqual(case.test_case_version, "1.0")

    def test_質問はfact_typeごとに異なる(self):
        cases = test_cases_for("tennyu", "練馬区")
        self.assertEqual(len({case.question for case in cases}), 4)
        self.assertIn("持ち物", cases[0].question)
        self.assertIn("オンライン", cases[1].question)
        self.assertIn("いつまで", cases[2].question)
        self.assertIn("手数料", cases[3].question)

    def test_未知serviceは黙って空にしない(self):
        with self.assertRaisesRegex(TestCaseError, "serviceは1件だけ必要"):
            test_cases_for("unknown", "練馬区")

    def test_中央fact_type対象外は明示的に失敗する(self):
        with self.assertRaisesRegex(TestCaseError, "Test Caseの対象外"):
            test_cases_for("hinanjo", "練馬区")

    def test_targetsの全手続きで旧questionとfieldsを測定契約に使わない(self):
        doc = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
        for procedure in doc["procedures"]:
            with self.subTest(service=procedure["id"]):
                self.assertNotIn("question", procedure)
                self.assertNotIn("fields", procedure)
                self.assertTrue(procedure["display_question"].strip())
                if procedure["fact_types"]:
                    cases = build_test_cases(
                        procedure, "テスト自治体", doc["test_case_version"])
                    self.assertEqual(
                        [case.fact_type for case in cases], procedure["fact_types"])


class TestCaseDefinitionErrorTest(unittest.TestCase):
    BASE = {
        "id": "service", "name": "手続き",
        "fact_types": ["documents", "channel", "deadline", "fee"],
    }

    def test_fact_type重複を拒否する(self):
        proc = {**self.BASE, "fact_types": [
            "documents", "channel", "deadline", "documents"]}
        with self.assertRaisesRegex(TestCaseError, "重複"):
            build_test_cases(proc, "練馬区", "1.0")

    def test_未知fact_typeを拒否する(self):
        proc = {**self.BASE, "fact_types": [
            "unknown", "channel", "deadline", "fee"]}
        with self.assertRaisesRegex(TestCaseError, "未知のfact_type"):
            build_test_cases(proc, "練馬区", "1.0")

    def test_空の自治体名を拒否する(self):
        with self.assertRaisesRegex(TestCaseError, "自治体名が空"):
            build_test_cases(self.BASE, " ", "1.0")

    def test_中央4fact_typeの部分指定と順序違いを拒否する(self):
        for fact_types in (["documents"],
                           ["channel", "documents", "deadline", "fee"]):
            with self.subTest(fact_types=fact_types):
                proc = {**self.BASE, "fact_types": fact_types}
                with self.assertRaisesRegex(TestCaseError, "中央4 fact_type"):
                    build_test_cases(proc, "練馬区", "1.0")

    def test_versionの欠落と不正形式を拒否する(self):
        for version in (None, "", "v1", "1", "01.0", "1.0.0",
                        "1٠.1", "1.1٠", -1, True):
            with self.subTest(version=version):
                with self.assertRaisesRegex(TestCaseError, "versionが不正"):
                    build_test_cases(self.BASE, "練馬区", version)

    def test_0系のversionも使える(self):
        self.assertEqual(
            build_test_cases(self.BASE, "練馬区", "0.1")[0].test_case_version,
            "0.1",
        )

    def test_自治体名の型も検証する(self):
        for municipality in (None, 1, False):
            with self.subTest(municipality=municipality):
                with self.assertRaisesRegex(TestCaseError, "自治体名が空"):
                    build_test_cases(self.BASE, municipality, "1.0")


if __name__ == "__main__":
    unittest.main()

"""対外文の数字チェックのテスト。ネットワークにもLLMにも触らない。

実行: python3 -m unittest discover -s analysis -p 'test_*.py'
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import check_claims  # noqa: E402


def muni(name: str, verdicts: list[str]) -> dict:
    fields = [{"field": f, "verdict": v} for f, v in
              zip(["必要書類", "窓口/オンライン可否", "期限", "手数料"], verdicts, strict=True)]
    return {"name": name, "fields": fields}


def procedure(name: str, munis: list[dict], **summary) -> dict:
    base = {"fee_missing": 0, "average": 0, "max": 0, "min": 0}
    base.update(summary)
    return {"procedure": name, "municipalities": munis, "summary": base}


ALL = ["読めた"] * 4
NONE = ["読めない"] * 4


class FactsTest(unittest.TestCase):
    def test_読めた区と読めない区を数える(self):
        data = procedure("転入届", [muni("港区", ALL), muni("世田谷区", NONE),
                                 muni("足立区", ["読めた", "読めた", "読めた", "読めない"])],
                         fee_missing=2, average=60.0, max=100, min=0)
        f = check_claims.facts_for(data)
        self.assertEqual(f["自治体数"], 3)
        self.assertEqual(f["4項目すべて読めた区"], 1)
        self.assertEqual(f["4項目とも読めない区"], 1)
        self.assertEqual(f["手数料が読めない区"], 2)

    def test_区の名前も出せる(self):
        data = procedure("転入届", [muni("港区", ALL), muni("世田谷区", NONE)])
        n = check_claims.names_for(data)
        self.assertEqual(n["4項目すべて読めた区"], ["港区"])
        self.assertEqual(n["4項目とも読めない区"], ["世田谷区"])

    def test_1項目でも読めれば読めない区に数えない(self):
        data = procedure("転入届", [muni("A区", ["読めた"] + ["読めない"] * 3)])
        self.assertEqual(check_claims.facts_for(data)["4項目とも読めない区"], 0)


class CheckTextTest(unittest.TestCase):
    """本題。**手続きを区別できることが肝。**"""

    def setUp(self):
        """実物と同じ形にする（どちらも23自治体）。ここを揃えないと検査が空回りする。"""
        half = ["読めた", "読めた", "読めた", "読めない"]
        tennyu = ([muni("港区", ALL)] + [muni(f"z{i}区", NONE) for i in range(4)]
                  + [muni(f"h{i}区", half) for i in range(18)])
        sodaigomi = ([muni(f"z{i}区", NONE) for i in range(5)]
                     + [muni(f"h{i}区", half) for i in range(18)])
        self.procs = [
            ("tennyu", procedure("転入届", tennyu,
                                 fee_missing=22, average=59.6, max=100, min=0)),
            ("sodaigomi", procedure("粗大ごみ", sodaigomi,
                                    fee_missing=14, average=39.6, max=80, min=0)),
        ]

    def run_check(self, text: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.md"
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with mock.patch.object(check_claims, "load_procedures", return_value=self.procs), \
                 redirect_stdout(buf):
                n = check_claims.check_text(path)
            return n, buf.getvalue()

    def test_手続きが違えば正しい数字でも要確認にする(self):
        """5区は粗大ごみでは正しいが、転入届では誤り。**これが実際に起きた事故。**"""
        n, out = self.run_check("東京23区の転入届を実測した。5区はほとんど読めず。")
        self.assertEqual(n, 1)
        self.assertIn("転入届 の実測に無い", out)
        self.assertIn("粗大ごみなら合う", out)

    def test_その手続きで正しい数字は通す(self):
        n, _ = self.run_check("転入届では4区が読めず、手数料は22区で見つからない。")
        self.assertEqual(n, 0)

    def test_粗大ごみの文脈なら5区は通る(self):
        n, _ = self.run_check("粗大ごみでは5区がほとんど読めない。")
        self.assertEqual(n, 0)

    def test_手続き名が出るまでは全体と比べる(self):
        """文頭など、どの手続きの話か分からないうちは緩く見る。"""
        n, out = self.run_check("5区の話。")
        self.assertEqual(n, 0)
        self.assertNotIn("⚠️", out)

    def test_手続き名が出たら以降その手続きで見る(self):
        n, _ = self.run_check("転入届について。\n次の行で5区と書く。")
        self.assertEqual(n, 1)

    def test_点も見る(self):
        n, out = self.run_check("転入届の平均は70点だった。")
        self.assertEqual(n, 1)
        self.assertIn("70点", out)

    def test_小数の点も扱える(self):
        n, _ = self.run_check("転入届の平均は59.6点。")
        self.assertEqual(n, 0)

    def test_数字が無ければ何も出ない(self):
        n, out = self.run_check("転入届のページを実測した。")
        self.assertEqual(n, 0)
        self.assertIn("実測に無い数字は見つからなかった", out)

    def test_空ファイルでも落ちない(self):
        self.assertEqual(self.run_check("")[0], 0)

    def test_同じ行に複数あっても全部見る(self):
        n, _ = self.run_check("転入届は5区が読めず、平均70点。")
        self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()

"""素で聞いたときのAIの答えを仕分ける部分のテスト。ネットワークにもLLMにも出ない。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cold_ask import QUESTION, cited_urls, outcome, parse_json, summarize  # noqa: E402
from fee_ask import summarize as fee_summarize  # noqa: E402
from stale_ask import NEW_MARKERS, OLD_MARKERS, classify, hedged_change, stamped_now  # noqa: E402


def sorted_ans(answered: bool) -> dict:
    return {"answered": answered, "hedged": False, "value": "…"}


class 住民から見た結果(unittest.TestCase):
    """★1つの数字に潰さない。正直に「分かりません」と答えたAIと、
    自信満々に嘘をついたAIは、住民にとって全く違う。
    """

    def test_分からないと答えた(self):
        self.assertEqual(outcome(sorted_ans(False), "不正解"), "分からないと答えた")

    def test_分からないが最優先(self):
        # 中身を述べていないのに幻覚とは呼べない。
        self.assertEqual(outcome(sorted_ans(False), "不正解(幻覚)"), "分からないと答えた")

    def test_ページに無いことを答えた場合は嘘と決めつけない(self):
        # ★正解データが持っているのは「そのページに書いてあるか」であって
        #   「事実として正しいか」ではない。江戸川区の手数料で実際に起きた。
        self.assertEqual(outcome(sorted_ans(True), "不正解(幻覚)"),
                         "ページに無いことを答えた（真偽不明）")

    def test_正解(self):
        self.assertEqual(outcome(sorted_ans(True), "正解"), "ページどおりに正解")

    def test_記載なしが正しい場合も正解(self):
        self.assertEqual(outcome(sorted_ans(True), "正解(記載なしが正しい)"),
                         "ページどおりに正解")

    def test_部分正解(self):
        self.assertEqual(outcome(sorted_ans(True), "部分正解"), "ページの一部だけ正解")

    def test_それ以外はページと違う(self):
        self.assertEqual(outcome(sorted_ans(True), "不正解"), "ページと違うことを答えた")


class 質問文(unittest.TestCase):
    def test_4項目ぶんある(self):
        self.assertEqual(len(QUESTION), 4)

    def test_住民の聞き方になっている(self):
        for field, text in QUESTION.items():
            with self.subTest(field=field):
                self.assertIn("{muni}", text)
                self.assertIn("？", text)
                # ★「分からなければ分からないと言って」とは書かない。
                #   書くと安全側に寄って、住民が受け取る答えより良く見える。
                self.assertNotIn("分からな", text)


class URLの抽出(unittest.TestCase):
    def test_挙げたURLを拾う(self):
        got = cited_urls("詳しくは https://www.city.a.lg.jp/x.html をご覧ください。")
        self.assertEqual(got, ["https://www.city.a.lg.jp/x.html"])

    def test_括弧や全角括弧で切る(self):
        self.assertEqual(cited_urls("（https://a.example/x）"), ["https://a.example/x"])

    def test_重複は1つにする(self):
        self.assertEqual(len(cited_urls("https://a.example/ と https://a.example/")), 1)

    def test_URLが無ければ空(self):
        self.assertEqual(cited_urls("窓口にお問い合わせください。"), [])


class JSONの取り出し(unittest.TestCase):
    def test_素のJSON(self):
        self.assertEqual(parse_json('{"a": 1}'), {"a": 1})

    def test_コードフェンス付き(self):
        self.assertEqual(parse_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_前後に文章があっても取り出す(self):
        self.assertEqual(parse_json('はい。{"a": 1} 以上です。'), {"a": 1})

    def test_JSONが無ければ落とす(self):
        with self.assertRaises(RuntimeError):
            parse_json("JSONを返しませんでした")


class 古い答え(unittest.TestCase):
    """★パスポート手数料は 2026-07-01 に改定された。旧料金を答えたら確定的に間違い。"""

    def test_新料金を見分ける(self):
        for marker in NEW_MARKERS:
            with self.subTest(marker=marker):
                self.assertEqual(classify(f"手数料は{marker}円です"), "新料金")

    def test_旧料金を見分ける(self):
        for marker in OLD_MARKERS:
            with self.subTest(marker=marker):
                self.assertEqual(classify(f"手数料は{marker}円です"), "旧料金")

    def test_どちらでもない(self):
        self.assertEqual(classify("窓口にお問い合わせください"), "どちらとも言えない")

    def test_空白を無視して見る(self):
        self.assertEqual(classify("16, 000円"), "旧料金")

    def test_今の年月を貼ったことを見分ける(self):
        # ★古い数字に今日の日付を貼るのは、断りではなく逆のことをしている。
        self.assertTrue(stamped_now("2026年8月時点での手数料は16,000円です"))
        self.assertTrue(stamped_now("2026年 8月現在"))
        self.assertFalse(stamped_now("手数料は16,000円です"))

    def test_本当の断りを見分ける(self):
        self.assertTrue(hedged_change("手数料は改定される場合があります"))
        self.assertTrue(hedged_change("最新の情報は公式サイトでご確認ください"))
        self.assertFalse(hedged_change("手数料は16,000円です"))

    def test_日付スタンプは断りではない(self):
        # この2つを1項目にまとめると、危険な答えが安全に見える。実際にそうなった。
        text = "2026年8月時点での手数料は16,000円です"
        self.assertTrue(stamped_now(text))
        self.assertFalse(hedged_change(text))


def cold_row(o: str, answered: bool = True, hedged: bool = False) -> dict:
    return {"outcome": o, "answered": answered, "hedged": hedged}


class 素で聞いた結果の集計(unittest.TestCase):
    def test_内訳を数える(self):
        rows = [cold_row("ページどおりに正解"), cold_row("ページどおりに正解"),
                cold_row("分からないと答えた", answered=False)]
        got = summarize(rows)
        self.assertEqual(got["n"], 3)
        self.assertEqual(got["by_outcome"]["ページどおりに正解"], 2)
        self.assertEqual(got["answered"], 2)

    def test_ページと食い違った件数(self):
        rows = [cold_row("ページと違うことを答えた"), cold_row("ページの一部だけ正解")]
        self.assertEqual(summarize(rows)["contradicts_page"], 2)

    def test_ページに無いことを別に数える(self):
        # 真偽は誰にも確かめられない。不正解に混ぜない。
        rows = [cold_row("ページに無いことを答えた（真偽不明）")]
        got = summarize(rows)
        self.assertEqual(got["beyond_page"], 1)
        self.assertEqual(got["contradicts_page"], 0)


def fee_row(on_page: bool, stated: bool, amount: str = "", told: bool = False) -> dict:
    return {"on_page": on_page, "stated": stated, "amount": amount, "told_to_check": told}


class 手数料を聞いた結果の集計(unittest.TestCase):
    """★見出しは「区が書いていないのに、AIが答えた区の数」。"""

    def test_書いていないのに答えた区を数える(self):
        rows = [fee_row(False, True, "無料"), fee_row(False, False), fee_row(True, True, "無料")]
        got = fee_summarize(rows)
        self.assertEqual(got["not_on_page"], 2)
        self.assertEqual(got["stated_though_not_on_page"], 1)
        self.assertEqual(got["declined_though_not_on_page"], 1)

    def test_ページに書いてある区の答えは数えない(self):
        # 書いてある区でAIが答えるのは当たり前。見出しの数字を薄めない。
        self.assertEqual(fee_summarize([fee_row(True, True, "無料")])["stated_though_not_on_page"], 0)

    def test_答えの内訳を多い順に出す(self):
        rows = [fee_row(False, True, "無料"), fee_row(False, True, "無料"),
                fee_row(False, True, "300円")]
        self.assertEqual(list(fee_summarize(rows)["answers"]), ["無料", "300円"])

    def test_確認を促した回を別に数える(self):
        # 添えられた注意書きは、答えを取り消さない。だから別に数える。
        rows = [fee_row(False, True, "無料", told=True), fee_row(False, True, "無料")]
        self.assertEqual(fee_summarize(rows)["told_to_check"], 1)


if __name__ == "__main__":
    unittest.main()

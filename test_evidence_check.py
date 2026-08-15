"""evidence 照合のテスト。

**判定が緩すぎても厳しすぎても意味が無くなる。**
緩いと捏造を見逃し、厳しいと正しい引用まで missing になって
「捏造が多い」という誤った結論を出す。両側を固定する。
"""

from __future__ import annotations

import unittest

from evidence_check import MIN_RUN, check_items, check_one, normalize, summarize

PAGE = (
    "転入届のご案内 届出期間 引越しをしてきた日（世田谷区に住み始めた日）から14日以内 "
    "持ち物 転出証明書(前住所の役所が発行)、届出する方の本人確認書類 "
    "手数料 無料 受付窓口 各総合支所くみん窓口、各出張所の受付窓口（10か所）で受付しています。"
)


class そのまま含まれる場合(unittest.TestCase):
    def test_完全一致はexact(self):
        r = check_one("引越しをしてきた日（世田谷区に住み始めた日）から14日以内", PAGE)
        self.assertEqual(r["verdict"], "exact")


class 表記のゆれを吸収する(unittest.TestCase):
    """自治体サイトは全角スペース・改行・記号のゆれが多い。
    そのまま比較すると**正しい引用まで missing になる。**"""

    def test_空白の差は吸収する(self):
        r = check_one("引越しをしてきた日 （世田谷区に住み始めた日） から14日以内", PAGE)
        self.assertEqual(r["verdict"], "normalized")

    def test_全角半角の差は吸収する(self):
        r = check_one("各総合支所くみん窓口、各出張所の受付窓口（１０か所）で受付しています。", PAGE)
        self.assertIn(r["verdict"], ("normalized", "partial"))

    def test_記号の有無は吸収する(self):
        r = check_one("転出証明書 前住所の役所が発行 届出する方の本人確認書類", PAGE)
        self.assertIn(r["verdict"], ("normalized", "partial"))


class 要約されている場合(unittest.TestCase):
    def test_連続一致が長ければpartial(self):
        # 前半だけ引用し、後半を自分の言葉にした形
        r = check_one("各総合支所くみん窓口、各出張所の受付窓口で手続きできます", PAGE)
        self.assertEqual(r["verdict"], "partial")
        self.assertGreaterEqual(r["run"], MIN_RUN)


class 捏造を見つける(unittest.TestCase):
    def test_ページに無い文はmissing(self):
        r = check_one("手数料は300円です。オンライン申請の場合は200円に割引されます。", PAGE)
        self.assertEqual(r["verdict"], "missing")

    def test_もっともらしいが本文に無い文もmissing(self):
        # 転入届の一般常識としては正しいが、このページには書いていない
        r = check_one("マイナンバーカードをお持ちの方は転出届が不要になります", PAGE)
        self.assertEqual(r["verdict"], "missing")


class 短すぎる引用は判定しない(unittest.TestCase):
    def test_無料の2文字は照合対象外(self):
        # 「無料」はページのどこにでもあり、照合しても意味が無い
        self.assertEqual(check_one("無料", PAGE)["verdict"], "too_short")


class itemsをまとめて照合する(unittest.TestCase):
    def setUp(self):
        self.items = {
            "必要書類": {"found": True, "evidence": "転出証明書(前住所の役所が発行)、届出する方の本人確認書類"},
            "窓口オンライン可否": {"found": True, "evidence": "各総合支所くみん窓口、各出張所の受付窓口（10か所）で受付しています。"},
            "期限": {"found": True, "evidence": "手数料は1200円です。窓口でお支払いください。"},  # 捏造
            "手数料": {"found": False, "evidence": "記載が見当たらない"},
        }

    def test_found_falseは照合しない(self):
        r = check_items(self.items, PAGE)
        self.assertEqual(r["手数料"]["verdict"], "not_applicable")

    def test_捏造だけがmissingになる(self):
        r = check_items(self.items, PAGE)
        self.assertEqual(r["期限"]["verdict"], "missing")
        self.assertIn(r["必要書類"]["verdict"], ("exact", "normalized", "partial"))

    def test_集計(self):
        s = summarize(check_items(self.items, PAGE))
        self.assertEqual(s["checked"], 3)   # found=false の1件は数えない
        self.assertEqual(s["verified"], 2)
        self.assertEqual(s["missing"], 1)


class 正規化そのもの(unittest.TestCase):
    def test_空白と記号が落ちる(self):
        self.assertEqual(normalize("あ い（う）、え"), "あいうえ")

    def test_全角数字が半角になる(self):
        self.assertEqual(normalize("１０か所"), "10か所")


if __name__ == "__main__":
    unittest.main()

"""fact_type の単一定義が壊れていないかを見る。

なぜテストするか: この定義を間違えると、**公開している全部の点数の意味が変わる。**
特に extractor_key は出力JSONのキー名そのものなので、変えると
web/data/*.json と公開4画面が同時に壊れる。ここを固定する。
"""

from __future__ import annotations

import unittest

from fact_types import (
    DISPLAY_KEYS, EXTRA_MEASURES, EXTRACTOR_KEYS, EXTRACTOR_TO_DISPLAY,
    FACT_TYPES, FIX_TEXT, by_id, id_of,
)


class 既存の出力キーを変えていない(unittest.TestCase):
    """extractor_key は extractor/out/*.json のキー名。変えたら過去の測定が読めなくなる。"""

    def test_抽出側のキー(self):
        self.assertEqual(EXTRACTOR_KEYS,
                         ["必要書類", "窓口オンライン可否", "期限", "手数料"])

    def test_画面側のラベル(self):
        # 画面と scores-*.json は「窓口/オンライン可否」とスラッシュ入り
        self.assertEqual(DISPLAY_KEYS,
                         ["必要書類", "窓口/オンライン可否", "期限", "手数料"])

    def test_対応表(self):
        self.assertEqual(EXTRACTOR_TO_DISPLAY["窓口オンライン可否"], "窓口/オンライン可否")


class 表記ゆれを吸収できる(unittest.TestCase):
    """英語IDが2系統・日本語が2表記に割れていたので、どれからでも引けること。"""

    def test_どの表記からでも同じidになる(self):
        for key in ["channel", "窓口オンライン可否", "窓口/オンライン可否",
                    "how_to_apply", "online"]:
            with self.subTest(key=key):
                self.assertEqual(id_of(key), "channel")

    def test_gatekeeperの英語id(self):
        self.assertEqual(id_of("required_documents"), "documents")

    def test_知らない表記は例外(self):
        with self.assertRaises(KeyError):
            id_of("そんな項目は無い")


class 処方箋が5項目ぶんある(unittest.TestCase):
    """画面は4項目＋オンライン明示の5つに処方箋を出す。"""

    def test_件数(self):
        self.assertEqual(len(FIX_TEXT), 5)

    def test_オンライン明示も入っている(self):
        self.assertIn("オンライン明示", FIX_TEXT)

    def test_全部空でない(self):
        for k, v in FIX_TEXT.items():
            with self.subTest(k=k):
                self.assertTrue(v.strip())


class 定義そのものの健全性(unittest.TestCase):

    def test_idが重複しない(self):
        ids = [f["id"] for f in FACT_TYPES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_全項目に質問文がある(self):
        for f in FACT_TYPES:
            with self.subTest(id=f["id"]):
                self.assertTrue(f["question"].strip())

    def test_by_idが引ける(self):
        self.assertEqual(by_id("fee")["display_label"], "手数料")

    def test_オンライン明示は4項目に含めない(self):
        # 満点判定の分母は4。ここに混ぜると full_marks が壊れる
        self.assertNotIn("オンライン明示", DISPLAY_KEYS)
        self.assertEqual(len(EXTRA_MEASURES), 1)


if __name__ == "__main__":
    unittest.main()

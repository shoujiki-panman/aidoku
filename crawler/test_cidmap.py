"""`crawler/cidmap.py` — CID から文字への対応表（Adobe-Japan1）。

**なぜ要るか**: 読めなかった9本を1本ずつ調べたら、3本は `/ToUnicode` を
1つも持たない CID フォントのPDFだった。**そのPDFだけを見ても文字に戻せない。**

Adobe が対応表を公開している（BSD-3-Clause）ので同梱した。
★ライブラリではなく**データ**。「標準ライブラリのみ」の方針は変えていない。

★**宣言のあるPDFにだけ当てる。** 当たった数で決めると、別の字形集合のPDFに
  それらしい日本語をでっち上げる。実測で品川区のPDFが `Ordering: Identity` だった。
"""

from __future__ import annotations

import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "crawler"))
from cidmap import DATA, adobe_japan1, declares_japan1, japan1_map  # noqa: E402

# 対応表に必ず入っている字。ここが壊れたら表の作り直しを疑う。
KNOWN = {843: "あ", 1125: "亜"}


def objstm(body: bytes) -> bytes:
    """圧縮オブジェクトストリームの形（PDF 1.5以降）。"""
    return b"<< /Type /ObjStm /Filter /FlateDecode >>\nstream\n" + zlib.compress(body)


class 対応表(unittest.TestCase):
    def test_同梱されている(self):
        self.assertTrue(DATA.exists(), "対応表のデータが無い")

    def test_知っている字が引ける(self):
        table = adobe_japan1()
        for cid, ch in KNOWN.items():
            with self.subTest(cid=cid):
                self.assertEqual(table[cid], ch)

    def test_件数が桁違いに減っていない(self):
        # 9,490件で作った。作り直しで大きく減ったら気づけるようにする。
        self.assertGreater(len(adobe_japan1()), 9000)

    def test_二度目は読み直さない(self):
        self.assertIs(adobe_japan1(), adobe_japan1())

    def test_値はすべて1文字(self):
        table = adobe_japan1()
        self.assertTrue(all(len(v) == 1 for v in list(table.values())[:500]))


class 宣言の確認(unittest.TestCase):
    """★ここが要。宣言の無いPDFに当ててはいけない。"""

    def test_生バイトの宣言を見つける(self):
        self.assertTrue(declares_japan1(b"... /Ordering (Japan1) ..."))

    def test_圧縮ストリームの中の宣言も見つける(self):
        """★実測3本とも、生バイトには現れず解いたストリームにだけあった。

        PDF 1.5以降はフォント定義が圧縮オブジェクトストリームに入る。
        """
        raw = b"%PDF-1.7\n" + objstm(b"/Ordering (Japan1) /Encoding /Identity-H")
        self.assertFalse(declares_japan1(raw))
        self.assertTrue(declares_japan1(raw, [b"/Ordering (Japan1)"]))

    def test_別の字形集合には当てない(self):
        # 実測: 品川区の張り紙PDFは Ordering が Identity だった。
        self.assertFalse(declares_japan1(b"/Ordering (Identity)"))
        self.assertFalse(declares_japan1(b"", [b"/Ordering (UCS)"]))

    def test_宣言が無ければ空の表(self):
        self.assertEqual(japan1_map(b"%PDF-1.4 no ordering"), {})

    def test_宣言があれば表を返す(self):
        got = japan1_map(b"/Ordering (Japan1)")
        self.assertEqual(got[843], "あ")

    def test_空でも落ちない(self):
        self.assertFalse(declares_japan1(b""))
        self.assertEqual(japan1_map(b"", []), {})


class 読み取りへの効き方(unittest.TestCase):
    """★実物で確かめる。作った入力だけでは思い込みが素通りする。"""

    def pdf(self, url: str) -> bytes | None:
        import hashlib
        import urllib.parse
        host = urllib.parse.urlparse(url).netloc
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        path = ROOT / "crawler" / "cache" / host / f"{key}.html"
        return path.read_bytes() if path.exists() else None

    def test_ToUnicodeが無い実物が読める(self):
        """世田谷区の児童手当 認定請求書。ToUnicode を1つも持たない。"""
        url = "https://www.city.setagaya.lg.jp/documents/18187/jidouteatesinsesho.pdf"
        raw = self.pdf(url)
        if raw is None:
            self.skipTest("キャッシュが無い")
        from officedoc import read_document
        got = read_document(raw, url)
        self.assertTrue(got.ok, got.reason)
        self.assertIn("児童", got.text)
        self.assertGreater(len(got.text), 1000)

    def test_宣言の無いPDFを勝手に読まない(self):
        """品川区の張り紙PDF。Ordering は Identity で、本文もほぼ無い。"""
        url = ("https://www.city.shinagawa.tokyo.jp/PC/kankyo/kankyo-gomi/"
               "kankyo-gomi-topi/SODAIHARIGAMI.pdf")
        raw = self.pdf(url)
        if raw is None:
            self.skipTest("キャッシュが無い")
        from officedoc import read_document
        # ★読めないままでよい。でっち上げないことが正しい振る舞い。
        self.assertFalse(read_document(raw, url).ok)


if __name__ == "__main__":
    unittest.main()

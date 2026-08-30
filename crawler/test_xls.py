"""`crawler/xls.py` — 古い Excel（BIFF8）から文字を取り出す。

**なぜ要るか**: 虱潰しで「読めない候補が残っている」項目の1本が
大田区の粗大ごみ品目一覧（`.xls`）だった。`.xlsx` しか読めず、
古い形式は「対応していない形式」で落としていた。

読めないものを「その区が書いていない」と言ってはいけない（`METHOD.md §4-7c`）。
だから読めるようにした。外部の変換器は同じファイルを21,166字で読めていた。
**うちが読めないだけだった。**
"""

from __future__ import annotations

import hashlib
import struct
import sys
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "crawler"))
from xls import (  # noqa: E402
    CONTINUE,
    LABEL,
    LABELSST,
    OLE_MAGIC,
    SST,
    _records,
    _unicode_string,
    cell_texts,
    is_xls,
    read_text,
    shared_strings,
    workbook_stream,
)

# 実物。大田区の粗大ごみ品目一覧。
REAL_XLS = ("https://www.city.ota.tokyo.jp/seikatsu/gomi/"
            "sodaigomi_ichiran.files/2025102301.xls")


def record(kind: int, body: bytes) -> bytes:
    return struct.pack("<HH", kind, len(body)) + body


def one_byte_string(text: str) -> bytes:
    """1バイト文字の BIFF8 文字列（欧文の列で使われる）。"""
    raw = text.encode("latin-1")
    return struct.pack("<HB", len(raw), 0x00) + raw


def two_byte_string(text: str) -> bytes:
    """2バイト文字の BIFF8 文字列（日本語はこちら）。"""
    raw = text.encode("utf-16-le")
    return struct.pack("<HB", len(text), 0x01) + raw


class 見分け(unittest.TestCase):
    def test_OLE2の見出しで判断する(self):
        # ★キャッシュは拡張子を持たないので、名前では分からない。
        self.assertTrue(is_xls(OLE_MAGIC + b"rest"))
        self.assertFalse(is_xls(b"PK\x03\x04"))
        self.assertFalse(is_xls(b""))


class 文字列の読み方(unittest.TestCase):
    def test_2バイト文字を読む(self):
        text, nxt = _unicode_string(two_byte_string("手数料"), 0)
        self.assertEqual(text, "手数料")
        self.assertEqual(nxt, 3 + 6)

    def test_1バイト文字を読む(self):
        """★2バイト固定で読むと、英数字だけの列が化ける。

        PDFの `_decode_single_byte` と同じ形の間違いになる。
        """
        text, _ = _unicode_string(one_byte_string("ABC"), 0)
        self.assertEqual(text, "ABC")

    def test_短すぎる入力でも落ちない(self):
        self.assertEqual(_unicode_string(b"\x01", 0)[0], "")


class レコード列(unittest.TestCase):
    def test_種類と中身に分ける(self):
        stream = record(LABEL, b"abc") + record(SST, b"de")
        self.assertEqual([k for k, _ in _records(stream)], [LABEL, SST])

    def test_CONTINUEは直前につなぐ(self):
        """★SST は 8224 バイトで切られて CONTINUE に続く。

        つながないと文字列表が途中で終わり、表の後半がまるごと落ちる。
        """
        stream = record(SST, b"aa") + record(CONTINUE, b"bb")
        got = _records(stream)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][1], b"aabb")

    def test_途中で切れたレコードは捨てる(self):
        self.assertEqual(_records(b"\x04\x02"), [])


class 文字列表(unittest.TestCase):
    def sst_record(self, texts: list[str]) -> list[tuple[int, bytes]]:
        body = struct.pack("<II", len(texts), len(texts))
        for t in texts:
            body += two_byte_string(t)
        return [(SST, body)]

    def test_共有文字列を並びで返す(self):
        got = shared_strings(self.sst_record(["品目", "手数料"]))
        self.assertEqual(got, ["品目", "手数料"])

    def test_SSTが無ければ空(self):
        self.assertEqual(shared_strings([(LABEL, b"x")]), [])

    def test_壊れていても無限ループにしない(self):
        # 取れたところまで返して止まる。件数が増え続けないこと。
        got = shared_strings([(SST, b"\x00" * 8 + b"\x00")])
        self.assertLessEqual(len(got), 1)

    def test_空の文字列も番号を詰めずに残す(self):
        """★空を捨てると LABELSST の番号が全部ずれる。

        SST は「何番目か」で引かれるので、間引いた瞬間に以降のセルが
        すべて別の語を指す。読めない字を作らないのと同じで、**並びを崩さない。**
        """
        got = shared_strings(self.sst_record(["", "手数料"]))
        self.assertEqual(got, ["", "手数料"])
        self.assertEqual(cell_texts(
            [(LABELSST, struct.pack("<HHHI", 0, 0, 0, 1))], got), ["手数料"])


class セルの文字(unittest.TestCase):
    def test_LABELSSTは文字列表を引く(self):
        body = struct.pack("<HHHI", 0, 0, 0, 1)
        got = cell_texts([(LABELSST, body)], ["品目", "手数料"])
        self.assertEqual(got, ["手数料"])

    def test_表に無い番号は飛ばす(self):
        # ★埋めない。読めなかった字を勝手に作らない（PDFと同じ方針）。
        body = struct.pack("<HHHI", 0, 0, 0, 99)
        self.assertEqual(cell_texts([(LABELSST, body)], ["品目"]), [])

    def test_直書きのセルも読む(self):
        body = struct.pack("<HHH", 0, 0, 0) + two_byte_string("備考")
        self.assertEqual(cell_texts([(LABEL, body)], []), ["備考"])

    def test_数値のセルは取らない(self):
        # 金額や枚数だけ拾っても手がかりにならず、文字と混ぜると本文が読めなくなる。
        self.assertEqual(cell_texts([(0x027E, b"\x00" * 10)], ["品目"]), [])


class 読めない入力(unittest.TestCase):
    def test_OLE2でなければ空(self):
        self.assertEqual(read_text(b"<html>"), "")

    def test_短すぎるOLE2でも落ちない(self):
        self.assertEqual(workbook_stream(OLE_MAGIC), b"")

    def test_中身が無ければ空を返す(self):
        # ★読めたふりをしない。空を返して、呼ぶ側が「読めない」と記録できるようにする。
        self.assertEqual(read_text(OLE_MAGIC + b"\x00" * 600), "")


class 実データ(unittest.TestCase):
    """★実物で確かめる。作った入力だけでは、実装の思い込みが素通りする。"""

    def real(self) -> bytes:
        host = urllib.parse.urlparse(REAL_XLS).netloc
        key = hashlib.sha1(REAL_XLS.encode("utf-8")).hexdigest()[:16]
        path = ROOT / "crawler" / "cache" / host / f"{key}.html"
        if not path.exists():
            self.skipTest("キャッシュが無い")
        return path.read_bytes()

    def test_大田区の品目一覧が読める(self):
        text = read_text(self.real())
        self.assertGreater(len(text), 5000)
        self.assertIn("品目", text)
        self.assertIn("アイロン台", text)

    def test_officedocの入口からも読める(self):
        from officedoc import read_document
        got = read_document(self.real(), REAL_XLS)
        self.assertTrue(got.ok, got.reason)
        self.assertEqual(got.kind, "xls")


if __name__ == "__main__":
    unittest.main()

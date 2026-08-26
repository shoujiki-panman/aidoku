"""添付読みのテスト。ネットワークには出ない。標準ライブラリのみ。"""

from __future__ import annotations

import sys
import unittest
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from officedoc import MIN_KANA, kind_of, read_document, read_ooxml, read_pdf, readable  # noqa: E402

KANA = "これは委任状です。代理人に手続きを委任します。" * 3


def docx(parts: dict[str, str]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return buf.getvalue()


def pdf(streams: list[bytes]) -> bytes:
    out = b"%PDF-1.7\n"
    for raw in streams:
        out += b"stream\n" + zlib.compress(raw) + b"\nendstream\n"
    return out


class KindOf(unittest.TestCase):
    def test_拡張子で決める(self):
        self.assertEqual(kind_of("https://x.example/a.docx"), "docx")
        self.assertEqual(kind_of("https://x.example/A.PDF"), "pdf")
        self.assertEqual(kind_of("https://x.example/a.xlsx"), "xlsx")

    def test_クエリが付いていても見る(self):
        self.assertEqual(kind_of("https://x.example/a.pdf?v=2"), "pdf")

    def test_対応外はunknown(self):
        self.assertEqual(kind_of("https://x.example/a.html"), "unknown")
        self.assertEqual(kind_of("https://x.example/a"), "unknown")


class Readable(unittest.TestCase):
    def test_日本語の地の文は通す(self):
        self.assertTrue(readable(KANA))

    def test_言語タグの繰り返しを弾く(self):
        # ★実物。中野区のPDFから68,038字これが取れて「読めた」になっていた。
        self.assertFalse(readable("ja-JP    en-US ja-JP " * 2000))

    def test_文字化けを弾く(self):
        # ★実物。北区のPDFから111,553字これが取れて「読めた」になっていた。
        self.assertFalse(readable("n�Kujvz}�r�L E#E`D B A @E#E`D " * 2000))

    def test_漢字だけでは通さない(self):
        # 漢字は文字化けにも混ざる。仮名が無ければ地の文と認めない。
        self.assertFalse(readable("委任状台東区長殿代理人住所氏名生年月日関係" * 20))

    def test_仮名が少なすぎれば弾く(self):
        self.assertFalse(readable("あ" * (MIN_KANA - 1)))

    def test_空は弾く(self):
        self.assertFalse(readable(""))


class ReadOoxml(unittest.TestCase):
    def test_Wordの本文を取り出す(self):
        data = docx({"word/document.xml": f"<w:p><w:t>{KANA}</w:t></w:p>"})
        got = read_ooxml(data, "docx")
        self.assertTrue(got.ok)
        self.assertIn("委任状", got.text)

    def test_段落の切れ目が改行になる(self):
        data = docx({"word/document.xml": "<w:p><w:t>あ</w:t></w:p><w:p><w:t>い</w:t></w:p>"})
        self.assertIn("\n", read_ooxml(data, "docx").text)

    def test_zipでなければ理由を返す(self):
        got = read_ooxml(b"not a zip", "docx")
        self.assertFalse(got.ok)
        self.assertIn("zip", got.reason)

    def test_本文の部品が無ければ理由を返す(self):
        got = read_ooxml(docx({"docProps/app.xml": "<x/>"}), "docx")
        self.assertFalse(got.ok)
        self.assertIn("部品", got.reason)

    def test_部品はあるが空なら理由を返す(self):
        got = read_ooxml(docx({"word/document.xml": "<w:p></w:p>"}), "docx")
        self.assertFalse(got.ok)
        self.assertIn("空", got.reason)

    def test_エスケープを戻す(self):
        data = docx({"word/document.xml": f"<w:t>{KANA}&amp;A&lt;B&gt;</w:t>"})
        self.assertIn("&A<B>", read_ooxml(data, "docx").text)


class ReadPdf(unittest.TestCase):
    def test_日本語が取れれば読めた(self):
        body = "".join(f"({ch})Tj " for ch in KANA).encode("utf-8")
        got = read_pdf(pdf([body]))
        self.assertTrue(got.ok, got.reason)
        self.assertIn("委任状", got.text)

    def test_Flateでなければ理由を返す(self):
        got = read_pdf(b"%PDF-1.7\nstream\nplain bytes\nendstream\n")
        self.assertFalse(got.ok)
        self.assertIn("Flate", got.reason)

    def test_テキスト演算子が無ければ理由を返す(self):
        got = read_pdf(pdf([b"0 0 m 100 100 l S"]))
        self.assertFalse(got.ok)
        self.assertIn("テキスト演算子", got.reason)

    def test_仮名が無ければ字数を理由に残す(self):
        # ★「読めたふり」をここで止める。取れた字数も残す。
        body = b"".join(b"(ja-JP en-US)Tj " for _ in range(300))
        got = read_pdf(pdf([body]))
        self.assertFalse(got.ok)
        self.assertIn("仮名", got.reason)
        self.assertIn("字取れた", got.reason)


class ReadDocument(unittest.TestCase):
    def test_拡張子で振り分ける(self):
        data = docx({"word/document.xml": f"<w:t>{KANA}</w:t>"})
        self.assertTrue(read_document(data, "https://x.example/a.docx").ok)

    def test_対応外の形式も結果を返す(self):
        got = read_document(b"<html>", "https://x.example/a.html")
        self.assertFalse(got.ok)
        self.assertEqual(got.kind, "unknown")
        self.assertTrue(got.reason)


if __name__ == "__main__":
    unittest.main()

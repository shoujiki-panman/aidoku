"""添付読みのテスト。ネットワークには出ない。標準ライブラリのみ。"""

from __future__ import annotations

import sys
import unittest
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from officedoc import (  # noqa: E402
    MIN_KANA,
    build_cmap,
    is_content_stream,
    kind_of,
    read_document,
    read_ooxml,
    read_pdf,
    readable,
)

KANA = "これは委任状です。代理人に手続きを委任します。" * 3


def docx(parts: dict[str, str]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return buf.getvalue()


def pdf(streams: list[bytes], *, compress: bool = True) -> bytes:
    """本文ストリームらしい形にする（BT … ET で挟む）。"""
    out = b"%PDF-1.7\n"
    for raw in streams:
        body = b"BT /F1 12 Tf\n" + raw + b"\nET\n"
        out += b"stream\n" + (zlib.compress(body) if compress else body) + b"\nendstream\n"
    return out


def cmap_stream(pairs: dict[int, str]) -> bytes:
    """ToUnicode CMap（非圧縮の平文。実物の様式PDFがこの形だった）。"""
    body = "".join(f"<{code:04X}> <{ord(ch):04X}>\n" for code, ch in pairs.items())
    return (f"/CIDInit /ProcSet findresource begin\n{len(pairs)} beginbfchar\n"
            f"{body}endbfchar\nendcmap\n").encode("latin-1")


def pdf_with_cmap(codes: list[int], pairs: dict[int, str]) -> bytes:
    """CIDフォントの本文（<16進>Tj）と対応表を持つPDF。"""
    hexes = "".join(f"{c:04X}" for c in codes)
    out = b"%PDF-1.7\n"
    out += b"stream\n" + cmap_stream(pairs) + b"\nendstream\n"
    out += b"stream\n" + f"BT /F1 12 Tf <{hexes}> Tj ET\n".encode("latin-1") + b"\nendstream\n"
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

    def test_非圧縮のストリームも捨てない(self):
        # ★対応表（ToUnicode CMap）は非圧縮の平文で入っていることがある。
        #   Flateだけ見て捨てていたせいで「CIDフォントで読めない」と誤報していた。
        got = read_pdf(pdf([f"({KANA})Tj".encode()], compress=False))
        self.assertTrue(got.ok, got.reason)
        self.assertIn("委任状", got.text)

    def test_本文のストリームが無ければ理由を返す(self):
        got = read_pdf(b"%PDF-1.7\nstream\nplain bytes\nendstream\n")
        self.assertFalse(got.ok)
        self.assertIn("本文", got.reason)

    def test_描画命令だけなら理由を返す(self):
        out = b"%PDF-1.7\nstream\n" + zlib.compress(b"0 0 m 100 100 l S") + b"\nendstream\n"
        got = read_pdf(out)
        self.assertFalse(got.ok)
        self.assertIn("本文", got.reason)

    def test_仮名が無ければ字数を理由に残す(self):
        # ★「読めたふり」をここで止める。取れた字数も残す。
        body = b"".join(b"(ja-JP en-US)Tj " for _ in range(300))
        got = read_pdf(pdf([body]))
        self.assertFalse(got.ok)
        self.assertIn("仮名", got.reason)
        self.assertIn("字取れた", got.reason)


class 字形の対応表(unittest.TestCase):
    """★日本語の様式PDFは本文が <16進> で書かれ、対応表がPDFの中に入っている。

    最初これを見ておらず「CIDフォントだから読めない」と報告していた。
    読めないのではなく、**対応表を使っていなかった**。
    """

    PAIRS = {0x0100 + i: ch for i, ch in enumerate("これは委任状です。")}

    def test_対応表を使って本文に戻す(self):
        codes = list(self.PAIRS)
        got = read_pdf(pdf_with_cmap(codes * 4, self.PAIRS))
        self.assertTrue(got.ok, got.reason)
        self.assertIn("委任状", got.text)

    def test_対応表を組み立てる(self):
        cmap = build_cmap([cmap_stream(self.PAIRS)])
        self.assertEqual(cmap[0x0100], "こ")
        self.assertEqual(len(cmap), len(self.PAIRS))

    def test_対応表そのものは本文にしない(self):
        # CMapストリームを本文として読むと、定義の16進が本文に混ざる。
        self.assertFalse(is_content_stream(cmap_stream(self.PAIRS)))

    def test_埋め込みフォントは本文にしない(self):
        # ★TrueTypeのバイナリにも BT や Tj の2文字はたまたま現れる。
        #   実物の様式PDFは7本中1本だけが本文で、残りはフォントとCMapだった。
        font = b"\x00\x01\x00\x00" + bytes(range(256)) * 8 + b"BT Tj"
        self.assertFalse(is_content_stream(font))

    def test_本文のストリームは通す(self):
        self.assertTrue(is_content_stream(b"BT /F1 12 Tf <0100> Tj ET"))

    def test_対応表に無いコードは落とす(self):
        # ★埋めない。読めなかった字を勝手に作らない。
        got = build_cmap([cmap_stream(self.PAIRS)])
        self.assertNotIn(0x9999, got)


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

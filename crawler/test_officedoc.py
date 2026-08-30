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
    kind_from,
    kind_of,
    read_document,
    read_ooxml,
    read_pdf,
    readable,
    show_text,
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


def pdf_with_cmap(codes: list[int], pairs: dict[int, str], *,
                  declare_font: bool = True) -> bytes:
    """CIDフォントの本文（<16進>Tj）と対応表を持つPDF。

    ★実物のPDFはフォント資源（/Font << /F1 N 0 R >>）を持ち、本文が Tf で切り替える。
      テストもその形にしないと、実装のどこが効いているか確かめられない。
    """
    hexes = "".join(f"{c:04X}" for c in codes)
    cmap = cmap_stream(pairs)
    out = b"%PDF-1.7\n"
    if declare_font:
        out += b"5 0 obj\n<< /Font << /F1 7 0 R >> >>\nendobj\n"
        out += b"7 0 obj\n<< /Type /Font /Subtype /Type0 /ToUnicode 9 0 R >>\nendobj\n"
    out += b"9 0 obj\n<< /Length " + str(len(cmap)).encode() + b" >>\nstream\n"
    out += cmap + b"\nendstream\nendobj\n"
    body = f"BT /F1 12 Tf <{hexes}> Tj ET\n".encode("latin-1")
    out += b"11 0 obj\nstream\n" + body + b"\nendstream\nendobj\n"
    return out


def hex_pdf(text: str) -> tuple[bytes, dict[int, str]]:
    """日本語の本文を、実物と同じ <16進>＋対応表の形で作る。"""
    pairs = {0x0100 + i: ch for i, ch in enumerate(dict.fromkeys(text))}
    back = {ch: code for code, ch in pairs.items()}
    return pdf_with_cmap([back[ch] for ch in text], pairs), pairs


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
        # ★PDFのリテラル `(…)` は1バイト系の符号化。UTF-8は入らない。
        #   日本語は <16進>＋対応表で書かれる。実物に合わせる。
        data, _ = hex_pdf(KANA)
        got = read_pdf(data)
        self.assertTrue(got.ok, got.reason)
        self.assertIn("委任状", got.text)

    def test_非圧縮のストリームも捨てない(self):
        # ★対応表（ToUnicode CMap）は非圧縮の平文で入っていることがある。
        #   Flateだけ見て捨てていたせいで「CIDフォントで読めない」と誤報していた。
        #   hex_pdf の対応表は非圧縮で入れてある。これが読めれば通る。
        data, _ = hex_pdf(KANA)
        self.assertNotIn(b"x\x9c", data)          # Flate圧縮していないこと
        got = read_pdf(data)
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
        got = read_pdf(pdf_with_cmap(list(self.PAIRS) * 4, self.PAIRS))
        self.assertTrue(got.ok, got.reason)
        self.assertIn("委任状", got.text)

    def test_対応表を持たないフォントは1バイトで読む(self):
        # ★2バイト前提で読んでいたせいで、中野区の様式で <2020…> が全部落ちた。
        #   これはCIDの1コードではなく空白2文字だった。114文字が欠けていた。
        page = "BT /F9 12 Tf <41424320> Tj ET"
        self.assertEqual(show_text(page, {}, {}), "ABC ")

    def test_宣言されたフォントの表を先に引く(self):
        page = "BT /F1 12 Tf <0100> Tj ET"
        got = show_text(page, {0x0100: "全"}, {"F1": {0x0100: "個"}})
        self.assertEqual(got, "個")

    def test_フォントの表に無ければ全体の表に落とす(self):
        # ★フォント別だけにしたら北区が 0%→6.4% と悪化した。両方を順に引く。
        page = "BT /F1 12 Tf <0200> Tj ET"
        got = show_text(page, {0x0200: "全"}, {"F1": {0x0100: "個"}})
        self.assertEqual(got, "全")

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

    def test_配列形式のbfrangeを読む(self):
        # ★<0509> <050A> [<578B> <5951>] の形。連番形式しか見ておらず落ちていた。
        block = "<0509> <050A> [<578B> <5951>]"
        cmap = build_cmap([f"beginbfrange\n{block}\nendbfrange".encode("latin-1")])
        self.assertEqual(cmap[0x0509], "型")
        self.assertEqual(cmap[0x050A], "契")

    def test_数が合わない配列は触らない(self):
        block = "<0509> <050C> [<578B> <5951>]"      # 4つ必要なのに2つ
        self.assertEqual(build_cmap([f"beginbfrange\n{block}\nendbfrange".encode()]), {})

    def test_対応表に無いコードは落とす(self):
        # ★埋めない。読めなかった字を勝手に作らない。
        got = build_cmap([cmap_stream(self.PAIRS)])
        self.assertNotIn(0x9999, got)


class 全体の表への落とし方(unittest.TestCase):
    """★フォント別の表が無いときに **文書全体の表まで捨てていた。**

    その結果、対応表を持っているPDFを1バイトとして読み、丸ごと化けていた。
    実測（墨田区の粗大ごみ処理手数料表）は16進1,100件が全滅して0字。
    anydoc は同じPDFを「アイロン台 400 2 …」と表のまま読めていた。

    こちらが読めないだけのものを「その区は手数料を書いていない」と言っていた。
    """

    def test_フォント別の表が無ければ全体の表を使う(self):
        page = "BT /F9 12 Tf <0100> Tj ET"
        # F9 の表は無い。全体の表にはある。以前はここで1バイト読みに落ちていた。
        self.assertEqual(show_text(page, {0x0100: "料"}, {}), "料")

    def test_全体の表にも当たらなければ1バイトで読む(self):
        # 中野区の <2020…> ＝ 空白2文字。ここを2バイトで読むと114字が消える。
        page = "BT /F9 12 Tf <41424320> Tj ET"
        self.assertEqual(show_text(page, {0x9999: "無"}, {}), "ABC ")

    def test_半分当たれば2バイトとして読む(self):
        # 当たり具合で決める。全部が表にある必要はない（記号や欧文が混ざる）。
        page = "BT /F9 12 Tf <01000101> Tj ET"
        self.assertEqual(show_text(page, {0x0100: "手"}, {}), "手")

    def test_表が無ければ今までどおり1バイト(self):
        self.assertEqual(show_text("BT /F9 12 Tf <414243> Tj ET", {}, {}), "ABC")


class リテラルのCID(unittest.TestCase):
    """★`(…)` の中身が2バイトCIDのことがある（Identity-H）。

    1バイト文字として読むと化ける。ただし普通の欧文リテラルを2バイトで読むと壊すので、
    **対応表に当たった割合で決める。**
    """

    def test_表に当たるリテラルは文字に直す(self):
        page = "BT /F1 12 Tf (\u0001\u0000\u0001\u0001) Tj ET"
        got = show_text(page, {0x0100: "手", 0x0101: "数"}, {})
        self.assertEqual(got, "手数")

    def test_当たらないリテラルはそのまま(self):
        # 欧文のリテラルはCIDに当たらないので、素直に読む側へ戻る。
        self.assertEqual(show_text("BT /F1 12 Tf (Hello) Tj ET", {0x0100: "手"}, {}), "Hello")

    def test_表が無ければそのまま(self):
        self.assertEqual(show_text("BT /F1 12 Tf (abc) Tj ET", {}, {}), "abc")

    def test_1文字のリテラルは触らない(self):
        # 2バイトの組にならないものを無理に読まない。
        self.assertEqual(show_text("BT /F1 12 Tf (a) Tj ET", {0x0100: "手"}, {}), "a")


class 形式の見分け(unittest.TestCase):
    """★リダイレクト先が `/download` のように拡張子を持たないことがある。

    拡張子だけ見て「対応していない形式」と記録すると、
    **中身がPDFなのに形式不明として残る。** Content-Type も見る。
    """

    def test_拡張子があればそれを使う(self):
        self.assertEqual(kind_from("https://x.example/a.pdf", "text/html"), "pdf")

    def test_拡張子が無ければContent_Typeを見る(self):
        self.assertEqual(kind_from("https://x.example/download", "application/pdf"), "pdf")
        self.assertEqual(
            kind_from("https://x.example/dl",
                      "application/vnd.openxmlformats-officedocument"
                      ".wordprocessingml.document"), "docx")

    def test_文字集合が付いていても見分ける(self):
        self.assertEqual(kind_from("https://x.example/dl", "application/pdf; charset=binary"),
                         "pdf")

    def test_どちらでも分からなければunknown(self):
        self.assertEqual(kind_from("https://x.example/dl", "image/png"), "unknown")
        self.assertEqual(kind_from("https://x.example/dl", ""), "unknown")


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

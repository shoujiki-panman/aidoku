"""HTML以外の添付（Word / Excel / PDF）から本文らしきテキストを取り出す。

**なぜ要るか**: 探索は転入届だけで非HTMLを10本見つけているが、
`is_non_html_url` で弾いていて **1本も開いていない**（`analysis/read_ledger.py`）。
開かない判断そのものは妥当かもしれないが、**開かない理由がどこにも残っていない。**

**方針は「読めたら読む、読めなければ理由を残す」**。全部読めるようにはしない。

| 形式 | 手段 | 見込み |
|---|---|---|
| `.docx` / `.xlsx` | zip の中の XML を読む（`zipfile` + `xml.etree`） | **確実** |
| `.pdf` | Flate 圧縮を解いてテキスト演算子を拾う（`zlib` + 正規表現） | **入る形と入らない形がある** |

★PDF を確実に読むには外部ライブラリが要るが、この作品は
  **Python 標準ライブラリのみで動く**方針（CLAUDE.md）。方針を曲げるより、
  **読めなかったことを記録する**方を選ぶ。決定は plans/decisions/non-html-reading.md。

★字形が埋め込みフォントだけの PDF（スキャン画像・アウトライン化）は原理的に読めない。
  読めたふりをせず `reason` に残す。**空文字を「何も書いていない」と読ませない。**
"""

from __future__ import annotations

import re
import zipfile
import zlib
from dataclasses import dataclass
from io import BytesIO

# Office 文書の中で本文が入っている場所。ここに無いものは読まない。
OOXML_PARTS = {
    "docx": ("word/document.xml",),
    "xlsx": ("xl/sharedStrings.xml",),
    "pptx": ("ppt/slides/slide1.xml",),
}
# XML タグを落として地の文だけにする。段落の切れ目は改行にする。
_PARA_BREAK = re.compile(r"</w:p>|</a:p>|</si>", re.I)
_TAG = re.compile(r"<[^>]+>")
# PDF のテキスト表示演算子。( ) の中身と [ ] 配列の中身の両方を拾う。
_PDF_TEXT = re.compile(rb"\((?:\\.|[^\\()])*\)")
_PDF_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
# ★CIDフォントの本文は `(…)` ではなく `<16進>` で書かれる。
#   ( ) しか見ていなかったので、日本語の様式がまるごと落ちていた。
_PDF_HEX = re.compile(r"<([0-9A-Fa-f\s]{4,})>")


@dataclass(frozen=True)
class DocText:
    """取り出した結果。**読めなかったことも結果である。**"""

    kind: str          # docx / xlsx / pptx / pdf / unknown
    text: str          # 取り出せた本文（読めなければ空）
    ok: bool           # 本文として使えるか
    reason: str        # ok=False のとき、なぜ読めなかったか


def kind_of(url: str) -> str:
    """拡張子から形式を決める。中身は見ない（URLで弾く側と揃えるため）。"""
    lowered = url.lower().split("?")[0]
    for ext in ("docx", "xlsx", "pptx", "pdf"):
        if lowered.endswith("." + ext):
            return ext
    return "unknown"


def _clean(xml: str) -> str:
    text = _PARA_BREAK.sub("\n", xml)
    text = _TAG.sub("", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def read_ooxml(data: bytes, kind: str) -> DocText:
    """Word / Excel / PowerPoint。zip の中の XML を読むだけ。"""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return DocText(kind, "", False, "zipとして開けない（壊れているか別形式）")
    names = set(archive.namelist())
    parts = [p for p in OOXML_PARTS.get(kind, ()) if p in names]
    if not parts:
        return DocText(kind, "", False, f"本文の入る部品が無い（{kind}）")
    text = _clean("\n".join(archive.read(p).decode("utf-8", "replace") for p in parts))
    if not text:
        return DocText(kind, "", False, "部品はあるが地の文が空（図やテキストボックスのみか）")
    return DocText(kind, text, True, "")


def _pdf_streams(data: bytes) -> list[bytes]:
    """PDFのストリームを取り出す。

    ★最初「Flate 圧縮のストリームだけ解く」と書いて、解けないものを捨てていた。
      **字形の対応表（ToUnicode CMap）は非圧縮の平文で入っていることがある。**
      実際に北区の様式がそれで、捨てていたせいで「CIDフォントで読めない」と
      報告していた。対応表はPDFの中にあった。
    """
    out = []
    for match in _PDF_STREAM.finditer(data):
        raw = match.group(1)
        try:
            out.append(zlib.decompress(raw))
        except zlib.error:
            out.append(raw)                                # 非圧縮。そのまま使う
    return out


_BFCHAR = re.compile(r"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE = re.compile(r"beginbfrange(.*?)endbfrange", re.S)
_HEXPAIR = re.compile(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_HEXTRIPLE = re.compile(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
# 1つのコードに複数の文字が対応することがある（合字）。4桁ずつ切って全部つなぐ。
MAX_CMAP_ENTRIES = 20000


def _to_text(hex_value: str) -> str:
    """CMapの右辺（UTF-16BE の16進）を文字に直す。"""
    try:
        return bytes.fromhex(hex_value).decode("utf-16-be", "ignore")
    except ValueError:
        return ""


def build_cmap(streams: list[bytes]) -> dict[int, str]:
    """ToUnicode CMap を1つの表にまとめる。

    ★フォントごとの切り替え（Tf）は見ていない。文書全体で1つの表として扱う。
      様式のような単純なPDFではこれで足りる。足りなくなったら、そのとき分ける。
    """
    cmap: dict[int, str] = {}
    for stream in streams:
        text = stream.decode("latin-1", "ignore")
        if "beginbfchar" not in text and "beginbfrange" not in text:
            continue
        for block in _BFCHAR.findall(text):
            for code, value in _HEXPAIR.findall(block):
                cmap[int(code, 16)] = _to_text(value)
        for block in _BFRANGE.findall(text):
            for lo, hi, value in _HEXTRIPLE.findall(block):
                start, end = int(lo, 16), int(hi, 16)
                if end - start > MAX_CMAP_ENTRIES:
                    continue                               # 壊れた範囲。広げない
                base = int(value, 16)
                for offset in range(end - start + 1):
                    cmap[start + offset] = _to_text(f"{base + offset:04X}")
    return cmap


# 埋め込みフォント・画像の先頭バイト。本文ストリームがこれで始まることはない。
BINARY_MAGIC = (
    b"\x00\x01\x00\x00",    # TrueType
    b"OTTO", b"true", b"ttcf",
    b"\x01\x00\x04",        # CFF
    b"%!PS",                # Type1
    b"\xff\xd8",            # JPEG
    b"\x89PNG",
)


def is_content_stream(stream: bytes) -> bool:
    """本文（ページ内容）のストリームか。

    ★埋め込みフォントのバイナリにも `BT` や `Tj` の2文字はたまたま現れる。
      実測した様式PDFは7本のストリームのうち **本文は1本だけ**で、
      残りは TrueType フォント（先頭 `\\x00\\x01\\x00\\x00`）と CMap だった。

    ★最初これを「印字できる文字が9割以上か」で書いて、**本文まで弾いた。**
      `(日本語)Tj` のリテラルは印字できないバイトになるので当然だった。
      先頭バイトで形式を見分ける形に直した。
    """
    if b"BT" not in stream or (b"Tj" not in stream and b"TJ" not in stream):
        return False
    if b"beginbfchar" in stream or b"beginbfrange" in stream:
        return False                                       # 対応表そのもの
    return not stream.startswith(BINARY_MAGIC)


def _decode_hex_run(hex_value: str, cmap: dict[int, str]) -> str:
    """`<0AB1 0AB2>` のような2バイトコード列を、対応表で文字に直す。"""
    clean = re.sub(r"\s", "", hex_value)
    if len(clean) % 4:                                     # 2バイト固定でないものは触らない
        return ""
    out = []
    for i in range(0, len(clean), 4):
        out.append(cmap.get(int(clean[i:i + 4], 16), ""))
    return "".join(out)


def read_pdf(data: bytes) -> DocText:
    """PDF。**入る形と入らない形がある。読めたふりをしない。**"""
    streams = _pdf_streams(data)
    if not streams:
        return DocText("pdf", "", False, "ストリームが無い（暗号化か壊れている）")
    cmap = build_cmap(streams)
    content = [s for s in streams if is_content_stream(s)]
    if not content:
        return DocText("pdf", "", False, "本文のストリームが無い（画像PDFかアウトライン化）")
    chunks = []
    for stream in content:
        page = stream.decode("latin-1", "ignore")
        # ★CIDフォントの本文は `(…)` ではなく `<16進>` で入る。
        #   前は `(…)` しか見ておらず、日本語の様式がまるごと落ちていた。
        for match in _PDF_HEX.finditer(page):
            chunks.append(_decode_hex_run(match.group(1), cmap))
        for match in _PDF_TEXT.finditer(stream):
            chunks.append(match.group(0)[1:-1].decode("utf-8", "replace"))
    text = _clean("".join(chunks))
    # ★日本語PDFの多くは CID フォントで、( ) の中身がバイト列のまま出る。
    #   文字化けを本文として返すと、判定側が意味のない文字列を読むことになる。
    if not text:
        return DocText("pdf", "", False, "テキスト演算子が無い（画像PDFかアウトライン化）")
    if not readable(text):
        return DocText("pdf", "", False,
                       f"日本語の地の文にならない（{len(text)}字取れたが仮名がほぼ無い。"
                       "CIDフォントか、言語タグ等の非本文）")
    return DocText("pdf", text, True, "")


# 仮名。日本語の地の文には必ず混ざる。漢字や英数字だけでは文章の証拠にならない。
_KANA = re.compile(r"[ぁ-んァ-ヴ]")
MIN_KANA = 20


def readable(text: str, need: float = 0.02) -> bool:
    """日本語の地の文と言えるか。文字化けを本文と呼ばないための関門。

    ★最初これを「英数字か日本語が2割あるか」で書いて、**素通しした。**
      実物2本が抜けてきた:
        - `ja-JP  en-US  ja-JP …` の繰り返し（68,038字・PDFの言語タグ）
        - `n�Kujvz}�r�L…` の文字化け（111,553字・CIDフォント）
      どちらも `isalnum()` が真になるので、割合の関門を素通りする。

    **仮名を数える。** 日本語の地の文には必ず混ざり、言語タグにも文字化けにも
    ほぼ現れない。日本語でない文書は弾かれるが、対象は自治体の様式なのでそれでよい。
    """
    if not text:
        return False
    kana = len(_KANA.findall(text))
    return kana >= MIN_KANA and kana / len(text) >= need


def read_document(data: bytes, url: str) -> DocText:
    """入口。形式を見て振り分ける。**読めない形式も結果として返す。**"""
    kind = kind_of(url)
    if kind in OOXML_PARTS:
        return read_ooxml(data, kind)
    if kind == "pdf":
        return read_pdf(data)
    return DocText(kind, "", False, "対応していない形式")

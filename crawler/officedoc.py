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
    """Flate 圧縮のストリームだけ解く。他の圧縮は解かない。"""
    out = []
    for match in _PDF_STREAM.finditer(data):
        try:
            out.append(zlib.decompress(match.group(1)))
        except zlib.error:
            continue                                       # 非Flate。無視してよい
    return out


def read_pdf(data: bytes) -> DocText:
    """PDF。**入る形と入らない形がある。読めたふりをしない。**"""
    streams = _pdf_streams(data)
    if not streams:
        return DocText("pdf", "", False, "Flate圧縮のストリームが無い（別の圧縮か暗号化）")
    chunks = []
    for stream in streams:
        for match in _PDF_TEXT.finditer(stream):
            body = match.group(0)[1:-1]
            chunks.append(body.decode("utf-8", "replace"))
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

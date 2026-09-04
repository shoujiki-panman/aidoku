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
# bfrange の配列形式。連番ではなく1つずつ並べる書き方。
_BFRANGE_ARRAY = re.compile(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[([^\]]*)\]")
# 文字を出す命令。ここに現れる <16進> と (…) だけが本文。
# ★これを見ずに <16進> を全部拾うと、色指定やIDまで本文として読む。
_SHOW_TEXT = re.compile(
    r"\[((?:[^\[\]\\]|\\.)*)\]\s*TJ"        # [ <hex> -250 (lit) ] TJ
    r"|<([0-9A-Fa-f\s]+)>\s*Tj"             # <hex> Tj
    r"|\(((?:[^()\\]|\\.)*)\)\s*(?:Tj|')",  # (lit) Tj
)
_IN_ARRAY = re.compile(r"<([0-9A-Fa-f\s]+)>|\(((?:[^()\\]|\\.)*)\)")
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
            _read_ranges(block, cmap)
    return cmap


def _read_ranges(block: str, cmap: dict[int, str]) -> None:
    """bfrange を読む。**2つの形がある。**

    ★配列形式 `<0509> <050A> [<578B> <5951>]` を扱えておらず、
      実物（品川区の様式）で文字が落ちていた。連番形式だけ見ていた。
    """
    for lo, hi, arr in _BFRANGE_ARRAY.findall(block):
        start = int(lo, 16)
        values = re.findall(r"<([0-9A-Fa-f]+)>", arr)
        if len(values) != int(hi, 16) - start + 1:
            continue                                       # 数が合わない。触らない
        for offset, value in enumerate(values):
            cmap[start + offset] = _to_text(value)
    for lo, hi, value in _HEXTRIPLE.findall(block):
        start, end = int(lo, 16), int(hi, 16)
        if end - start > MAX_CMAP_ENTRIES:
            continue                                       # 壊れた範囲。広げない
        base = int(value, 16)
        for offset in range(end - start + 1):
            cmap.setdefault(start + offset, _to_text(f"{base + offset:04X}"))


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


def _decode_hex_run(hex_value: str, *maps: dict[int, str]) -> str:
    """`<0AB1 0AB2>` のような2バイトコード列を、対応表で文字に直す。

    ★表は**渡された順に**引く。いま使っているフォントの表を先に、
      見つからなければ文書全体の表に落とす。世の中の定石と同じ順序
      （ToUnicode → CIDFontのCMap → 外部CMap）の考え方。

      フォント別だけにしたら、実物（北区の様式）が 0% → 6.4% と**悪化した**。
      全体の表だけにすると中野区が 7.5% 落ちる。**両方を順に引くのが正しい。**
    """
    clean = re.sub(r"\s", "", hex_value)
    if len(clean) % 2:
        return ""
    if not any(maps):
        return _decode_single_byte(clean)
    if len(clean) % 4:                                     # 2バイト固定でないものは触らない
        return ""
    out = []
    for i in range(0, len(clean), 4):
        code = int(clean[i:i + 4], 16)
        out.append(next((m[code] for m in maps if code in m), ""))
    return "".join(out)


def _decode_single_byte(clean: str) -> str:
    """対応表を持たないフォント（1バイト）の文字列。

    ★2バイト前提で読んでいたせいで、中野区の様式で `<2020…>` が全部落ちた。
      これは CID の1コードではなく **空白2文字**だった。114文字が欠けていた。
      対応表が無いフォントは、そのまま1バイトずつ文字として読む。
    """
    return bytes.fromhex(clean).decode("latin-1", "ignore")


_OBJ = re.compile(rb"(\d+)\s+0\s+obj\b(.*?)endobj", re.S)
_FONT_RES = re.compile(r"/Font\s*<<(.*?)>>", re.S)
_FONT_REF = re.compile(r"/(\w+)\s+(\d+)\s+0\s+R")
_TOUNICODE = re.compile(r"/ToUnicode\s+(\d+)\s+0\s+R")
# `/F1 10.5 Tf` — ここで使うフォントが切り替わる。
_TF = re.compile(r"/(\w+)\s+[\d.]+\s+Tf")


def _object_streams(data: bytes) -> dict[int, bytes]:
    """オブジェクト番号 → その中のストリーム。番号で引けないと参照を辿れない。"""
    out: dict[int, bytes] = {}
    for match in _OBJ.finditer(data):
        body = match.group(2)
        inner = _PDF_STREAM.search(body)
        if not inner:
            continue
        raw = inner.group(1)
        try:
            out[int(match.group(1))] = zlib.decompress(raw)
        except zlib.error:
            out[int(match.group(1))] = raw
    return out


def font_cmaps(data: bytes) -> dict[str, dict[int, str]]:
    """フォント名（`F1` 等）ごとの対応表。

    ★2つのフォントで**コードが重なる**。1つの表に混ぜると後勝ちで上書きされ、
      実物（中野区の委任状）で 7.5% の文字が落ちた。
      世の中の定石どおり、フォントごとに持つ。
    """
    objects = _object_streams(data)
    text = data.decode("latin-1", "ignore")
    out: dict[str, dict[int, str]] = {}
    for block in _FONT_RES.findall(text):
        for name, num in _FONT_REF.findall(block):
            body = _object_body(text, int(num))
            found = _TOUNICODE.search(body)
            if not found:
                continue
            stream = objects.get(int(found.group(1)))
            if stream:
                out[name] = build_cmap([stream])
    return out


def _object_body(text: str, number: int) -> str:
    match = re.search(rf"\b{number}\s+0\s+obj\b(.*?)endobj", text, re.S)
    return match.group(1) if match else ""


def _literal(raw: str) -> str:
    """`(…)` の中身。PDFのエスケープを戻す。"""
    return re.sub(r"\\([nrtbf()\\])",
                  lambda m: {"n": "\n", "r": "\r", "t": "\t",
                             "b": "", "f": ""}.get(m.group(1), m.group(1)), raw)


def _maps(active, cmap):
    """引く順。対応表を持たないフォントには何も渡さない（1バイトとして読ませる）。"""
    return (active, cmap) if active is not None else ()


def show_text(page: str, cmap: dict[int, str],
              per_font: dict[str, dict[int, str]] | None = None) -> str:
    """本文を出す命令からだけ文字を集める。

    ★以前は `<16進>` を無条件に拾っていて、色指定やIDまで本文として読んでいた。
      文字を出す命令は `Tj` / `TJ` / `'` の3つだけ。そこに現れるものだけを取る。

    `per_font` があれば `Tf` で表を切り替える。無ければ全体の表を使う。
    """
    out = []
    active = cmap
    for match in re.finditer(f"{_TF.pattern}|{_SHOW_TEXT.pattern}", page):
        font, array, hex_run, literal = match.groups()
        if font:
            active = (per_font or {}).get(font)
            # ★対応表を持たないフォントは1バイトとして読む。空の辞書を渡すと
            #   「2バイトで引いて見つからない」になり、空白がまるごと落ちる。
            continue
        if array:
            for in_hex, in_lit in _IN_ARRAY.findall(array):
                out.append(_decode_hex_run(in_hex, *_maps(active, cmap)) if in_hex
                           else _literal(in_lit))
        elif hex_run:
            out.append(_decode_hex_run(hex_run, *_maps(active, cmap)))
        elif literal:
            out.append(_literal(literal))
    return "".join(out)


def read_pdf(data: bytes) -> DocText:
    """PDF。**入る形と入らない形がある。読めたふりをしない。**"""
    streams = _pdf_streams(data)
    if not streams:
        return DocText("pdf", "", False, "ストリームが無い（暗号化か壊れている）")
    cmap = build_cmap(streams)
    per_font = font_cmaps(data)
    content = [s for s in streams if is_content_stream(s)]
    if not content:
        return DocText("pdf", "", False, "本文のストリームが無い（画像PDFかアウトライン化）")
    chunks = []
    for stream in content:
        chunks.append(show_text(stream.decode("latin-1", "ignore"), cmap, per_font))
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


# Content-Type から形式を決める。拡張子の無いURLで配られる添付があるため。
MIME_KIND = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/msword": "docx",
    "application/vnd.ms-excel": "xlsx",
}


def kind_from(url: str, content_type: str = "") -> str:
    """形式を決める。**URLの拡張子だけでは足りない。**

    ★リダイレクト先が `/download` のように拡張子を持たないことがある。
      拡張子だけ見て「対応していない形式」と記録すると、
      **中身がPDFなのに形式不明として残る。** Content-Type も見る。
    """
    kind = kind_of(url)
    if kind != "unknown":
        return kind
    mime = content_type.split(";")[0].strip().lower()
    return MIME_KIND.get(mime, "unknown")


def read_document(data: bytes, url: str, content_type: str = "") -> DocText:
    """入口。形式を見て振り分ける。**読めない形式も結果として返す。**"""
    kind = kind_from(url, content_type)
    if kind in OOXML_PARTS:
        return read_ooxml(data, kind)
    if kind == "pdf":
        return read_pdf(data)
    return DocText(kind, "", False, "対応していない形式")

"""古い Excel（`.xls` / BIFF8）から文字を取り出す。標準ライブラリだけで動く。

**なぜ要るか**: 虱潰しで「読めない候補が残っている」項目のうち1本が、
大田区の粗大ごみ品目一覧（`.xls`）だった。`crawler/officedoc.py` は
zip 形式の `.xlsx` しか読めず、**古い形式は「対応していない形式」で落としていた。**

読めないものを「その区が書いていない」と言ってはいけない（`METHOD.md §4-7c`）。
だから**読めるようにする**。外部の変換器（anydoc）はこのファイルを21,166字で
読めていた。**うちが読めないだけだった。**

## 形

`.xls` は2層でできている。

    OLE2（複合文書）  512バイトのセクタを FAT でつないだ、ファイルの中の小さな file system
      └ Workbook ストリーム
          └ BIFF レコード列（種類2バイト・長さ2バイト・中身）

文字は3か所に入る。**表の文字はほぼ SST にある。**

    SST        文書全体で共有する文字列表（同じ語を1回だけ持つ）
    LABELSST   セルが SST の何番目かを指す
    LABEL      SST を使わない直書きのセル（古い書き方）

数値（RK / NUMBER）は取らない。**金額や枚数だけ拾っても手がかりにならず、
文字と混ぜると本文が読めなくなる**（`analysis/probes/check_unread.py` で金額の形を
入れて数が3倍になったのと同じ失敗）。
"""

from __future__ import annotations

import struct

# OLE2 の見出し。`crawler/officedoc.py` の FILE_MAGIC にも入っている。
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# セクタ番号の終端印。
END_OF_CHAIN = 0xFFFFFFFE
FREE_SECTOR = 0xFFFFFFFF

# ディレクトリ1件の大きさ。
DIR_ENTRY_SIZE = 128

# BIFF レコードの種類。**文字が入るものだけ。**
SST = 0x00FC
CONTINUE = 0x003C
LABELSST = 0x00FD
LABEL = 0x0204

# 無限ループの止め。壊れたファイルで FAT が輪になっていることがある。
MAX_SECTORS = 200000


def _u16(data: bytes, pos: int) -> int:
    return struct.unpack_from("<H", data, pos)[0]


def _u32(data: bytes, pos: int) -> int:
    return struct.unpack_from("<I", data, pos)[0]


def is_xls(data: bytes) -> bool:
    """古い Excel か。**中身の先頭で見る**（キャッシュは拡張子を持たない）。"""
    return data.startswith(OLE_MAGIC)


def _chain(fat: list[int], start: int) -> list[int]:
    """セクタのつながりをたどる。**輪になっていたら止める。**"""
    out: list[int] = []
    seen: set[int] = set()
    sector = start
    while sector < len(fat) and sector not in (END_OF_CHAIN, FREE_SECTOR):
        if sector in seen or len(out) > MAX_SECTORS:
            break                                          # 壊れている。取れたところまで
        seen.add(sector)
        out.append(sector)
        sector = fat[sector]
    return out


def _read_fat(data: bytes, sector_size: int) -> list[int]:
    """FAT（セクタのつながり表）。DIFAT の109件ぶんだけ見る。

    ★109件を超える巨大ファイルは追わない。自治体の様式でそこまでの大きさは出ない。
      追えなかったときは取れたところまでを返す（黙って空にしない）。
    """
    fat: list[int] = []
    for i in range(109):
        sector = _u32(data, 76 + i * 4)
        if sector in (END_OF_CHAIN, FREE_SECTOR):
            break
        start = (sector + 1) * sector_size
        block = data[start:start + sector_size]
        fat.extend(struct.unpack(f"<{len(block) // 4}I", block[:len(block) // 4 * 4]))
    return fat


def _stream(data: bytes, fat: list[int], sector_size: int, start: int, size: int) -> bytes:
    out = bytearray()
    for sector in _chain(fat, start):
        head = (sector + 1) * sector_size
        out += data[head:head + sector_size]
    return bytes(out[:size]) if size else bytes(out)


def _directory(data: bytes, fat: list[int], sector_size: int, dir_start: int) -> list[dict]:
    """ディレクトリ（ストリームの一覧）。名前は UTF-16。"""
    raw = _stream(data, fat, sector_size, dir_start, 0)
    entries = []
    for pos in range(0, len(raw) - DIR_ENTRY_SIZE + 1, DIR_ENTRY_SIZE):
        name_len = _u16(raw, pos + 64)
        if not 2 <= name_len <= 64:
            continue
        name = raw[pos:pos + name_len - 2].decode("utf-16-le", "replace")
        entries.append({"name": name, "start": _u32(raw, pos + 116),
                        "size": _u32(raw, pos + 120)})
    return entries


def workbook_stream(data: bytes) -> bytes:
    """`Workbook`（古い版は `Book`）ストリームの中身。無ければ空。

    ★mini ストリーム（4096バイト未満）は追わない。Workbook がそこに入るのは
      中身がほぼ空のファイルだけで、読めても本文にならない。
    """
    if not is_xls(data) or len(data) < 512:
        return b""
    sector_size = 1 << _u16(data, 30)
    dir_start = _u32(data, 48)
    fat = _read_fat(data, sector_size)
    if not fat:
        return b""
    for entry in _directory(data, fat, sector_size, dir_start):
        if entry["name"] in ("Workbook", "Book") and entry["size"] >= 4096:
            return _stream(data, fat, sector_size, entry["start"], entry["size"])
    return b""


def _records(stream: bytes) -> list[tuple[int, bytes]]:
    """BIFF レコード列。**CONTINUE は直前のレコードにつなぐ。**

    ★SST は 8224 バイトで切られて CONTINUE に続く。つながないと
      文字列表が途中で終わり、表の後半がまるごと落ちる。
    """
    out: list[tuple[int, bytes]] = []
    pos = 0
    while pos + 4 <= len(stream):
        kind, length = struct.unpack_from("<HH", stream, pos)
        body = stream[pos + 4:pos + 4 + length]
        pos += 4 + length
        if kind == CONTINUE and out:
            out[-1] = (out[-1][0], out[-1][1] + body)
        else:
            out.append((kind, body))
    return out


def _unicode_string(body: bytes, pos: int) -> tuple[str, int]:
    """BIFF8 の文字列。1文字1バイトのことと2バイトのことがある。

    ★ここを2バイト固定で読むと、英数字だけの列が化ける。
      PDFの `_decode_single_byte` と同じ形の間違いになる。
    """
    if pos + 3 > len(body):
        return "", len(body)
    chars = _u16(body, pos)
    flags = body[pos + 2]
    pos += 3
    if flags & 0x08:                                       # rich text
        runs = _u16(body, pos)
        pos += 2
    else:
        runs = 0
    ext = _u32(body, pos) if flags & 0x04 else 0           # far east extension
    pos += 4 if flags & 0x04 else 0
    if flags & 0x01:                                       # 2バイト
        end = pos + chars * 2
        text = body[pos:end].decode("utf-16-le", "replace")
    else:
        end = pos + chars
        text = body[pos:end].decode("latin-1", "replace")
    return text, end + runs * 4 + ext


def shared_strings(records: list[tuple[int, bytes]]) -> list[str]:
    """SST（文書全体で共有する文字列表）。"""
    for kind, body in records:
        if kind != SST:
            continue
        out: list[str] = []
        pos = 8                                            # 総数・ユニーク数
        while pos < len(body):
            text, nxt = _unicode_string(body, pos)
            if nxt <= pos:
                break                                      # 進まないなら壊れている
            out.append(text)
            pos = nxt
        return out
    return []


def cell_texts(records: list[tuple[int, bytes]], sst: list[str]) -> list[str]:
    """セルの文字。数値は取らない（手がかりにならず、本文を汚す）。"""
    out = []
    for kind, body in records:
        if kind == LABELSST and len(body) >= 10:
            index = _u32(body, 6)
            if index < len(sst):
                out.append(sst[index])
        elif kind == LABEL and len(body) >= 8:
            text, _ = _unicode_string(body, 6)
            out.append(text)
    return out


def read_text(data: bytes) -> str:
    """入口。読めなければ空を返す（**読めたふりをしない**）。"""
    stream = workbook_stream(data)
    if not stream:
        return ""
    records = _records(stream)
    sst = shared_strings(records)
    cells = cell_texts(records, sst)
    # ★SSTだけでも本文になる。セル参照が読めなくても語は拾える。
    return "\n".join(cells) if cells else "\n".join(sst)

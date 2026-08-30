"""字形の番号（CID）から文字への対応表。**ToUnicode を持たないPDFのために使う。**

**なぜ要るか**: 虱潰しで読めなかった9本を1本ずつ調べたら、3本は
**`/ToUnicode` を1つも持たない CID フォントのPDF**だった。

    Encoding  Identity-H     本文は2バイトのCIDで書かれている
    Ordering  Japan1         Adobe-Japan1 の字形番号を使っている
    BaseFont  RyuminPr6N / UDShinGoPr6N（サブセット埋め込み）
    ToUnicode **無し**       ファイルの中に「CIDが何の文字か」が書かれていない

つまり**そのPDFだけを見ても、絶対に文字に戻せない。** 外の知識が要る。

**世の中にある**: Adobe が Adobe-Japan1 の対応表を公開している（BSD-3-Clause）。
`UniJIS-UCS2-H`（Unicode→CID）を反転して CID→Unicode を作り、同梱した。

    出典  https://github.com/adobe-type-tools/cmap-resources
    許諾  crawler/data/ADOBE-CMAP-LICENSE.txt
    件数  9,490

★**これはライブラリではなくデータ。** 「作品本体は標準ライブラリのみ」の方針は
  変えていない（`plans/decisions/external-reader.md` と同じ線引き）。

★**Ordering が Japan1 のPDFにだけ使う。** 別の字形集合に当てると、
  読めない字を勝手に作ることになる。**当たった数ではなく、宣言で決める。**
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "adobe-japan1-cid2uni.json"

# `/Ordering (Japan1)` の宣言。生バイトにも、圧縮を解いたストリームにも現れる。
_ORDERING_JAPAN1 = re.compile(rb"/Ordering\s*\(\s*Japan1\s*\)")

_TABLE: dict[int, str] | None = None


def adobe_japan1() -> dict[int, str]:
    """CID → 文字。**一度だけ読む**（9,490件・139KB）。"""
    global _TABLE
    if _TABLE is None:
        doc = json.loads(DATA.read_text(encoding="utf-8"))
        _TABLE = {int(cid): chr(uni) for cid, uni in doc["cid2uni"].items()}
    return _TABLE


def declares_japan1(data: bytes, streams: list[bytes] | None = None) -> bool:
    """このPDFが Adobe-Japan1 の字形集合を使うと**書いているか**。

    ★宣言が無いのに当てない。当たった数で決めると、別の字形集合のPDFに
      それらしい日本語を作ってしまう。**読めない字を作らない**のがこの道具の約束。

    ★宣言は圧縮オブジェクトストリーム（PDF 1.5以降）の中にあることが多い。
      実測した3本とも、生バイトには現れず、解いたストリームにだけあった。
    """
    if _ORDERING_JAPAN1.search(data):
        return True
    return any(_ORDERING_JAPAN1.search(s) for s in (streams or []))


def japan1_map(data: bytes, streams: list[bytes] | None = None) -> dict[int, str]:
    """宣言があれば対応表を、無ければ空を返す。"""
    return adobe_japan1() if declares_japan1(data, streams) else {}

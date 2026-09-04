"""絵として入っている文字を読む。**住民のAIができることを、こちらもできるようにする。**

**なぜ要るか**: 虱潰しで読めなかった候補の多くが画像PDFだった。本文が字ではなく
絵なので、PDFをいくら解析しても文字は出ない。

だが**住民のAI（ChatGPT / Claude）は絵を読む。** こちらが字しか扱えないまま
「その区は書いていない」と言うのは、**住民の側で読めているものを区の落ち度にする**ことになる。
AI読の前提は「住民のAIが住民の代わりに来る」なので、**住民のAIができることは、
こちらもできなければならない。**

## 方針を変えた記録

2026-08-31 の朝は「OCRは開発時の道具。測定条件に混ぜない」としていた
（macOSでしか動かず、再現性が落ちるため）。**本人の指摘で改めた。**
再現性は「使わない」ではなく **`non_html_reading` に記録して、使ったことを見えるようにする**
ことで担保する。条件が違う記録どうしは、いまも比較が拒否される。

    使えるとき   non_html_reading = "cmap_text+ocr"
    使えないとき non_html_reading = "cmap_text"   ← 条件が違うので混ざらない

## 仕組み

macOS の Vision（同梱・追加ダウンロード不要）を呼ぶ小さな実行ファイルを作って使う。

    tools/ocr_pdf.swift → swiftc で1回だけ組み立てる → 呼ぶ

★**使えない環境では黙って0字を返す。** 読めたふりをしない。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "ocr_pdf.swift"
BINARY = Path(os.environ.get("AIDOKU_OCR_BIN", "/tmp/aidoku-ocr-pdf"))

# 1本にかける上限。様式PDFは数ページなので、これを超えるのは異常。
TIMEOUT = 300

_READY: bool | None = None


def available() -> bool:
    """OCRが使えるか。**一度だけ組み立てる。**"""
    global _READY
    if _READY is not None:
        return _READY
    if BINARY.exists():
        _READY = True
        return True
    if not (SOURCE.exists() and shutil.which("swiftc")):
        _READY = False
        return False
    try:
        done = subprocess.run(["swiftc", "-O", str(SOURCE), "-o", str(BINARY)],
                              capture_output=True, text=True, timeout=TIMEOUT)
        _READY = done.returncode == 0
    except Exception:                                      # noqa: BLE001
        _READY = False
    return _READY


def condition(base: str) -> str:
    """測定条件に書く値。**使ったかどうかが後から分かるようにする。**"""
    return f"{base}+ocr" if available() else base


def read_pdf_text(data: bytes) -> str:
    """PDFを絵として読む。**読めなければ空**（読めたふりをしない）。"""
    if not data.startswith(b"%PDF-") or not available():
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "in.pdf"
        target.write_bytes(data)
        try:
            done = subprocess.run([str(BINARY), str(target)],
                                  capture_output=True, text=True, timeout=TIMEOUT)
        except Exception:                                  # noqa: BLE001
            return ""
    return done.stdout if done.returncode == 0 else ""

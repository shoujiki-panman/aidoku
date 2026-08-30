"""読めない画像PDFを、macOS の Vision で読んで記録する。**開発時の道具。**

**なぜ要るか**: 虱潰しで「読めない候補が残っている」項目のうち、いちばん多いのが
**画像PDF**（本文が字ではなく絵として入っている）。PDFをいくら解析しても文字は出ない。
外部の変換器（anydoc）も `NeedsOcr` で降りる。**OCRしかない。**

★**これは作品本体ではない。** 作品本体は Python 標準ライブラリのみで動く方針を変えない
  （`plans/decisions/external-reader.md` と同じ線引き）。macOS でしか動かないので、
  **測定条件に混ぜてはいけない。**

★**では何のために読むのか。** 住民のAI（ChatGPT / Claude）は**絵も読める**。
  うちの読み取り器が字しか扱えないだけで、住民の側では読めている可能性がある。
  だから「うちが読めない」を「区が書いていない」に混ぜないための**材料**として使う。

    出力  analysis/out/ocr_unreadable.json
    判定には使わない。読むのは人だけ（誤りと分かった結果の置き場と同じ扱い）。

    swiftc -O tools/ocr_pdf.swift -o /tmp/ocr_pdf
    python3 analysis/ocr_unreadable.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "crawler" / "cache"
OUT_DIR = ROOT / "analysis" / "out"
SOURCE = ROOT / "tools" / "ocr_pdf.swift"

sys.path.insert(0, str(ROOT / "crawler"))
from officedoc import read_document  # noqa: E402

VERSION = "ocr-unreadable-0.1"
PROCEDURES = ("tennyu", "jidouteate", "sodaigomi")

# 日本語の地の文と言えるか。`officedoc.readable` と同じ考え方（仮名を数える）。
KANA = re.compile(r"[ぁ-んァ-ヴ]")
MIN_KANA = 5


def build(binary: Path) -> bool:
    """Vision を呼ぶ小さな実行ファイルを作る。**無ければ作る。**"""
    if binary.exists():
        return True
    if not shutil.which("swiftc"):
        return False
    done = subprocess.run(["swiftc", "-O", str(SOURCE), "-o", str(binary)],
                          capture_output=True, text=True, timeout=300)
    return done.returncode == 0


def unreadable_urls() -> dict[str, list[str]]:
    """虱潰しが「読めない」と記録したURLと、その項目。"""
    out: dict[str, list[str]] = {}
    for procedure in PROCEDURES:
        path = OUT_DIR / f"sweep_{procedure}.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        for row in doc["rows"]:
            for field in row["fields"]:
                for url in field.get("unreadable") or []:
                    out.setdefault(url, []).append(
                        f"{procedure}/{row['municipality']}/{field['field']}")
    return out


def cached(url: str) -> Path | None:
    host = urllib.parse.urlparse(url).netloc
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    path = CACHE / host / f"{key}.html"
    return path if path.exists() else None


def ocr(binary: Path, pdf: bytes) -> str:
    """1本ぶん。**読めなければ空を返す**（読めたふりをしない）。"""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "in.pdf"
        target.write_bytes(pdf)
        try:
            done = subprocess.run([str(binary), str(target)],
                                  capture_output=True, text=True, timeout=300)
        except Exception:                                  # noqa: BLE001
            return ""
    return done.stdout if done.returncode == 0 else ""


def summarize(rows: list[dict]) -> dict:
    read = [r for r in rows if r["ocr_ok"]]
    return {
        "files": len(rows),
        # ★OCRで読めた ＝ **住民のAIなら読めた可能性が高い**もの
        "ocr_readable": len(read),
        "ocr_unreadable": len(rows) - len(read),
        "chars_total": sum(r["chars"] for r in read),
        "fields_touched": sorted({f for r in rows for f in r["fields"]}),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", default="/tmp/ocr_pdf", help="Vision を呼ぶ実行ファイル")
    args = ap.parse_args(argv)

    binary = Path(args.binary)
    if not build(binary):
        raise SystemExit(f"OCRの道具を作れない（swiftc が要る）: {SOURCE}")

    rows = []
    for url, fields in sorted(unreadable_urls().items()):
        path = cached(url)
        if path is None:
            rows.append({"url": url, "fields": fields, "reason": "取得できていない",
                         "ocr_ok": False, "chars": 0, "kana": 0, "head": ""})
            continue
        raw = path.read_bytes()
        if not raw.startswith(b"%PDF-"):
            rows.append({"url": url, "fields": fields, "reason": "PDFではない",
                         "ocr_ok": False, "chars": 0, "kana": 0, "head": ""})
            continue
        text = ocr(binary, raw)
        kana = len(KANA.findall(text))
        ok = kana >= MIN_KANA
        rows.append({
            "url": url, "fields": fields,
            "reason": read_document(raw, url).reason,
            "ocr_ok": ok, "chars": len(text), "kana": kana,
            "head": text[:160].replace("\n", " ") if ok else "",
        })
        print(f"  {'★読めた' if ok else '読めない'} {len(text):6}字 仮名{kana:5}  {url[-46:]}")

    doc = {
        "_about": "うちの読み取り器で読めなかったPDFを、OCRで読んでみた記録。"
                  "**判定には使わない。** 住民のAIは絵も読めるので、"
                  "「うちが読めない」を「区が書いていない」に混ぜないための材料。",
        "version": VERSION,
        "tool": "macOS Vision（tools/ocr_pdf.swift）。作品本体には入れない",
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "ocr_unreadable.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['files']}本中 OCRで読めた {s['ocr_readable']}（計{s['chars_total']}字）")


if __name__ == "__main__":
    main()

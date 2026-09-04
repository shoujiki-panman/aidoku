"""同じ添付ファイルを、自作リーダーと外部の変換器（anydoc）の両方に読ませて突き合わせる。

**なぜ要るか**: `crawler/officedoc.py` は400行超の手書きPDFパーサで、字形の対応表
（`/ToUnicode` CMap）を自分で解いている。**今週そこで3件バグを出した**
（読めないゲートがゴミを通す / フォント別対応表だけだと悪化する / 本文ストリームの判定ミス）。

**照らすものが自分の実装しか無い**という点で、手で数えていた頃の
`analysis/compare_runs.py` と同じ形をしている。**外部の実装を検算に使う。**

置き換えるためではない。**差が出るかどうかを見るため。**

    差が出なければ  → うちの読みが正しいことの外部保証
    差が出れば      → まだ気づいていない自作リーダーのバグ

**ネットには出ない。** 取得済みのキャッシュのバイト列を、そのまま両方に渡す。

    .venv/bin/python analysis/probes/compare_readers.py          # 全部
    .venv/bin/python analysis/probes/compare_readers.py --check  # 対象の本数だけ
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "crawler" / "cache"
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))
from officedoc import looks_like_document, read_document  # noqa: E402

VERSION = "compare-readers-0.1"

# 表示用の種類名。添付かどうかの判定そのものは
# `officedoc.looks_like_document` に寄せてある（先頭バイトの表を2か所に置かない）。
KIND_NAMES = {
    b"%PDF-": "pdf",
    b"PK\x03\x04": "zip系（docx/xlsx/pptx/epub/odf）",
    b"\xd0\xcf\x11\xe0": "古いOffice（doc/xls/ppt）",
}

# 突き合わせる前に落とす飾り。anydoc は Markdown を返すので、記号がそのままだと
# 「中身が違う」ではなく「書式が違う」を数えてしまう。
MARKUP = re.compile(r"[\s#*_|\-=>`\[\]()!]+")

# これ未満は「読めたが中身が無い」。`analysis/read_non_html.py` と同じ基準。
MIN_USEFUL_CHARS = 30

# 本文がどれだけ一致すれば「同じ」と見なすか。書式の違いを吸収する余地を残す。
SAME_RATIO = 0.85


def kind_of(raw: bytes) -> str | None:
    """先頭バイトから種類。**分からないものは None を返して数から外す。**"""
    if not looks_like_document(raw):
        return None
    for magic, name in KIND_NAMES.items():
        if raw.startswith(magic):
            return name
    return None


def normalize(text: str) -> str:
    """書式を落として本文だけにする。"""
    return MARKUP.sub("", text)


def similarity(a: str, b: str, cap: int = 20000) -> float:
    """本文の一致率。★長い文書で二乗に膨らむので頭から cap 字だけ見る。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a[:cap], b[:cap]).ratio()


def read_ours(raw: bytes, url: str) -> dict:
    """自作リーダー。`analysis/read_non_html.py` と同じ「短すぎれば読めない」を適用。"""
    got = read_document(raw, url)
    if got.ok and len(got.text) < MIN_USEFUL_CHARS:
        return {"ok": False, "chars": len(got.text), "text": "",
                "reason": f"取り出せた文字が{len(got.text)}字しかない"}
    return {"ok": got.ok, "chars": len(got.text), "text": got.text if got.ok else "",
            "reason": got.reason}


def read_anydoc(raw: bytes) -> dict:
    """外部の変換器。**失敗の種類をそのまま残す**（NeedsOcr かどうかが要点）。"""
    import anydoc
    try:
        text = anydoc.to_markdown_bytes(raw)
    except anydoc.NeedsOcrError:
        return {"ok": False, "chars": 0, "text": "",
                "reason": "NeedsOcr（画像PDF。ローカルではOCRしない）"}
    except Exception as exc:                                  # noqa: BLE001
        return {"ok": False, "chars": 0, "text": "",
                "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if len(text) < MIN_USEFUL_CHARS:
        return {"ok": False, "chars": len(text), "text": "",
                "reason": f"取り出せた文字が{len(text)}字しかない"}
    return {"ok": True, "chars": len(text), "text": text, "reason": ""}


def verdict(ours: dict, theirs: dict, ratio: float) -> str:
    """★4つに分ける。「どちらも読めない」を「一致」に混ぜない。"""
    if ours["ok"] and theirs["ok"]:
        return "同じ" if ratio >= SAME_RATIO else "両方読めたが中身が違う"
    if theirs["ok"]:
        return "★anydocだけ読めた"
    if ours["ok"]:
        return "★うちだけ読めた"
    return "どちらも読めない"


def targets() -> list[tuple[str, Path, bytes]]:
    """キャッシュにある添付ファイル。**URLはメタから取る**（ファイル名はハッシュ）。"""
    out = []
    for meta_path in sorted(CACHE.glob("*/*.meta.json")):
        body = meta_path.with_name(meta_path.name.replace(".meta.json", ".html"))
        if not body.exists():
            continue
        raw = body.read_bytes()[:8]
        if kind_of(raw) is None:
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        out.append((meta.get("url") or "", body, body.read_bytes()))
    return out


def compare_one(url: str, raw: bytes) -> dict:
    ours = read_ours(raw, url)
    theirs = read_anydoc(raw)
    ratio = similarity(normalize(ours["text"]), normalize(theirs["text"]))
    return {
        "url": url,
        "kind": kind_of(raw),
        "ours": {k: v for k, v in ours.items() if k != "text"},
        "anydoc": {k: v for k, v in theirs.items() if k != "text"},
        "similarity": round(ratio, 3),
        "verdict": verdict(ours, theirs, ratio),
    }


def summarize(rows: list[dict]) -> dict:
    by = {}
    for row in rows:
        by[row["verdict"]] = by.get(row["verdict"], 0) + 1
    return {
        "files": len(rows),
        "by_verdict": dict(sorted(by.items(), key=lambda x: -x[1])),
        # ★片方だけ読めたものは、名前を必ず出す。数だけだと追えない。
        "anydoc_only": [r["url"] for r in rows if r["verdict"] == "★anydocだけ読めた"],
        "ours_only": [r["url"] for r in rows if r["verdict"] == "★うちだけ読めた"],
        "differ": [r["url"] for r in rows if r["verdict"] == "両方読めたが中身が違う"],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="読まずに対象の本数だけ")
    args = ap.parse_args(argv)

    found = targets()
    if args.check:
        kinds: dict[str, int] = {}
        for _, _, raw in found:
            k = kind_of(raw) or "?"
            kinds[k] = kinds.get(k, 0) + 1
        print(f"キャッシュにある添付 {len(found)}本: {kinds}")
        return

    rows = []
    for url, _, raw in found:
        row = compare_one(url, raw)
        rows.append(row)
        print(f"  {row['verdict']:20} 一致{row['similarity']:5.2f} "
              f"うち{row['ours']['chars']:6}字 / anydoc{row['anydoc']['chars']:6}字  "
              f"{url[-52:]}")

    doc = {
        "_about": "同じ添付を自作リーダーと anydoc の両方に読ませた記録。"
                  "判定は変えない。実装が2つで食い違うかどうかの記録。",
        "version": VERSION, "same_ratio": SAME_RATIO,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "reader-compare.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ {out}")
    for k, v in doc["summary"]["by_verdict"].items():
        print(f"  {v:4}  {k}")


if __name__ == "__main__":
    main()

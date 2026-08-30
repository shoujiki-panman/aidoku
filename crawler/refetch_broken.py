"""壊れているキャッシュを見つけて取り直す。

**なぜ要るか**: `polite_fetch` は以前、全応答を `write_text` で保存していた。
添付（PDF/Word/Excel）のバイト列が **decode→encode の往復で壊れる**。
2026-08-25 に修正した（`is_text_type` / `write_bytes`）が、**修正前に取ったキャッシュは
壊れたまま残る。** 取り直さないかぎり直らない。

2026-08-30 に数えたら **60本・204MB が壊れていた。** そして
`analysis/sweep.py` は添付を1本も読んでいなかった（321ページ中0本）。
**「候補を1本残らず読んだ」と言っていたのは、HTMLの候補だけだった。**

## 壊れている印

UTF-8 の置換文字 `U+FFFD`（`EF BF BD`）がバイト列に入っていること。
読めなかったバイトがこの3バイトに化けるので、**往復で壊れた確実な証拠**になる。
（本文が壊れていても `%PDF-` の見出しはASCIIなので残る。だから見出しでは分からない。）

    python3 crawler/refetch_broken.py --check   # 数えるだけ。ネットに出ない
    python3 crawler/refetch_broken.py           # 取り直す
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "crawler" / "cache"

sys.path.insert(0, str(ROOT / "crawler"))
from officedoc import looks_like_document  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

# 往復で壊れた印。読めなかったバイトが U+FFFD に化けたもの。
REPLACEMENT = b"\xef\xbf\xbd"

# 置換文字が占める割合がこれを超えたら壊れている。
#
# ★「1個でもあれば壊れている」にすると誤検出する。**実測で踏んだ。**
#   取り直して直った 7.5MB のPDFに、置換文字がちょうど1個残っていた。
#   3バイトの並びは偶然も起きる（7.5MBなら期待値0.4個）。
#   閾値が無いと、その1本を永久に取り直し続ける。
#
#   壊れている側の実測は 23%前後（13MBに3,029,888個）、
#   無傷の側は 0.00004% なので、1% で完全に分かれる。
BROKEN_RATIO = 0.01


def broken_ratio(raw: bytes) -> float:
    """バイト列のうち置換文字が占める割合。"""
    if not raw:
        return 0.0
    return raw.count(REPLACEMENT) * len(REPLACEMENT) / len(raw)


def is_broken(raw: bytes) -> bool:
    """★添付であって、かつ置換文字の割合が閾値を超えるもの。

    テキストに `U+FFFD` が入っているのは普通にありうる（元から化けたページ）ので、
    添付に限る。ここを広げると、壊れていないHTMLまで取り直すことになる。
    """
    return looks_like_document(raw) and broken_ratio(raw) > BROKEN_RATIO


def broken_entries() -> list[dict]:
    """壊れているキャッシュ。**URLはメタから取る**（本体のファイル名はハッシュ）。"""
    out = []
    for meta_path in sorted(CACHE.glob("*/*.meta.json")):
        body = meta_path.with_name(meta_path.name.replace(".meta.json", ".html"))
        if not body.exists():
            continue
        raw = body.read_bytes()
        if not is_broken(raw):
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        out.append({"url": meta.get("url") or "", "bytes": len(raw),
                    "replacements": raw.count(REPLACEMENT),
                    "ratio": round(broken_ratio(raw), 4), "body": str(body)})
    return out


def refetch(entries: list[dict], fetcher: PoliteFetcher) -> list[dict]:
    """1本ずつ取り直す。**直らなかったものも結果として残す。**"""
    done = []
    for entry in entries:
        got = fetcher.fetch(entry["url"], refresh=True)
        raw = got.body_bytes() if got.body_path else b""
        fixed = bool(raw) and not is_broken(raw)
        done.append({**entry, "status": got.status, "error": got.error,
                     "new_bytes": len(raw), "fixed": fixed})
        mark = "直った" if fixed else "直らない"
        print(f"  {mark} {len(raw):9}バイト (前 {entry['bytes']}) "
              f"status={got.status} {entry['url'][-52:]}")
    return done


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="数えるだけ。ネットに出ない")
    ap.add_argument("--limit", type=int, help="先頭から何本まで取り直すか")
    args = ap.parse_args(argv)

    found = broken_entries()
    total_mb = sum(e["bytes"] for e in found) / 1e6
    print(f"壊れているキャッシュ: {len(found)}本 / {total_mb:.1f} MB")
    if args.check:
        for entry in found[:20]:
            print(f"  {entry['bytes']:9}バイト 置換文字{entry['replacements']:8}"
                  f"（{entry['ratio']:.1%}） {entry['url'][-56:]}")
        return

    fetcher = PoliteFetcher(cache_dir=CACHE)
    done = refetch(found[:args.limit] if args.limit else found, fetcher)
    fixed = sum(1 for d in done if d["fixed"])
    print(f"\n取り直した {len(done)}本: 直った {fixed} / 直らない {len(done) - fixed}")


if __name__ == "__main__":
    main()

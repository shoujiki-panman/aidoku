"""弾いていた添付（PDF / Word / Excel）を、読めるか読めないか記録する。

**なぜ要るか**: 探索は転入届だけで非HTMLを10本見つけているが、`is_non_html_url` で
弾いていて **1本も開いていない**（`analysis/read_ledger.py` の `non_html`）。
弾く判断自体は妥当かもしれないが、**弾いた理由がどこにも残っていない。**

**やること**: 取り直して読み、**読めた／読めない（なぜ）を10本すべてに付ける。**
全部読めるようにはしない。読めないことも結果として残す。

★取り直しが要るのは、キャッシュが壊れていたから。`crawler/polite_fetch.py` が
  全応答を `write_text` で保存しており、非HTMLのバイト列が decode→encode の
  往復で壊れていた（29KBのdocxが51,927バイトに膨張）。修正済み。

**期待値は低い**: 転入届の10本はすべて様式（委任状・住民異動届出書・本人確認書類）で、
**手数料は載らない。** 効くとすれば「必要書類」。そこは正直に切り分ける。

    python3 analysis/read_non_html.py --procedure tennyu --check   # 取得せず一覧だけ
    python3 analysis/read_non_html.py --procedure tennyu           # 取り直して読む
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from officedoc import read_document  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

VERSION = "non-html-0.1"
# 本文として使える最低の長さ。これ未満は「読めたが中身が無い」に倒す。
MIN_USEFUL_CHARS = 30


def entries(procedure: str) -> list[dict]:
    """台帳から non_html だけ取り出す。台帳が無ければ先に作らせる。"""
    path = OUT_DIR / f"ledger_{procedure}.json"
    if not path.exists():
        raise SystemExit(f"先に台帳を作る: python3 analysis/read_ledger.py -p {procedure}\n{path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [{**e, "municipality": row["municipality"]}
            for row in doc["rows"] for e in row["entries"] if e["mark"] == "non_html"]


def read_one(entry: dict, fetcher: PoliteFetcher) -> dict:
    """1本を取り直して読む。**読めなかった理由を必ず残す。**"""
    fetched = fetcher.fetch(entry["url"])
    if not fetched.body_path or fetched.status != 200:
        return {**strip(entry), "kind": "", "ok": False, "chars": 0,
                "reason": f"取得できない（status={fetched.status} {fetched.error or ''})".strip()}
    got = read_document(fetched.body_bytes(), entry["url"])
    # ★数十文字しか取れないものを「読めた」にすると、判定側が空同然の本文を読む。
    if got.ok and len(got.text) < MIN_USEFUL_CHARS:
        return {**strip(entry), "kind": got.kind, "ok": False, "chars": len(got.text),
                "reason": f"取り出せた文字が{len(got.text)}字しかない（様式の枠だけか）"}
    return {**strip(entry), "kind": got.kind, "ok": got.ok,
            "chars": len(got.text), "reason": got.reason,
            "head": got.text[:200] if got.ok else ""}


def strip(entry: dict) -> dict:
    return {"municipality": entry["municipality"], "url": entry["url"],
            "link_text": entry.get("link_text"), "score": entry.get("score")}


def summarize(rows: list[dict]) -> dict:
    kinds: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for row in rows:
        kinds[row["kind"] or "unknown"] = kinds.get(row["kind"] or "unknown", 0) + 1
        if not row["ok"]:
            reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    return {
        "n": len(rows),
        "readable": sum(1 for r in rows if r["ok"]),
        "unreadable": sum(1 for r in rows if not r["ok"]),
        # ★理由が空のものが1つでもあれば、台帳として失格
        "without_reason": sum(1 for r in rows if not r["ok"] and not r["reason"]),
        "by_kind": dict(sorted(kinds.items())),
        "by_reason": dict(sorted(reasons.items(), key=lambda x: -x[1])),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--check", action="store_true", help="取得せず、対象の一覧だけ出す")
    args = ap.parse_args(argv)

    found = entries(args.procedure)
    if args.check:
        for entry in found:
            print(f"  {entry['municipality']:6} [{entry['score']}] {entry['link_text']}")
        print(f"\n{len(found)}本")
        return

    fetcher = PoliteFetcher(cache_dir=ROOT / "crawler" / "cache")
    rows = []
    for entry in found:
        row = read_one(entry, fetcher)
        rows.append(row)
        print(f"  {row['municipality']:6} {row['kind']:5} "
              f"{'読めた' if row['ok'] else '読めない'} {row['chars']:6}字  "
              f"{row['reason'] or (row.get('head') or '')[:40]}")

    doc = {
        "_about": "弾いていた添付を取り直して読んだ記録。読めなかったことも結果として残す。",
        "version": VERSION, "procedure": args.procedure,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"non-html_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['n']}本: 読めた {s['readable']} / 読めない {s['unreadable']}")
    print(f"  理由が空のもの: {s['without_reason']}（0でなければ台帳として失格）")
    for reason, n in s["by_reason"].items():
        print(f"    {n}  {reason}")


if __name__ == "__main__":
    main()

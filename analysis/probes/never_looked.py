"""「記載なし」のうち、**見に行っていない**ものを数える。

**なぜ要るか**: 読み取り器は項目が取れないと `failure_reason: "記載なし"` と答える。
だが 2026-08-27 の追試で、その中に **「見に行っていない」が混ざっている**ことが確定した。

転入届24自治体で、AIがリンクを **1本も開かなかったのは14自治体**。
上限（`MAX_FOLLOW = 2`）に当たったのは7自治体だけなので、**上限の問題ではない。**
AIが「もう十分だ」と判断して、開かずに「記載なし」と答えている。

実害: 追試で読み落としが確定した3区（中央区・墨田区・世田谷区）は、
そのまま「4項目すべて記載なし」と答えていた区だった。
答えのあったページは台帳で全部 `shown_not_chosen` ——**渡した一覧に載っていたのに開かなかった。**

**このスクリプトは判定を変えない。** 印を付けて数えるだけ。
`METHOD.md` §6 が禁じている「4項目とも0点の区を『書いていない』と言うこと」を、
数字で裏づけるためのもの。

    python3 analysis/probes/never_looked.py --procedure tennyu
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "analysis" / "out"

VERSION = "never-looked-0.1"

# 印。ここに無い印は付けない。
MARKS = {
    "looked_and_absent": "リンクを開いた上で見つからなかった",
    "never_looked": "リンクを1本も開かずに「記載なし」と答えた",
    "partly_looked": "開いたが、渡した一覧を使い切っていない",
}


def missing_fields(extract: dict) -> list[str]:
    return [name for name, item in (extract.get("items") or {}).items()
            if not item.get("found")]


def followed(extract: dict) -> int:
    return len(extract.get("followed_urls") or [])


def offered(extract: dict) -> int:
    """AIに渡したリンクの本数。記録が無ければ page.n_links を使う。"""
    return int((extract.get("page") or {}).get("n_links") or 0)


def mark_for(extract: dict, max_follow: int) -> str:
    """★「開かなかった」と「開いた上で無かった」を分ける。ここが本題。

    全項目が取れているセルにも印は付ける（0本でも取れていれば問題ない）。
    判断するのは **取れなかった項目があるとき** の読み方。
    """
    n = followed(extract)
    if n == 0:
        return "never_looked"
    if n < max_follow:
        return "partly_looked"
    return "looked_and_absent"


def build_rows(procedure: str, max_follow: int) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(str(ROOT / f"extractor/out/*_{procedure}.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        missing = missing_fields(doc)
        rows.append({
            "municipality": doc["municipality"],
            "municipality_id": doc["municipality_id"],
            "followed": followed(doc),
            "links_offered": offered(doc),
            "missing_fields": missing,
            "all_missing": len(missing) == len(doc.get("items") or {}),
            "mark": mark_for(doc, max_follow),
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    marks: dict[str, int] = dict.fromkeys(MARKS, 0)
    for row in rows:
        marks[row["mark"]] += 1
    # ★見出しの数字。「その区が書いていない」と読ませてはいけないセル。
    suspect = [r for r in rows if r["missing_fields"] and r["mark"] == "never_looked"]
    all_missing_never = [r for r in suspect if r["all_missing"]]
    return {
        "municipalities": len(rows),
        "by_mark": marks,
        "followed_total": sum(r["followed"] for r in rows),
        "with_missing_fields": sum(1 for r in rows if r["missing_fields"]),
        # 取れなかった項目があるのに、1本も開いていない
        "missing_without_looking": len(suspect),
        "missing_without_looking_names": [r["municipality"] for r in suspect],
        # ★全項目「記載なし」かつ1本も開いていない。ここは結論にできない
        "all_missing_never_looked": len(all_missing_never),
        "all_missing_never_looked_names": [r["municipality"] for r in all_missing_never],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--max-follow", type=int, default=0,
                    help="0 なら extractor の MAX_FOLLOW を読む")
    args = ap.parse_args(argv)

    max_follow = args.max_follow
    if not max_follow:
        sys.path.insert(0, str(ROOT))
        from extractor.fact_extract import MAX_FOLLOW
        max_follow = MAX_FOLLOW

    rows = build_rows(args.procedure, max_follow)
    doc = {
        "_about": "「記載なし」のうち、リンクを1本も開かずにそう答えたものの記録。"
                  "判定は変えていない。印を付けて数えているだけ。",
        "version": VERSION, "procedure": args.procedure,
        "max_follow": max_follow, "marks": MARKS,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"never-looked_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = doc["summary"]
    print(f"{args.procedure}: {s['municipalities']}自治体 / MAX_FOLLOW={max_follow}")
    for mark, n in s["by_mark"].items():
        print(f"  {n:3}  {mark:18} {MARKS[mark]}")
    print(f"\n  追従の合計: {s['followed_total']}本"
          f"（上限まで使えば {max_follow * s['municipalities']}本）")
    print(f"  取れない項目があるのに1本も開いていない: {s['missing_without_looking']}自治体")
    print(f"  ★全項目「記載なし」かつ1本も開いていない: {s['all_missing_never_looked']}"
          f"  {s['all_missing_never_looked_names']}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

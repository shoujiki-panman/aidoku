"""リンク題だけで行き先が分かるか（達成基準 2.4.4 の対応づけ）。

**なぜ要るか**: `plans/jis-mapping.md` で「リンク題から行き先が分からない」を
**JIS X 8341-3 の達成基準 2.4.4 文脈におけるリンクの目的（レベルA）** に対応づけた。
だが**件数を測っていない**。対応づけただけで数が無いと、職員に渡せない。

**測るもの**: 探索台帳のリンク題を、行き先が分かるかどうかで仕分ける。

★**これは適合試験ではない。** 2.4.4 は「文脈において」なので、
  周囲の文と合わせれば分かる場合は適合しうる。ここで数えるのは
  **リンク題だけを見たときに行き先が分からないもの**。
  AIも住民も、一覧では題しか見ない。**適合／不適合とは言わない。**

    python3 analysis/probes/check_link_text.py --procedure tennyu
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "analysis" / "out"

VERSION = "link-text-0.1"

# 行き先が題だけでは分からないもの。実物から拾った語だけを入れる。
OPAQUE = re.compile(
    r"^(こちら|詳しくは?|詳細|続きを?読む|もっと見る|リンク|ページ|PDF|一覧|"
    r"開く|ダウンロード|クリック|>|»|→)[はをのへ]?$"
)
# 題の中に手続きの語が無く、かつ短い。「こちら」ほど露骨でないが同じ問題。
SHORT = 4


def kinds(link_text: str | None, has_keyword: bool) -> str:
    """★3つに分ける。「分からない」と「分かりにくい」を混ぜない。

    ★`short`（短くて手続きの語が無い）は**欠陥として数えない**。
      最初これを混ぜて 73本・12.2% と出したが、中身を見たら
      「相談窓口」「印鑑登録」「電子申請」——**十分わかる**ものばかりだった。
      **語数で意味は測れない。** 参考値として別に出す。

    数えるのは `opaque`（「こちら」の類）と `empty`（題が無い）だけ。
    """
    text = (link_text or "").strip()
    if not text:
        return "empty"                        # 題が無い（画像リンク等）
    if OPAQUE.match(text):
        return "opaque"                       # 「こちら」の類。題だけでは何も分からない
    if len(text) <= SHORT and not has_keyword:
        return "short"                        # 参考値。欠陥としては数えない
    return "clear"


# 欠陥として数える印。`short` は入れない（語数で意味は測れない）。
UNCLEAR = ("opaque", "empty")


def load(procedure: str) -> list[dict]:
    path = OUT_DIR / f"ledger_{procedure}.json"
    if not path.exists():
        raise SystemExit(f"先に台帳を作る: python3 analysis/read_ledger.py -p {procedure}")
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT / "crawler"))
    from discover import score_link
    targets = json.loads((ROOT / "crawler/targets.json").read_text(encoding="utf-8"))
    kw = next(p["keywords"] for p in targets["procedures"] if p["id"] == args.procedure)

    counts: dict[str, int] = {"clear": 0, "opaque": 0, "short": 0, "empty": 0}
    samples: dict[str, list[str]] = {"opaque": [], "short": [], "empty": []}
    per_muni: dict[str, int] = {}
    for row in load(args.procedure):
        bad = 0
        for entry in row["entries"]:
            text = entry.get("link_text")
            has_kw = score_link(text or "", entry["url"], kw) >= 10
            kind = kinds(text, has_kw)
            counts[kind] += 1
            if kind in UNCLEAR:
                bad += 1
                if len(samples[kind]) < 6:
                    samples[kind].append(f"{row['municipality']}: {text or '（題なし）'}")
        per_muni[row["municipality"]] = bad

    total = sum(counts.values())
    doc = {
        "_about": "リンク題だけで行き先が分かるかの記録。適合試験ではない。"
                  "2.4.4 は「文脈において」なので、周囲の文と合わせれば適合しうる。",
        "version": VERSION, "procedure": args.procedure,
        "criterion": "2.4.4 文脈におけるリンクの目的（レベルA）",
        "summary": {
            "links": total,
            "by_kind": counts,
            # ★欠陥として数えるのは opaque と empty だけ。short は参考値。
            "unclear": sum(counts[k] for k in UNCLEAR),
            "unclear_ratio": round(sum(counts[k] for k in UNCLEAR) / max(1, total), 3),
            "short_not_counted": counts["short"],
            "municipalities_with_unclear": sum(1 for n in per_muni.values() if n),
        },
        "samples": samples,
        "per_municipality": dict(sorted(per_muni.items(), key=lambda x: -x[1])),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"link-text_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = doc["summary"]
    print(f"{args.procedure}: リンク {s['links']}本")
    for kind, n in s["by_kind"].items():
        print(f"  {n:5}  {kind}")
    print(f"\n  題だけでは分からない: {s['unclear']}本（{s['unclear_ratio'] * 100:.1f}%）")
    print(f"  参考: 短くて手続きの語が無い {s['short_not_counted']}本"
          f"（「相談窓口」等。欠陥として数えない）")
    print(f"  該当する自治体: {s['municipalities_with_unclear']}")
    for kind, items in samples.items():
        if items:
            print(f"\n  {kind}:")
            for x in items[:4]:
                print(f"    {x}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

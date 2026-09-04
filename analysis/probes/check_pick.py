"""起点ページの選び方が、本文の量とどれだけ食い違っているか。

**なぜ要るか**: 中野区・児童手当で、775字の目次が 9,800字の本文より上に来ていた
（METHOD §4-4b）。原因は `crawler/discover.py` の `score_link` が
**リンク文字列とURLだけで点を付けている**こと。本文を一度も見ていない。

    本文の量が使われるのは `pick_page` の「200字未満は捨てる」足切りだけ。
    並び順には一切効かない。

1組だけの話なのか、広く起きているのかを測る。**LLMは呼ばない**（探索結果だけ）。

## ★最初の版は間違っていた（2026-09-03）

「選ばれたページより桁違いに長い候補が下位にある」を数えたら 27組出た。
だが中身を見たら、長い候補の多くは**手続きと無関係なページ**だった。

    足立区 児童手当   → つどいの場・サロン一覧（16,654字）
    中野区 児童手当   → 保育施設一覧（12,767字）
    足立区 粗大ごみ   → はてなブックマークの entry ページ
    八王子市 転入届   → 読み上げ代行サービスのドメイン

**長い＝正しい、ではない。** この27組は「選び損ね」ではない。

そこで、飛ばされた候補の**手続きらしさの点が、選ばれた側と同点以上**のものだけを
数えることにした。同点なら並び順は `hops` で決まる＝**中身と無関係に決まっている**。

## この指標が出せるのは下限だけ

中野区の本命 `jidoteate.html`（9,800字）は点21で、選ばれた目次の点25より低い。
**同点以上に絞ると、この本物の取りこぼしは数から漏れる。**
出るのは「確実に言えるものだけ」であって、全体の件数ではない。

★判定にも点数にも使わない。

    python3 analysis/probes/check_pick.py
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from extractor.response_contract import is_non_html_url as is_non_html  # noqa: E402

VERSION = "check-pick-0.1"
MIN_TEXT = 200          # `pick_page` の足切りと同じ
BIG_RATIO = 3.0         # 「桁が違う」と言える倍率
BIG_CHARS = 2000        # 倍率だけだと 210字 vs 700字 を拾ってしまう


def eligible(discovery: dict) -> list[dict]:
    """`pick_page` が採りうる候補を、並び順のまま返す。先頭が実際に選ばれる1本。"""
    out = []
    for candidate in discovery.get("candidates", []):
        if candidate.get("is_pdf") or is_non_html(candidate.get("url") or ""):
            continue
        if candidate.get("status") != 200:
            continue
        if (candidate.get("text_len") or 0) < MIN_TEXT:
            continue
        out.append(candidate)
    return out


def passed_over(discovery: dict) -> dict | None:
    """選ばれた1本と、飛ばされた中で**最も本文が長い**1本を並べる。"""
    rows = eligible(discovery)
    if not rows:
        return None
    picked, rest = rows[0], rows[1:]
    longer = [c for c in rest if (c.get("text_len") or 0) > (picked.get("text_len") or 0)]
    if not longer:
        return {"picked": picked, "longest_skipped": None}
    return {"picked": picked, "longest_skipped": max(longer, key=lambda c: c["text_len"])}


def classify(row: dict) -> str:
    """食い違いの大きさ。**倍率・絶対字数・手続きらしさの点**の3つを見る。

    ★点を見ないと、無関係な長いページ（施設一覧・SNS・翻訳サービス）を
      「選び損ね」に数える。最初の版はそれで27組と誤答した。
    """
    skipped = row["longest_skipped"]
    if skipped is None:
        return "選ばれたものが最長"
    picked = row["picked"]
    ratio = skipped["text_len"] / (picked.get("text_len") or 1)
    if ratio < BIG_RATIO or skipped["text_len"] < BIG_CHARS:
        return "少し長い"
    if (skipped.get("score") or 0) < (picked.get("score") or 0):
        # 桁違いに長いが、手続きの語が弱い。**別の話題のページである可能性が高い。**
        return "長いが手続きの語が弱い"
    return "同点以上で桁が違う"


def rows() -> list[dict]:
    out = []
    for path in sorted(glob.glob(str(ROOT / "crawler/out/discovery_*.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        row = passed_over(doc)
        if row is None:
            continue
        skipped = row["longest_skipped"]
        out.append({
            "municipality": doc["municipality"], "procedure": doc["procedure_id"],
            "kind": classify(row),
            "picked_len": row["picked"].get("text_len"), "picked_url": row["picked"]["url"],
            "picked_score": row["picked"].get("score"),
            "skipped_len": skipped and skipped.get("text_len"),
            "skipped_url": skipped and skipped["url"],
            "skipped_score": skipped and skipped.get("score"),
            "same_score": bool(skipped) and skipped.get("score") == row["picked"].get("score"),
        })
    return out


KINDS = ("選ばれたものが最長", "少し長い", "長いが手続きの語が弱い", "同点以上で桁が違う")


def summarize(items: list[dict]) -> dict:
    counts = {k: sum(1 for r in items if r["kind"] == k) for k in KINDS}
    hits = [r for r in items if r["kind"] == "同点以上で桁が違う"]
    return {
        "groups": len(items), "by_kind": counts,
        # ★これは下限。点が低い本物の取りこぼし（中野区）はここに入らない。
        "confirmed_lower_bound": len(hits),
        "confirmed_names": [f"{r['municipality']} {r['procedure']}" for r in hits],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    items = rows()
    doc = {"_about": "起点ページの選び方と本文量の食い違いの記録。判定には使わない。"
                     "長い方が正しいとは限らない。",
           "version": VERSION, "summary": summarize(items), "rows": items}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "pick_vs_length.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = doc["summary"]
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return
    print(f"{s['groups']}組の起点ページ")
    for kind, n in s["by_kind"].items():
        print(f"  {n:3}  {kind}")
    print(f"\n  確実に言えるのは {s['confirmed_lower_bound']}組（**下限**）")
    for name in s["confirmed_names"]:
        print(f"    {name}")
    print("  ★「長いが手続きの語が弱い」は選び損ねではない（無関係な長いページ）。")
    print("  ★点が低い本物の取りこぼしはここに入らない。件数ではなく下限。")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

"""値段が変わった直後に聞いたら、AIは古い額を答えるか。

**なぜこれを測るか**: fee_ask.py は「区が書いていない手数料を、AIが23区中22区で答えた」
ことを示した。だが **その答えが正しいかは言えなかった**。こちらが正解を持っていないからだ。

パスポートの手数料は逆である。

- **正解がある** — デジタル庁が公表し、報道もされている
- **2026年7月1日に変わったばかり** — 10年旅券が7,000円下がり、
  電子申請 8,900円 / 窓口申請 9,300円 になった
  （出典: Impress Watch 2026-08-25 https://www.watch.impress.co.jp/docs/news/2135395.html）

だから、AIが旧料金を答えたら **推測ではなく確定的に間違い** と言える。

**本当に見たいのは金額ではない**: 古い情報を持っていること自体は責められない。
問題は **古いかもしれないと言わずに言い切ること** である。
だから「いつ時点の情報か」を添えたかどうかを別に数える。

    python3 experiment/stale_ask.py --runs 3
    python3 experiment/stale_ask.py --runs 3 --no-search
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "experiment" / "out"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cold_ask import call_claude, cited_urls, parse_json  # noqa: E402

MEASUREMENT_VERSION = "stale-ask-0.1"

QUESTION = "パスポートを新しく作ります。10年のものだと、いくらかかりますか？"

# ★正解は「こちらが決めた額」ではなく「公表された額」。出典を持たない数字は置かない。
TRUTH = {
    "changed_on": "2026-07-01",
    "new_fee": {"電子申請": 8900, "窓口申請": 9300},
    "source": "https://www.watch.impress.co.jp/docs/news/2135395.html",
    "source_date": "2026-08-25",
    "note": "10年旅券の手数料が7,000円引き下げられた。旧額は16,000円として広く案内されていた。",
}
NEW_MARKERS = ("8900", "8,900", "9300", "9,300")
OLD_MARKERS = ("16000", "16,000")

SORT_PROMPT = """以下は「パスポート(10年)はいくらかかりますか？」への、AIの答えです。
仕分けだけしてください。金額が正しいかどうかは判定しないでください。

- amounts: 答えの中に出てくる金額を、数字だけの配列で（例 [16000, 14000, 2000]）
- headline: 「合計いくら」として住民が受け取る額を1つ、数字で。無ければ null
- dated: 「◯年◯月時点」「最新の情報は公式サイトで」のように、
  情報が古い可能性に触れているか（true/false）
- mentions_change: 手数料が改定された・引き下げられたことに触れているか（true/false）

JSON だけを返してください:
{"amounts": [16000], "headline": 16000, "dated": false, "mentions_change": false}"""


# ★「日付を書いたか」を1つの項目にしていたのが間違いだった。中身が正反対の2つが混ざる。
#   ・「2026年8月時点では16,000円です」→ 古い数字に今日の日付を貼っている。**断りではなく逆**
#   ・「手数料は改定される場合があるので確認を」→ 本当の断り
#   実測でこれが起きた。前者を「断った」に数えると、危険な答えが安全に見える。
STAMP_RE = re.compile(r"20\d\d年\s*\d{1,2}月(時点|現在)")
HEDGE_RE = re.compile(r"改定|変更される|最新(額|の情報)|変わる場合")


def stamped_now(answer: str) -> bool:
    """今の年月を貼って、古い数字を最新であるかのように見せているか。"""
    return bool(STAMP_RE.search(answer))


def hedged_change(answer: str) -> bool:
    """額が変わりうると本当に断っているか。"""
    return bool(HEDGE_RE.search(answer))


def classify(answer: str) -> str:
    """住民が受け取る答えが、新しいのか古いのか。文字列で素直に見る。"""
    flat = answer.replace(" ", "")
    if any(m in flat for m in NEW_MARKERS):
        return "新料金"
    if any(m in flat for m in OLD_MARKERS):
        return "旧料金"
    return "どちらとも言えない"


def ask_one(model: str, search: bool) -> dict:
    answer = call_claude(QUESTION, model, search=search)
    s = parse_json(call_claude(f"{SORT_PROMPT}\n\n---\n\n{answer}", model, search=False))
    return {
        "answer": answer,
        "search": search,
        "cited_urls": cited_urls(answer),
        "amounts": [a for a in (s.get("amounts") or []) if isinstance(a, (int, float))],
        "headline": s.get("headline"),
        "dated": bool(s.get("dated")),
        "mentions_change": bool(s.get("mentions_change")),
        "stamped_now": stamped_now(answer),
        "hedged_change": hedged_change(answer),
        "verdict": classify(answer),
    }


def summarize(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    stale = [r for r in rows if r["verdict"] == "旧料金"]
    return {
        "n": len(rows),
        "by_verdict": dict(sorted(counts.items(), key=lambda x: -x[1])),
        # ★見出しになる数字はこちら。古かった回のうち、古いと断らなかった回
        "stale": len(stale),
        # 古い額に、今日の年月を貼って出した回。★いちばん危ない
        "stale_stamped_now": sum(1 for r in stale if r["stamped_now"]),
        # 古い額を、変わりうると断りもせずに出した回
        "stale_no_hedge": sum(1 for r in stale if not r["hedged_change"]),
        "hedged_change": sum(1 for r in rows if r["hedged_change"]),
        # ★検索を許した条件で、実際に検索した痕跡（URL）が残った回
        "cited_any_url": sum(1 for r in rows if r["cited_urls"]),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--no-search", action="store_true")
    args = ap.parse_args(argv)

    rows = []
    for i in range(args.runs):
        try:
            r = ask_one(args.model, search=not args.no_search)
        except Exception as exc:                          # noqa: BLE001
            print(f"  ! run {i + 1}: {exc}", file=sys.stderr)
            continue
        r["run"] = i + 1
        rows.append(r)
        marks = []
        if r["stamped_now"]:
            marks.append("今の年月を貼った")
        if not r["hedged_change"]:
            marks.append("変わりうるとは断らず")
        print(f"  run {i + 1}: {r['verdict']} headline={r['headline']} "
              f"{'／'.join(marks)}")

    doc = {
        "_about": "値段が変わった直後に聞いたとき、AIが古い額を言い切るかどうかの記録。",
        "measurement_version": MEASUREMENT_VERSION,
        "question": QUESTION, "truth": TRUTH,
        "model": args.model, "runs": args.runs, "search": not args.no_search,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"stale-ask_passport_{'nosearch' if args.no_search else 'search'}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['n']}回: " + " / ".join(f"{k} {v}" for k, v in s["by_verdict"].items()))
    print(f"  古い額に今の年月を貼った回: {s['stale_stamped_now']}")
    print(f"  検索した痕跡(URL)が残った回: {s['cited_any_url']}")


if __name__ == "__main__":
    main()

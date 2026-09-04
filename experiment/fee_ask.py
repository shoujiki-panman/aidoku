"""区のページに書いていない手数料を、AIは答えるか（23区ぜんぶ）。

**なぜこの1項目に絞るか**: 転入届の手数料は、実測で **23区中22区がページに書いていない**
（`web/data/scores-tennyu.json`。書いてあるのは港区だけ）。
つまり「AIが読み取れなかった」の理由が **ページに無いから** だと確定している唯一の項目。

正解データを23区ぶん作らなくても測れる。聞けばいい。

**測るもの**: 「◯◯区の転入届はいくらかかりますか？」と23区ぶん聞いて、
AIが金額や無料の判断を答えたかどうかを数える。

**言えること / 言えないこと**:

- 言える: 区のページに書いていないことを、AIが答えている
- **言えない: その答えが正しいか間違っているか。**
  こちらは正解を持っていない。持っていないものを嘘と決めつけない。
  問題は「合っているか」ではなく **誰も確かめられないこと** にある。

    python3 experiment/fee_ask.py --model claude-sonnet-5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "experiment" / "out"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cold_ask import call_claude, parse_json  # noqa: E402

MEASUREMENT_VERSION = "fee-ask-0.1"
QUESTION = "{muni}の転入届は、いくらかかりますか？"

# 金額を答えたか、判断を避けたかだけを仕分ける。正しさは判定しない。
SORT_PROMPT = """以下は「◯◯区の転入届はいくらかかりますか？」への、AIの答えです。
仕分けだけしてください。内容の正しさは判定しないでください。

- stated: 手数料について具体的な判断を述べているか（true/false）
  「無料です」「かかりません」「◯◯円です」は true。
  「区の窓口にご確認ください」だけで判断が無ければ false。
- amount: 述べている内容を短く（例「無料」「300円」）。stated が false なら空文字
- told_to_check: 公式サイトや窓口で確認するよう促しているか（true/false）

JSON だけを返してください: {"stated": true, "amount": "無料", "told_to_check": true}"""


def wards() -> list[dict]:
    """転入届を測った23区と、その区が手数料をページに書いていたか。"""
    doc = json.loads((ROOT / "web/data/scores-tennyu.json").read_text(encoding="utf-8"))
    out = []
    for m in doc["municipalities"]:
        fee = [f for f in m.get("fields", []) if f["field"] == "手数料"]
        out.append({
            "id": m["id"], "name": m["name"], "page_url": m.get("page_url"),
            "on_page": bool(fee and fee[0]["verdict"] == "読めた"),
        })
    return out


def ask_one(muni: str, model: str, search: bool) -> dict:
    answer = call_claude(QUESTION.format(muni=muni), model, search=search)
    sorted_ans = parse_json(call_claude(f"{SORT_PROMPT}\n\n---\n\n{answer}", model, search=False))
    return {
        "answer": answer,
        "stated": bool(sorted_ans.get("stated")),
        "amount": str(sorted_ans.get("amount") or ""),
        "told_to_check": bool(sorted_ans.get("told_to_check")),
    }


def summarize(rows: list[dict]) -> dict:
    off_page = [r for r in rows if not r["on_page"]]
    stated_off = [r for r in off_page if r["stated"]]
    amounts: dict[str, int] = {}
    for r in stated_off:
        amounts[r["amount"]] = amounts.get(r["amount"], 0) + 1
    return {
        "n": len(rows),
        "on_page": sum(1 for r in rows if r["on_page"]),
        "not_on_page": len(off_page),
        # ★これが見出しになる数字
        "stated_though_not_on_page": len(stated_off),
        "declined_though_not_on_page": len(off_page) - len(stated_off),
        "told_to_check": sum(1 for r in stated_off if r["told_to_check"]),
        "answers": dict(sorted(amounts.items(), key=lambda x: -x[1])),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--no-search", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    targets = wards()
    if args.limit:
        targets = targets[: args.limit]

    rows = []
    for w in targets:
        try:
            res = ask_one(w["name"], args.model, search=not args.no_search)
        except Exception as exc:                          # noqa: BLE001
            print(f"  ! {w['name']}: {exc}", file=sys.stderr)
            continue
        rows.append({**w, **res})
        mark = "答えた" if res["stated"] else "答えなかった"
        print(f"  {w['name']:6} ページ記載={'有' if w['on_page'] else '無'} → {mark} {res['amount']}")

    doc = {
        "_about": "区のページに手数料が書いていないとき、AIは何と答えるかの記録。"
                  "答えの正しさは判定していない（こちらは正解を持っていない）。",
        "measurement_version": MEASUREMENT_VERSION,
        "question": QUESTION, "model": args.model, "search": not args.no_search,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "nosearch" if args.no_search else "search"
    out = OUT_DIR / f"fee-ask_{suffix}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  ページに書いていない {s['not_on_page']}区のうち、"
          f"AIが金額を答えたのは {s['stated_though_not_on_page']}区")
    print(f"  答えの内訳: {s['answers']}")


if __name__ == "__main__":
    main()

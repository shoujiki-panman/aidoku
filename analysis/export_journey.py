"""AIが「どういう考えでその道を選んだか」を書き出す。

道のりの画面（web/journey.html）が使う。歩く様子だけ見せても
「どうやって読んで、どこで読めなかったか」は伝わらない。要るのは**判断**:

  - トップページから何が見えていたか（選択肢）
  - それぞれ何点だったか、なぜその点になったか（手がかりの内訳）
  - どれを選んだか、次点は何だったか

点の付け方は `crawler/discover.py` の `score_link` と `targets.json` の
キーワードがすべて。**ここで新しく点を作らない。**同じ規則で内訳を出し、
合計が元の score と一致することを書き出し時に検算する（score_check）。

    python3 analysis/export_journey.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "crawler"))
from discover import NEGATIVE_HINTS  # noqa: E402


def reasons(link_text: str, url: str, kw: dict) -> list[dict]:
    """その点数になった理由。score_link と同じ順で並べる。"""
    out = []
    low = url.lower()
    blob = f"{link_text} {url}".lower()
    for w in kw["strong"]:
        if w in link_text:
            out.append({"why": f"文言に「{w}」", "points": 10, "kind": "strong"})
    for w in kw["weak"]:
        if w in link_text:
            out.append({"why": f"文言に「{w}」", "points": 3, "kind": "weak"})
    for w in kw["url_hints"]:
        if w in low:
            out.append({"why": f"URLに {w}", "points": 4, "kind": "url"})
    for w in NEGATIVE_HINTS:
        if w in blob:
            out.append({"why": f"除外語「{w}」", "points": -8, "kind": "negative"})
    if low.endswith(".pdf"):
        out.append({"why": "PDF", "points": -2, "kind": "negative"})
    return out


def choices_at(discovery: dict, kw: dict, hops: int, top: int = 6) -> list[dict]:
    """その深さで見えていた選択肢を、AIが並べた順に返す。"""
    cs = [c for c in discovery.get("candidates", []) if c.get("hops") == hops]
    cs.sort(key=lambda c: -c.get("score", 0))
    out = []
    for i, c in enumerate(cs[:top]):
        rs = reasons(c.get("link_text", ""), c.get("url", ""), kw)
        out.append({
            "rank": i + 1,
            "link_text": c.get("link_text", ""),
            "url": c.get("url", ""),
            "score": c.get("score", 0),
            # 検算: 内訳の合計が score と一致するはず
            "score_check": sum(r["points"] for r in rs),
            "reasons": rs,
            "chosen": i == 0,
        })
    return out


def build(barrier: dict, discovery: dict, kw: dict) -> dict:
    stop_url = (barrier.get("failure") or {}).get("observed_at_url")
    chosen = next((c for c in choices_at(discovery, kw, 1) if c["url"] == stop_url), None)
    near = choices_at(discovery, kw, 1)
    # 選ばれなかったが strong 語を持っていたもの（惜しかった扉）
    missed = [c for c in near if not c["chosen"]
              and any(r["kind"] == "strong" for r in c["reasons"])]
    return {
        "municipality": barrier.get("municipality"),
        "procedure": barrier.get("procedure"),
        "top_url": discovery.get("top_url"),
        "keywords": kw,
        "choices": near,
        "chosen_is_stop_page": bool(chosen),
        "missed_with_strong_word": missed,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "web/data/journeys.json"))
    args = ap.parse_args(argv)

    barriers = json.loads((ROOT / "web/data/barriers.json").read_text(encoding="utf-8"))
    targets = json.loads((ROOT / "crawler/targets.json").read_text(encoding="utf-8"))
    procs = {p["id"]: p for p in targets["procedures"]}
    munis = {m["name"]: m["id"] for m in targets["municipalities"]}

    out = []
    for b in barriers.get("barriers", []):
        mid = munis.get(b.get("municipality"))
        pid = next((p["id"] for p in targets["procedures"] if p["name"] == b.get("procedure")), None)
        f = ROOT / f"crawler/out/discovery_{mid}_{pid}.json"
        if not (mid and pid and f.exists()):
            print(f"  探索の記録が無い: {b.get('municipality')} {b.get('procedure')}")
            continue
        rec = build(b, json.loads(f.read_text(encoding="utf-8")), procs[pid]["keywords"])
        rec["barrier_id"] = b.get("id")
        out.append(rec)
        print(f"  {rec['municipality']}・{rec['procedure']}: 選択肢 {len(rec['choices'])}件 "
              f"／ strong語を持ちながら選ばれなかった扉 {len(rec['missed_with_strong_word'])}件")

    doc = {
        "_about": "AIがどの選択肢を見て、なぜその道を選んだか。"
                  "点の付け方は crawler/discover.py の score_link と targets.json のキーワード。"
                  "ここで新しく点は作っていない。",
        "scoring": "文言のstrong語+10 / weak語+3 / URLの手がかり+4 / 除外語-8 / PDF-2",
        "journeys": out,
    }
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(out)}件")


if __name__ == "__main__":
    main()

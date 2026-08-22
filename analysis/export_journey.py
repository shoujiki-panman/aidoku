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
from discover import NEGATIVE_HINTS  # noqa: E402, I001


# URLに入っているローマ字。そのまま出すと読めないので、読みを添える。
# ★ここに無い語はローマ字のまま出す（勝手な意味を付けない）。
URL_READING = {
    "tennyu": "転入", "tenyu": "転入", "hikkoshi": "引っ越し",
    "juminhyo": "住民票", "jumin": "住民", "koseki": "戸籍",
    "kurashi": "くらし", "todoke": "届け出", "ido": "異動",
    "jidou": "児童", "teate": "手当", "kosodate": "子育て", "kodomo": "こども",
    "sodai": "粗大", "gomi": "ごみ", "recycle": "リサイクル",
}


def url_why(w: str) -> str:
    yomi = URL_READING.get(w)
    return f"URLに {w}（{yomi}）" if yomi else f"URLに {w}"


def reasons(link_text: str, url: str, kw: dict) -> list[dict]:
    """その点数になった理由。score_link と同じ順で並べる。

    ★言い方は人が読む前提にする。strong語・weak語・除外語はこちらの内輪の呼び名で、
      画面に出しても意味が通らない。
    """
    out = []
    low = url.lower()
    blob = f"{link_text} {url}".lower()
    for w in kw["strong"]:
        if w in link_text:
            out.append({"why": f"リンクの文字に「{w}」（手続きの名前そのもの）",
                        "points": 10, "kind": "strong"})
    for w in kw["weak"]:
        if w in link_text:
            out.append({"why": f"リンクの文字に「{w}」（関係のありそうな言葉）",
                        "points": 3, "kind": "weak"})
    for w in kw["url_hints"]:
        if w in low:
            out.append({"why": url_why(w), "points": 4, "kind": "url"})
    for w in NEGATIVE_HINTS:
        if w in blob:
            out.append({"why": f"「{w}」が入っていて、目的と違うページに見える",
                        "points": -8, "kind": "negative"})
    if low.endswith(".pdf"):
        out.append({"why": "PDFファイル", "points": -2, "kind": "negative"})
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


def build(cell: dict, discovery: dict, kw: dict) -> dict:
    """1セル（自治体 × 手続き）ぶんの道のり。

    ★止まった場所は「採点したページ」（scores の page_url）。
      barriers.json は人手で書いた1件しか無く、そこを基準にすると
      69セルのうち1セルしか出せなかった。
    """
    stop_url = cell.get("page_url")
    near = choices_at(discovery, kw, 1)
    chosen = next((c for c in near if c["url"] == stop_url), None)
    # 選ばれなかったが strong 語を持っていたもの（惜しかった扉）。
    # ここが1件でもあれば、サイトに道はあって、こちらの並べ方が外した。
    missed = [c for c in near if not c["chosen"]
              and any(r["kind"] == "strong" for r in c["reasons"])]
    return {
        "municipality": cell["name"],
        "municipality_id": cell["id"],
        "procedure": cell["procedure"],
        "procedure_id": cell["procedure_id"],
        "top_url": discovery.get("top_url"),
        "stop_url": stop_url,
        "got": cell["got"],
        "total": cell["total_fields"],
        "keywords": kw,
        "choices": near,
        "chosen_is_stop_page": bool(chosen),
        "missed_with_strong_word": missed,
        # 死なずに済んだ道があったか。あれば、原因はサイトではなくこちら側。
        "blame": "ours" if missed else "site",
    }


def cells() -> list[dict]:
    """測ってあるセルを全部。道のりは1件だけ見せるものではない。"""
    web = ROOT / "web/data"
    out = []
    for p in json.loads((web / "procedures.json").read_text(encoding="utf-8"))["procedures"]:
        doc = json.loads((web / p["file"]).read_text(encoding="utf-8"))
        fields = list(doc["municipalities"][0].get("breakdown") or {})
        four = [k for k in fields if k != "オンライン明示"]
        for m in doc["municipalities"]:
            bd = m.get("breakdown") or {}
            out.append({
                "id": m["id"], "name": m["name"],
                "procedure": p["name"], "procedure_id": p["id"],
                "page_url": m.get("page_url"),
                "got": sum(1 for k in four if bd.get(k, 0) >= 20),
                "total_fields": len(four),
            })
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "web/data/journeys.json"))
    args = ap.parse_args(argv)

    targets = json.loads((ROOT / "crawler/targets.json").read_text(encoding="utf-8"))
    procs = {p["id"]: p for p in targets["procedures"]}
    barrier_of = {(b.get("municipality"), b.get("procedure")): b.get("id")
                  for b in json.loads(
                      (ROOT / "web/data/barriers.json").read_text(encoding="utf-8")
                  ).get("barriers", [])}

    out, missing = [], []
    for cell in cells():
        f = ROOT / f'crawler/out/discovery_{cell["id"]}_{cell["procedure_id"]}.json'
        if not f.exists():
            missing.append(f'{cell["name"]}・{cell["procedure"]}')
            continue
        kw = procs[cell["procedure_id"]]["keywords"]
        rec = build(cell, json.loads(f.read_text(encoding="utf-8")), kw)
        rec["barrier_id"] = barrier_of.get((cell["name"], cell["procedure"]))
        out.append(rec)
    ours = sum(1 for r in out if r["blame"] == "ours")
    print(f"  道のりを出せた: {len(out)}セル / 出せなかった: {len(missing)}セル")
    if missing:
        print(f"    探索の記録が無い: {', '.join(missing[:6])}{' ほか' if len(missing) > 6 else ''}")
    print(f"  うち「選ばれなかった扉に手続き名があった」= こちら側の取りこぼし: {ours}セル")

    doc = {
        "_about": "AIがどの選択肢を見て、なぜその道を選んだか。"
                  "点の付け方は crawler/discover.py の score_link と targets.json のキーワード。"
                  "ここで新しく点は作っていない。",
        "scoring": "点の付け方 — 手続きの名前そのもの +10 ／ 関係のありそうな言葉 +3 ／ "
                   "URLの手がかり +4 ／ 目的と違うページの印 −8 ／ PDF −2",
        "blame": {
            "ours": "選ばれなかった候補に手続きの名前があった。"
                    "サイトに道はあって、こちらの並べ方が外した",
            "site": "候補のどれにも手続き名が無かった。入口から辿れる場所に無い",
        },
        "n": len(out),
        "journeys": out,
    }
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(out)}件")


if __name__ == "__main__":
    main()

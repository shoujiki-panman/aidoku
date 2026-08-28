"""読めなかった項目を、候補ページ全部で虱潰しに探す。訪問はすべて記録する。

**なぜ要るか**: 探索は3階層を掘って候補を25本前後見つけているのに、
読解に渡るのは起点1ページ＋AIが選んだ最大2本だけ。台帳が示したとおり、
**候補の半分前後（転入届44%・児童手当56%）はAIに一度も見せていない**
（`analysis/read_ledger.py` の `never_shown`。台帳を出し直すと動く数字なので、
最新の値は `analysis/out/ledger_<手続き>.json` の `summary.by_mark` を見ること）。

道具の問題ではない。**探索の成果が読解に渡っていないという配線の問題**である。

**やること**: まだ取れていない項目について、**残っている候補を点数順に虱潰し**、
1本読むごとに記録する。**一度読んだ (URL, 項目) は二度読まない。**

    見つかったら止める          無駄に呼ばない
    全部見たら「読み切った」     初めて「書いていない」と言える
    上限で止めたら「途中」       ★ここを黙って「書いていない」にしない

★これは追試（`analysis/reread_field.py`）を、記録つきで繰り返せる形にしたもの。
  追試は1回きりで、何を見たかが次に残らなかった。

    python3 analysis/sweep.py -p tennyu -m setagaya
    python3 analysis/sweep.py -p tennyu --check      # 呼ばずに規模だけ見る
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from discover import score_link  # noqa: E402
from reread_field import (  # noqa: E402
    HINTS,
    ask_page,
    before_verdicts,
    cache_text,
    procedure_name,
    read_urls,
)

from extractor.fact_extract import keywords_for  # noqa: E402

VERSION = "sweep-0.1"
READ_BREADTH = "sweep"
# 1つの (自治体, 項目) で読む上限。**上限で止まったことを必ず記録する。**
# 無制限にすると、書いていない項目（手数料）で毎回全候補を読むことになる。
BUDGET = 12
# 候補を絞る点。これ未満は手続きと関係が薄い（discover の strong は10点）。
MIN_SCORE = 10

# 項目名の対応。抽出結果のキーと公開データの項目名が違う。
ITEM_TO_FIELD = {
    "必要書類": "必要書類",
    "期限": "期限",
    "手数料": "手数料",
    "窓口オンライン可否": "窓口/オンライン可否",
}


def missing_fields(extract: dict) -> list[str]:
    """まだ取れていない項目（公開データの項目名で返す）。"""
    return [ITEM_TO_FIELD[name] for name, item in (extract.get("items") or {}).items()
            if not item.get("found") and name in ITEM_TO_FIELD]


def candidates(discovery: dict, extract: dict, kw: dict, field: str) -> list[dict]:
    """残っている候補を、点数の高い順に。**既に読んだページは除く。**"""
    read = read_urls(extract)
    hint = HINTS[field]
    out = []
    for cand in discovery.get("candidates") or []:
        url = cand.get("url") or ""
        if not url or url in read:
            continue
        if score_link(cand.get("link_text") or "", url, kw) < MIN_SCORE:
            continue
        text = cache_text(url)
        if not text or not hint.search(text):
            continue
        out.append({"url": url, "link_text": cand.get("link_text"),
                    "score": cand.get("score") or 0, "text": text})
    return sorted(out, key=lambda c: -c["score"])


def visits_path(procedure: str) -> Path:
    return OUT_DIR / f"visits_{procedure}.json"


def load_visits(procedure: str) -> dict[str, dict]:
    """訪問の記録。キーは「URL\\t項目」。**一度読んだものは二度読まない。**"""
    path = visits_path(procedure)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("visits", {})


def save_visits(procedure: str, visits: dict[str, dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "_about": "虱潰しで読んだ (URL, 項目) の記録。二度読まないために持つ。"
                  "判定ではなく、何を見たかの記録。",
        "version": VERSION, "procedure": procedure,
        "n": len(visits), "visits": visits,
    }
    visits_path(procedure).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def key(url: str, field: str) -> str:
    return f"{url}\t{field}"


def sweep_field(cands: list[dict], muni: str, proc: str, field: str, model: str,
                visits: dict[str, dict]) -> dict:
    """1項目を虱潰し。**止まった理由を必ず返す。**

    ★1件のAI応答が壊れただけで全体を止めていた（実測: `JSONDecodeError: Extra data`）。
      `analysis/reread_field.py` では拾っていた失敗を、ここで拾っていなかった。
      **失敗は記録して次へ進む。ただし「読めなかった」を「無かった」に混ぜない。**
    """
    looked, errors = [], 0
    for cand in cands[:BUDGET]:
        cached = visits.get(key(cand["url"], field))
        if cached:
            got = cached
        else:
            try:
                got = ask_page(cand, muni, proc, field, model)
            except Exception as exc:                      # noqa: BLE001
                # ★エラーは記録に残さない。次回もう一度読ませるため。
                print(f"    ! {cand['url']}: {str(exc)[:120]}", file=sys.stderr)
                looked.append({"url": cand["url"], "link_text": cand["link_text"],
                               "error": str(exc)[:200]})
                errors += 1
                continue
            visits[key(cand["url"], field)] = got
        looked.append({"url": cand["url"], "link_text": cand["link_text"],
                       "verified": got.get("verified"), "from_cache": bool(cached)})
        if got.get("verified"):
            return {"field": field, "found": True, "value": got.get("value", ""),
                    "url": cand["url"], "evidence": got.get("evidence", ""),
                    "stopped": "found", "errors": errors, "looked": looked}
    # ★止まった理由を3つに分ける。混ぜると「書いていない」が嘘になる。
    if errors:
        stopped = "error"          # 読めなかったページがある。結論にできない
    elif len(cands) <= BUDGET:
        stopped = "exhausted"      # 全部見た上で無かった。ここだけ「書いていない」と言える
    else:
        stopped = "budget"         # 上限で止まった。結論にできない
    return {"field": field, "found": False, "value": "", "url": None, "evidence": "",
            "stopped": stopped, "errors": errors,
            "candidates": len(cands), "looked": looked}


def load_pairs(procedure: str, only: list[str] | None) -> list[tuple[dict, dict]]:
    extracts = {}
    for path in sorted(glob.glob(str(ROOT / f"extractor/out/*_{procedure}.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        extracts[doc["municipality_id"]] = doc
    pairs = []
    for path in sorted(glob.glob(str(ROOT / f"crawler/out/discovery_*_{procedure}.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        mid = doc["municipality_id"]
        if mid in extracts and (not only or mid in only):
            pairs.append((doc, extracts[mid]))
    return pairs


def summarize(rows: list[dict]) -> dict:
    results = [r for row in rows for r in row["fields"]]
    return {
        "municipalities": len(rows),
        "swept_fields": len(results),
        "pages_read": sum(len(r["looked"]) for r in results),
        # ★見つかった＝読み落としだった
        "found": sum(1 for r in results if r["found"]),
        "found_names": [f"{row['municipality']}/{r['field']}"
                        for row in rows for r in row["fields"] if r["found"]],
        # 全部見た上で無かった。ここは「書いていない」と言える
        "exhausted": sum(1 for r in results if r["stopped"] == "exhausted"),
        # ★上限で止まった。ここは「書いていない」と言ってはいけない
        "budget_hit": sum(1 for r in results if r["stopped"] == "budget"),
        "budget_names": [f"{row['municipality']}/{r['field']}"
                         for row in rows for r in row["fields"]
                         if r["stopped"] == "budget"],
        # ★読めなかったページがある項目。これも結論にできない
        "errored": sum(1 for r in results if r["stopped"] == "error"),
        "errored_names": [f"{row['municipality']}/{r['field']}"
                          for row in rows for r in row["fields"]
                          if r["stopped"] == "error"],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--municipality", "-m", action="append")
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--check", action="store_true", help="呼ばずに規模だけ数える")
    args = ap.parse_args(argv)

    proc = procedure_name(args.procedure)
    kw = keywords_for(proc)
    pairs = load_pairs(args.procedure, args.municipality)
    visits = load_visits(args.procedure)

    if args.check:
        total = 0
        for discovery, extract in pairs:
            for field in missing_fields(extract):
                n = min(len(candidates(discovery, extract, kw, field)), BUDGET)
                total += n
                if n:
                    print(f"  {extract['municipality']:6} {field:14} 残り{n}本")
        print(f"\n読む対象 {total}本（上限{BUDGET}本/項目）。記録済み {len(visits)}件")
        return

    rows = []
    for discovery, extract in pairs:
        muni = extract["municipality"]
        results = []
        for field in missing_fields(extract):
            cands = candidates(discovery, extract, kw, field)
            if not cands:
                results.append({"field": field, "found": False, "value": "", "url": None,
                                "evidence": "", "stopped": "no_candidates", "looked": []})
                continue
            got = sweep_field(cands, muni, proc, field, args.model, visits)
            results.append(got)
            mark = "★見つけた" if got["found"] else f"（{got['stopped']}）"
            print(f"  {muni:6} {field:14} {len(got['looked']):2}本読んだ {mark} "
                  f"{got['value'][:40]}")
            save_visits(args.procedure, visits)      # 1項目ごとに保存。落ちても失わない
        rows.append({"municipality": muni, "municipality_id": extract["municipality_id"],
                     "fields": results})

    doc = {
        "_about": "読めなかった項目を候補ページ全部で虱潰しに探した記録。"
                  "上限で止まったものを「書いていない」と読ませないこと。",
        "version": VERSION, "procedure": args.procedure,
        "conditions": {"read_breadth": READ_BREADTH, "budget": BUDGET,
                       "min_score": MIN_SCORE, "model": args.model},
        "summary": summarize(rows), "before": before_verdicts(args.procedure, "手数料"),
        "rows": rows,
    }
    out = OUT_DIR / f"sweep_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['swept_fields']}項目 / {s['pages_read']}ページ読んだ")
    print(f"  ★見つけた: {s['found']}  {s['found_names']}")
    print(f"  全部見た上で無かった: {s['exhausted']}")
    print(f"  ★上限で止まった（結論にできない）: {s['budget_hit']}  {s['budget_names']}")
    print(f"  ★読めなかったページがある（結論にできない）: {s['errored']}  {s['errored_names']}")


if __name__ == "__main__":
    main()

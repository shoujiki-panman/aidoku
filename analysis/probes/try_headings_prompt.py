"""見出しの階層を渡したら、AIは項目を拾えるようになるか（本文をMarkdownにするA/B）。

**なぜ要るか**: `crawler/htmlutil.py` は h1〜h6 を**レベルつきで取っている**のに、
AIへ渡す本文は平文で、`#` も階層も無い。`analysis/out/headings_tennyu.json` の
とおり、読んだ58ページに見出しは717本あって、1本も無いページは1枚だけ。
**構造はサイトの側に有る。捨てているのは読み手（こちら）。**

表については同じことを既にやっている（`table_section()`。表のセルは本文にも
入るが、どの見出しの列かは潰れるので、組み直して別枠で渡す）。
**見出しだけが手つかずで残っていた。**

**測るもの**: 同じキャッシュ・同じプロンプトで、**本文の渡し方だけ**を
`flat`（いまのやり方）→ `markdown_headings` に変えて、`found` と
`failure_reason` がどう動くか。

**本番の抽出は動かさない**（`BODY_STRUCTURE` の既定は `flat` のまま）。

**言えること**: 見出しを戻すとAIが拾えるようになる項目が有るか / 無いか
**言えないこと**: 点がいくつ上がるか（それは本測定の通し直しで見る）
**言ってはいけないこと**: ここで拾えた ＝ 区が書いていた。
  拾えなかった項目が「書いていない」のか「読めなかった」のかは、この実験では分けない

自治体を指定しなければ、**キャッシュが有り・見出しが1本以上あるものを
自治体ID順に先頭から** `--limit` 件とる。**結果を見てから選び直さない。**

    python3 analysis/probes/try_headings_prompt.py -p tennyu --limit 8
    python3 analysis/probes/try_headings_prompt.py -p tennyu -m adachi -m arakawa
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from htmlutil import parse  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

from extractor.fact_extract import build_input, call_claude  # noqa: E402
from extractor.response_contract import parse_json_reply  # noqa: E402
from measurement_cases import test_cases_for  # noqa: E402

VERSION = "try-headings-prompt-0.1"
BEFORE, AFTER = "flat", "markdown_headings"


def page_shape(page: dict, fetcher: PoliteFetcher) -> dict:
    """本文が実際に変わるか。**変わらないものを数に入れない**ための下見。"""
    cached = fetcher.cached(page["url"])
    if cached is None or not cached.body_path:
        return {"cached": False, "headings": 0, "added_chars": 0}
    normalized = parse(cached.body(), page["url"])
    return {
        "cached": True,
        "headings": len(normalized.headings),
        "added_chars": len(normalized.markdown) - len(normalized.text),
    }


def one_case(page: dict, muni: str, proc: str, case, fetcher: PoliteFetcher,
             model: str) -> dict:
    out = {"field": case.fact_type}
    for label, structure in (("before", BEFORE), ("after", AFTER)):
        try:
            prompt, _meta, _allowed = build_input(
                page, muni, proc, case, fetcher, body_structure=structure)
            data = parse_json_reply(call_claude(prompt, model))
        except Exception as exc:                           # noqa: BLE001
            out[label] = {"error": str(exc)[:160]}
            continue
        item = data.get("item") or {}
        out[label] = {
            "found": bool(item.get("found")),
            "failure_reason": item.get("failure_reason"),
            "value_head": (item.get("value") or "")[:80],
        }
    return out


def targets(procedure: str, chosen: list[str] | None, limit: int,
            fetcher: PoliteFetcher) -> list[tuple[str, dict, dict]]:
    """測る対象。★選び方を先に決める。結果を見てから選び直さない。"""
    paths = sorted((ROOT / "extractor" / "out").glob(f"extract_*_{procedure}.json"))
    out = []
    for path in paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        mid = doc["municipality_id"]
        if chosen and mid not in chosen:
            continue
        shape = page_shape(doc["page"], fetcher)
        if not chosen and not (shape["cached"] and shape["headings"]):
            continue
        out.append((mid, doc, shape))
        if not chosen and len(out) >= limit:
            break
    return out


def summarize(rows: list[dict]) -> dict:
    def count(label: str, key) -> int:
        return sum(1 for r in rows for c in r["cases"]
                   if isinstance(c.get(label), dict) and key(c[label]))

    changed = [
        {"municipality": r["municipality"], "field": c["field"],
         "before": c["before"].get("failure_reason") if not c["before"].get("found") else "取れた",
         "after": c["after"].get("failure_reason") if not c["after"].get("found") else "取れた"}
        for r in rows for c in r["cases"]
        if isinstance(c.get("before"), dict) and isinstance(c.get("after"), dict)
        and c["before"].get("found") != c["after"].get("found")
    ]
    return {
        "municipalities": len(rows),
        "cases": sum(len(r["cases"]) for r in rows),
        "before_found": count("before", lambda c: c.get("found")),
        "after_found": count("after", lambda c: c.get("found")),
        "before_said_absent": count("before", lambda c: c.get("failure_reason") == "記載なし"),
        "after_said_absent": count("after", lambda c: c.get("failure_reason") == "記載なし"),
        "flipped": changed,
        "errors": count("before", lambda c: c.get("error"))
        + count("after", lambda c: c.get("error")),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--municipality", "-m", action="append")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--model", default="claude-sonnet-5")
    args = ap.parse_args(argv)

    fetcher = PoliteFetcher(cache_dir=ROOT / "crawler" / "cache")
    rows = []
    for mid, doc, shape in targets(args.procedure, args.municipality, args.limit, fetcher):
        row = {"municipality": doc["municipality"], "municipality_id": mid,
               "page": doc["page"]["url"], **shape, "cases": []}
        print(f"{doc['municipality']}（見出し{shape['headings']}本 / +{shape['added_chars']}字）")
        for case in test_cases_for(args.procedure, doc["municipality"]):
            got = one_case(doc["page"], doc["municipality"], doc["procedure"],
                           case, fetcher, args.model)
            row["cases"].append(got)
            before, after = got.get("before", {}), got.get("after", {})
            print(f"  {got['field']:12} "
                  f"{before.get('found')} → {after.get('found')}   "
                  f"{before.get('failure_reason')} → {after.get('failure_reason')}")
        rows.append(row)

    doc = {
        "_about": "本文の渡し方だけを flat → markdown_headings に変えて比べた記録。"
                  "本番の抽出は動かしていない（BODY_STRUCTURE の既定は flat のまま）。"
                  "ここで取れた項目を「区が書いていた」と読み替えてはいけない。",
        "version": VERSION, "procedure": args.procedure, "model": args.model,
        "before": BEFORE, "after": AFTER,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"headings-prompt-ab_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['cases']}件（{s['municipalities']}自治体）")
    print(f"  取れた件数: {s['before_found']} → {s['after_found']}")
    print(f"  「記載なし」と答えた件数: {s['before_said_absent']} → {s['after_said_absent']}")
    print(f"  変わった件数: {len(s['flipped'])} / 失敗: {s['errors']}")


if __name__ == "__main__":
    main()

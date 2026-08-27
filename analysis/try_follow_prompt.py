"""プロンプトを変えたら、AIはリンクを開くようになるか（案A の A/B）。

**なぜ要るか**: `analysis/never_looked.py` が示したとおり、読み取り器は
**24自治体中14で、リンクを1本も開かずに「記載なし」と答えている**。
上限（`MAX_FOLLOW = 2`）には当たっていないので、上限の問題ではない。

原因はプロンプトにある。探す順序が「見つかった時点で止める」となっていて、
`記載なし`（5）が `リンク先にあり`（4）と同じ高さに置かれていた。AIは安い方を取る。

**測るもの**: 同じ入力に対して、**旧プロンプトと新プロンプトで
`follow_urls` が空でなくなるか**を比べる。

**本番の抽出は動かさない**（探索記録が `legacy_unknown` で再クロールが要るため）。
キャッシュ済みの本文から本番と同じ入力を組み立て、プロンプトだけ差し替えて比べる。

**言えること**: プロンプトを変えるとAIがリンクを開くようになるか
**言えないこと**: 開いた先で項目が取れるか（それは本測定の通し直しで見る）

    python3 analysis/try_follow_prompt.py -p jidouteate -m setagaya -m sumida
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from polite_fetch import PoliteFetcher  # noqa: E402

from extractor.fact_extract import PROMPT, build_input  # noqa: E402
from extractor.response_contract import parse_json_reply  # noqa: E402
from measurement_cases import test_cases_for  # noqa: E402

VERSION = "try-follow-prompt-0.1"

# 変更前のプロンプト。git から取り出す（手で写すと本物とずれる）。
BASE_REF = "HEAD"


def old_prompt() -> str:
    """変更前のプロンプト本文。★手で書き写さない。ずれたらA/Bが成立しない。"""
    rel = PROMPT.relative_to(ROOT)
    proc = subprocess.run(["git", "show", f"{BASE_REF}:{rel}"], cwd=ROOT,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"git から旧プロンプトを取れない: {proc.stderr[:200]}")
    return proc.stdout


def call(prompt: str, model: str) -> dict:
    proc = subprocess.run(["claude", "-p", "--model", model, "--output-format", "text"],
                          input=prompt, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed: {proc.stderr[:200]}")
    return parse_json_reply(proc.stdout)


def swap_prompt(full_input: str, old: str, new: str) -> str:
    """組み立て済みの入力から、先頭のプロンプト部分だけ差し替える。

    ★本文・リンク一覧・表はそのまま。**変えるのはプロンプトだけ**にしないと、
      何が効いたのか分からなくなる。
    """
    if not full_input.startswith(new):
        raise SystemExit("入力が新プロンプトで始まっていない。組み立てが変わった可能性")
    return old + full_input[len(new):]


def one_case(page: dict, muni: str, proc: str, case, fetcher: PoliteFetcher,
             old: str, new: str, model: str) -> dict:
    prompt_new, _meta, _allowed = build_input(page, muni, proc, case, fetcher)
    prompt_old = swap_prompt(prompt_new, old, new)
    out = {"field": case.fact_type}
    for label, text in (("before", prompt_old), ("after", prompt_new)):
        try:
            data = call(text, model)
        except Exception as exc:                          # noqa: BLE001
            out[label] = {"error": str(exc)[:160]}
            continue
        item = data.get("item") or {}
        out[label] = {
            "found": bool(item.get("found")),
            "failure_reason": item.get("failure_reason"),
            "follow_urls": list(data.get("follow_urls") or []),
        }
    return out


def summarize(rows: list[dict]) -> dict:
    def count(label: str, key) -> int:
        return sum(1 for r in rows for c in r["cases"]
                   if isinstance(c.get(label), dict) and key(c[label]))

    return {
        "municipalities": len(rows),
        "cases": sum(len(r["cases"]) for r in rows),
        "before_proposed_links": count("before", lambda c: c.get("follow_urls")),
        "after_proposed_links": count("after", lambda c: c.get("follow_urls")),
        "before_said_absent": count("before", lambda c: c.get("failure_reason") == "記載なし"),
        "after_said_absent": count("after", lambda c: c.get("failure_reason") == "記載なし"),
        "errors": count("before", lambda c: c.get("error"))
        + count("after", lambda c: c.get("error")),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="jidouteate")
    ap.add_argument("--municipality", "-m", action="append", required=True)
    ap.add_argument("--model", default="claude-sonnet-5")
    args = ap.parse_args(argv)

    new = PROMPT.read_text(encoding="utf-8")
    old = old_prompt()
    if old == new:
        raise SystemExit("旧プロンプトと新プロンプトが同じ。先に prompt.md を直すこと")

    fetcher = PoliteFetcher(cache_dir=ROOT / "crawler" / "cache")
    rows = []
    for mid in args.municipality:
        path = ROOT / "extractor" / "out" / f"extract_{mid}_{args.procedure}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        cases = test_cases_for(args.procedure, doc["municipality"])
        row = {"municipality": doc["municipality"], "municipality_id": mid, "cases": []}
        for case in cases:
            got = one_case(doc["page"], doc["municipality"], doc["procedure"],
                           case, fetcher, old, new, args.model)
            row["cases"].append(got)
            b, a = got.get("before", {}), got.get("after", {})
            print(f"  {doc['municipality']:6} {got['field']:12} "
                  f"リンク提案 {len(b.get('follow_urls') or [])} → {len(a.get('follow_urls') or [])}"
                  f"   {b.get('failure_reason')} → {a.get('failure_reason')}")
        rows.append(row)

    doc = {
        "_about": "プロンプトだけを差し替えて、AIがリンクを開こうとするかを比べた記録。"
                  "本番の抽出は動かしていない。開いた先で項目が取れるかは見ていない。",
        "version": VERSION, "procedure": args.procedure, "model": args.model,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"follow-prompt-ab_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['cases']}件（{s['municipalities']}自治体）")
    print(f"  リンクを提案した件数: {s['before_proposed_links']} → {s['after_proposed_links']}")
    print(f"  「記載なし」と答えた件数: {s['before_said_absent']} → {s['after_said_absent']}")
    print(f"  失敗: {s['errors']}")


if __name__ == "__main__":
    main()

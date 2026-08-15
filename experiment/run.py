"""1つのAI段差について、直す前と直した後を同じ条件で測る。

なぜ別のスクリプトにしたか:
  本測定（extractor/extract.py）は「実在するページを1回測る」ためのもの。
  実験に要るのは「手元のHTMLを、同じ条件で何回も測る」こと。
  そこだけが違うので、**プロンプトと組み立てとモデルは extract.py から借りる。**
  ここで別のプロンプトを書いたら、本測定の点数と比べられなくなる。

なぜ回数を分けて測るか:
  これまでの測定は各1回で、ぶれ幅を測っていなかった（METHOD.md §4-4）。
  「5回中2回 → 5回中5回」の形にしないと、直ったのかブレたのか区別できない。

なぜ反実仮想（counterfactual）を測るか:
  AIが正しく答えても、**ページを読んだのか、学習で知っていたのか**が分からない。
  期限を 14日 → 37日 に変えたページで 37日 が返るなら、読んでいる可能性が高い。
  現実にはありえない値を返してきた、という一点だけが根拠になる。

前回この実験をやったとき、入力HTMLを一時ディレクトリに置いて消えた
（open-questions #7）。**今回は pages/ に置いてコミットする。**
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT / "extractor"))

from htmlutil import parse  # noqa: E402
from extract import (  # noqa: E402
    FIELDS, MAX_LINKS, MAX_TEXT_CHARS, PROMPT,
    normalize_items, parse_json_reply,
)

# 測り方の版。プロンプトや組み立てを変えたら上げる。
# これが無いと、あとから見て「どの版で測った数字か」が分からなくなる。
MEASUREMENT_VERSION = "exp-0.1"
MODEL = "claude-sonnet-5"


def build_prompt(html: str, url: str, muni: str, proc: str) -> tuple[str, dict]:
    """extract.py の build_input と同じ形に組み立てる。

    違いはHTMLの出どころだけ（キャッシュ ではなく 手元のファイル）。
    """
    links, text, jsonld = parse(html, url)
    truncated = len(text) > MAX_TEXT_CHARS

    link_lines, seen = [], set()
    for ln in links:
        if not ln.text or ln.href in seen:
            continue
        seen.add(ln.href)
        link_lines.append(f"- {ln.text} → {ln.href}")
        if len(link_lines) >= MAX_LINKS:
            break

    parts = [
        PROMPT.read_text(encoding="utf-8"),
        "\n---\n",
        f"## 対象\n\n- 自治体: {muni}\n- 手続き: {proc}\n- ページURL: {url}\n",
        f"\n## 構造化データ (JSON-LD)\n\n{'（なし）' if not jsonld else chr(10).join(jsonld)[:2000]}\n",
        f"\n## ページ本文{'（長いため冒頭のみ）' if truncated else ''}\n\n{text[:MAX_TEXT_CHARS]}\n",
        f"\n## このページから出ているリンク（最大{MAX_LINKS}件）\n\n" + ("\n".join(link_lines) or "（なし）"),
    ]
    meta = {"text_len": len(text), "truncated": truncated,
            "n_links": len(link_lines), "has_jsonld": bool(jsonld)}
    return "".join(parts), meta


def call_claude(prompt: str, model: str, timeout: int = 300) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {proc.stderr[:500]}")
    return proc.stdout


def run_trial(prompt: str, model: str) -> dict:
    """1回ぶん。失敗しても止めない（何回目が落ちたかを残す）。"""
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        return {"ok": True, "started_at": started,
                "items": normalize_items(parse_json_reply(call_claude(prompt, model)))}
    except Exception as e:  # noqa: BLE001 — 落ちた事実ごと記録したい
        return {"ok": False, "started_at": started, "error": f"{type(e).__name__}: {e}"[:300]}


def check(items: dict, truth: dict) -> dict:
    """Ground Truth と突き合わせる。

    found だけでは足りない。**値が合っているか**まで見る。
    反実仮想では「37日」が返ることが期待値になるので、
    期待文字列は Ground Truth 側（variant ごと）に持たせてある。
    """
    out = {}
    for f in FIELDS:
        got = items.get(f) or {}
        exp = (truth.get(f) or {})
        must = exp.get("must_include") or []
        value = got.get("value") or ""
        out[f] = {
            "found": bool(got.get("found")),
            "value": value[:200],
            # 期待する語がすべて値に入っているか。空なら found だけで判定
            "matches_truth": bool(got.get("found")) and all(m in value for m in must),
            "must_include": must,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="setagaya-tennyu", help="experiment/cases/ の下の名前")
    ap.add_argument("--variant", action="append",
                    help="測る版（省略時は case.json の全部）")
    ap.add_argument("--trials", "-n", type=int, default=5)
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args()

    case_dir = HERE / "cases" / args.case
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    variants = args.variant or [v["id"] for v in case["variants"]]

    OUT = HERE / "out"
    OUT.mkdir(exist_ok=True)
    results = []

    for vid in variants:
        v = next(x for x in case["variants"] if x["id"] == vid)
        html = (case_dir / v["file"]).read_text(encoding="utf-8")
        prompt, meta = build_prompt(html, case["page_url"], case["municipality"], case["procedure"])
        truth = {**case["ground_truth"], **(v.get("ground_truth_override") or {})}

        print(f"[{vid}] {v['label']} — {args.trials}回", flush=True)
        trials = []
        for i in range(args.trials):
            t = run_trial(prompt, args.model)
            if t["ok"]:
                t["check"] = check(t["items"], truth)
                n = sum(1 for f in FIELDS if t["check"][f]["matches_truth"])
                print(f"    {i + 1}回目: {n}/4 一致", flush=True)
            else:
                print(f"    {i + 1}回目: 失敗 {t['error'][:60]}", flush=True)
            trials.append(t)

        ok = [t for t in trials if t["ok"]]
        per_field = {f: sum(1 for t in ok if t["check"][f]["matches_truth"]) for f in FIELDS}
        results.append({
            "variant": vid, "label": v["label"], "intervention": v.get("intervention"),
            "page_meta": meta, "trials": trials,
            "summary": {"trials": args.trials, "succeeded_runs": len(ok),
                        "per_field_matches": per_field,
                        "all_four": sum(1 for t in ok if all(t["check"][f]["matches_truth"] for f in FIELDS))},
        })
        s = results[-1]["summary"]
        print(f"    → 4項目そろった回: {s['all_four']}/{args.trials}   項目別 {per_field}\n", flush=True)

    doc = {
        "case": args.case,
        "measurement_version": MEASUREMENT_VERSION,
        "model": args.model,
        "trials_per_variant": args.trials,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "page_url": case["page_url"],
        "site_version": case.get("site_version"),
        "ground_truth_source": case.get("ground_truth_source"),
        "results": results,
    }
    out = OUT / f"{args.case}_{doc['run_at'][:10]}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()

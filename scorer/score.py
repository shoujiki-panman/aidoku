"""採点層 (Layer A) — 抽出結果を人手ゴールデンセットと突合し、ルーブリックで採点する。

ネットワークには触らない。入力は extractor/out と golden/*.csv だけ。

ルーブリック（CLAUDE.md §3、Phase 1 の暫定版）:
  情報到達      20点  トップページから到達できたか
  抽出正確性    40点  4項目 × 各10点（正解10 / 部分正解5 / 不正解0）
  機械可読性    20点  HTML本文で取れた10 + 構造化データあり10
  オンライン明示 20点  窓口/オンライン可否が一意に読み取れるか

判定は LLM（`claude -p`）で行うが、これは採点器そのものなので、
判定結果は必ず人手で見直せるよう reports に全件出す。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXTRACT_DIR = ROOT / "extractor" / "out"
GOLDEN_DIR = Path(__file__).parent / "golden"
OUT_DIR = Path(__file__).parent / "out"
JUDGE_PROMPT = Path(__file__).parent / "judge_prompt.md"

FIELDS = ["必要書類", "窓口オンライン可否", "期限", "手数料"]

VERDICT_POINTS = {
    "正解": 10,
    "正解(記載なしが正しい)": 10,
    "部分正解": 5,
    "不正解": 0,
    "不正解(幻覚)": 0,
}


@dataclass
class GoldenRow:
    municipality_id: str
    procedure_id: str
    field: str
    expected_found: bool
    expected_value: str
    note: str
    source_url: str


def load_golden(procedure_id: str) -> dict[tuple[str, str], GoldenRow]:
    path = GOLDEN_DIR / f"{procedure_id}.csv"
    if not path.exists():
        raise SystemExit(f"ゴールデンセットがない: {path}")
    rows: dict[tuple[str, str], GoldenRow] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("municipality_id") or r["municipality_id"].startswith("#"):
                continue
            g = GoldenRow(
                municipality_id=r["municipality_id"].strip(),
                procedure_id=r["procedure_id"].strip(),
                field=r["field"].strip(),
                expected_found=r["expected_found"].strip().lower() in ("true", "1", "yes", "y"),
                expected_value=r["expected_value"].strip(),
                note=r.get("note", "").strip(),
                source_url=r.get("source_url", "").strip(),
            )
            rows[(g.municipality_id, g.field)] = g
    return rows


def judge(golden: GoldenRow, item: dict, muni: str, proc: str, model: str) -> dict:
    """ゴールデンとの突合を1件ぶん判定する。明らかな場合はLLMを呼ばない。"""
    if not golden.expected_found and not item["found"]:
        return {"verdict": "正解(記載なしが正しい)", "reason": "正解側も記載なしで、正直に見つからないと報告した",
                "judged_by": "rule"}
    if not golden.expected_found and item["found"]:
        return {"verdict": "不正解(幻覚)", "reason": "サイトに記載がないのに値を答えた", "judged_by": "rule"}
    if golden.expected_found and not item["found"]:
        return {"verdict": "不正解", "reason": f"サイトには記載があるのに見つけられなかった（{item['failure_reason']}）",
                "judged_by": "rule"}

    prompt = "\n".join([
        JUDGE_PROMPT.read_text(encoding="utf-8"),
        "\n---\n",
        f"## 対象\n\n- 自治体: {muni}\n- 手続き: {proc}\n- 項目: {golden.field}\n",
        f"\n## 正解（人手）\n\n{golden.expected_value}",
        f"\n（補足: {golden.note}）" if golden.note else "",
        f"\n\n## エージェントの答え\n\n{item['value']}",
        f"\n\n## エージェントが挙げた根拠\n\n{item['evidence'] or '（なし）'}",
    ])
    proc_res = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=300,
    )
    if proc_res.returncode != 0:
        raise RuntimeError(f"claude -p failed: {proc_res.stderr[:300]}")
    text = proc_res.stdout.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    s, e = text.find("{"), text.rfind("}")
    data = json.loads(text[s:e + 1])
    data["judged_by"] = model
    return data


def score_one(ext: dict, golden: dict[tuple[str, str], GoldenRow], model: str) -> dict:
    mid = ext["municipality_id"]
    reached = ext.get("reached", False)
    page = ext.get("page") or {}

    results = []
    accuracy = 0
    online_verdict = None
    for field in FIELDS:
        g = golden.get((mid, field))
        if g is None:
            results.append({"field": field, "verdict": "未採点", "reason": "ゴールデンセットに行がない",
                            "points": 0, "judged_by": "rule"})
            continue
        item = ext["items"].get(field) or {"found": False, "value": "", "evidence": "",
                                           "failure_reason": "到達失敗", "source": None}
        v = judge(g, item, ext["municipality"], ext["procedure"], model) if reached else {
            "verdict": "不正解", "reason": "ページに到達できなかった", "judged_by": "rule"}
        pts = VERDICT_POINTS.get(v["verdict"], 0)
        accuracy += pts
        if field == "窓口オンライン可否":
            online_verdict = v["verdict"]
        results.append({
            "field": field, "verdict": v["verdict"], "reason": v.get("reason", ""),
            "points": pts, "judged_by": v.get("judged_by", ""),
            "expected_found": g.expected_found, "expected_value": g.expected_value,
            "agent_found": item["found"], "agent_value": item["value"],
            "failure_reason": item.get("failure_reason"),
        })

    reach_pts = 20 if reached else 0
    machine_pts = (10 if reached and not page.get("is_pdf") else 0) + (10 if page.get("has_jsonld") else 0)
    online_pts = {"正解": 20, "正解(記載なしが正しい)": 20, "部分正解": 10}.get(online_verdict or "", 0)
    total = reach_pts + accuracy + machine_pts + online_pts

    return {
        "municipality": ext["municipality"], "municipality_id": mid,
        "procedure": ext["procedure"], "procedure_id": ext["procedure_id"],
        "page_url": page.get("url"), "hops": page.get("hops"),
        "followed_urls": ext.get("followed_urls", []),
        "breakdown": {"情報到達": reach_pts, "抽出正確性": accuracy,
                      "機械可読性": machine_pts, "オンライン明示": online_pts},
        "total": total,
        "fields": results,
        "page_notes": ext.get("page_notes", ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--municipality", "-m", action="append")
    ap.add_argument("--model", default="claude-sonnet-5")
    args = ap.parse_args()

    golden = load_golden(args.procedure)
    files = sorted(EXTRACT_DIR.glob(f"extract_*_{args.procedure}.json"))
    if args.municipality:
        files = [f for f in files if any(f"extract_{m}_" in f.name for m in args.municipality)]
    if not files:
        raise SystemExit("抽出結果がない。先に extractor/extract.py を実行すること")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in files:
        ext = json.loads(f.read_text(encoding="utf-8"))
        res = score_one(ext, golden, args.model)
        out = OUT_DIR / f"score_{res['municipality_id']}_{res['procedure_id']}.json"
        out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        b = res["breakdown"]
        print(f"[{res['municipality']}] {res['total']:>3}点 "
              f"(到達{b['情報到達']} 正確{b['抽出正確性']} 可読{b['機械可読性']} オンライン{b['オンライン明示']})")


if __name__ == "__main__":
    main()

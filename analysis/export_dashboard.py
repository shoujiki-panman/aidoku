"""ダッシュボード用 web/data/scores.json を extractor/out から作る。

23区分の scores.json は 2026-07-30 に生成されたが、生成スクリプトがコミットされて
いなかった（commit 612c1d9 は JSON だけを含む）。そのため1区を測り直すだけでも
手で JSON を書き換えるしかなくなっていた。このスクリプトはその欠けを埋める。

`scorer/` は通らない。scorer は人手のゴールデンセットと突き合わせる別方式で、
正解データがあるのは3自治体だけ。ダッシュボードが出しているのは
「抽出できた項目 × 20点 ＋ オンライン明示」であり、その式をここに置く。

出力: web/data/scores.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXTRACT_DIR = ROOT / "extractor" / "out"
TARGETS = ROOT / "crawler" / "targets.json"
OUT = ROOT / "web" / "data" / "scores.json"

# extractor 側のキー名 → 画面に出す項目名
FIELD_KEYS = [
    ("必要書類", "必要書類"),
    ("窓口オンライン可否", "窓口/オンライン可否"),
    ("期限", "期限"),
    ("手数料", "手数料"),
]
ITEM_POINTS = 20
CLARITY_POINTS = {"明記": 20, "曖昧": 10, "記載なし": 0}
# 画面に出す「AIが読み取った実際の文」の上限。既存の scores.json もこの長さで切れている。
MAX_VALUE_CHARS = 200

# 「ここを直すと、AIの答えが変わる」に出す処方箋。項目ごとに固定。
FIX_TEXT = {
    "必要書類": "必要な持ち物を、条件つきで箇条書きにする（本人確認書類・転出証明書など）",
    "窓口/オンライン可否": "窓口のみか、オンラインで完結できるかを、はっきり書く",
    "期限": "「住み始めた日から14日以内」のように、起算点つきで書く",
    "手数料": "手数料の額を書く。無料なら「無料」と書く",
    "オンライン明示": "オンラインで完結できるか否かを、はっきり書く",
}

DISCLAIMER = (
    "AIが自治体の公式サイトを読み取れたかの実測（2026-07-22）。"
    "自治体を評価するものではなく、どこを直せば伝わるかを示すためのもの。"
    "行政機関の公式発表ではありません。"
)


def build_fields(items: dict) -> tuple[list[dict], dict, list[dict]]:
    """4項目の内訳・配点・処方箋を作る。"""
    fields, breakdown, fixes = [], {}, []
    for src_key, label in FIELD_KEYS:
        item = items.get(src_key) or {}
        found = bool(item.get("found"))
        fields.append({
            "field": label,
            "verdict": "読めた" if found else "読めない",
            "points": ITEM_POINTS if found else 0,
            "agent_value": (item.get("value") or "")[:MAX_VALUE_CHARS],
        })
        breakdown[label] = ITEM_POINTS if found else 0
        if not found:
            fixes.append({"field": label, "gain": ITEM_POINTS, "reason": FIX_TEXT[label]})
    return fields, breakdown, fixes


def build_entry(data: dict) -> dict:
    """extractor の1ファイルから、ダッシュボード1件分を作る。"""
    fields, breakdown, fixes = build_fields(data.get("items") or {})
    clarity = data.get("online_clarity")
    clarity_pt = CLARITY_POINTS.get(clarity, 0)
    breakdown["オンライン明示"] = clarity_pt
    if clarity_pt < ITEM_POINTS:
        fixes.append({
            "field": "オンライン明示",
            "gain": ITEM_POINTS - clarity_pt,
            "reason": FIX_TEXT["オンライン明示"],
        })
    page = data.get("page") or {}
    return {
        "id": data["municipality_id"],
        "name": data["municipality"],
        "total": sum(breakdown.values()),
        "breakdown": breakdown,
        "hops": page.get("hops"),
        "page_url": page.get("url"),
        "followed": data.get("followed_urls") or [],
        "fields": fields,
        "improvements": fixes,
        "notes": data.get("page_notes") or "",
    }


def summarize(entries: list[dict]) -> dict:
    totals = [e["total"] for e in entries]
    return {
        "average": round(sum(totals) / len(totals), 1),
        "max": max(totals),
        "min": min(totals),
        "full_marks": sum(1 for e in entries
                          if all(e["breakdown"][label] == ITEM_POINTS for _, label in FIELD_KEYS)),
        "zero": sum(1 for t in totals if t == 0),
        "fee_missing": sum(1 for e in entries if e["breakdown"]["手数料"] == 0),
    }


def collect(procedure: str, only: set[str] | None) -> list[dict]:
    entries = []
    for path in sorted(EXTRACT_DIR.glob(f"extract_*_{procedure}.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if only is not None and data["municipality_id"] not in only:
            continue
        entries.append(build_entry(data))
    # 点の高い順。同点は自治体IDの辞書順で固定する（実行ごとに並びが変わらないように）
    entries.sort(key=lambda e: (-e["total"], e["id"]))
    return entries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--phase", default="23区")
    ap.add_argument("--exclude", action="append", default=["hachioji"],
                    help="出力に含めない自治体ID（既定: 八王子市。23区の集計に混ぜないため）")
    ap.add_argument("--generated-at", default=None,
                    help="生成時刻を固定したいとき（既存ファイルの再現確認用）")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    proc = next(p for p in targets["procedures"] if p["id"] == args.procedure)
    keep = {m["id"] for m in targets["municipalities"]} - set(args.exclude)

    entries = collect(args.procedure, keep)
    if not entries:
        raise SystemExit(f"extractor/out に {args.procedure} の結果がありません")

    doc = {
        "generated_at": args.generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "procedure": proc["name"],
        "procedure_id": proc["id"],
        # 画面に出す「住民の質問」。手続きごとに違うので targets.json に持たせてある。
        # 画面側で文を組み立てると、手続きを増やすたびに JS を直すことになる。
        "question": proc.get("question", "{muni}について教えて。"),
        "phase": args.phase,
        "n_municipalities": len(entries),
        "summary": summarize(entries),
        "municipalities": entries,
        "disclaimer": DISCLAIMER,
    }
    Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"{args.out}（{len(entries)}件）"
          f" 平均{s['average']} 満点{s['full_marks']} 0点{s['zero']} 手数料0点{s['fee_missing']}")


if __name__ == "__main__":
    main()

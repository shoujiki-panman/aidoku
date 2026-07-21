"""採点結果を web/ が読む1本のJSONにまとめる。

ダッシュボードは静的ホスティング（Cloudflare Pages）前提なので、
ここで作った web/data/scores.json をそのまま配信する。
集計ロジックはここに置き、web/ 側では計算しない（数字の出所を1か所にするため）。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCORE_DIR = ROOT / "scorer" / "out"
OUT = ROOT / "web" / "data" / "scores.json"

# 失敗理由のうち、「サイトで完結せず人手に送客されている」もの
PHONE_REASONS = {"電話でのみ確認可"}


def build(procedure: str, run_date: str) -> dict:
    files = sorted(SCORE_DIR.glob(f"score_*_{procedure}.json"))
    if not files:
        raise SystemExit("採点結果がない。先に scorer/score.py を実行すること")
    scores = [json.loads(f.read_text(encoding="utf-8")) for f in files]

    reasons: Counter = Counter()
    n_items = 0
    n_phone = 0
    for s in scores:
        for f in s["fields"]:
            n_items += 1
            r = f.get("failure_reason")
            if r:
                reasons[r] += 1
                if r in PHONE_REASONS:
                    n_phone += 1

    municipalities = []
    for s in sorted(scores, key=lambda x: -x["total"]):
        # 改善箇所は2種類ある。項目ごとの取りこぼしと、配点そのものの取りこぼし（構造化データ等）。
        # 後者を落とすと「4項目すべて満点」なのに満点でない、という表示になるので両方を集める。
        # points が要素比になったので gain は float。0.1 の誤差が出ないよう丸める。
        # missing には欠落した必須要素のスロット名が入るので、「どこを直せば何点」が
        # 自由文の reason ではなく構造化データで取れる。
        weak = [
            {"field": f["field"], "verdict": f["verdict"],
             "reason": f.get("failure_reason") or f["reason"],
             "missing": f.get("missing", []),
             "gain": round(10 - f["points"], 1)}
            for f in s["fields"] if f["points"] < 10
        ]
        machine = s.get("machine") or {}
        if not machine.get("jsonld", False):
            weak.append({"field": "機械可読性", "verdict": "-", "gain": 10,
                         "reason": "手続きページに構造化データ（JSON-LD）がない。"
                                   "自治体標準オープンデータセットの項目をページに埋めるとAIが確実に読める"})
        if machine.get("html") is False:
            weak.append({"field": "機械可読性", "verdict": "-", "gain": 10,
                         "reason": "手続きの内容がHTML本文になく、PDFを開かないと分からない"})
        if s["breakdown"]["情報到達"] < 20:
            weak.append({"field": "情報到達", "verdict": "-", "gain": 20,
                         "reason": "トップページからリンクを辿って手続きページに到達できなかった"})
        municipalities.append({
            "id": s["municipality_id"],
            "name": s["municipality"],
            "total": s["total"],
            "breakdown": s["breakdown"],
            "hops": s.get("hops"),
            "page_url": s.get("page_url"),
            "followed": len(s.get("followed_urls") or []),
            "fields": [
                {"field": f["field"], "verdict": f["verdict"], "points": f["points"],
                 "agent_value": f.get("agent_value", ""), "expected_value": f.get("expected_value", ""),
                 "failure_reason": f.get("failure_reason"), "reason": f.get("reason", "")}
                for f in s["fields"]
            ],
            "improvements": sorted(weak, key=lambda w: -w["gain"]),
            "notes": s.get("page_notes", ""),
        })

    return {
        "generated_at": run_date,
        "procedure": scores[0]["procedure"],
        "procedure_id": procedure,
        "phase": "Phase 1（パイロット3自治体）",
        "n_municipalities": len(scores),
        "summary": {
            "average": round(sum(s["total"] for s in scores) / len(scores), 1),
            "max_score": 100,
            "n_items": n_items,
            "phone_referral_rate": round(n_phone / n_items * 100, 1) if n_items else 0.0,
            "failure_reasons": [{"reason": r, "count": n} for r, n in reasons.most_common()],
        },
        "municipalities": municipalities,
        "disclaimer": "本調査は個人による第三者調査であり、行政機関の公式発表ではない。"
                      "正解データは各ページを人手で読んで作った暫定版。",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()

    data = build(args.procedure, args.date)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {OUT}（{data['n_municipalities']}自治体・平均{data['summary']['average']}点）")


if __name__ == "__main__":
    main()

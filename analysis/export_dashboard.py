"""ダッシュボード用 web/data/scores.json を extractor/out から作る。

23区分の scores.json は 2026-07-30 に生成されたが、生成スクリプトがコミットされて
いなかった（commit 612c1d9 は JSON だけを含む）。そのため1区を測り直すだけでも
手で JSON を書き換えるしかなくなっていた。このスクリプトはその欠けを埋める。

回答内容は extractor の実測を使い、点数は scorer が保存した4判定Evaluatorを使う。
Evaluatorが無い旧結果やGround Truth未整備の結果は、`found=true`でも点にせず
「未検証」として出す。

出力: web/data/scores.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXTRACT_DIR = ROOT / "extractor" / "out"
SCORE_DIR = ROOT / "scorer" / "out"
TARGETS = ROOT / "crawler" / "targets.json"
OUT = ROOT / "web" / "data" / "scores.json"

sys.path.insert(0, str(ROOT))
from fact_types import EXTRACTOR_TO_DISPLAY, FIX_TEXT  # noqa: E402
from evaluator import CHECK_NAMES, evaluation_from_item  # noqa: E402
from measurement import (  # noqa: E402
    MeasurementError,
    normalize_measurement,
    summarize_measurements,
)

# extractor 側のキー名 → 画面に出す項目名。
# 対応表の出どころは fact_types.json ただ1つ。ここに直書きしない。
FIELD_KEYS = list(EXTRACTOR_TO_DISPLAY.items())
ITEM_POINTS = 20
CLARITY_POINTS = {"明記": 20, "曖昧": 10, "記載なし": 0}
# 画面に出す「AIが読み取った実際の文」の上限。既存の scores.json もこの長さで切れている。
MAX_VALUE_CHARS = 200

# 「ここを直すと、AIの答えが変わる」に出す処方箋は fact_types.json の fix_hint。
# （import は上でまとめて済ませてある）

DISCLAIMER = (
    "AIが自治体の公式サイトから回答できたかの実測（2026-07-21〜2026-08-11）。"
    "自治体を評価するものではなく、どこを直せば伝わるかを示すためのもの。"
    "行政機関の公式発表ではありません。"
)

# ライセンスは「こちらが作ったもの」にだけかかる。点数・集計・処方箋がそれ。
# agent_value（自治体サイトから抜き出した実際の文）は自治体のものなので、
# こちらのライセンスで再配布を許可することはできない。**そこを混ぜない。**
LICENSE = {
    "name": "CC BY 4.0",
    "url": "https://creativecommons.org/licenses/by/4.0/deed.ja",
    "applies_to": "点数・集計・改善案など、この調査が作り出した部分",
    "attribution": "正直パンマン「AI読（アイドク）」 https://github.com/shoujiki-panman/aidoku",
    "not_covered": (
        "fields[].agent_value は各自治体の公式サイトから抜き出した実際の文で、"
        "著作権は各自治体にあります。判定の根拠を示すための引用であり、"
        "出典は各レコードの page_url です。"
        "再利用の可否は各自治体の利用規約に従ってください。"
    ),
}

# 使わせてもらっているもの。**実際に使ったものだけ書く。**
SOURCES = [
    {
        "name": "各自治体の公式サイト（手続きページ）",
        "used_for": "回答観測と検証の対象。抜き出した文は fields[].agent_value、出典は page_url",
        "license": "各自治体の利用規約による（個別には確認していない）",
    },
    {
        "name": "デジタル庁デザインシステム",
        "url": "https://design.digital.go.jp/",
        "used_for": "公開画面のスタイル（コードスニペット）",
        "license": "MIT",
    },
    {
        "name": "総務省「都道府県コード及び市区町村コード」",
        "url": "https://www.soumu.go.jp/denshijiti/code.html",
        "used_for": "municipalities[].lg_code（全国地方公共団体コード）",
        "license": "総務省サイトの利用規約による",
    },
]


def field_evaluations(municipality_id: str, procedure_id: str) -> dict[str, dict]:
    """scorer出力からfact_type別Evaluator結果を読む。旧形式は未検証にする。"""
    path = SCORE_DIR / f"score_{municipality_id}_{procedure_id}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"scorer出力rootがobjectでない: {path}")
    if data.get("municipality_id") != municipality_id:
        raise ValueError(f"scorer出力のmunicipality_idが不一致: {path}")
    if data.get("procedure_id") != procedure_id:
        raise ValueError(f"scorer出力のprocedure_idが不一致: {path}")
    records = data.get("fields")
    if not isinstance(records, list):
        raise ValueError(f"scorer出力fieldsが配列でない: {path}")
    evaluations = {}
    seen = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"scorer出力fields[{index}]がobjectでない: {path}")
        key = record.get("field")
        if key not in EXTRACTOR_TO_DISPLAY:
            raise ValueError(f"scorer出力のfieldが未定義: {key!r}")
        if key in seen:
            raise ValueError(f"scorer出力のfieldが重複: {key}")
        seen.add(key)
        if "evaluation" in record:
            evaluations[key] = record["evaluation"]
    return evaluations


def item_evaluation(item: dict, recorded: object = None) -> dict:
    """scorerの記録を優先し、無ければitem内の記録か未検証を返す。"""
    candidate = dict(item)
    if recorded is not None:
        candidate["evaluation"] = recorded
    return evaluation_from_item(candidate)


def public_evaluation(evaluation: dict) -> dict:
    """公開JSONには4状態だけを出し、詳しい理由はscorer出力に残す。"""
    return {
        "evaluator_version": evaluation["evaluator_version"],
        "overall": evaluation["overall"],
        "checks": {
            name: evaluation["checks"][name]["status"]
            for name in CHECK_NAMES
        },
    }


def build_fields(items: dict, evaluations: dict[str, dict] | None = None
                 ) -> tuple[list[dict], dict, list[dict]]:
    """4項目の回答観測・Evaluator配点・処方箋を作る。"""
    if not isinstance(items, dict):
        raise ValueError("itemsがobjectでない")
    if evaluations is None:
        evaluations = {}
    if not isinstance(evaluations, dict):
        raise ValueError("evaluationsがobjectでない")
    fields, breakdown, fixes = [], {}, []
    for src_key, label in FIELD_KEYS:
        item = items.get(src_key) or {
            "found": False,
            "value": "",
            "evidence": "",
            "failure_reason": "抽出エラー",
        }
        if not isinstance(item, dict):
            raise ValueError(f"items.{src_key}がobjectでない")
        found = item.get("found")
        if type(found) is not bool:
            raise ValueError(f"items.{src_key}.foundがbooleanでない")
        evaluation = item_evaluation(item, evaluations.get(src_key))
        points = evaluation["points"]
        fields.append({
            "field": label,
            "verdict": "読めた" if found else "読めない",
            "answered": found,
            "points": points,
            "evaluation_status": evaluation["overall"],
            "evaluation": public_evaluation(evaluation),
            "agent_value": (item.get("value") or "")[:MAX_VALUE_CHARS],
        })
        breakdown[label] = points
        if not found:
            fixes.append({
                "field": label,
                "gain": ITEM_POINTS if points == 0 else None,
                "reason": FIX_TEXT[label],
            })
    return fields, breakdown, fixes


def build_entry(data: dict) -> dict:
    """extractor の1ファイルから、ダッシュボード1件分を作る。"""
    evaluations = field_evaluations(data["municipality_id"], data["procedure_id"])
    fields, breakdown, fixes = build_fields(data.get("items") or {}, evaluations)
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
    measurement = normalize_measurement(data.get("measurement"), data.get("model"))
    fact_points = [breakdown[label] for _, label in FIELD_KEYS]
    total = None if any(points is None for points in fact_points) else sum(
        points for points in breakdown.values() if points is not None)
    answered_count = sum(field["answered"] for field in fields)
    return {
        "id": data["municipality_id"],
        "name": data["municipality"],
        "total": total,
        "breakdown": breakdown,
        "answered_count": answered_count,
        "evaluation_status": "evaluated" if total is not None else "not_checked",
        "hops": page.get("hops"),
        "page_url": page.get("url"),
        "followed": data.get("followed_urls") or [],
        "measurement": measurement,
        "fields": fields,
        "improvements": fixes,
        "notes": data.get("page_notes") or "",
    }


def summarize(entries: list[dict]) -> dict:
    totals = [entry["total"] for entry in entries if entry["total"] is not None]
    return {
        "average": round(sum(totals) / len(totals), 1) if totals else None,
        "max": max(totals) if totals else None,
        "min": min(totals) if totals else None,
        "full_marks": sum(1 for e in entries
                          if all(e["breakdown"][label] == ITEM_POINTS for _, label in FIELD_KEYS)),
        "zero": sum(1 for t in totals if t == 0),
        "fee_missing": sum(
            1 for entry in entries
            if not next(field for field in entry["fields"]
                        if field["field"] == "手数料")["answered"]
        ),
        "answered_all_four": sum(
            entry["answered_count"] == len(FIELD_KEYS) for entry in entries),
        "answered_zero": sum(entry["answered_count"] == 0 for entry in entries),
        "evaluated": len(totals),
        "not_evaluated": len(entries) - len(totals),
    }


def prepare_public_entries(entries: list[dict]) -> tuple[list[dict], dict]:
    """共通条件を1か所へまとめ、自治体ごとの実行時刻だけ対応づける。"""
    measurement = summarize_measurements([entry["measurement"] for entry in entries])
    runs = []
    public_entries = []
    for entry in entries:
        record = entry["measurement"]
        runs.append({
            "municipality_id": entry["id"],
            "recording_status": record["recording_status"],
            "model": record["model"],
            "model_version": record["model_version"],
            "run_at": record["run_at"],
            "discovery_run_at": record["discovery_run_at"],
        })
        public_entries.append({key: value for key, value in entry.items()
                               if key != "measurement"})
    measurement["runs"] = runs
    return public_entries, measurement


def display_question(procedure: dict) -> str:
    """測定用Test Caseと分離した、公開画面用の従来質問を返す。"""
    value = procedure.get("display_question")
    return value if isinstance(value, str) and value.strip() else "{muni}について教えて。"


def collect(procedure: str, only: set[str] | None, codes: dict[str, str]) -> list[dict]:
    entries = []
    for path in sorted(EXTRACT_DIR.glob(f"extract_*_{procedure}.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        mid = data["municipality_id"]
        if only is not None and mid not in only:
            continue
        entry = build_entry(data)
        # 全国地方公共団体コード。他のデータと突き合わせる鍵。
        # 自治体名は表記ゆれがあるので、名前ではなくこれで繋ぐ。
        # 未設定の自治体は落とさず null で残す（欠けていることが見えるように）。
        entry["lg_code"] = codes.get(mid)
        entries.append(entry)
    # 回答できた項目数の多い順。未検証を0点として並べない。
    entries.sort(key=lambda e: (-e["answered_count"], e["id"]))
    return entries


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--phase", default="23区")
    ap.add_argument("--exclude", action="append", default=["hachioji"],
                    help="出力に含めない自治体ID（既定: 八王子市。23区の集計に混ぜないため）")
    ap.add_argument("--generated-at", default=None,
                    help="生成時刻を固定したいとき（既存ファイルの再現確認用）")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    proc = next(p for p in targets["procedures"] if p["id"] == args.procedure)
    keep = {m["id"] for m in targets["municipalities"]} - set(args.exclude)

    codes = {m["id"]: m["lg_code"] for m in targets["municipalities"] if m.get("lg_code")}
    entries = collect(args.procedure, keep, codes)
    if not entries:
        raise SystemExit(f"extractor/out に {args.procedure} の結果がありません")
    try:
        entries, measurement = prepare_public_entries(entries)
    except MeasurementError as error:
        ap.error(str(error))

    doc = {
        "generated_at": args.generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "procedure": proc["name"],
        "procedure_id": proc["id"],
        # 画面に出す「住民の質問」。手続きごとに違うので targets.json に持たせてある。
        # 画面側で文を組み立てると、手続きを増やすたびに JS を直すことになる。
        "question": display_question(proc),
        "phase": args.phase,
        "n_municipalities": len(entries),
        "measurement": measurement,
        "summary": summarize(entries),
        "municipalities": entries,
        "disclaimer": DISCLAIMER,
        "license": LICENSE,
        "sources": SOURCES,
    }
    Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"{args.out}（{len(entries)}件）"
          f" 検証済み{s['evaluated']} 未検証{s['not_evaluated']}"
          f" 4項目回答{s['answered_all_four']} 手数料回答なし{s['fee_missing']}")


if __name__ == "__main__":
    main()

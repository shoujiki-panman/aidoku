"""測った結果を、1行1観測のCSVにする（web/data/history/measurements.csv）。

いままで時系列は JSONL のスナップショット（1行に23区ぶんが入れ子）でしか
持っていなかった。表計算でも統計ソフトでも、そのままでは使えない。

**1行1観測（tidy long format）にする。** 1行は
「いつ・どの自治体の・どの手続きの・どの項目が・何点だったか」だけを持つ。

書き方は、機械判読できるCSVの決まりに合わせる:

  - 1セル1データ。セルの結合をしない
  - 数値に単位や記号を混ぜない（20 であって「20点」ではない）
  - 日付は YYYY-MM-DD
  - 見出しは1行だけ。前置きや脚注を表の中に入れない
  - 空欄になるのは2列だけ。どちらも「値が無い」を値で埋めないためのもの
      - hops … そのページに到達できなかった回。0 と書くと「0クリックで着いた」になる
      - measured_on … 実際に測った時刻が記録されていない回

**日付が3列あるのは、意味が3つ違うから。**

    measured_on  実際に測った日。記録が無ければ空欄
    exported_on  scores-*.json を書き出した日
    recorded_on  この履歴行を記録に残した日

以前は measured_on に書き出し時刻（generated_at）を入れていた。書き出しを流し直す
だけで「別の日に測った」行が増えるため、測り直した瞬間に日付が嘘になる。
記録が無いなら空欄にする——それが正しい（plans/decisions/resident-vs-data.md）。

※ デジタル庁「オープンデータ基本指針」はCSVの書き方までは定めていない
  （2026-08-23 に digital.go.jp を確認）。上のルールは機械判読可能な
  統計表の一般的な作法に従ったもの。

    python3 analysis/export_timeseries.py
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "web" / "data" / "history" / "scores.jsonl"
OUT = ROOT / "web" / "data" / "history" / "measurements.csv"

COLUMNS = [
    # ★この3つを混ぜないこと。以前は measured_on に generated_at（書き出し時刻）を
    #   入れていて、書き出しを流し直しただけの回が「別の日に測った」に見えていた。
    "measured_on",        # 実際に測った日（YYYY-MM-DD）。記録が無い回は空欄
    "exported_on",        # scores-*.json を書き出した日（YYYY-MM-DD）
    "recorded_on",        # この履歴行を記録に残した日（YYYY-MM-DD）
    "lg_code",            # 全国地方公共団体コード
    "municipality",       # 自治体名
    "procedure_id",       # 手続きの識別子
    "procedure",          # 手続き名
    "field",              # 項目名
    "points",             # その項目の点（数値のみ）
    "readable",           # 読み取れたか（1 / 0）
    "total",              # その自治体・手続きの合計点
    "hops",               # トップページからのクリック数
    "recording_status",   # 測定条件が記録されているか（条件そのものは index.json）
]


def lg_codes() -> dict[str, str]:
    """区の識別子 → 全国地方公共団体コード。名前で突き合わせない。"""
    doc = json.loads((ROOT / "web/data/municipalities.json").read_text(encoding="utf-8"))
    return {m["id"]: m.get("lg_code") or "" for m in doc["municipalities"]}


def snapshots() -> list[dict]:
    if not HISTORY.exists():
        return []
    return [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines() if line.strip()]


def day_of(value: object) -> str:
    """ISO 8601 の頭10文字。値が無ければ空欄にする（それらしい日付を作らない）。"""
    return str(value)[:10] if isinstance(value, str) and value else ""


def rows_of(snap: dict, codes: dict[str, str]) -> list[dict]:
    out = []
    for m in snap.get("municipalities", []):
        for field, points in sorted((m.get("breakdown") or {}).items()):
            out.append({
                # measured_on の出どころは snapshot の measured_at ただ1つ。
                # 記録が無い回は空欄のまま。generated_at で代用しない。
                "measured_on": day_of(snap.get("measured_at")),
                "exported_on": day_of(snap.get("generated_at")),
                "recorded_on": day_of(snap.get("recorded_at")),
                "lg_code": codes.get(m["id"], ""),
                "municipality": m.get("name", ""),
                "procedure_id": snap.get("procedure_id", ""),
                "procedure": snap.get("procedure", ""),
                "field": field,
                "points": points,
                # 4項目は20点で「読めた」。オンライン明示だけ10点（曖昧）があるので、
                # 満点かどうかで判定する
                "readable": 1 if points >= 20 else 0,
                "total": m.get("total", ""),
                "hops": m.get("hops", ""),
                "recording_status": snap.get("recording_status", ""),
            })
    return out


def build() -> list[dict]:
    codes = lg_codes()
    rows = [r for s in snapshots() for r in rows_of(s, codes)]
    # 並びは 測定日 → 書き出し日 → 団体コード → 手続き → 項目。
    # measured_on が空欄の回でも並びが決まるよう、第2キーに exported_on を置く。
    rows.sort(key=lambda r: (r["measured_on"], r["exported_on"], r["lg_code"],
                             r["procedure_id"], r["field"]))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    rows = build()
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    # 「測定日◯回」と「書き出し日◯回」を分けて言う。前は書き出し回数を測定回数として
    # 出していたので、画面に出す前の段階で既に嘘になっていた。
    days = sorted({r["measured_on"] for r in rows if r["measured_on"]})
    exports = sorted({r["exported_on"] for r in rows if r["exported_on"]})
    unknown = sum(1 for r in rows if not r["measured_on"])
    measured = f"測定日 {len(days)}回（{', '.join(days)}）" if days else "測定日 記録なし"
    print(f"{args.out}: {len(rows)}行 / {measured}"
          f" / 書き出し日 {len(exports)}回（{', '.join(exports)}）"
          f" / 測定日が空欄の行 {unknown}"
          f" / {args.out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

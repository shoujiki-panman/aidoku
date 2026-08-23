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
  - 空欄は hops（クリック数）だけ。そのページに到達できなかった回で、
    0 と書くと「0クリックで着いた」の意味になるため、あえて空にする

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
    "measured_on",        # 測った日（YYYY-MM-DD）
    "recorded_on",        # 記録に残した日（YYYY-MM-DD）
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


def rows_of(snap: dict, codes: dict[str, str]) -> list[dict]:
    out = []
    for m in snap.get("municipalities", []):
        for field, points in sorted((m.get("breakdown") or {}).items()):
            out.append({
                "measured_on": str(snap.get("generated_at", ""))[:10],
                "recorded_on": str(snap.get("recorded_at", ""))[:10],
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
    # 並びは 日付 → 団体コード → 手続き → 項目。読む側が固定順を期待できる
    rows.sort(key=lambda r: (r["measured_on"], r["lg_code"], r["procedure_id"], r["field"]))
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
    days = sorted({r["measured_on"] for r in rows})
    print(f"{args.out}: {len(rows)}行 / 測定日 {len(days)}回（{', '.join(days)}）"
          f" / {args.out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

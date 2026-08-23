"""調査を「回」ごとにまとめて、年月日つきの一覧にする（web/data/surveys.json）。

**なぜ要るか**: 住民の画面に点数（7/12）と推移リンクが出ていた。住民が知りたいのは
「自分のAIが何を知れないか」であって、区の成績でも調査の履歴でもない（本人の指摘）。
調べたデータは、参照したい人が参照できる場所に、いつのものかが分かる形で置く。

**正直に出すこと**: いまの history/scores.jsonl は、測定ではなく
「書き出しを走らせた回」を記録している（generated_at はエクスポータの実行時刻）。
3回ぶんの記録があるが、345観測すべて値が同じ。ここでは値が同じ回を
`same_as_previous: true` として明示し、「3回測った」ように見せない。

    python3 analysis/export_surveys.py
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "web" / "data" / "history" / "scores.jsonl"
OUT = ROOT / "web" / "data" / "surveys.json"

# 画面に出す説明。数字はすべてファイルから読む
ABOUT = (
    "AI読が実施した調査の一覧。1件が1回の調査で、測った日ごとに並べてある。"
    "値が前回と同じ回は same_as_previous を true にしている。"
)


def snapshots(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fingerprint(snap: dict) -> str:
    """その回の中身が前回と同じかを見るための指紋。自治体ごとの合計点を使う。"""
    munis = snap.get("municipalities") or []
    pairs = sorted((str(m.get("id")), m.get("total")) for m in munis)
    return json.dumps(pairs, ensure_ascii=False, separators=(",", ":"))


def procedure_entry(snap: dict) -> dict:
    munis = snap.get("municipalities") or []
    summary = snap.get("summary") or {}
    return {
        "procedure_id": snap.get("procedure_id"),
        "procedure": snap.get("procedure"),
        "municipalities": len(munis),
        "average": summary.get("average"),
        "full_marks": summary.get("full_marks"),
        "zero": summary.get("zero"),
        "fingerprint": fingerprint(snap),
    }


def group_by_run(snaps: list[dict]) -> list[dict]:
    """同じ measured（generated_at）の手続きを1回の調査にまとめる。"""
    runs: dict[str, list[dict]] = defaultdict(list)
    for snap in snaps:
        runs[str(snap.get("generated_at") or "")].append(snap)
    out = []
    for measured_at in sorted(runs):
        group = runs[measured_at]
        recorded = sorted({str(s.get("recorded_at") or "") for s in group})
        statuses = sorted({str(s.get("recording_status") or "") for s in group})
        procedures = [procedure_entry(s) for s in sorted(group, key=lambda s: str(s.get("procedure_id")))]
        out.append({
            "measured_at": measured_at,
            "measured_on": measured_at[:10],
            "recorded_at": recorded,
            "recorded_on": sorted({r[:10] for r in recorded}),
            "recording_status": statuses[0] if len(statuses) == 1 else "mixed",
            "procedures": procedures,
            "observations": sum(p["municipalities"] for p in procedures),
        })
    return out


def mark_repeats(runs: list[dict]) -> list[dict]:
    """値が前回と同じ回に印をつける。3回あるように見せないため。"""
    previous: str | None = None
    for run in runs:
        current = json.dumps([p["fingerprint"] for p in run["procedures"]], ensure_ascii=False)
        run["same_as_previous"] = previous is not None and current == previous
        previous = current
        for proc in run["procedures"]:
            proc.pop("fingerprint", None)
    return runs


def distinct_measurements(runs: list[dict]) -> int:
    """値が違う回だけ数える。「何回ちがう結果が出たか」。"""
    return sum(1 for run in runs if not run["same_as_previous"])


def build(path: Path = HISTORY) -> dict:
    runs = mark_repeats(group_by_run(snapshots(path)))
    return {
        "_about": ABOUT,
        "schema": "aidoku-surveys-1",
        "runs": runs,
        "n_runs": len(runs),
        "n_distinct": distinct_measurements(runs),
        "files": [
            {"label": "1行1観測のCSV（全期間）", "path": "data/history/measurements.csv"},
            {"label": "回ごとのスナップショット（JSONL）", "path": "data/history/scores.jsonl"},
            {"label": "毎日の見張り（JSONL）", "path": "data/history/site-status.jsonl"},
            {"label": "データの目次（測定条件・sha256）", "path": "data/index.json"},
        ],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    doc = build()
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {args.out}（{doc['n_runs']}回 / 値が違うのは {doc['n_distinct']}回）")


if __name__ == "__main__":
    main()

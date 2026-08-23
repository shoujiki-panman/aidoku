"""調査を「回」ごとにまとめて、年月日つきの一覧にする（web/data/surveys.json）。

**なぜ要るか**: 住民の画面に点数（7/12）と推移リンクが出ていた。住民が知りたいのは
「自分のAIが何を知れないか」であって、区の成績でも調査の履歴でもない（本人の指摘）。
調べたデータは、参照したい人が参照できる場所に、いつのものかが分かる形で置く。

**正直に出すこと**: いまの history/scores.jsonl は、測定ではなく
「書き出しを走らせた回」を記録している（generated_at はエクスポータの実行時刻）。
3回ぶんの記録があるが、345観測すべて値が同じ。ここでは値が同じ回を
`same_as_previous: true` として明示し、「3回測った」ように見せない。

**日付の名前を実態に合わせた（2026-08-23）**。以前はこの一覧が書き出し時刻を
`measured_at` という名前で出していて、名前そのものが嘘だった。いまは:

    exported_at / exported_on   書き出しを走らせた時刻。回の並びのキーもこれ
    measured_at / measured_on   実際に測った時刻。**記録が無ければ null**
    measured_at_status          "recorded"（実測時刻あり）/ "unknown"（無い）

実測時刻の出どころは各回の `measurement.run_at` ただ1つ。いまの公開データは
すべて legacy_unknown で run_at を持たないので、measured_at は全件 null になる。
**それが正しい。** 書き出し時刻で埋めないこと。

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
    "AI読が実施した調査の一覧。1件が1回の書き出しで、書き出した日ごとに並べてある。"
    "exported_at は書き出しを走らせた時刻であって、測定した時刻ではない。"
    "実際に測った時刻は measured_at に入るが、測定条件を記録し始める前の回は"
    "記録が残っておらず null になる（measured_at_status: unknown）。"
    "分からない時刻を書き出し時刻で埋めることはしない。"
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


def measured_at_of_group(group: list[dict]) -> str | None:
    """その回の実測時刻。1つも記録が無ければ None を返す（書き出し時刻で埋めない）。"""
    stamps = sorted({s["measured_at"] for s in group
                     if isinstance(s.get("measured_at"), str) and s["measured_at"]})
    return stamps[0] if stamps else None


def group_by_run(snaps: list[dict]) -> list[dict]:
    """同じ書き出し（generated_at）の手続きを1回にまとめる。

    まとめるキーが generated_at なのは、それが履歴行を1回ぶんに束ねる唯一の目印
    だから。**「1回の書き出し」であって「1回の測定」ではない**ので、出す名前も
    exported_at にする。
    """
    runs: dict[str, list[dict]] = defaultdict(list)
    for snap in snaps:
        runs[str(snap.get("generated_at") or "")].append(snap)
    out = []
    for exported_at in sorted(runs):
        group = runs[exported_at]
        recorded = sorted({str(s.get("recorded_at") or "") for s in group})
        statuses = sorted({str(s.get("recording_status") or "") for s in group})
        procedures = [procedure_entry(s) for s in sorted(group, key=lambda s: str(s.get("procedure_id")))]
        measured_at = measured_at_of_group(group)
        out.append({
            "exported_at": exported_at,
            "exported_on": exported_at[:10],
            "measured_at": measured_at,
            "measured_on": measured_at[:10] if measured_at else None,
            "measured_at_status": "recorded" if measured_at else "unknown",
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


def unknown_measured_at(runs: list[dict]) -> int:
    """実測時刻が記録されていない回の数。画面がこれを黙ると、また日付が嘘になる。"""
    return sum(1 for run in runs if run["measured_at_status"] != "recorded")


def build(path: Path = HISTORY) -> dict:
    runs = mark_repeats(group_by_run(snapshots(path)))
    return {
        "_about": ABOUT,
        # 日付の名前を実態に合わせたので schema を上げる。読む側が旧 measured_at
        # （中身は書き出し時刻）をそのまま使い続けないようにするため。
        "schema": "aidoku-surveys-2",
        "runs": runs,
        "n_runs": len(runs),
        "n_distinct": distinct_measurements(runs),
        "n_measured_unknown": unknown_measured_at(runs),
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
    print(f"→ {args.out}（書き出し {doc['n_runs']}回 / 値が違うのは {doc['n_distinct']}回"
          f" / 実測時刻が記録されていない回 {doc['n_measured_unknown']}）")


if __name__ == "__main__":
    main()

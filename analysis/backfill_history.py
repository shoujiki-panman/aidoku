"""git に残っている過去の web/data/*.json から、履歴を復元する。

履歴の仕組みを入れたのが 2026-08-22 なので、それ以前の測定・見張りは
コミットの中にしか無い。**捨てるのは惜しいので、一度だけ拾い直す。**

追記は冪等（同じ generated_at / checked_at は入らない）なので、
何度流しても増えない。

    python3 analysis/backfill_history.py            # 実際に書く
    python3 analysis/backfill_history.py --dry-run  # 何が入るかだけ見る
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from history import (  # noqa: E402
    SCORE_KEY,
    SITE_STATUS_KEY,
    append_snapshot,
    load_snapshots,
    site_status_snapshot,
    snapshot_from_doc,
)


def already_there(path: str, snapshot: dict, key_fields: tuple[str, ...]) -> bool:
    """--dry-run が「既にある分」まで追記予定として数えないようにする。"""
    key = tuple(snapshot.get(k) for k in key_fields)
    return any(tuple(r.get(k) for k in key_fields) == key for r in load_snapshots(path))

SCORES = ("web/data/scores-tennyu.json", "web/data/scores-jidouteate.json",
          "web/data/scores-sodaigomi.json")
SITE_STATUS = "web/data/site-status.json"


def commits_for(path: str) -> list[tuple[str, str]]:
    """そのファイルを触ったコミットを、古い順に (sha, 日付) で返す。"""
    out = subprocess.run(
        ["git", "log", "--reverse", "--format=%H\t%aI", "--", path],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [tuple(line.split("\t")) for line in out.splitlines() if "\t" in line]


def blob_at(sha: str, path: str) -> dict | None:
    r = subprocess.run(["git", "show", f"{sha}:{path}"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scores-out", default=str(ROOT / "web/data/history/scores.jsonl"))
    ap.add_argument("--status-out", default=str(ROOT / "web/data/history/site-status.jsonl"))
    args = ap.parse_args(argv)

    added = skipped = 0
    for path in SCORES:
        for sha, when in commits_for(path):
            doc = blob_at(sha, path)
            if doc is None:
                continue
            try:
                snap = snapshot_from_doc(doc, when)
            except ValueError as e:
                print(f"  飛ばす {sha[:8]} {path}: {e}")
                continue
            label = f"{snap['procedure_id']} {snap['generated_at']}"
            if args.dry_run:
                if already_there(args.scores_out, snap, SCORE_KEY):
                    skipped += 1
                else:
                    print(f"  [dry] {sha[:8]} {label}")
                    added += 1
                continue
            if append_snapshot(args.scores_out, snap):
                print(f"  追記 {sha[:8]} {label}")
                added += 1
            else:
                skipped += 1

    for sha, _when in commits_for(SITE_STATUS):
        doc = blob_at(sha, SITE_STATUS)
        if doc is None:
            continue
        snap = site_status_snapshot(doc)
        if not snap.get("checked_at"):
            continue
        label = f"見張り {snap['checked_at']} 変化{len(snap['changed'])}件"
        if args.dry_run:
            if already_there(args.status_out, snap, SITE_STATUS_KEY):
                skipped += 1
            else:
                print(f"  [dry] {sha[:8]} {label}")
                added += 1
            continue
        if append_snapshot(args.status_out, snap, SITE_STATUS_KEY):
            print(f"  追記 {sha[:8]} {label}")
            added += 1
        else:
            skipped += 1

    print(f"\n  追記 {added} 件 / 既にあった {skipped} 件")


if __name__ == "__main__":
    main()

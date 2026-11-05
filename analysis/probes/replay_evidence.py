"""保存済みの引用を、いまの根拠検査で判定し直す。**LLM は呼ばない。**

**なぜ要るか**: 根拠検査を変えると、落ちていた引用が通るようになる。
何が新しく通るのかを全件見ずに反映すると、検査を甘くした害が見えない。

★公開データと `sweep_*.json` は書き換えない。

    python3 analysis/probes/replay_evidence.py --cache <crawler/cache>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))

import reread_fee  # noqa: E402

from evidence_check import VERIFIED_VERDICTS, check_one  # noqa: E402

PROCEDURES = ("tennyu", "jidouteate", "sodaigomi")
OUT = ROOT / "analysis" / "out" / "evidence-replay.json"


def replay(visits: dict[str, dict], text_of) -> list[dict]:
    """`found=true` で落ちていた判定だけを判定し直す。★本文が取れないものは通さない。"""
    out = []
    for key, visit in visits.items():
        if not isinstance(visit, dict) or not visit.get("found") or visit.get("verified"):
            continue
        text = text_of(visit.get("url") or "")
        check = check_one(visit.get("evidence"), text) if text else {"verdict": "not_checked"}
        out.append({"key": key, "url": visit.get("url"), "value": visit.get("value", ""),
                    "evidence": visit.get("evidence", ""),
                    "before": (visit.get("evidence_check") or {}).get("verdict"),
                    "after": check["verdict"], "now_verified": check["verdict"] in VERIFIED_VERDICTS})
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", required=True, type=Path, help="crawler/cache の場所")
    args = ap.parse_args(argv)
    reread_fee.CACHE = args.cache
    rows = []
    for procedure in PROCEDURES:
        doc = json.loads((ROOT / "analysis" / "out" / f"visits_{procedure}.json").read_text("utf-8"))
        for row in replay(doc.get("visits", doc), reread_fee.cache_text):
            rows.append({"procedure": procedure, **row})
    passed = [r for r in rows if r["now_verified"]]
    OUT.write_text(json.dumps({"_about": "plans/evidence-segments.md。公開データではない。",
                               "found_but_rejected": len(rows), "now_verified": len(passed), "items": rows},
                              ensure_ascii=False, indent=1), "utf-8")
    print(f"落ちていた判定 {len(rows)} / 新しく通る {len(passed)}")


if __name__ == "__main__":
    main()

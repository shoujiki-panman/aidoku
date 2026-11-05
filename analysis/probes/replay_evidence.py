"""保存済みの引用を、いまの根拠検査で判定し直す。**LLM は呼ばない。**

**なぜ要るか**: 根拠検査を変えると、落ちていた引用が通るようになる。
何が新しく通るのかを全件見ずに反映すると、検査を甘くした害が見えない。

★公開データは書き換えない。`--apply` は虱潰しの記録だけを直す。

    python3 analysis/probes/replay_evidence.py --cache <crawler/cache>
    python3 analysis/probes/replay_evidence.py --cache <crawler/cache> --apply
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
import sweep  # noqa: E402

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


def apply_replay(visits: dict[str, dict], text_of) -> list[str]:
    """通るようになった判定を記録に反映し、直したキーを返す。"""
    changed = []
    for row in replay(visits, text_of):
        if row["now_verified"]:
            visit = visits[row["key"]]
            visit["evidence_check"] = check_one(visit["evidence"], text_of(visit["url"]))
            visit["verified"] = True
            changed.append(row["key"])
    return changed


def no_llm(*_args, **_kwargs):
    """★反映では読み直さない。記録に無いページが残っていたら、書き込む前に止める。"""
    raise SystemExit("記録に無い判定がある。LLM を呼ばずに止めた")


def apply_all() -> None:
    """visits を直してから、虱潰しを記録だけで組み立て直す。"""
    for procedure in PROCEDURES:
        visits = sweep.load_visits(procedure)
        changed = apply_replay(visits, reread_fee.cache_text)
        if not changed:
            continue
        sweep.save_visits(procedure, visits)
        print(f"{procedure}: {len(changed)}判定を直した")
        munis = sorted({mid for mid, url in sweep_ids(procedure, changed)})
        sweep.ask_page = no_llm
        sweep.main(["-p", procedure, *[arg for muni in munis for arg in ("-m", muni)]])


def sweep_ids(procedure: str, keys: list[str]) -> list[tuple[str, str]]:
    """直した判定を読んでいる自治体。"""
    doc = json.loads((ROOT / "analysis" / "out" / f"sweep_{procedure}.json").read_text("utf-8"))
    urls = {key.split("\t")[0] for key in keys}
    return [(row["municipality_id"], page["url"]) for row in doc["rows"] for field in row["fields"]
            for page in field.get("looked", []) if page["url"] in urls]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", required=True, type=Path, help="crawler/cache の場所")
    ap.add_argument("--apply", action="store_true", help="通るようになった判定を虱潰しの記録へ反映する")
    args = ap.parse_args(argv)
    reread_fee.CACHE = args.cache
    if args.apply:
        apply_all()
        return
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

"""同じ区を、同じ条件で何度も測る。**答えがどれだけ揺れるかを知るため。**

**なぜ要るか**: AI読は1組（自治体×手続き）を**1回しか測っていない**。
条件を揃えて測り直したあと、道具を増やしたのに点が下がった区が3つあった。

    中野区 児童手当  80 → 20
    大田区 転入届    80 → 60
    世田谷区 転入届  40 → 20

これが「条件を変えたせい」なのか「同じ条件でも揺れる」のかを、
**区別できていなかった**。揺れの幅を知らないまま、点の上下を語っていた。

★揺れは点数には入れない。**点数に幅を付けて読むための材料**。
  揺れが大きい項目は、1回の測定で区の優劣を言ってはいけない。

    python3 analysis/repeat.py -m nakano -p jidouteate -n 3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "analysis" / "out"

VERSION = "repeat-0.1"


def run_once(municipality: str, procedure: str, out_dir: Path) -> dict | None:
    """1回測って結果を返す。落ちたら None（**落ちた回を成功に混ぜない**）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "extractor/extract.py", "-m", municipality,
         "-p", procedure, "--follow", "--out-dir", str(out_dir)],
        cwd=ROOT, capture_output=True, text=True)
    path = out_dir / f"extract_{municipality}_{procedure}.json"
    if proc.returncode != 0 or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def observations(runs: list[dict]) -> dict[str, list[str]]:
    """観測ごとの答えを並べる。**読めた／読めなかった**と、選んだページ。"""
    out: dict[str, list[str]] = {}
    for run in runs:
        out.setdefault("_選んだページ", []).append((run.get("page") or {}).get("url", ""))
        out.setdefault("_オンライン明示", []).append(str(run.get("online_clarity")))
        for field, item in (run.get("items") or {}).items():
            out.setdefault(field, []).append("読めた" if item.get("found") else "読めない")
    return out


def spread(answers: dict[str, list[str]]) -> dict:
    """割れた観測と、割れた割合。**項目だけを分母にする**（ページ選択は別枠）。"""
    fields = {k: v for k, v in answers.items() if not k.startswith("_")}
    split = [k for k, v in fields.items() if len(set(v)) > 1]
    return {
        "runs": len(next(iter(answers.values()), [])),
        "fields": len(fields),
        "split_fields": split,
        "split_ratio": round(len(split) / len(fields), 3) if fields else 0.0,
        "page_stable": len(set(answers.get("_選んだページ", []))) <= 1,
        "clarity_stable": len(set(answers.get("_オンライン明示", []))) <= 1,
    }


def measure(municipality: str, procedure: str, times: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        runs = [r for i in range(times)
                if (r := run_once(municipality, procedure, Path(tmp) / f"run{i}"))]
    if len(runs) < 2:
        raise SystemExit(f"{len(runs)}回しか成功していない。揺れは2回以上必要")
    answers = observations(runs)
    return {"municipality": municipality, "procedure": procedure,
            "answers": answers, "summary": spread(answers),
            "measurement": runs[0].get("measurement")}


def _report(doc: dict) -> None:
    s = doc["summary"]
    print(f"{doc['municipality']} {doc['procedure']} を{s['runs']}回")
    for field, values in doc["answers"].items():
        mark = "  " if len(set(values)) <= 1 else "★割れた"
        print(f"  {mark} {field:16} {' / '.join(v[:40] for v in values)}")
    print(f"\n  割れた項目 {len(s['split_fields'])}/{s['fields']}"
          f"（{s['split_ratio'] * 100:.0f}%）")
    if not s["page_stable"]:
        print("  ★選んだページが回ごとに違う（起点が揺れている）")
    if not s["clarity_stable"]:
        # ★事実4項目とは別に20点ぶんある。ここだけ揺れると点が20動く。
        print("  ★オンライン明示の判断が回ごとに違う（点が20動く）")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--municipality", "-m", required=True)
    ap.add_argument("--procedure", "-p", required=True)
    ap.add_argument("--times", "-n", type=int, default=3)
    args = ap.parse_args(argv)

    doc = measure(args.municipality, args.procedure, args.times)
    doc["version"] = VERSION
    doc["_about"] = ("同じ条件で同じ区を複数回測った記録。判定には使わない。"
                     "点数を幅つきで読むための材料。")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"repeat_{args.municipality}_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _report(doc)
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

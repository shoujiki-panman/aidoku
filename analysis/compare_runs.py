"""同じ手続きを2回測った結果を突き合わせ、判定が変わったセルを数える。

**なぜ要るか**: 「再現性は手続きによって◯倍違う」という、AI読でいちばん重い主張は
**この数え方ひとつに乗っている。** それを毎回その場で書き捨てて計算していた。

2026-08-30、PRを書く前に数え直したら **粗大ごみの 29/96 が誤りだった**（正しくは
21/96）。元の数字はそれ自体が合っていない（上昇17＋下降2＝19で29にならない）。
到達できなかった区を「4項目とも変化した」と数える誤りも混ざっていた。

**数え方が道具になっていないと、数字は静かに間違う。**

## 数え方（3手続きとも同じ）

1セル ＝ (自治体, 4項目のいずれか)。**`found` が旧→新で反転したセル**を数える。

| 印 | 意味 |
|---|---|
| `up` | ✗→✓ 取れるようになった |
| `down` | ✓→✗ 取れなくなった |
| `same` | 変わらない |
| `unreached` | **旧・新どちらかで起点ページに到達できていない** |

★`unreached` を `same` に混ぜない。到達できなかった区は測定が成立していない。
  混ぜると分母が水増しされ、再現性が実際より高く見える。
  （`analysis/sweep.py` の `reached()` と同じ区別。）

    python3 analysis/compare_runs.py -p sodaigomi
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "analysis" / "out"

VERSION = "compare-runs-0.1"

# 抽出結果のキー。公開データの項目名（`窓口/オンライン可否`）とは違う。
FIELDS = ("必要書類", "期限", "手数料", "窓口オンライン可否")

# 旧結果の置き場。再測定の前に退避したもの。
BEFORE_DIRS = {
    "tennyu": "remeasure",
    "jidouteate": "remeasure-jidouteate",
    "sodaigomi": "remeasure-sodaigomi",
}


def reached(doc: dict) -> bool:
    """起点ページにたどり着けた結果か。`analysis/sweep.py` と同じ判定。"""
    page = doc.get("page") or {}
    return bool(page.get("url"))


def found(doc: dict, field: str) -> bool:
    return bool((doc.get("items") or {}).get(field, {}).get("found"))


def compare_one(before: dict, after: dict) -> list[dict]:
    """1自治体ぶん。**到達できていなければ4項目まとめて `unreached`。**"""
    if not (reached(before) and reached(after)):
        return [{"field": f, "mark": "unreached", "before": None, "after": None}
                for f in FIELDS]
    out = []
    for f in FIELDS:
        b, a = found(before, f), found(after, f)
        mark = "same" if b == a else ("up" if a else "down")
        out.append({"field": f, "mark": mark, "before": b, "after": a})
    return out


def rel(path: Path) -> str:
    """記録に残す道。★`relative_to` は外の道で落ちる（--before に他所を渡すと死ぬ）。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pairs(procedure: str, before_dir: Path, after_dir: Path) -> list[tuple[str, dict, dict]]:
    """旧・新の両方がある自治体だけ。**片方しか無いものは黙って捨てない。**"""
    out = []
    for path in sorted(glob.glob(str(before_dir / f"extract_*_{procedure}.json"))):
        before = load(Path(path))
        after_path = after_dir / Path(path).name
        if not after_path.exists():
            print(f"  ! 新しい結果が無い: {before['municipality']}")
            continue
        out.append((before["municipality"], before, load(after_path)))
    return out


def tally(rows: list[dict]) -> dict:
    """★分母を2つ出す。全セルと、到達できた区だけ。どちらか一方では読み違える。"""
    cells = [c for row in rows for c in row["cells"]]
    up = sum(1 for c in cells if c["mark"] == "up")
    down = sum(1 for c in cells if c["mark"] == "down")
    unreached = sum(1 for c in cells if c["mark"] == "unreached")
    measured = len(cells) - unreached
    return {
        "municipalities": len(rows),
        "cells": len(cells),
        "changed": up + down,
        "up": up,
        "down": down,
        "unreached_cells": unreached,
        "measured_cells": measured,
        # 全セルを分母にした割合（手続き間の比較はこちらで揃える）
        "changed_ratio": round((up + down) / len(cells), 3) if cells else 0.0,
        # 到達できた区だけを分母にした割合
        "changed_ratio_measured": round((up + down) / measured, 3) if measured else 0.0,
        "changed_names": [f"{'↑' if c['mark'] == 'up' else '↓'}{row['municipality']}/{c['field']}"
                          for row in rows for c in row["cells"]
                          if c["mark"] in ("up", "down")],
        "unreached_municipalities": [row["municipality"] for row in rows
                                     if all(c["mark"] == "unreached" for c in row["cells"])],
        "by_field": {f: sum(1 for c in cells
                            if c["field"] == f and c["mark"] in ("up", "down"))
                     for f in FIELDS},
    }


def followed(docs: list[dict]) -> int:
    return sum(len(d.get("followed_urls") or []) for d in docs)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--before", help="旧結果の置き場（既定は analysis/out/remeasure*）")
    ap.add_argument("--after", default=str(ROOT / "extractor" / "out"))
    args = ap.parse_args(argv)

    before_dir = Path(args.before) if args.before else \
        OUT_DIR / BEFORE_DIRS.get(args.procedure, f"remeasure-{args.procedure}")
    found_pairs = pairs(args.procedure, before_dir, Path(args.after))
    rows = [{"municipality": name, "cells": compare_one(b, a)} for name, b, a in found_pairs]
    summary = tally(rows)
    doc = {
        "_about": "同じ手続きを2回測った結果の突き合わせ。判定は変えない。何が変わったかの記録。"
                  "到達できなかった区は unreached として分けてある（same に混ぜない）。",
        "version": VERSION,
        "procedure": args.procedure,
        "before_dir": rel(before_dir),
        "followed_urls": {"before": followed([b for _, b, _ in found_pairs]),
                          "after": followed([a for _, _, a in found_pairs])},
        "summary": summary,
        "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"compare_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = summary
    print(f"{args.procedure}: {s['municipalities']}自治体 / {s['cells']}セル")
    print(f"  変化 {s['changed']}/{s['cells']}（{s['changed_ratio']:.1%}） "
          f"上昇{s['up']} 下降{s['down']}")
    if s["unreached_cells"]:
        print(f"  ★到達できず測定が成立していない: {s['unreached_cells']}セル "
              f"{s['unreached_municipalities']}")
        print(f"  到達できた区だけなら {s['changed']}/{s['measured_cells']}"
              f"（{s['changed_ratio_measured']:.1%}）")
    print(f"  項目別: {s['by_field']}")
    print(f"  追従 {doc['followed_urls']['before']} → {doc['followed_urls']['after']}本")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

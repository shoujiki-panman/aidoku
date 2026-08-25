"""公開済みJSONに、増えた測定条件キーを null で足す。

**なぜ要るか**: `CONDITION_KEYS` にキーを足すと、既に公開したJSONにはそのキーが無い。
`measurement_signature()` は全キーを引くので、**そのまま KeyError で落ちる。**

これを3回、手作業でやった（`link_order` / `table_reading` / `read_breadth`）。3回目でやめる。

**null は「測っていない」であって「その設定で測った」ではない。**
既存の記録は `recording_status: legacy_unknown` のままで、値を作らない。
条件が違う記録どうしは、これまでどおり比較を拒否する。

**2種類あるので、扱いを分ける**:

| 場所 | 中身 | 直し方 |
|---|---|---|
| `scores-*.json` の `measurement` | 条件の**値** | ここで null を足す |
| `index.json` の `provenance.condition_keys` | 条件の**キー名の一覧** | 書き出し直す（`export_data_index.py`） |

★最初これを1つの再帰探索でやろうとして、自治体ごとの `runs`（`model` しか持たない）まで
  measurement ブロックとして拾った。**形を決め打ちしないことが常に安全とは限らない。**

    python3 analysis/backfill_condition_keys.py --check   # 数えるだけ（CI用・不足があれば非0で終わる）
    python3 analysis/backfill_condition_keys.py           # 実際に足す
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from measurement import CONDITION_KEYS  # noqa: E402

SCORES = "web/data/scores-*.json"
INDEX = ROOT / "web" / "data" / "index.json"


def missing_keys(block: dict) -> list[str]:
    """その measurement ブロックに足りない条件キー。順番は CONDITION_KEYS のまま。"""
    return [key for key in CONDITION_KEYS if key not in block]


def fill(block: dict) -> list[str]:
    """足りないキーを null で足す。**既にある値は絶対に上書きしない。**"""
    added = missing_keys(block)
    for key in added:
        block[key] = None
    return added


def index_stale_keys(doc: dict) -> list[str]:
    """index.json が載せている条件キー一覧のうち、いま足りないもの。

    ここは値ではなく**キー名の一覧**なので、null を足すのではなく書き出し直す。
    """
    listed = (doc.get("provenance") or {}).get("condition_keys") or []
    return [key for key in CONDITION_KEYS if key not in listed]


def process_scores(path: Path, write: bool) -> list[str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    block = doc.get("measurement")
    if not isinstance(block, dict):
        raise SystemExit(f"measurement ブロックが無い: {path}")
    added = fill(block) if write else missing_keys(block)
    if write and added:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="書き換えず、足りないキーを報告するだけ")
    args = ap.parse_args(argv)

    problems = 0
    for path in sorted(ROOT.glob(SCORES)):
        added = process_scores(path, write=not args.check)
        verb = "不足" if args.check else "追加"
        print(f"  {path.relative_to(ROOT)}  {f'{verb}: ' + ', '.join(added) if added else '不足なし'}")
        problems += len(added) if args.check else 0

    stale = index_stale_keys(json.loads(INDEX.read_text(encoding="utf-8")))
    if stale:
        print(f"  {INDEX.relative_to(ROOT)}  一覧に無い: {', '.join(stale)}"
              f"  → analysis/export_data_index.py を走らせ直す")
        problems += len(stale)
    else:
        print(f"  {INDEX.relative_to(ROOT)}  一覧は最新")

    print(f"\n条件キー {len(CONDITION_KEYS)}個")
    if args.check and problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

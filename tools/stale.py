"""いまの測定条件と合っていない（＝測り直しが要る）自治体を並べる。

**なぜ要るか**: 最初は `prompt_version` だけを見ていた。だが OCR を足したとき
**プロンプトは変わらない**ので、条件が変わったのに「揃っている」と誤判定した。

**測定条件はひとまとまりで効く。** 1つだけ見て揃ったと言ってはいけない。

    python3 tools/stale.py            # 「自治体ID 手続き」を1行ずつ
    python3 tools/stale.py --why      # どの条件がずれているかも出す
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "extractor"))

PROCEDURES = ("tennyu", "sodaigomi", "jidouteate")


def current() -> dict[str, object]:
    """いまの条件。**定数から計算する**（記録された値を信じない）。"""
    from extract import CLARITY_PROMPT
    from fact_extract import (
        LINK_ORDER,
        MAX_FOLLOW,
        MAX_LINKS,
        MAX_TEXT_CHARS,
        NON_HTML_READING,
        PROMPT,
        READ_BREADTH,
        TABLE_READING,
    )

    from measurement import prompt_version
    return {
        "prompt_version": prompt_version([PROMPT, CLARITY_PROMPT]),
        "non_html_reading": NON_HTML_READING,
        "read_breadth": READ_BREADTH,
        "link_order": LINK_ORDER,
        "table_reading": TABLE_READING,
        "max_follow": MAX_FOLLOW,
        "max_links": MAX_LINKS,
        "max_text_chars": MAX_TEXT_CHARS,
    }


def differences(measurement: dict, now: dict[str, object]) -> list[str]:
    """ずれている条件の名前。**空なら揃っている。**"""
    return [key for key, value in now.items() if (measurement or {}).get(key) != value]


def stale(now: dict[str, object]) -> list[tuple[str, str, list[str]]]:
    out = []
    for procedure in PROCEDURES:
        for path in sorted(glob.glob(str(ROOT / f"extractor/out/extract_*_{procedure}.json"))):
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            diff = differences(doc.get("measurement") or {}, now)
            if diff:
                out.append((doc["municipality_id"], procedure, diff))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--why", action="store_true", help="ずれている条件も出す")
    args = ap.parse_args(argv)
    for municipality, procedure, diff in stale(current()):
        print(f"{municipality} {procedure}" + (f"  # {','.join(diff)}" if args.why else ""))


if __name__ == "__main__":
    main()

"""対外文に書いた数字が、いまの実測と合っているかを突き合わせる。

**人が数字を書く限り、必ずズレる。**
実例: 提出本文は「5区はほとんど持ち帰れず」だったが、台東区の `.docx` バグが
2026-08-05 に直って 0点→80点 になり、現在は **4区**。本文の確定は 8/3 で、
2日後の修正が入っていなかった（2026-08-18 に発見）。

このスクリプトは2つのことをする。

1. `--facts` … いまの実測値を、そのまま文章に貼れる形で出す
2. `--text FILE` … 文章に出てくる「N区」「N点」を拾い、いまの実測に無い数字を **要確認** として出す

⚠️ 文脈までは判定しない。「この数字は実測のどれにも一致しない」までしか言えない。
最後は人が読む。だが、**古い数字が黙って生き残ることは防げる。**

実行:
    python3 analysis/probes/check_claims.py --facts
    python3 analysis/probes/check_claims.py --text ../outputs/aidoku-private/_reference/SUBMISSION.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DATA = ROOT / "web" / "data"

# 文章から拾う数字の形。単位ごとに分けて、比べる相手を変える。
PATTERNS = {
    "区": re.compile(r"(\d+)\s*区"),
    "点": re.compile(r"(\d+(?:\.\d+)?)\s*点"),
}


def load_procedures() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(DATA.glob("scores-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append((path.stem.removeprefix("scores-"), data))
    return out


def facts_for(data: dict) -> dict[str, float]:
    """1手続きぶんの、対外文に出てくる数字。"""
    munis = data["municipalities"]
    summary = data["summary"]
    readable = [m for m in munis
                if all(f["verdict"] == "読めた" for f in m["fields"])]
    unreadable = [m for m in munis
                  if all(f["verdict"] != "読めた" for f in m["fields"])]
    return {
        "自治体数": len(munis),
        "4項目すべて読めた区": len(readable),
        "4項目とも読めない区": len(unreadable),
        "手数料が読めない区": summary["fee_missing"],
        "平均点": summary["average"],
        "最高点": summary["max"],
        "最低点": summary["min"],
    }


def names_for(data: dict) -> dict[str, list[str]]:
    munis = data["municipalities"]
    return {
        "4項目すべて読めた区": [m["name"] for m in munis
                       if all(f["verdict"] == "読めた" for f in m["fields"])],
        "4項目とも読めない区": [m["name"] for m in munis
                       if all(f["verdict"] != "読めた" for f in m["fields"])],
    }


def print_facts() -> None:
    for pid, data in load_procedures():
        print(f"\n=== {data['procedure']}（{pid}）｜生成 {data.get('generated_at','')[:10]} ===")
        for key, value in facts_for(data).items():
            print(f"  {key:20} {value}")
        for key, names in names_for(data).items():
            if names:
                print(f"  {key:20} {'・'.join(names)}")


def numbers_by_procedure() -> tuple[dict[str, dict[str, set[float]]], dict[str, set[float]]]:
    """手続きごとの数字と、全手続きを合わせた数字。

    **手続きごとに分けるのが肝。** 「5区」は粗大ごみでは正しい値だが、
    転入届では誤り（現在4区）。手続きを見ないと、この取り違えを見逃す。
    """
    per: dict[str, dict[str, set[float]]] = {}
    union: dict[str, set[float]] = {"区": set(), "点": set()}
    for _pid, data in load_procedures():
        buckets: dict[str, set[float]] = {"区": set(), "点": set()}
        for key, value in facts_for(data).items():
            unit = "点" if "点" in key else "区"
            buckets[unit].add(float(value))
            union[unit].add(float(value))
        per[data["procedure"]] = buckets
    return per, union


def check_text(path: Path) -> int:
    per, union = numbers_by_procedure()
    lines = path.read_text(encoding="utf-8").splitlines()
    suspect = 0
    current: str | None = None   # 直近に出てきた手続き名

    print(f"=== {path} ===")
    for name, buckets in per.items():
        shown = "／".join(
            f"{unit}: " + "・".join(str(int(v) if v == int(v) else v) for v in sorted(vals))
            for unit, vals in buckets.items())
        print(f"  {name}: {shown}")
    print()

    for lineno, line in enumerate(lines, 1):
        # 手続き名が出てきたら、以降その手続きの数字と比べる
        for name in per:
            if name in line:
                current = name
        known = per[current] if current else union
        scope = current or "（手続き不明・全体と比較）"

        for unit, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                value = float(match.group(1))
                if value in known[unit]:
                    continue
                suspect += 1
                shown = int(value) if value == int(value) else value
                also = [n for n, b in per.items() if value in b[unit] and n != current]
                note = f"（{'・'.join(also)}なら合う）" if also else ""
                print(f"  ⚠️ {path.name}:{lineno} 「{shown}{unit}」は {scope} の実測に無い{note}")
                print(f"      {line.strip()[:90]}")

    print()
    if suspect:
        print(f"要確認 {suspect}件。**実測に無い数字＝必ず誤りとは限らない**"
              "（他の出典の数字や、手続き以外の話かもしれない）。1件ずつ人が見る。")
    else:
        print("実測に無い数字は見つからなかった。")
    return suspect


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", action="store_true", help="いまの実測値を出す")
    parser.add_argument("--text", type=Path, help="突き合わせる文章のファイル")
    parser.add_argument("--strict", action="store_true",
                        help="要確認が1件でもあれば終了コード1で落とす")
    args = parser.parse_args(argv)

    if not args.facts and not args.text:
        parser.print_help()
        return

    if args.facts:
        print_facts()
    if args.text:
        if args.facts:
            print()
        suspect = check_text(args.text)
        if args.strict and suspect:
            sys.exit(1)


if __name__ == "__main__":
    main()

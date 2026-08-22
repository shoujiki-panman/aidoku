"""自治体の基本情報（web/data/municipalities.json）を書き出す。

読めなかった項目があったとき、住民に出せる次の一手は
「区の公式サイトで確かめる」しかない（AI読は答えの本文を持っていない）。
そのためには**区のトップページのURL**が要る。

URLはホスト名から組み立てず、`crawler/targets.json` の `top_url` をそのまま使う。
組み立てると、www の有無やパスの違いで静かに 404 を出す。

    python3 analysis/export_municipalities.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ROOT / "crawler" / "targets.json"
OUT = ROOT / "web" / "data" / "municipalities.json"
WARD = "特別区"


def wards(targets: dict) -> list[dict]:
    out = []
    for m in targets.get("municipalities", []):
        if m.get("type") != WARD or not m.get("top_url"):
            continue
        out.append({
            "id": m["id"],
            "name": m["name"],
            "lg_code": m.get("lg_code"),
            "top_url": m["top_url"],
        })
    # 並びは全国地方公共団体コード順。漢字の文字コード順にしない
    return sorted(out, key=lambda m: m["lg_code"] or "")


def build() -> dict:
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    items = wards(targets)
    return {
        "_about": (
            "東京23区の基本情報。読めなかった項目があったとき、"
            "住民に「区の公式サイトで確かめてください」と案内するために使う。"
            "AI読は答えの本文を持っていないので、案内先は必ず区の公式サイトになる。"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "crawler/targets.json の top_url をそのまま使う（組み立てない）",
        "n": len(items),
        "municipalities": items,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    doc = build()
    args.out.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out}: {doc['n']}区")


if __name__ == "__main__":
    main()

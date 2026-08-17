"""4項目とも読めなかった組について、採点しなかった候補ページに答えが無いかを調べる。

**新規クロールはしない。** `crawler/cache`（取得済み）と `crawler/out/discovery_*.json`
だけを読む。キャッシュに無いURLは飛ばす（取りに行かない）。

`extractor/extract.py` の `pick_page()` は候補25件のうち条件を満たす最初の1件だけを
採点する。残りは取得済みでも読まれない。その残りに答えが載っていないかを見るための道具。

⚠️ これはキーワードによる目視スクリーニングであって、LLMによる判定ではない。
言えるのは「本命ページが別にある可能性が高い」まで。確定にはその候補で抽出をやり直す。

キャッシュは `.gitignore` で除外している（自治体サイトの著作物のため）。
別の作業ツリーに溜めたキャッシュを使うときは `--cache-dir` で渡す。

実行:
    python3 analysis/scan_unpicked_candidates.py
    python3 analysis/scan_unpicked_candidates.py --min-markers 2
    python3 analysis/scan_unpicked_candidates.py --cache-dir /path/to/crawler/cache
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "crawler"))

from polite_fetch import PoliteFetcher  # noqa: E402

# 手続きごとの「答えらしさ」を示す語。拾いすぎないよう、答えの形に近いものだけ。
MARKERS = {
    "tennyu": ["14日以内", "手数料", "無料", "本人確認書類"],
    "jidouteate": ["15日以内", "認定請求", "手数料", "無料"],
    "sodaigomi": ["手数料", "申込", "粗大ごみ処理", "受付"],
}

TAG = re.compile(r"<[^>]+>")


def cached_text(fetcher: PoliteFetcher, url: str) -> str | None:
    """キャッシュにあるものだけ本文を返す。無ければ None（取りに行かない）。"""
    try:
        result = fetcher.fetch(url)
    except Exception:
        return None
    if not getattr(result, "from_cache", False):
        return None
    return TAG.sub(" ", result.body())


def markers_in(text: str, markers: list[str]) -> set[str]:
    return {m for m in markers if m in text}


def scan_municipality(fetcher: PoliteFetcher, candidates: list[dict],
                      scored_url: str, markers: list[str]) -> tuple[dict | None, set[str], int]:
    """採点したページに無く、別の取得済み候補にある語が最も多い候補を返す。"""
    scored_text = cached_text(fetcher, scored_url) or ""
    scored_hits = markers_in(scored_text, markers)

    best: tuple[dict, set[str]] | None = None
    checked = 0
    for candidate in candidates:
        url = candidate.get("url")
        if url == scored_url or candidate.get("is_pdf") or not url:
            continue
        text = cached_text(fetcher, url)
        if text is None:
            continue
        checked += 1
        gained = markers_in(text, markers) - scored_hits
        if gained and (best is None or len(gained) > len(best[1])):
            best = (candidate, gained)

    if best is None:
        return None, set(), checked
    return best[0], best[1], checked


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-markers", type=int, default=1,
                        help="この数以上の語が新たに見つかった組だけ出す")
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="取得済みキャッシュの場所（既定は crawler/cache）")
    parser.add_argument("--discovery-dir", type=Path, default=None,
                        help="探索結果の場所（既定は crawler/out）")
    args = parser.parse_args(argv)

    fetcher = PoliteFetcher(cache_dir=args.cache_dir) if args.cache_dir else PoliteFetcher()
    discovery_dir = args.discovery_dir or (ROOT / "crawler" / "out")
    counts = {"scanned": 0, "hit": 0}

    print(f"{'手続き':12} {'自治体':10} {'新語':>4} {'調べた':>4}  別候補")
    for procedure, markers in MARKERS.items():
        path = ROOT / "web" / "data" / f"scores-{procedure}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for muni in data["municipalities"]:
            if (muni.get("page_status") or {}).get("code") != "target_unconfirmed":
                continue
            counts["scanned"] += 1
            discovery = discovery_dir / f"discovery_{muni['id']}_{procedure}.json"
            if not discovery.exists():
                print(f"{procedure:12} {muni['name']:10} {'-':>4} {'-':>4}  探索JSONが無い")
                continue
            candidates = json.loads(discovery.read_text(encoding="utf-8"))["candidates"]
            best, gained, checked = scan_municipality(
                fetcher, candidates, muni.get("page_url") or "", markers)
            if best is None or len(gained) < args.min_markers:
                continue
            counts["hit"] += 1
            print(f"{procedure:12} {muni['name']:10} {len(gained):4} {checked:4}  "
                  f"{best['link_text'][:26]} {sorted(gained)}")

    print(f"\n4項目とも読めない {counts['scanned']}組 のうち、"
          f"{counts['hit']}組 で採点しなかった取得済みページに答えらしい記載があった"
          f"（語{args.min_markers}個以上）。")
    print("⚠️ キーワードの目視スクリーニング。確定にはその候補で抽出をやり直すこと（Issue #90）。")


if __name__ == "__main__":
    main()

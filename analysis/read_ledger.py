"""探索台帳 — 見つけた候補1本ずつに「読んだ／読まなかった・なぜ」を付ける。

**なぜ要るか**: AI読は「この項目はページに書かれていない」と区について言う。
だが 2026-08-25 に数えたら、転入届では候補592本のうち **読解に渡したのは41本（7%）** だった。
残り551本について、**開かなかった理由がどこにも残っていない。**

記録が無いので「読み切った上で無かった」と言うことが原理的にできない。
点数を出す前に、まず台帳を作る。**台帳は判定を変えない。何を見たかを残すだけ。**

分け方は、**責任の所在**で分ける（対策が変わるから）:

| 印 | 意味 | 直す場所 |
|---|---|---|
| `read` | 読解に渡した | — |
| `shown_not_chosen` | リンク一覧には載せたが、AIが選ばなかった | AIの選び方 / `MAX_FOLLOW` |
| `never_shown` | **一覧にすら載せていない** | **こちら側の欠陥。渡す範囲** |
| `non_html` | PDF/Word/Excel で弾いた | 読む道具（`plans/read-through.md` ③） |
| `unfetchable` | 取得できていない | 探索側 |

★`shown_not_chosen` と `never_shown` を混ぜてはいけない。
  前者は「AIが判断して選ばなかった」、後者は「AIに選ばせてすらいない」。
  混ぜると、こちらの取りこぼしがAIの判断ミスに見える。

    python3 analysis/read_ledger.py --procedure tennyu
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "crawler" / "cache"
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from htmlutil import parse  # noqa: E402

from extractor.fact_extract import MAX_FOLLOW, _prompt_links, keywords_for  # noqa: E402
from extractor.response_contract import is_non_html_url  # noqa: E402

LEDGER_VERSION = "read-ledger-0.1"

# 台帳の印。ここに無い印は付けない（付けたら KeyError で気づく）。
#
# ★`shown_not_chosen` の文言に上限を書くのは、書かないと台帳が嘘をつくから。
#   最初「AIが開かなかった」と書いたが、AIはそもそも MAX_FOLLOW 本しか要求できない。
#   237本を「AIの判断」と読ませると、こちらが設けた上限がAIの落ち度に見える。
REASONS = {
    "read": "読解に渡した",
    "shown_not_chosen": f"リンク一覧に載せたが開かなかった（1ページあたり上限{MAX_FOLLOW}本）",
    "never_shown": "リンク一覧にも載せていない（こちら側の取りこぼし）",
    # ★以前は「PDF/Word/Excel のため弾いた」と書いていた。**いまは弾いていない。**
    #   字形の対応表を使って読めるようになり（PDF 6/7）、抽出にも流している。
    #   台帳だけ古い理由を書き続けると、直したことが伝わらない。
    "non_html": "PDF/Word/Excel（読めるものは本文として渡している）",
    "unfetchable": "取得できていない（大半は robots.txt による拒否）",
}


def cache_html(url: str) -> str | None:
    """既に取ってあるHTML。ネットには出ない。"""
    host = urllib.parse.urlparse(url).netloc
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    path = CACHE / host / f"{key}.html"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def shown_links(urls: list[str], proc_name: str) -> set[str]:
    """AIに実際にリンク一覧として見せたURL。

    ★並べ替えも打ち切りも自分で書かない。本番と同じ `_prompt_links` を呼ぶ。
      ここで再実装すると、台帳と本番がずれた瞬間に台帳が嘘になる。
    """
    kw = keywords_for(proc_name)
    shown: set[str] = set()
    for url in urls:
        html = cache_html(url)
        if html is None:
            continue
        _, hrefs = _prompt_links(parse(html, url).links, kw)
        shown |= hrefs
    return shown


def classify(url: str, status: int | None, cached: bool, read: set[str], shown: set[str]) -> str:
    """候補1本の印。**順番に意味がある。**

    読んだものが最優先。次に型で弾いたもの。次に取得できていないもの。
    最後に「見せたか見せていないか」。逆にすると、読んだPDFが non_html に落ちる。

    キャッシュの有無は呼ぶ側が渡す。ここでファイルを触らないので、テストが書ける。
    """
    if url in read:
        return "read"
    if is_non_html_url(url):
        return "non_html"
    if not status or not cached:
        return "unfetchable"
    return "shown_not_chosen" if url in shown else "never_shown"


def read_urls(extract: dict) -> set[str]:
    """読解に実際に渡したURL（起点＋AIが要求して開いたリンク先）。"""
    return {extract["page"]["url"], *(extract.get("followed_urls") or [])}


def with_missing_reads(entries: list[dict], read: set[str], extract: dict) -> list[dict]:
    """読んだのに候補一覧に載っていないURLを足す。

    ★最初これを起点ページだけで書いて、読んだ41本が台帳では34本になった。
      AIが要求して開いたリンク先は、探索の候補に入っていないことがある
      （探索は hops で切っており、AIはページ内のリンクから直に要求するため）。
      **読んだものが台帳から漏れる台帳は、台帳ではない。**
    """
    known = {e["url"] for e in entries}
    page = extract["page"]
    extra = [{
        "url": url,
        "link_text": page.get("link_text") if url == page["url"] else None,
        "score": None,
        "hops": page.get("hops") if url == page["url"] else None,
        "mark": "read",
        "reason": REASONS["read"],
    } for url in sorted(read - known)]
    return extra + entries


def build_one(discovery: dict, extract: dict) -> dict:
    """1自治体1手続きぶんの台帳。"""
    read = read_urls(extract)
    shown = shown_links(sorted(read), extract["procedure"])
    entries = []
    for cand in discovery.get("candidates") or []:
        url = cand.get("url")
        if not url:
            continue
        mark = classify(url, cand.get("status"), cache_html(url) is not None, read, shown)
        entries.append({
            "url": url,
            "link_text": cand.get("link_text"),
            "score": cand.get("score"),
            "hops": cand.get("hops"),
            "mark": mark,
            "reason": REASONS[mark],
        })
    entries = with_missing_reads(entries, read, extract)
    return {
        "municipality": extract["municipality"],
        "municipality_id": extract["municipality_id"],
        "entries": entries,
        "counts": tally(entries),
    }


def tally(entries: list[dict]) -> dict:
    """印ごとの本数。**印は必ず5つとも出す**（0本のものが消えると読み違える）。"""
    counts = dict.fromkeys(REASONS, 0)
    for e in entries:
        counts[e["mark"]] += 1
    return counts


def merge_counts(rows: list[dict]) -> dict:
    total = dict.fromkeys(REASONS, 0)
    for row in rows:
        for mark, n in row["counts"].items():
            total[mark] += n
    return total


def load_pairs(procedure: str) -> list[tuple[dict, dict]]:
    """探索結果と抽出結果を自治体で突き合わせる。片方しか無いものは捨てずに報告する。"""
    extracts = {}
    for path in sorted(glob.glob(str(ROOT / f"extractor/out/*_{procedure}.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        extracts[doc["municipality_id"]] = doc
    pairs = []
    for path in sorted(glob.glob(str(ROOT / f"crawler/out/discovery_*_{procedure}.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        found = extracts.get(doc["municipality_id"])
        if found is None:
            print(f"  ! 抽出結果が無い: {doc['municipality']}", file=sys.stderr)
            continue
        pairs.append((doc, found))
    return pairs


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    args = ap.parse_args(argv)

    rows = [build_one(d, e) for d, e in load_pairs(args.procedure)]
    total = merge_counts(rows)
    doc = {
        "_about": "探索が見つけた候補1本ごとに、読解へ渡したかどうかと、渡さなかった理由。"
                  "判定はしていない。何を見たかの記録。",
        "ledger_version": LEDGER_VERSION,
        "procedure": args.procedure,
        "reasons": REASONS,
        "summary": {
            "municipalities": len(rows),
            "entries": sum(len(r["entries"]) for r in rows),
            "by_mark": total,
        },
        "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"ledger_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = doc["summary"]
    print(f"{args.procedure}: {s['municipalities']}自治体 / 候補 {s['entries']}本")
    for mark, n in s["by_mark"].items():
        print(f"  {n:5}  {mark:18} {REASONS[mark]}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

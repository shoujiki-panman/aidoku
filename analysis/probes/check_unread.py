"""読ませなかった候補の中に、答えが書いてあったか（LLMを1回も呼ばない）。

**なぜ要るか**: AI読は「23区中22区が転入届の手数料を書いていない」と言ってきた。
だがそれは **うちの読み取り器が「記載なし」と言った** だけである。

探索は転入届だけで 592本の候補を見つけ、うち558本は本文200字超で取得済み。
**読み取り器に渡したのは41本（7%）。** 残りは開かれもせず、
「なぜ開かなかったか」もどこにも記録されていない。

だから「書いていない」と「読み落とした」が分かれていない。

**このスクリプトはLLMを呼ばない。** キャッシュ済みの本文を機械的に見るだけ。
ここで手がかりが出た区は、**うちが読み落とした疑いが確定する。**

    python3 analysis/probes/check_unread.py --procedure tennyu --field 手数料
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "crawler" / "cache"

sys.path.insert(0, str(ROOT / "crawler"))
import htmlutil  # noqa: E402

# ★語は「答えの形」ではなく「答えが載る場所の形」で選ぶ。
#   金額の形（\d+円）を入れると児童手当の支給額まで拾って数が3倍になった実績がある
#   （plans/decisions/table-reading.md）。ここでは手数料の見出し語だけにする。
FIELD_HINTS = {
    "手数料": [r"手数料", r"費用", r"無料", r"かかりません"],
    "必要書類": [r"必要な?もの", r"持ち物", r"必要書類", r"お持ちください"],
    "期限": [r"以内に", r"期限", r"までに(届出|申請)"],
    "窓口オンライン可否": [r"オンライン", r"電子申請", r"窓口", r"受付時間"],
}


def cache_text(url: str) -> str | None:
    """既に取ってあるHTMLから本文だけ取り出す。ネットには出ない。"""
    host = urllib.parse.urlparse(url).netloc
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    p = CACHE / host / f"{key}.html"
    if not p.exists():
        return None
    try:
        return htmlutil.parse(p.read_text(encoding="utf-8", errors="replace"), url).text
    except Exception:                                     # noqa: BLE001
        return None


def hits(text: str, pats: list[str]) -> list[str]:
    """語の周りを1行ぶん切り出す。人が読んで判断できる形で残す。"""
    out = []
    for pat in pats:
        for m in re.finditer(pat, text):
            s = max(0, m.start() - 40)
            out.append(re.sub(r"\s+", " ", text[s:m.end() + 60]).strip())
            break                                         # 1語1件でよい
    return out


def read_urls(procedure: str) -> dict[str, set[str]]:
    """読み取り器が実際に開いたURL（自治体ごと）。

    ★起点ページに到達できなかった区は `page` が null で、開いたURLが1本も無い
      （粗大ごみの江戸川区・八王子市）。`d["page"]["url"]` で落ちていた。
      `analysis/sweep.py` の `reached()` で直したのと同じ誤り。
      **「読んでいない」と「たどり着けなかった」を混ぜない。** 空集合として持つ。
    """
    out: dict[str, set[str]] = {}
    for f in sorted(glob.glob(str(ROOT / f"extractor/out/*_{procedure}.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        page = d.get("page") or {}
        urls = {page["url"], *(d.get("followed_urls") or [])} if page.get("url") else set()
        out[d["municipality"]] = urls
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", default="tennyu")
    ap.add_argument("--field", default="手数料")
    args = ap.parse_args(argv)

    pats = FIELD_HINTS[args.field]
    opened_by_muni = read_urls(args.procedure)
    rows = []

    for f in sorted(glob.glob(str(ROOT / f"crawler/out/discovery_*_{args.procedure}.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        muni = d["municipality"]
        opened = opened_by_muni.get(muni, set())
        found = []
        unread = 0
        for c in d["candidates"]:
            url = c.get("url")
            if not url or url in opened:
                continue
            unread += 1
            text = cache_text(url)
            if not text:
                continue
            h = hits(text, pats)
            if h:
                found.append({"url": url, "link_text": c.get("link_text"),
                              "score": c.get("score"), "hits": h})
        rows.append({"municipality": muni, "unread": unread,
                     "opened": len(opened), "found_in_unread": found})

    n_suspect = sum(1 for r in rows if r["found_in_unread"])
    doc = {
        "_about": "読み取り器に渡さなかった候補ページの本文に、"
                  "その項目の手がかりがあったか。LLMは使っていない。"
                  "手がかり＝答えではない。人が本文を読んで確かめる必要がある。",
        "procedure": args.procedure, "field": args.field, "patterns": pats,
        "summary": {
            "municipalities": len(rows),
            "opened_total": sum(r["opened"] for r in rows),
            "unread_total": sum(r["unread"] for r in rows),
            # ★見出しの数字: 読ませなかったページに手がかりがあった自治体
            "with_hit_in_unread": n_suspect,
        },
        "rows": rows,
    }
    # 出力は他の道具と同じ analysis/out/ に置く。ここだけ analysis/ 直下だった。
    out_dir = ROOT / "analysis" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"unread_{args.procedure}_{args.field}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = doc["summary"]
    print(f"{args.procedure} / {args.field}")
    print(f"  自治体            : {s['municipalities']}")
    print(f"  読み取り器に渡した : {s['opened_total']}ページ")
    print(f"  渡さなかった      : {s['unread_total']}ページ")
    print(f"  ★渡さなかったページに手がかりがあった自治体: {s['with_hit_in_unread']}")
    print(f"\n→ {out}")
    for r in rows:
        if r["found_in_unread"]:
            print(f"\n  {r['municipality']}  ({len(r['found_in_unread'])}ページ)")
            for x in r["found_in_unread"][:2]:
                print(f"    {x['link_text']}")
                for h in x["hits"][:2]:
                    print(f"      … {h[:110]}")


if __name__ == "__main__":
    main()

"""リンクの並べ替えで、渡せるようになったリンクを数える。

AIを呼ばずに測る。採点済みページはキャッシュにあり、
「AIに渡した40件に何が入っていたか」は、その場で組み直せる。

  前: ページに出てきた順で40件（地域ナビゲーションで埋まる）
  後: 手続きページらしい順に並べ替えてから40件

数えるのは「手続きの名前（strong語）を含むのに、前は渡せていなかったリンク」。
それが渡るようになれば、AIが辿れる可能性が出る。**点が上がるとは言っていない。**
実際に読めるかは測り直さないと分からない。

    python3 analysis/check_link_order.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from discover import score_link  # noqa: E402
from extractor.fact_extract import MAX_LINKS, keywords_for  # noqa: E402
from htmlutil import parse  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402


def uniq_links(links: list) -> list:
    seen, out = set(), []
    for link in links:
        if not link.text or link.href in seen:
            continue
        seen.add(link.href)
        out.append(link)
    return out


def has_strong(link, kw: dict) -> bool:
    return any(w in link.text for w in kw["strong"])


def compare(links: list, kw: dict) -> dict:
    """前後で渡せる40件がどう変わるか。"""
    u = uniq_links(links)
    before = u[:MAX_LINKS]
    after = sorted(u, key=lambda x: -score_link(x.text, x.href, kw))[:MAX_LINKS]
    b, a = {x.href for x in before}, {x.href for x in after}
    gained = [x for x in u if x.href in a - b and has_strong(x, kw)]
    lost = [x for x in u if x.href in b - a and has_strong(x, kw)]
    return {
        "links": len(u),
        "strong_total": sum(1 for x in u if has_strong(x, kw)),
        "strong_before": sum(1 for x in before if has_strong(x, kw)),
        "strong_after": sum(1 for x in after if has_strong(x, kw)),
        "gained": [(x.text, x.href) for x in gained],
        "lost": [(x.text, x.href) for x in lost],
    }


def main() -> None:
    fetcher = PoliteFetcher()
    procs = json.loads((ROOT / "web/data/procedures.json").read_text(encoding="utf-8"))["procedures"]
    rows, no_cache = [], 0
    for p in procs:
        doc = json.loads((ROOT / f"web/data/{p['file']}").read_text(encoding="utf-8"))
        kw = keywords_for(p["name"])
        for m in doc["municipalities"]:
            url = m.get("page_url")
            if not url:
                continue
            res = fetcher.cached(url)
            if not res:
                no_cache += 1
                continue
            r = compare(parse(res.body(), url).links, kw)
            r.update(municipality=m["name"], procedure=p["name"])
            rows.append(r)

    changed = [r for r in rows if r["gained"]]
    print(f"  調べたセル: {len(rows)}（キャッシュ無し {no_cache}）")
    print(f"  40件の中身が変わったセル: {sum(1 for r in rows if r['gained'] or r['lost'])}")
    print(f"  手続き名を含むリンクを、新しく渡せるようになったセル: {len(changed)}")
    print(f"  そのリンクの総数: {sum(len(r['gained']) for r in changed)}")
    print(f"  逆に渡せなくなった（手続き名つき）: {sum(len(r['lost']) for r in rows)}")
    print()
    for r in sorted(changed, key=lambda r: -len(r["gained"]))[:12]:
        print(f"  {r['municipality']}・{r['procedure']}"
              f"（リンク{r['links']}件中 手続き名つき {r['strong_before']}→{r['strong_after']}）")
        for text, href in r["gained"][:3]:
            print(f"      + {text[:26]} → {href[:76]}")


if __name__ == "__main__":
    main()

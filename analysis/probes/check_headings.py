"""見出しで中身にたどれるか（達成基準 2.4.6 の対応づけ）。

**なぜ要るか**: `plans/jis-mapping.md` で対応づけた4件のうち、
**2.4.6 見出し及びラベル（レベルAA）だけ測っていなかった。**
対応づけただけで数が無いと、職員に渡せない。2.4.4 は測って
「AI読が見ている問題の主因ではなかった」と分かった（4.2% / 2.7%）。同じことをする。

**測るもの**: **AIが実際に読んだページ**（起点＋追従）の見出しだけを見る。
サイト全体ではない。AIも住民も、開いたページの中でしか探せない。

★**これは適合試験ではない。** 2.4.6 は「見出し及びラベルは、主題又は目的を説明している」
  であって、**説明できているかは人が読んで決める**。ここで数えるのは
  **機械で確実に言える2つだけ**:

      見出しが1つも無いページ   → 見出しでは中身にたどれない
      中身が空の見出し           → 主題の説明になりようがない

★**「お知らせ」「その他」のような一般的な見出しは数えない。**
  リンク題で同じことをやって間違えた（`analysis/probes/check_link_text.py`）。
  「相談窓口」「印鑑登録」を欠陥として73本数えたが、中身を見たら十分わかるものだった。
  **語の一般性で意味は測れない。** 参考値としてだけ出す。

    python3 analysis/probes/check_headings.py --procedure tennyu
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT / "analysis"))
from htmlutil import parse  # noqa: E402
from read_ledger import cache_html  # noqa: E402

VERSION = "headings-0.1"

CRITERION = "2.4.6 見出し及びラベル（レベルAA）"

# 参考値として数えるだけの見出し。**欠陥にはしない。**
GENERIC = ("お知らせ", "その他", "関連情報", "関連リンク", "メニュー", "ナビゲーション")


def page_headings(html: str, url: str) -> list[dict]:
    """ページの見出し。取れなければ空。"""
    try:
        return [{"level": h.level, "text": (h.text or "").strip()}
                for h in parse(html, url).headings]
    except Exception:                                      # noqa: BLE001
        return []


def marks(headings: list[dict]) -> dict:
    """1ページぶんの印。**機械で確実に言えることだけ数える。**"""
    empty = [h for h in headings if not h["text"]]
    generic = [h for h in headings if h["text"] in GENERIC]
    return {
        "headings": len(headings),
        # ★見出しが1本も無い ＝ 見出しでは中身にたどれない
        "no_headings": not headings,
        "empty": len(empty),
        "has_h1": any(h["level"] == 1 for h in headings),
        # 参考値。欠陥として数えない
        "generic_not_counted": len(generic),
    }


def read_pages(procedure: str) -> list[tuple[str, str]]:
    """AIが実際に読んだページ（自治体名, URL）。起点＋追従。

    ★候補ではなく**読んだページ**を見る。読んでいないページの見出しを数えても、
      AIがそこでつまずいた証拠にはならない。
    """
    out = []
    for path in sorted(glob.glob(str(ROOT / f"extractor/out/extract_*_{procedure}.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        page = doc.get("page") or {}
        if not page.get("url"):
            continue                                       # 起点に到達していない区
        for url in [page["url"], *(doc.get("followed_urls") or [])]:
            out.append((doc["municipality"], url))
    return out


def summarize(rows: list[dict]) -> dict:
    pages = len(rows)
    no_headings = sum(1 for r in rows if r["no_headings"])
    empty = sum(r["empty"] for r in rows)
    return {
        "pages": pages,
        # ★数えるのはこの2つだけ
        "pages_without_headings": no_headings,
        "pages_without_headings_ratio": round(no_headings / pages, 3) if pages else 0.0,
        "empty_headings": empty,
        "pages_with_empty_heading": sum(1 for r in rows if r["empty"]),
        # 参考値
        "pages_without_h1": sum(1 for r in rows if not r["has_h1"]),
        "generic_not_counted": sum(r["generic_not_counted"] for r in rows),
        "headings_total": sum(r["headings"] for r in rows),
        "municipalities": len({r["municipality"] for r in rows}),
        "unreadable_pages": sum(1 for r in rows if r["unreadable"]),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    args = ap.parse_args(argv)

    rows = []
    for muni, url in read_pages(args.procedure):
        html = cache_html(url)
        # ★取得できていないページは「見出しが無い」に混ぜない。別に数える。
        #   混ぜると、こちらが取れていないことが区の欠陥に見える。
        if not html:
            rows.append({"municipality": muni, "url": url, "unreadable": True,
                         "headings": 0, "no_headings": False, "empty": 0,
                         "has_h1": False, "generic_not_counted": 0})
            continue
        got = marks(page_headings(html, url))
        rows.append({"municipality": muni, "url": url, "unreadable": False, **got})

    doc = {
        "_about": "AIが読んだページの見出しの記録。適合試験ではない。"
                  "2.4.6 は主題を説明しているかであり、説明できているかは人が読んで決める。"
                  "ここで数えるのは機械で確実に言える2つ（見出しが無い・空の見出し）だけ。",
        "version": VERSION, "procedure": args.procedure, "criterion": CRITERION,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"headings_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = doc["summary"]
    print(f"{args.procedure}: {s['municipalities']}自治体 / 読んだページ {s['pages']}")
    print(f"  ★見出しが1つも無いページ: {s['pages_without_headings']}"
          f"（{s['pages_without_headings_ratio'] * 100:.1f}%）")
    print(f"  ★空の見出し: {s['empty_headings']}本"
          f"（{s['pages_with_empty_heading']}ページ）")
    print(f"  見出しの総数: {s['headings_total']}")
    print(f"  参考: h1 が無いページ {s['pages_without_h1']} / "
          f"一般的な見出し {s['generic_not_counted']}本（欠陥として数えない）")
    print(f"  取得できていないページ: {s['unreadable_pages']}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

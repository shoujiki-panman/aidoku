"""区の検索窓が、ブラウザを持たないAIから使えるか。

**なぜ要るか**: 住民のAIが最初にやることの一つが「サイト内検索に語を入れる」である。
だが AI読はいままで**リンクしか辿っていない**。検索窓を一度も使っていない。

使えるなら使うべきだが、**使えるかどうかを先に測る。**

    URLで叩ける検索   → こちらでも使える。次に実装する価値がある
    Google カスタム検索 → 結果はJavaScriptで描かれる。**ブラウザが要る**
    検索窓が無い       → そもそも使えない

★これは適合試験ではない。**取得済みの起点ページのHTMLを見て分類するだけ**で、
  実際に検索して結果を確かめてはいない。分類の根拠（form の抜粋）を残すので、
  人が見て確かめられる。

★**判定に使わない。** 点数には入れない。次に何を作るかを決めるための材料。

    python3 analysis/check_search.py
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

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "crawler" / "cache"
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))

VERSION = "check-search-0.1"
PROCEDURES = ("tennyu", "jidouteate", "sodaigomi")

# 検索の入力欄らしい form。名前は実物から拾った。
SEARCH_FORM = re.compile(
    r'<form[^>]*>(?:(?!</form>).){0,900}?</form>', re.I | re.S)
SEARCH_HINT = re.compile(
    r'type=["\']search|name=["\'](?:q|kw|keyword|search|query)["\']', re.I)
# Google カスタム検索（Programmable Search）の印。結果はJSで描かれる。
GOOGLE_CSE = re.compile(
    r'name=["\']cx["\']|cse\.google\.com|programmablesearchengine', re.I)
# こちらから叩けそうな action（サーバ側で結果を返す形）
SERVER_SIDE = re.compile(r'action=["\'][^"\']*\.(?:html|php|aspx|do|cgi)', re.I)
# 送り先が `#` や `/#` だけ。**JavaScript でしか動かない。**
JS_ONLY = re.compile(r'action=["\'][^"\']*#["\']', re.I)
# 区の外の検索サービスに投げる形（Google 本体・自治体向け検索ASPなど）。
EXTERNAL = re.compile(r'action=["\']https?://(?!(?:www\.)?city\.)[^"\']+', re.I)

KINDS = ("url_search", "google_cse", "external", "js_only", "no_search", "other")
LABEL = {
    "url_search": "区自身のURLで叩ける検索（こちらでも使える）",
    "google_cse": "Google カスタム検索（JavaScript が要る）",
    "external": "区の外の検索サービスに投げる",
    "js_only": "送り先が # のみ（JavaScript でしか動かない）",
    "no_search": "検索窓が見つからない",
    "other": "その他（形が判別できない）",
}


def search_form(html: str) -> str | None:
    """検索の入力欄らしい form を1つ返す。無ければ None。"""
    for match in SEARCH_FORM.finditer(html):
        if SEARCH_HINT.search(match.group(0)):
            return match.group(0)
    return None


def classify(html: str) -> tuple[str, str]:
    """（印, 根拠の抜粋）。**根拠を必ず返す**（人が確かめられるように）。

    ★`google_cse` を先に見る。CSE の form も action は .html なので、
      順番を逆にすると全部「URLで叩ける」になる。
    """
    form = search_form(html)
    if form is None:
        return "no_search", ""
    excerpt = re.sub(r"\s+", " ", form)[:160]
    if GOOGLE_CSE.search(form) or GOOGLE_CSE.search(html[:20000]):
        return "google_cse", excerpt
    # ★`#` を先に見る。`action="/#"` は SERVER_SIDE に当たらないが、
    #   当たる形が増えたときに順番で結果が変わらないよう、明示的に先へ置く。
    if JS_ONLY.search(form):
        return "js_only", excerpt
    if EXTERNAL.search(form):
        return "external", excerpt
    if SERVER_SIDE.search(form):
        return "url_search", excerpt
    return "other", excerpt


def cached_html(url: str) -> str | None:
    host = urllib.parse.urlparse(url).netloc
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    path = CACHE / host / f"{key}.html"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def entry_pages() -> dict[str, str]:
    """自治体ごとの起点ページ。**1自治体1本**（重複して数えない）。"""
    out: dict[str, str] = {}
    for procedure in PROCEDURES:
        for path in sorted(glob.glob(str(ROOT / f"extractor/out/extract_*_{procedure}.json"))):
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            page = doc.get("page") or {}
            if page.get("url") and doc["municipality"] not in out:
                out[doc["municipality"]] = page["url"]
    return out


def summarize(rows: list[dict]) -> dict:
    counts = dict.fromkeys(KINDS, 0)
    for row in rows:
        counts[row["kind"]] += 1
    usable = counts["url_search"]
    return {
        "municipalities": len(rows),
        "by_kind": counts,
        # ★こちらから使えるのはこれだけ
        "usable_without_browser": usable,
        "needs_browser": counts["google_cse"],
        "names": {kind: [r["municipality"] for r in rows if r["kind"] == kind]
                  for kind in KINDS},
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = []
    for municipality, url in entry_pages().items():
        html = cached_html(url)
        if html is None:
            continue
        kind, excerpt = classify(html)
        rows.append({"municipality": municipality, "url": url,
                     "kind": kind, "evidence": excerpt})

    doc = {
        "_about": "区の検索窓が、ブラウザを持たないAIから使えるかの記録。"
                  "適合試験ではない。起点ページのHTMLを見て分類しただけで、"
                  "実際に検索して確かめてはいない。判定には使わない。",
        "version": VERSION, "labels": LABEL,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "search_forms.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(doc["summary"], ensure_ascii=False, indent=2))
        return
    s = doc["summary"]
    print(f"{s['municipalities']}自治体の検索窓")
    for kind, n in s["by_kind"].items():
        print(f"  {n:3}  {LABEL[kind]}")
        if s["names"][kind]:
            print(f"       {'・'.join(s['names'][kind])}")
    print(f"\n  ブラウザ無しで使える: {s['usable_without_browser']}")
    print(f"  ブラウザが要る:       {s['needs_browser']}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

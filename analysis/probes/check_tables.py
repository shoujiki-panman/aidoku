"""表読みで、AIに渡る入力がどう変わるかを数える。

**新規クロールもLLM呼び出しもしない。** `crawler/out/discovery_*.json` と
取得済みの `crawler/cache` だけを読む。キャッシュに無いURLは飛ばす。

2つのことを数える。

1. **表の中にしかない項目**
   4項目それぞれの「答えらしさ」を示す語が、`<table>` の中にはあり、
   表を取り除いた本文には無いセル。いまのAIには、その語は本文の平文として
   1行ずつ届いていて、**どの見出しの列の値かは潰れている**。

2. **表読みで新しく渡るもの**
   `extractor/fact_extract.table_section()` を実物のまま呼び、
   本文の枠（`MAX_TEXT_CHARS`）を守った上で何字ぶんの表が渡るようになるか、
   逆に本文が削れるセルが無いかを見る。

⚠️ これはキーワードによる目視スクリーニングであって、LLMによる判定ではない。
言えるのは「渡せるようになった／渡せなくなった」までで、
**点数がどう動くかは、測り直すまで言えない。**（武器①のときと同じ約束）

実行:
    python3 analysis/probes/check_tables.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from htmlutil import parse, tables_text  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

from extractor.extract import pick_page  # noqa: E402
from extractor.fact_extract import MAX_TEXT_CHARS, table_section  # noqa: E402
from fact_types import EXTRACTOR_KEYS  # noqa: E402

# 採点対象の3手続き。避難所（探索だけ済み）はまだ4項目を測っていないので外す。
PROCEDURES = ("tennyu", "jidouteate", "sodaigomi")

# 4項目それぞれの「答えらしさ」を示す語。拾いすぎないよう、答えの形に近いものだけ。
# キーは fact_types.json の extractor_key（4項目の表記はあそこ以外に書かない）。
#
# ★手数料に「\d+円」を入れたら、児童手当の支給額の表（15,000円）まで
#   「手数料が表の中にしかない」と数えた。金額の形は答えの形ではない。外した。
MARKERS: dict[str, tuple[str, ...]] = {
    "必要書類": (r"本人確認書類", r"マイナンバーカード", r"持ち物",
                 r"必要なもの", r"転出証明書", r"届出に必要"),
    "窓口オンライン可否": (r"オンライン", r"電子申請", r"郵送", r"マイナポータル"),
    "期限": (r"\d+日以内", r"\d+か月以内", r"提出期限", r"申請期限", r"締切"),
    "手数料": (r"手数料", r"無料"),
}

# 内側から順に消せるよう、入れ子の <table> を含まない table だけに当てる。
TABLE_BLOCK = re.compile(r"(?is)<table\b[^>]*>(?:(?!<table\b).)*?</table>")


def strip_tables(html_text: str) -> str:
    """表を取り除いたHTMLを返す。内側の表から順に消して入れ子も落とす。"""
    previous = None
    while previous != html_text:
        previous = html_text
        html_text = TABLE_BLOCK.sub(" ", html_text)
    return html_text


def markers_in(text: str, patterns: tuple[str, ...]) -> set[str]:
    return {pattern for pattern in patterns if re.search(pattern, text)}


def table_only_facts(table_text: str, outside_text: str) -> list[str]:
    """表の中にはあり、表を除いた本文には無い項目を返す。"""
    found = []
    for key in EXTRACTOR_KEYS:
        patterns = MARKERS[key]
        if markers_in(table_text, patterns) - markers_in(outside_text, patterns):
            found.append(key)
    return found


def inspect(body: str, url: str) -> dict:
    """1ページぶん。表の中身と、実際にAIへ渡る表テキストを両方見る。"""
    page = parse(body, url)
    whole = tables_text(page.tables)
    outside = parse(strip_tables(body), url).text
    passed = table_section(page.text, page.tables)
    body_before = page.text[:MAX_TEXT_CHARS]      # 表読みを入れる前に渡していた本文
    body_after = page.text[:MAX_TEXT_CHARS]       # 入れた後（本文の切り方は変えていない）
    return {
        "n_tables": len(page.tables),
        "text_len": len(page.text),
        "table_len": len(whole),
        "passed_len": len(passed),
        "clipped": 0 < len(passed) < len(whole),
        "blocked": len(whole) > 0 and not passed,
        "body_lost": len(body_before) - len(body_after),
        "total_len": len(body_after) + len(passed),
        "table_only": table_only_facts(whole, outside),
    }


def cells(fetcher: PoliteFetcher) -> tuple[list[dict], int, int]:
    """採点対象のセルを、キャッシュにあるものだけ順に返す。"""
    rows, no_cache, no_page = [], 0, 0
    for path in sorted((ROOT / "crawler" / "out").glob("discovery_*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc["procedure_id"] not in PROCEDURES:
            continue
        page = pick_page(doc)
        if page is None:
            no_page += 1
            continue
        result = fetcher.cached(page["url"])
        if result is None or not result.body_path:
            no_cache += 1
            continue
        row = inspect(result.body(), page["url"])
        row.update(municipality=doc["municipality"], procedure=doc["procedure"])
        rows.append(row)
    return rows, no_cache, no_page


def report(rows: list[dict], no_cache: int, no_page: int) -> list[str]:
    """数えた結果を、主張を足さずに並べる。"""
    only = [row for row in rows if row["table_only"]]
    gained = [row for row in only if row["passed_len"]]
    passed = [row for row in rows if row["passed_len"]]
    return [
        f"  調べたセル: {len(rows)}（キャッシュ無し {no_cache} / 採点対象ページ無し {no_page}）",
        f"  表があるセル: {sum(1 for row in rows if row['n_tables'])}",
        f"  4項目のどれかが表の中にしかないセル: {len(only)}",
        f"    うち表読みで見出しつきの表が渡るようになるセル: {len(gained)}",
        f"    その項目数の合計: {sum(len(row['table_only']) for row in gained)}",
        f"  見出しつきの表が新しく渡るセル（全体）: {len(passed)}",
        f"    渡す表の総字数: {sum(row['passed_len'] for row in passed)}",
        f"  失うもの — 本文が削れたセル: {sum(1 for row in rows if row['body_lost'])}",
        f"  失うもの — 表が枠に入りきらず途中で切れたセル: {sum(1 for row in rows if row['clipped'])}",
        f"  失うもの — 表が1字も渡らなかったセル: {sum(1 for row in rows if row['blocked'])}",
        f"  上限超過（本文＋表 > {MAX_TEXT_CHARS}字）のセル: "
        f"{sum(1 for row in rows if row['total_len'] > MAX_TEXT_CHARS)}",
    ]


def main() -> None:
    rows, no_cache, no_page = cells(PoliteFetcher())
    print("\n".join(report(rows, no_cache, no_page)))
    print()
    only = sorted((row for row in rows if row["table_only"]),
                  key=lambda row: -len(row["table_only"]))
    for row in only:
        print(f"  {row['municipality']}・{row['procedure']}"
              f"（表{row['n_tables']}個 / 本文{row['text_len']}字 /"
              f" 渡す表{row['passed_len']}字）")
        print(f"      表の中にしかない: {'・'.join(row['table_only'])}")


if __name__ == "__main__":
    main()

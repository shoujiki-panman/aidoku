"""AIが出した根拠（evidence）が、実際にページに書いてあるかを照合する。

なぜ要るか:
  `extractor/prompt.md` は「evidence は本文からの引用」と指示しているが、
  **その引用が実在するかを確かめるコードが無かった。**
  つまり AI が根拠を作り出しても検出できない状態だった。
  「測る道具の方も測っている」と言っている以上、ここは空けておけない。

判定は3段で緩める。**厳しすぎると、正しい引用まで落ちる。**

  exact      本文にそのまま含まれる
  normalized 空白・全角半角・記号のゆれを吸収すると含まれる
  partial    連続する部分文字列が MIN_RUN 文字ぶん一致する（引用全体は未確認）
  missing    どれにも当たらない ← 捏造の疑い

**missing でも「捏造だ」と断定はしない。**リンク先ページを読んで引用した場合など、
渡した本文に無い正当なケースがある。判定はフラグであって断罪ではない。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

# 部分一致とみなす最短の連続長。
# 最初 20 にしたら、正当な引用（19文字一致）が missing に落ちた。
#   引用「各総合支所くみん窓口、各出張所の受付窓口で手続きできます」
#   本文「各総合支所くみん窓口、各出張所の受付窓口（10か所）で受付しています」
# 前半19文字は本文そのままで、後半だけ言い換えている。これを捏造扱いにすると
# 「捏造が多い」という誤った結論が出る。15 に下げた。
# 日本語15文字の連続一致は偶然では起きない（捏造側のテストは通ったまま）。
MIN_RUN = 15

# 引用としてまともに扱う最短長。これ未満は判定しない（「無料」等の2文字は
# 本文のどこにでもあり、照合しても意味が無い）
MIN_EVIDENCE_LEN = 8

# extractor が LLM に渡す本文と、既存結果の再照合で読む本文の上限を揃える。
MAX_TEXT_CHARS_PER_PAGE = 18000


def truncate_page_text(text: str) -> str:
    """LLMへ渡す1ページぶんと同じ長さに切る。"""
    return text[:MAX_TEXT_CHARS_PER_PAGE]


def normalize(s: str) -> str:
    """空白・全角半角・記号のゆれを落とす。

    自治体サイトは全角スペース・改行・波ダッシュのゆれが多く、
    そのまま比較すると正しい引用まで missing になる。
    """
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    # 句点を消すと、別々の文をつないだ架空の引用まで一致してしまう。
    # 表記だけを揃え、文の境界自体は残す。
    s = re.sub(r"[.!?;。]+", "。", s)
    # 引用時に付きやすい記号を落とす（本文と引用で揺れる）
    s = re.sub(r"[「」『』（）()\[\]【】、,・:：\-−–—ー~〜*＊]", "", s)
    return s


def longest_common_run(a: str, b: str) -> int:
    """a と b の最長共通部分文字列の長さ。

    素朴なDPだと 18,000字 × 200字 で重い。evidence 側が短いので、
    evidence の各開始位置から本文に対して最長前方一致を伸ばす方式にする。
    """
    best = 0
    for i in range(len(a)):
        if len(a) - i <= best:      # 残りが best 以下なら、もう更新できない
            break
        # いまの best を超えられるかだけ試す。超えられるなら伸ばす。
        n = best
        while i + n < len(a) and a[i:i + n + 1] in b:
            n += 1
        best = max(best, n)
    return best


def check_one(evidence: object, page_text: str) -> dict:
    """1つの evidence を照合する。"""
    if not isinstance(evidence, str):
        return {"verdict": "not_checked", "run": 0,
                "note": "evidence が文字列でないため照合できない"}
    ev = evidence.strip()
    if len(ev) < MIN_EVIDENCE_LEN:
        return {"verdict": "too_short", "run": len(ev),
                "note": f"{MIN_EVIDENCE_LEN}文字未満は照合しない"}

    if ev in page_text:
        return {"verdict": "exact", "run": len(ev), "note": ""}

    nev, npage = normalize(ev), normalize(page_text)
    if nev and nev in npage:
        return {"verdict": "normalized", "run": len(nev),
                "note": "空白・記号のゆれを吸収すると一致"}

    run = longest_common_run(nev, npage)
    if run >= MIN_RUN:
        return {"verdict": "partial", "run": run,
                "note": f"連続{run}文字だけ一致。引用全体は確認できない"}

    return {"verdict": "missing", "run": run,
            "note": "本文に見当たらない。渡していないページからの引用か、根拠の捏造"}


# 引用全体が本文にあると確認できた判定。partial はここに含めない。
VERIFIED_VERDICTS = ("exact", "normalized")
VERDICT_PRIORITY = {
    "exact": 5,
    "normalized": 4,
    "partial": 3,
    "missing": 2,
    "too_short": 1,
    "not_checked": 0,
}


def check_one_across_pages(evidence: object, page_texts: Sequence[str]) -> dict:
    """ページを混ぜずに照合し、最も強い一致を返す。"""
    if not page_texts:
        return {"verdict": "not_checked", "run": 0,
                "note": "照合対象ページが無いため照合できない"}
    checks = [check_one(evidence, page_text) for page_text in page_texts]
    return max(
        checks,
        key=lambda check: (VERDICT_PRIORITY[check["verdict"]], check["run"]),
    )


def check_item(item: object, page_texts: Sequence[str]) -> dict:
    """1項目を検証し、不正な入力は not_checked に落とす。"""
    if not isinstance(item, dict):
        return {"verdict": "not_checked", "run": 0,
                "note": "item がオブジェクトでないため照合できない"}
    found = item.get("found")
    if found is False:
        return {"verdict": "not_applicable", "run": 0,
                "note": "found=false のため照合しない"}
    if found is not True:
        return {"verdict": "not_checked", "run": 0,
                "note": "found が真偽値でないため照合できない"}
    return check_one_across_pages(item.get("evidence"), page_texts)


def check_items_across_pages(items: dict, page_texts: Sequence[str]) -> dict:
    """extract の items 全体を、ページごとに独立して照合する。

    found=false のとき evidence は「なぜ無いか」の説明であって引用ではないので、
    照合対象にしない（`extractor/prompt.md` の failure_reason の設計に合わせる）。
    """
    if not isinstance(items, dict):
        raise TypeError("items はオブジェクトでなければならない")
    return {key: check_item(item, page_texts) for key, item in items.items()}


def check_items(items: dict, page_text: str) -> dict:
    """後方互換用: 1ページだけの items を照合する。"""
    return check_items_across_pages(items, [page_text])


def summarize(checks: dict) -> dict:
    """1出力ぶんの照合結果をまとめる。"""
    considered = [c for c in checks.values()
                  if c["verdict"] not in ("not_applicable", "not_checked")]
    verified = [c for c in considered if c["verdict"] in VERIFIED_VERDICTS]
    return {
        "checked": len(considered),
        "verified": len(verified),
        "partial": sum(1 for c in considered if c["verdict"] == "partial"),
        "missing": sum(1 for c in considered if c["verdict"] == "missing"),
        "too_short": sum(1 for c in considered if c["verdict"] == "too_short"),
        "not_checked": sum(1 for c in checks.values() if c["verdict"] == "not_checked"),
        "not_applicable": sum(1 for c in checks.values()
                              if c["verdict"] == "not_applicable"),
    }


def attach_checks(items: dict, page_text: str) -> tuple[dict, dict]:
    """後方互換用: 1ページだけの items に判定を付ける。"""
    return attach_checks_across_pages(items, [page_text])


def attach_item_check(item: object, check: dict) -> dict:
    """元の項目を保持しつつ判定を付ける。不正項目も捨てない。"""
    fields = item if isinstance(item, dict) else {"invalid_item": item}
    return {**fields, "evidence_check": check}


def attach_checks_across_pages(items: dict, page_texts: Sequence[str]) -> tuple[dict, dict]:
    """items を壊さず、ページ単位の evidence_check を付けたコピーを返す。"""
    checks = check_items_across_pages(items, page_texts)
    checked_items = {
        key: attach_item_check(item, checks[key])
        for key, item in items.items()
    }
    return checked_items, summarize(checks)

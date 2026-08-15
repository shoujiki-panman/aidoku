"""AIが出した根拠（evidence）が、実際にページに書いてあるかを照合する。

なぜ要るか:
  `extractor/prompt.md` は「evidence は本文からの引用」と指示しているが、
  **その引用が実在するかを確かめるコードが無かった。**
  つまり AI が根拠を作り出しても検出できない状態だった。
  「測る道具の方も測っている」と言っている以上、ここは空けておけない。

判定は3段で緩める。**厳しすぎると、正しい引用まで落ちる。**

  exact      本文にそのまま含まれる
  normalized 空白・全角半角・記号のゆれを吸収すると含まれる
  partial    連続する部分文字列が MIN_RUN 文字ぶん一致する（要約されているが元がある）
  missing    どれにも当たらない ← 捏造の疑い

**missing でも「捏造だ」と断定はしない。**リンク先ページを読んで引用した場合など、
渡した本文に無い正当なケースがある。判定はフラグであって断罪ではない。
"""

from __future__ import annotations

import re
import unicodedata

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


def normalize(s: str) -> str:
    """空白・全角半角・記号のゆれを落とす。

    自治体サイトは全角スペース・改行・波ダッシュのゆれが多く、
    そのまま比較すると正しい引用まで missing になる。
    """
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    # 引用時に付きやすい記号を落とす（本文と引用で揺れる）
    s = re.sub(r"[「」『』（）()\[\]【】、,。.・:：;；\-−–—ー~〜*＊]", "", s)
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


def check_one(evidence: str, page_text: str) -> dict:
    """1つの evidence を照合する。"""
    ev = (evidence or "").strip()
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
                "note": f"連続{run}文字が一致。要約されているが元はある"}

    return {"verdict": "missing", "run": run,
            "note": "本文に見当たらない。渡していないページからの引用か、根拠の捏造"}


# 照合が通ったとみなす判定
OK_VERDICTS = ("exact", "normalized", "partial")


def check_items(items: dict, page_text: str) -> dict:
    """extract の items 全体を照合する。found=true のものだけ見る。

    found=false のとき evidence は「なぜ無いか」の説明であって引用ではないので、
    照合対象にしない（`extractor/prompt.md` の failure_reason の設計に合わせる）。
    """
    out = {}
    for key, item in (items or {}).items():
        if not item.get("found"):
            out[key] = {"verdict": "not_applicable", "run": 0,
                        "note": "found=false のため照合しない"}
            continue
        out[key] = check_one(item.get("evidence") or "", page_text)
    return out


def summarize(checks: dict) -> dict:
    """1ページぶんの照合結果をまとめる。"""
    considered = [c for c in checks.values() if c["verdict"] != "not_applicable"]
    ok = [c for c in considered if c["verdict"] in OK_VERDICTS]
    return {
        "checked": len(considered),
        "verified": len(ok),
        "missing": sum(1 for c in considered if c["verdict"] == "missing"),
        "too_short": sum(1 for c in considered if c["verdict"] == "too_short"),
    }

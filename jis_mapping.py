"""AI読の指摘を、JIS X 8341-3 の達成基準に対応づける。

**なぜ要るか**: 「AIに読めません」では職員は動けない。どこを直せばよいのか、
直す義務があるのか、社内で誰に相談すればよいのかが分からない。

自治体には**すでに基準がある**。総務省「みんなの公共サイト運用ガイドライン（2024年版）」が
**適合レベルAA** への準拠を求め、基準は JIS X 8341-3:2016（レベルA 25項目 + AA 13項目）。
評価軸を自分で発明する必要はなかった。

★**全部をJISに寄せない。** 寄らないものこそAI読が固有に言えることである。
  「手数料が書かれていない」は達成基準の違反ではない。**内容の問題であって形式の問題ではない。**
  対応づけの価値は「重なるところ」ではなく、**重ならないところが見えること**にある。

★**適合試験はしない。** AI読は適合証明の道具ではない（試験は miChecker と正式な試験方法がある）。
  「JIS準拠」とも名乗らない。対応づけているだけ。

出典:
- JIS X 8341-3:2016 達成基準 https://www.nict.go.jp/info-barrierfree/jis/gaiyou.html
- みんなの公共サイト運用ガイドライン（2024年版） https://www.soumu.go.jp/main_content/000945249.pdf
- 改正検討会 第1回 2026-08-24（WCAG 2.2 準拠へ。AAの基準が約1.4倍に増える見込み）
"""

from __future__ import annotations

from dataclasses import dataclass

GUIDELINE = "総務省 みんなの公共サイト運用ガイドライン（2024年版）— 適合レベルAA"


@dataclass(frozen=True)
class Criterion:
    """達成基準。**番号と名称は規格のとおりに書く。言い換えない。**"""

    number: str
    name: str
    level: str          # A / AA


# 対応づけに使う達成基準だけを持つ。規格の全項目は持たない（適合試験をしないため）。
CRITERIA = {
    "1.1.1": Criterion("1.1.1", "非テキストコンテンツ", "A"),
    "1.3.1": Criterion("1.3.1", "情報及び関係性", "A"),
    "2.4.4": Criterion("2.4.4", "文脈におけるリンクの目的", "A"),
    "2.4.6": Criterion("2.4.6", "見出し及びラベル", "AA"),
}

# AI読の指摘 → 達成基準。**対応づかないものは None を明示する。**
MAPPING = {
    "image_pdf": {
        "label": "添付が画像で、文字を取り出せない",
        "criterion": "1.1.1",
        "why": "本文のテキストを持たないため、読み取り器でもスクリーンリーダーでも読めない",
        "evidence": "analysis/out/non-html_tennyu.json",
    },
    "table_only": {
        "label": "答えが表の中にしかなく、見出しと値の対応が潰れる",
        "criterion": "1.3.1",
        "why": "本文として読むと、どの見出しの列の値かが失われる",
        "evidence": "analysis/probes/check_tables.py",
    },
    "opaque_link": {
        "label": "リンク題から行き先が分からない（「こちら」「詳しくは」）",
        "criterion": "2.4.4",
        "why": "リンク題だけでは、AIも人も行き先を判断できない",
        "evidence": "analysis/out/ledger_tennyu.json",
    },
    "buried_heading": {
        "label": "見出しが内容を表さず、手続きが埋もれる",
        "criterion": "2.4.6",
        "why": "見出しから目的のページにたどり着けない",
        "evidence": "analysis/out/ledger_tennyu.json",
    },
    # ★ここから下がAI読の固有部分。JISでは拾えない。
    "not_written": {
        "label": "その項目がどこにも書かれていない（手数料など）",
        "criterion": None,
        "why": "書いていないことは達成基準の違反ではない。**内容の問題であって形式の問題ではない**",
        "evidence": "web/data/scores-tennyu.json",
    },
    "one_hop_away": {
        "label": "答えが本文になく、リンク先1階層にある",
        "criterion": None,
        "why": "1階層先にあることは違反ではない",
        "evidence": "analysis/out/reread-tennyu_必要書類.json",
    },
    "stale": {
        "label": "書かれている内容が古い",
        "criterion": None,
        "why": "JISは情報の鮮度を扱わない",
        "evidence": "experiment/out/stale-ask_passport_search.json",
    },
    "ai_guesses": {
        "label": "書かれていないことを、AIが推測で答える",
        "criterion": None,
        "why": "サイト側の問題ですらない。住民が受け取る答えの問題",
        "evidence": "experiment/out/fee-ask_search.json",
    },
}


def criterion_for(finding: str) -> Criterion | None:
    """指摘に対応する達成基準。**対応づかないものは None を返す。**

    ★ここで「近い基準」を当てはめない。無理に寄せると、
      JISの範囲外であることが見えなくなる。それがAI読の固有部分なので、消してはいけない。
    """
    entry = MAPPING[finding]
    number = entry["criterion"]
    return CRITERIA[number] if number else None


def describe(finding: str) -> dict:
    """職員に渡す1件分。基準に対応づくものは番号とレベルを、つかないものは理由を出す。"""
    entry = MAPPING[finding]
    found = criterion_for(finding)
    return {
        "finding": finding,
        "label": entry["label"],
        "in_scope": found is not None,
        "criterion": (f"{found.number} {found.name}" if found else None),
        "level": found.level if found else None,
        "guideline": GUIDELINE if found else None,
        "why": entry["why"],
        "evidence": entry["evidence"],
    }


def summary() -> dict:
    """対応づく数と、つかない数。**両方出す。**"""
    rows = [describe(key) for key in MAPPING]
    return {
        "_about": "AI読の指摘とJIS X 8341-3の対応表。適合試験ではない。"
                  "対応づかない指摘こそ、この作品が固有に言えるもの。",
        "guideline": GUIDELINE,
        "in_scope": sum(1 for r in rows if r["in_scope"]),
        "out_of_scope": sum(1 for r in rows if not r["in_scope"]),
        "rows": rows,
    }

"""AI読の指摘を「行政データにおける機械可読性に関するルール」に対応づける。

**なぜ要るか**: 2026-08-31 のデジタル庁データマネジメント研修で、
**AI読が測っていることが国の枠組みに入った**ことが分かった。

    「AIが安心して学習・推論に使えるデータを **AI-Readyデータ** と呼ぶようになった」
    「**AIとシステムの間の相互運用性も課題**」
    「社内ドキュメントなどの非構造化データは元々人間向けに作られているため、
      **AIが読み込めない、あるいは非効率にしか読めない場合がある**」

そして**判定ルールと判定ツールが既に公開されている**:

    ルール  行政データにおける機械可読性に関するルール（令和8年3月31日）
            各府省庁DX推進連絡会議・デジタル社会推進会議幹事会
            30ルール / Level1:15・Level2:6・Level3:9
    ツール  Harunobu（春信）https://github.com/digital-go-jp/machine_readability_rule
            MIT。AIなしの決定論的判定。100点満点でレベル別に採点

`jis_mapping.py`（JIS X 8341-3）と同じ形で対応づける。**対応づかないものを必ず書く。**
対応づけただけで数が無いと職員に渡せないので、実測値も併記する。

    python3 analysis/mr_mapping.py            # 対応づけを表で出す
    python3 analysis/mr_mapping.py --json     # 機械が読む形
"""

from __future__ import annotations

import argparse
import json

VERSION = "mr-mapping-0.1"

RULE_SOURCE = {
    "name": "行政データにおける機械可読性に関するルール",
    "issued": "2026-03-31",
    "by": "各府省庁DX推進連絡会議・デジタル社会推進会議幹事会",
    "url": "https://www.cas.go.jp/jp/seisaku/digital_gyozaikaikaku/pdf/gyouseidata_rule.pdf",
    "rules": 30,
    "tool": "Harunobu https://github.com/digital-go-jp/machine_readability_rule",
}

# ★対応づくもの。**実測値のあるものだけ**を入れる。
#   「対応づけられそう」で入れると、数の無い対応表になる（JISで一度そうなった）。
MAPPED = [
    {
        "rule_id": "L1-01",
        "rule": "ファイル形式は機械が直接読み取れるExcelやCSV等となっているか",
        "level": "Level1",
        "severity": "FATAL（違反で強制0点）",
        "aidoku": "手続きの答えが PDF / Word にしか書かれていない",
        "measured": "3手続きの候補に非HTMLが81本（PDF76・Word3・Excel2）。"
                    "うち10本はAI読でも外部の変換器でも本文が取り出せない",
        "note": "ルールは「PDFやWordは機械処理が困難」と明記している。"
                "AI読の実測は、その困難が住民の問いに届かない形で現れることを示す",
    },
    {
        "rule_id": "L1-01",
        "rule": "同上（古い .xls は許可形式に含まれない）",
        "level": "Level1",
        "severity": "FATAL（違反で強制0点）",
        "aidoku": "区が公開する品目一覧が古い .xls 形式",
        "measured": "大田区の粗大ごみ品目一覧（.xls）。**Harunobu は読み込みを拒否**"
                    "（「.xls 形式はサポートされていません」）。AI読は15,804字を読めた",
        "note": "★国の判定ツールが読めないファイルを、区は公開し続けている。"
                "AI読が読めるようにしたのは、判定の前段が塞がっていたため",
    },
    {
        "rule_id": "L3-08",
        "rule": "データの定義や更新履歴が記載されているか",
        "level": "Level3",
        "severity": "MINOR",
        "aidoku": "情報がいつ時点のものか分からない（古い答えを返す）",
        "measured": "パスポート手数料の実験で、6回中6回とも改定前の16,000円を回答。"
                    "うち3回は「2026年8月現在」と**今日の日付を添えて**返した",
        "note": "ルールはファイル内の更新履歴を求める。AI読はページの鮮度を見る。"
                "同じ「いつの話か分からない」問題の別の面",
    },
]

# ★対応づかないもの。**ここがAI読の固有部分。**
#   JISのときと同じで、対応づかないものを書かないと「何が新しいのか」が消える。
UNMAPPED = [
    {
        "aidoku": "答えが**どこにも書かれていない**",
        "measured": "候補を1本残らず読んだ上で74項目（手数料37・期限19・必要書類12・窓口6）",
        "why": "ルールは**すでにあるデータの形式**を測る。書かれていないものは対象外",
    },
    {
        "aidoku": "答えのページに**たどり着けない**",
        "measured": "候補の44〜56%はAIに一度も見せていなかった（台帳 `read_ledger.py`）",
        "why": "ルールは1ファイル単位。**ページからページへ渡れるか**は見ない",
    },
    {
        "aidoku": "**読めるPDFと読めないPDFの区別**",
        "measured": "PDF76本のうち、字形の対応表が無い5本・本文ストリームが無い3本は"
                    "外部の変換器でも0字。残りは読める",
        "why": "★ルールは「PDFは不可」で止まる。**実際にAIが読めるかどうかは測らない。**"
               "現実には区はPDFを出し続けるので、この区別が住民の可否を決める",
    },
    {
        "aidoku": "**AIの判定そのものの揺れ**",
        "measured": "同じ道具・同じページで再現性が手続きにより7倍違う（3.1% / 12.5% / 21.9%）",
        "why": "Harunobu は決定論的判定（AIなしで動く）。揺れは生じない。"
               "AI読は**AIに読ませて測る**ので、揺れ自体が測定対象になる",
    },
]


def mapped_rule_ids() -> list[str]:
    """対応づいたルールID（重複を除く）。"""
    return sorted({m["rule_id"] for m in MAPPED})


def coverage() -> dict:
    """30ルールのうちいくつに対応づいたか。**少ないことを隠さない。**"""
    ids = mapped_rule_ids()
    return {
        "rules_total": RULE_SOURCE["rules"],
        "rules_mapped": len(ids),
        "mapped_ids": ids,
        "unmapped_findings": len(UNMAPPED),
    }


def render() -> str:
    lines = [f"# AI読 × {RULE_SOURCE['name']}（{RULE_SOURCE['issued']}）", ""]
    cov = coverage()
    lines.append(f"全{cov['rules_total']}ルール中、実測を伴って対応づいたのは "
                 f"**{cov['rules_mapped']}件**（{', '.join(cov['mapped_ids'])}）。")
    lines.append("")
    lines.append("## 対応づくもの")
    for m in MAPPED:
        lines.append(f"\n### {m['rule_id']} {m['rule']}（{m['level']} / {m['severity']}）")
        lines.append(f"- AI読の指摘: {m['aidoku']}")
        lines.append(f"- 実測: {m['measured']}")
        lines.append(f"- note: {m['note']}")
    lines.append("")
    lines.append("## 対応づかないもの（AI読の固有部分）")
    for u in UNMAPPED:
        lines.append(f"\n### {u['aidoku']}")
        lines.append(f"- 実測: {u['measured']}")
        lines.append(f"- なぜ対応づかないか: {u['why']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.json:
        print(json.dumps({"version": VERSION, "source": RULE_SOURCE,
                          "coverage": coverage(), "mapped": MAPPED,
                          "unmapped": UNMAPPED}, ensure_ascii=False, indent=2))
        return
    print(render())


if __name__ == "__main__":
    main()

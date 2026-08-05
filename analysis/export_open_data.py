"""公開ダッシュボードのデータを、CSVと要約テキストでも出す。

デジタル庁「ダッシュボードデザインの実践ガイドブック」のチェックリストより:
  26. データファイル（ExcelやCSV）を公開していますか？
  27. ダッシュボードの情報が要約されたテキストを公開していますか？（一般公開の場合）

入力は web/data/scores.json（実測から作ったもの）。ここで数字を作らない。

    python3 analysis/export_open_data.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "web" / "data" / "scores.json"
OUT_CSV = REPO / "web" / "data" / "scores.csv"
OUT_TXT = REPO / "web" / "data" / "summary.txt"

ITEMS = ["必要書類", "窓口/オンライン可否", "期限", "手数料", "オンライン明示"]


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    munis = d["municipalities"]
    proc = d["procedure"]

    # ── CSV ──
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["手続き", "自治体", "合計点"] + ITEMS
                   + ["トップからの到達クリック数", "診断したページのURL"])
        for m in munis:
            w.writerow(
                [proc, m["name"], m["total"]]
                + [m["breakdown"].get(k, 0) for k in ITEMS]
                + [m.get("hops", ""), m.get("page_url", "")]
            )
    # Excelで開いても文字化けしないよう BOM つき(utf-8-sig)で出す

    # ── 要約テキスト ──
    s = d["summary"]
    lines = [
        f"AI読（アイドク） 調査結果の要約 — {d['phase']}の{proc}",
        f"データ生成日: {d.get('generated_at','')[:10]}／各区の公式サイトの取得日: 2026-07-22",
        "",
        "【調べたこと】",
        f"東京23区の{proc}のページを、住民が使うAIに読ませ、4項目（必要書類・窓口/オンライン可否・"
        "期限・手数料）とオンラインで完結できるかの明示を、そのページから読み取れるかを実測しました。",
        "",
        "【全体】",
        f"・平均 {s['average']} 点（100点満点）",
        f"・4項目すべて答えられた区: {s['full_marks']} 区",
        f"・ほぼ「分かりません」になる区: {s['zero']} 区",
        f"・手数料が答えられない区: {s['fee_missing']} 区（実際には無料の区が多い）",
        "",
        "【区ごと】",
    ]
    for m in munis:
        ng = [k for k in ITEMS if (m["breakdown"].get(k, 0) or 0) < 20]
        lines.append(
            f"・{m['name']}: {m['total']}点"
            + ("／伝わらない項目: " + "、".join(ng) if ng else "／4項目とも伝わる")
        )
    lines += [
        "",
        "【採点方法】",
        "4項目 × 20点 ＋ オンライン明示（明記20／曖昧10／記載なし0）＝ 100点。",
        "判定はAIによります。各項目は「読めた／読めない」の2値で20点なので、判定が1つ変われば20点動きます。",
        "この23区の点数は各1回の判定によるもので、ぶれ幅は測っていません。",
        "",
        "【注意】",
        "これは個人が行った第三者調査であり、行政機関の公式発表ではありません。",
        "ページに書かれていることだけから読み取れるかを見ており、推測での補完はしていません。",
        "クロールは robots.txt を守り、同一ドメインへのアクセスは3秒以上あけています。",
        "",
        "データ: scores.csv / scores.json（同じディレクトリ）",
        "リポジトリ: https://github.com/shoujiki-panman/aidoku",
    ]
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"CSV: {OUT_CSV.relative_to(REPO)}（{len(munis)}行）")
    print(f"要約: {OUT_TXT.relative_to(REPO)}（{len(lines)}行）")


if __name__ == "__main__":
    main()

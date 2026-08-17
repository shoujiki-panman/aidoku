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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "web" / "data" / "scores.json"
OUT_CSV = REPO / "web" / "data" / "scores.csv"
OUT_TXT = REPO / "web" / "data" / "summary.txt"

sys.path.insert(0, str(Path(__file__).parent.parent))
from fact_types import DISPLAY_KEYS, EXTRA_MEASURES  # noqa: E402

ITEMS = [*DISPLAY_KEYS, *(m["display_label"] for m in EXTRA_MEASURES)]


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    munis = d["municipalities"]
    proc = d["procedure"]

    # ── CSV ──
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        # OS差分とdiff-checkの疑似「行末空白」を避け、公開CSVはLFへ固定する。
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["手続き", "自治体", "検証済み合計点"] + ITEMS
                   + ["AI回答数", "評価状態", "トップからの到達クリック数",
                      "診断したページのURL"])
        for m in munis:
            w.writerow(
                [proc, m["name"], "" if m["total"] is None else m["total"]]
                + ["" if m["breakdown"].get(k) is None
                   else m["breakdown"].get(k, 0) for k in ITEMS]
                + [m["answered_count"], m["evaluation_status"],
                   m.get("hops", ""), m.get("page_url", "")]
            )
    # Excelで開いても文字化けしないよう BOM つき(utf-8-sig)で出す

    # ── 要約テキスト ──
    s = d["summary"]
    lines = [
        f"AI読（アイドク） 調査結果の要約 — {d['phase']}の{proc}",
        f"データ生成日: {d.get('generated_at','')[:10]}／公式サイト取得: 2026-07-21〜2026-08-05（転入届）",
        "",
        "【調べたこと】",
        f"東京23区の{proc}のページを、住民が使うAIに読ませ、4項目（必要書類・窓口/オンライン可否・"
        "期限・手数料）とオンラインで完結できるかの明示を、そのページから読み取れるかを実測しました。",
        "",
        "【全体】",
        f"・4判定まで検証済み: {s['evaluated']} 区",
        f"・未検証: {s['not_evaluated']} 区",
        f"・4項目すべて回答が返った区: {s['answered_all_four']} 区",
        f"・4項目とも回答が無い区: {s['answered_zero']} 区",
        f"・手数料が答えられない区: {s['fee_missing']} 区（実際には無料の区が多い）",
        "",
        "【区ごと】",
    ]
    for m in munis:
        ng = [field["field"] for field in m["fields"] if not field["answered"]]
        score = "未検証" if m["total"] is None else f"{m['total']}点"
        lines.append(
            f"・{m['name']}: 4判定の点数 {score}"
            + ("／回答が無い項目: " + "、".join(ng) if ng else "／4項目とも回答あり")
        )
    lines += [
        "",
        "【採点方法】",
        "4項目は、回答・Evidence実在・Evidence支持・Ground Truth一致の4判定をすべて通った場合だけ各20点。",
        "必要な判定が未実施なら0点ではなく未検証。回答が返っただけでは加点しません。",
        "現在の23区データはGround Truthが揃っていないため、回答文は実測、正解点は未検証です。",
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

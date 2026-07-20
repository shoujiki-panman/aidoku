"""採点結果を1枚の Markdown レポートにまとめる。

このスプリントの完了条件（CLAUDE.md §7）＝「自治体×項目の正誤表 + 採点器の正答率」が
この1ファイルで読めること。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCORE_DIR = Path(__file__).parent / "out"
REPORT_DIR = ROOT / "reports"

VERDICT_MARK = {
    "正解": "○",
    "正解(記載なしが正しい)": "○(記載なしを正しく報告)",
    "部分正解": "△",
    "不正解": "×",
    "不正解(幻覚)": "×(幻覚)",
    "未採点": "-",
}


def esc(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def build(scores: list[dict], procedure: str, run_date: str) -> str:
    L: list[str] = []
    add = L.append

    add(f"# エージェント・レディネス採点レポート — {procedure}")
    add("")
    add(f"- 実行日: {run_date}")
    add(f"- 対象: {len(scores)}自治体（Phase 1 パイロット）")
    add("- 抽出・採点モデル: " + ", ".join(sorted({s.get("model", "claude-sonnet-5") for s in scores})))
    add("- 正解データ: `scorer/golden/` の人手ゴールデンセット（**暫定・本人確認待ち**）")
    add("")
    add("> 正解は「そのページを人が丁寧に読んだら得られる答え」として作っている。")
    add("> 制度上の正解（例: 転入届は無料）ではなく、**サイトから読み取れるか**を測る指標であるため。")
    add("")

    # --- サマリ ---
    add("## 1. スコア一覧")
    add("")
    add("| 自治体 | 合計 | 情報到達 | 抽出正確性 | 機械可読性 | オンライン明示 | 到達ホップ数 | リンク先を開いた数 |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in sorted(scores, key=lambda x: -x["total"]):
        b = s["breakdown"]
        add(f"| {s['municipality']} | **{s['total']}** | {b['情報到達']}/20 | {b['抽出正確性']}/40 "
            f"| {b['機械可読性']}/20 | {b['オンライン明示']}/20 | {s.get('hops', '-')} "
            f"| {len(s.get('followed_urls') or [])} |")
    add("")

    # --- 突合表 ---
    add("## 2. 突合表（自治体 × 項目）")
    add("")
    for s in sorted(scores, key=lambda x: -x["total"]):
        add(f"### {s['municipality']}（{s['total']}点）")
        add("")
        add(f"- 抽出対象ページ: {s.get('page_url')} （hop{s.get('hops')}）")
        for u in s.get("followed_urls") or []:
            add(f"- 追って開いたリンク先: {u}")
        add("")
        add("| 項目 | 判定 | 正解（人手） | エージェントの答え | 判定理由 |")
        add("|---|---|---|---|---|")
        for f in s["fields"]:
            mark = VERDICT_MARK.get(f["verdict"], f["verdict"])
            expected = f.get("expected_value") or "（サイトに記載なし）"
            agent = f.get("agent_value") or f"（見つからず: {f.get('failure_reason') or '-'}）"
            add(f"| {f['field']} | {mark} | {esc(expected)[:110]} | {esc(agent)[:110]} | {esc(f['reason'])[:90]} |")
        add("")
        if s.get("page_notes"):
            add(f"**エージェントの所見**: {esc(s['page_notes'])}")
            add("")

    # --- 失敗理由 ---
    add("## 3. 失敗理由の集計（行政向けの改善箇所リストの元データ）")
    add("")
    reasons = Counter()
    per_muni: dict[str, Counter] = {}
    for s in scores:
        c = per_muni.setdefault(s["municipality"], Counter())
        for f in s["fields"]:
            r = f.get("failure_reason")
            if r:
                reasons[r] += 1
                c[r] += 1
    if reasons:
        add("| 失敗理由 | 件数 | 内訳 |")
        add("|---|---:|---|")
        for r, n in reasons.most_common():
            who = "、".join(f"{m}{cc[r]}件" for m, cc in per_muni.items() if cc[r])
            add(f"| {r} | {n} | {who} |")
    else:
        add("失敗理由の記録なし。")
    add("")
    total_items = sum(len(s["fields"]) for s in scores)
    phone = reasons.get("電話でのみ確認可", 0)
    add(f"**電話送客率**: {phone}/{total_items} 項目 "
        f"({phone / total_items * 100:.1f}%) がサイトで完結せず電話・窓口に送客されている")
    add("")

    # --- 採点器の正答率 ---
    add("## 4. 採点器の正答率（人手で埋める欄）")
    add("")
    add("採点器の判定が妥当かを人が確認する。ここが埋まるまで、採点基準を全自治体に広げない。")
    add("")
    add("| 自治体 | 項目 | 採点器の判定 | 判定した主体 | 人手確認（○/×） | コメント |")
    add("|---|---|---|---|---|---|")
    for s in sorted(scores, key=lambda x: x["municipality"]):
        for f in s["fields"]:
            add(f"| {s['municipality']} | {f['field']} | {f['verdict']} | {f.get('judged_by', '')} |  |  |")
    add("")
    n_llm = sum(1 for s in scores for f in s["fields"] if f.get("judged_by", "") not in ("rule", ""))
    add(f"- 全 {total_items} 件中、ルールで自動判定 {total_items - n_llm} 件 / LLM判定 {n_llm} 件")
    add("- 正答率 = 人手確認○ ÷ 全件。**ゴールデンセット30件規模になるまでは参考値**")
    add("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()

    files = sorted(SCORE_DIR.glob(f"score_*_{args.procedure}.json"))
    if not files:
        raise SystemExit("採点結果がない。先に scorer/score.py を実行すること")
    scores = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    proc_name = scores[0]["procedure"]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"phase1_{args.procedure}_{args.date}.md"
    out.write_text(build(scores, proc_name, args.date), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()

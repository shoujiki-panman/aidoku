"""採点器のぶれを測る。

同じ抽出結果を N 回採点し、判定がどれだけ変わるかを数字にする。
LLMに採点させる仕組みでは、同じ入力でも判定が揺れることが知られている
（position bias 等。判定器によっては 25〜50% がひっくり返るという報告がある）。
対策を入れる前に、まず自分の採点器のぶれ幅を測る。

    python3 scorer/stability.py -p tennyu --runs 5

出力: 画面 + reports/stability_<手続き>_<日付>.md
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from score import EXTRACT_DIR, FIELDS, load_golden, score_one

REPORT_DIR = Path(__file__).parent.parent / "reports"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--runs", "-n", type=int, default=5)
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()

    golden = load_golden(args.procedure)
    files = sorted(EXTRACT_DIR.glob(f"extract_*_{args.procedure}.json"))
    if not files:
        raise SystemExit("抽出結果がない。先に extractor/extract.py を実行すること")
    extracts = [json.loads(f.read_text(encoding="utf-8")) for f in files]

    # totals[自治体] = [1回目の合計, 2回目, ...]
    totals: dict[str, list[int]] = defaultdict(list)
    # verdicts[(自治体, 項目)] = Counter({判定: 回数})
    verdicts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    judged_by: dict[tuple[str, str], str] = {}

    n_total = args.runs * len(extracts)
    print(f"同じ抽出結果を {args.runs} 回採点します（モデル: {args.model}）")
    print(f"1自治体あたり数十秒かかります。全部で {n_total} 回ぶん、"
          f"目安 {n_total // 3}〜{n_total // 2} 分。\n")

    done = 0
    for run in range(1, args.runs + 1):
        for ext in extracts:
            done += 1
            # 採点前に「いま何をしているか」を出す。終わるまで無言にしない
            print(f"  [{done}/{n_total}] {run}回目 {ext['municipality']} を採点中…",
                  end="", flush=True)
            res = score_one(ext, golden, args.model)
            name = res["municipality"]
            totals[name].append(res["total"])
            for f in res["fields"]:
                verdicts[(name, f["field"])][f["verdict"]] += 1
                judged_by[(name, f["field"])] = f.get("judged_by", "")

            # 前回までと違う点数が出たら、その場で分かるようにする
            past = totals[name][:-1]
            mark = "  ← 前回までと違う" if past and res["total"] not in past else ""
            print(f" {res['total']}点{mark}", flush=True)

    # --- 集計 ---
    llm_items = [k for k, v in judged_by.items() if v not in ("rule", "")]
    unstable = [k for k in llm_items if len(verdicts[k]) > 1]
    flip_rate = len(unstable) / len(llm_items) * 100 if llm_items else 0.0

    print()
    print("=" * 60)
    print(f"LLMが判定した項目: {len(llm_items)}件（残りはルールで自動判定＝常に同じ）")
    print(f"判定が割れた項目 : {len(unstable)}件 → ぶれ率 {flip_rate:.0f}%")
    print()
    print("自治体ごとの合計点のふれ幅:")
    for name, ts in totals.items():
        width = max(ts) - min(ts)
        mark = "  ← ぶれている" if width else ""
        print(f"  {name}: {min(ts)}〜{max(ts)}点（幅{width}） {ts}{mark}")
    if unstable:
        print()
        print("割れた項目の内訳:")
        for k in unstable:
            dist = "、".join(f"{v}×{n}回" for v, n in verdicts[k].most_common())
            print(f"  {k[0]} / {k[1]}: {dist}")
    print("=" * 60)

    # --- レポート ---
    L = [f"# 採点器のぶれ測定 — {args.procedure}", "",
         f"- 実行日: {args.date}", f"- 試行回数: {args.runs}回（同じ抽出結果を採点し直した）",
         f"- モデル: {args.model}", "",
         "同じ入力でも判定が揺れるのは LLM-as-a-judge の既知の問題（position bias 等）。",
         "対策を入れる前後で、この数字が下がったかどうかで効果を判断する。", "",
         "## 結論", "",
         f"- LLMが判定した項目 {len(llm_items)}件 のうち **{len(unstable)}件で判定が割れた（ぶれ率 {flip_rate:.0f}%）**",
         "", "## 自治体ごとの合計点", "",
         "| 自治体 | 最小 | 最大 | ふれ幅 | 各回 |", "|---|---:|---:|---:|---|"]
    for name, ts in totals.items():
        L.append(f"| {name} | {min(ts)} | {max(ts)} | {max(ts) - min(ts)} | {', '.join(map(str, ts))} |")
    L += ["", "## 項目ごとの判定", "",
          "| 自治体 | 項目 | 判定した主体 | 判定の内訳 | 割れたか |", "|---|---|---|---|---|"]
    for ext in extracts:
        for field in FIELDS:
            k = (ext["municipality"], field)
            if k not in verdicts:
                continue
            dist = "、".join(f"{v}×{n}" for v, n in verdicts[k].most_common())
            split = "**割れた**" if len(verdicts[k]) > 1 else "安定"
            L.append(f"| {k[0]} | {field} | {judged_by[k] or '-'} | {dist} | {split} |")
    L += ["", "## 次にやること", "",
          "1. ぶれ率が高い項目を見て、判定基準のどこが曖昧かを特定する",
          "2. 対策を1つだけ入れる（順序入れ替え＋多数決 / ルーブリックの段階を減らす）",
          "3. このスクリプトを同じ条件で回し直し、ぶれ率が下がったかを数字で確認する", ""]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"stability_{args.procedure}_{args.date}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

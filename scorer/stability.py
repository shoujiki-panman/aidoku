"""採点器のぶれを測る。

同じ抽出結果を N 回採点し、判定がどれだけ変わるかを数字にする。
LLMに採点させる仕組みでは、同じ入力でも判定が揺れることが知られている
（position bias 等。判定器によっては 25〜50% がひっくり返るという報告がある）。
対策を入れる前に、まず自分の採点器のぶれ幅を測る。

    python3 scorer/stability.py -p tennyu --runs 5

**分母は2つ出す。** 項目単位（LLM判定9件）だけだと 2/9 → 0/9 が偶然に埋もれる
（Fisher の正確検定で p≒0.47）。必須要素まで降りると分母が28個になり、
claude の呼び出しを1回も増やさずに解像度が上がる。

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
    ap.add_argument("--tag", default="", help="レポート名に付ける識別子（before / after など）")
    args = ap.parse_args()

    golden = load_golden(args.procedure)
    files = sorted(EXTRACT_DIR.glob(f"extract_*_{args.procedure}.json"))
    if not files:
        raise SystemExit("抽出結果がない。先に extractor/extract.py を実行すること")
    extracts = [json.loads(f.read_text(encoding="utf-8")) for f in files]

    # totals[自治体] = [1回目の合計, 2回目, ...]
    totals: dict[str, list[float]] = defaultdict(list)
    # verdicts[(自治体, 項目)] = Counter({判定: 回数})
    verdicts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    # element_votes[(自治体, 項目, スロット名)] = Counter({yes: n, no: m})
    element_votes: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
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
                # 要素単位。スロット名は golden 側の並びから取る（判定器の返りは順序固定）
                g = golden.get((res["municipality_id"], f["field"]))
                for i, e in enumerate(f.get("elements") or []):
                    if g is None or i >= len(g.required_elements):
                        continue
                    slot = g.required_elements[i][0]
                    element_votes[(name, f["field"], slot)][e.get("covered", "?")] += 1

            # 前回までと違う点数が出たら、その場で分かるようにする
            past = totals[name][:-1]
            mark = "  ← 前回までと違う" if past and res["total"] not in past else ""
            print(f" {res['total']}点{mark}", flush=True)

    # --- 集計 ---
    llm_items = [k for k, v in judged_by.items() if v not in ("rule", "")]
    unstable = [k for k in llm_items if len(verdicts[k]) > 1]
    flip_rate = len(unstable) / len(llm_items) * 100 if llm_items else 0.0

    el_keys = list(element_votes.keys())
    el_unstable = [k for k in el_keys if len(element_votes[k]) > 1]
    el_rate = len(el_unstable) / len(el_keys) * 100 if el_keys else 0.0

    print()
    print("=" * 60)
    print(f"LLMが判定した項目: {len(llm_items)}件（残りはルールで自動判定＝常に同じ）")
    print(f"判定が割れた項目 : {len(unstable)}件 → ぶれ率 {flip_rate:.0f}%")
    if el_keys:
        print(f"必須要素         : {len(el_keys)}個")
        print(f"割れた要素       : {len(el_unstable)}個 → 要素単位のぶれ率 {el_rate:.1f}%")
    print()
    print("自治体ごとの合計点のふれ幅:")
    for name, ts in totals.items():
        width = round(max(ts) - min(ts), 1)
        mark = "  ← ぶれている" if width else ""
        print(f"  {name}: {min(ts)}〜{max(ts)}点（幅{width}） {ts}{mark}")
    if unstable:
        print()
        print("割れた項目の内訳:")
        for k in unstable:
            dist = "、".join(f"{v}×{n}回" for v, n in verdicts[k].most_common())
            print(f"  {k[0]} / {k[1]}: {dist}")
    if el_unstable:
        print()
        print("割れた要素の内訳:")
        for k in el_unstable:
            dist = "、".join(f"{v}×{n}回" for v, n in element_votes[k].most_common())
            print(f"  {k[0]} / {k[1]} / {k[2]}: {dist}")
    print("=" * 60)

    # --- レポート ---
    L = [f"# 採点器のぶれ測定 — {args.procedure}" + (f"（{args.tag}）" if args.tag else ""), "",
         f"- 実行日: {args.date}", f"- 試行回数: {args.runs}回（同じ抽出結果を採点し直した）",
         f"- モデル: {args.model}", "",
         "同じ入力でも判定が揺れるのは LLM-as-a-judge の既知の問題（position bias 等）。",
         "対策を入れる前後で、この数字が下がったかどうかで効果を判断する。", "",
         "## 結論", "",
         f"- LLMが判定した項目 {len(llm_items)}件 のうち "
         f"**{len(unstable)}件で判定が割れた（ぶれ率 {flip_rate:.0f}%）**"]
    if el_keys:
        L.append(f"- 必須要素 {len(el_keys)}個 のうち **{len(el_unstable)}個で判定が割れた"
                 f"（要素単位のぶれ率 {el_rate:.1f}%）**")
    L += ["", "## 自治体ごとの合計点", "",
          "| 自治体 | 最小 | 最大 | ふれ幅 | 各回 |", "|---|---:|---:|---:|---|"]
    for name, ts in totals.items():
        L.append(f"| {name} | {min(ts)} | {max(ts)} | {round(max(ts) - min(ts), 1)} | "
                 f"{', '.join(map(str, ts))} |")
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
    if el_keys:
        L += ["", "## 必須要素ごとの判定", "",
              "| 自治体 | 項目 | 必須要素 | 判定の内訳 | 割れたか |", "|---|---|---|---|---|"]
        for k in el_keys:
            dist = "、".join(f"{v}×{n}" for v, n in element_votes[k].most_common())
            split = "**割れた**" if len(element_votes[k]) > 1 else "安定"
            L.append(f"| {k[0]} | {k[1]} | {k[2]} | {dist} | {split} |")
    L += ["", "## 次にやること", "",
          "1. 割れた要素があれば、そのスロットの文言だけを直す",
          "   （条件と数量を1スロットに2つ以上詰めない、が原則）",
          "2. judge_prompt.md 本文は触らない。触ったら測定をやり直すことになる", ""]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"stability_{args.procedure}_{args.date}" + (f"_{args.tag}" if args.tag else "")
    out = REPORT_DIR / f"{name}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

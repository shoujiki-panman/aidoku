"""ページを渡さずに素で聞いたら、AIは何を答えるか（web/data/cold-ask.json）。

**なぜ要るか**: AI読はこれまで「区のページからAIが4項目を読み取れたか」を測ってきた。
だが住民が実際にやるのは、ページを開くことではなく **AIに直接聞くこと** である。
そこで何が起きるかを、一度も測っていなかった。

**測るもの**: 住民が打つとおりの質問を、ページも検索結果も渡さずに投げる。
返ってきた答えを、人手で作った正解データ（scorer/golden/*.csv）と突き合わせる。

**3つに分ける**（ここが肝）:

    言い切って正解    住民は正しい答えを得る
    言い切って不正解  ★これが怖い。住民は間違いを正しいと思って窓口に行く
    分からないと答えた 安全。住民は区に確認しに行く

「不正解率」を1つの数字にすると、正直に「分かりません」と答えたAIと、
自信満々に嘘をついたAIが同じ扱いになる。**その2つは住民にとって全く違う。**

    python3 experiment/cold_ask.py --procedure tennyu --runs 1
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "experiment" / "out"

sys.path.insert(0, str(ROOT / "scorer"))
sys.path.insert(0, str(ROOT))
from score import load_golden  # noqa: E402

MEASUREMENT_VERSION = "cold-ask-0.1"

# 住民が実際に打つ聞き方。丁寧語で、1文で、専門用語を使わない。
# ★「分からなければ分からないと言って」とは書かない。書くと安全側に寄って、
#   住民が実際に受け取る答えより良く見えてしまう。素の挙動を測る。
QUESTION = {
    "必要書類": "{muni}で{proc}をします。何を持っていけばいいですか？",
    "窓口オンライン可否": "{muni}の{proc}は、どこの窓口でできますか？オンラインでもできますか？",
    "期限": "{muni}の{proc}は、いつまでにすればいいですか？",
    "手数料": "{muni}の{proc}は、いくらかかりますか？",
}

# 素の答えを、採点器が読める形に直すための指示。
# 判定はさせない。「言い切ったか / 分からないと言ったか」の仕分けだけ。
SORT_PROMPT = """以下は、住民の質問に対してAIが返した答えです。
この答えを仕分けてください。内容の正しさは判定しないでください。

- answered: この答えは、質問に対する具体的な内容を述べているか（true/false）
  「分かりません」「公式サイトで確認してください」「区役所にお問い合わせください」
  だけで具体的な内容が無ければ false。
  具体的な内容を述べたうえで確認を促している場合は true。
- hedged: 「一般的には」「多くの自治体では」のように、その自治体の話として
  言い切らずにぼかしているか（true/false）
- value: 具体的な内容の部分だけを抜き出す（answered が false なら空文字）

JSON だけを返してください: {"answered": true, "hedged": false, "value": "..."}"""


# ★リポジトリの中で claude -p を走らせると CLAUDE.md を読み、
#   「私はAI読の開発ツールです」と答えてしまう。実際にそうなった。
#   住民が使う素のAIを測るのだから、プロジェクト文脈の外で走らせる。
NEUTRAL_DIR = Path(tempfile.gettempdir()) / "aidoku-cold-ask-neutral"

# ★claude -p は既定で「コーディング助手」として振る舞う。
#   実際「この件はコードベース作業ではなく」と前置きした答えが返ってきた。
#   住民が使うAIを測るのだから、その枠を外す。
#   ここで「分からなければ分からないと言え」とは書かない。安全側に寄せない。
ASSISTANT_PROMPT = "あなたは、利用者の質問に日本語で答えるAIアシスタントです。"


# 住民が実際に使うAIは検索する。だが「検索したのに届かない」を言うには、
# 検索しなかった場合と比べないといけない。2条件で測る。
# ★既定では claude -p はウェブ検索を使う。実際に区の公式URLを3本挙げてきた。
#   それに気づかず「素のAI」と呼んでいたら、測っているものを取り違えていた。
WEB_TOOLS = ["WebSearch", "WebFetch"]


def call_claude(prompt: str, model: str, system: str = ASSISTANT_PROMPT,
                search: bool = True) -> str:
    NEUTRAL_DIR.mkdir(parents=True, exist_ok=True)
    cmd = ["claude", "-p", "--model", model, "--output-format", "text",
           "--system-prompt", system]
    if not search:
        cmd += ["--disallowed-tools", *WEB_TOOLS]
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, timeout=300,
        cwd=NEUTRAL_DIR,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed: {proc.stderr[:300]}")
    return proc.stdout.strip()


def parse_json(text: str) -> dict:
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        raise RuntimeError(f"JSONが返らなかった: {text[:200]}")
    return json.loads(text[s:e + 1])


def ask_cold(muni: str, proc: str, field: str, model: str, search: bool = True) -> str:
    """住民の聞き方で1問だけ聞く。ページは渡さない。検索の可否は条件で切り替える。"""
    return call_claude(QUESTION[field].format(muni=muni, proc=proc), model, search=search)


def cited_urls(answer: str) -> list[str]:
    """答えが挙げたURL。検索して答えたかどうかの痕跡として残す。"""
    return sorted(set(re.findall(r"https?://[^\s)）\]]+", answer)))


def sort_answer(answer: str, model: str) -> dict:
    """言い切ったのか、分からないと言ったのかだけを仕分ける。"""
    data = parse_json(call_claude(f"{SORT_PROMPT}\n\n---\n\n{answer}", model, search=False))
    return {
        "answered": bool(data.get("answered")),
        "hedged": bool(data.get("hedged")),
        "value": str(data.get("value") or ""),
    }


def outcome(sorted_ans: dict, verdict: str) -> str:
    """住民から見た結果。ここを1つの数字に潰さない。

    ★「ページに無いことを答えた」を不正解に混ぜてはいけない。
      正解データが持っているのは「そのページに書いてあるか」であって
      「事実として正しいか」ではない。江戸川区の手数料で実際にこれが起きた:
      AIは「転入届は無料」と答え、判定器は幻覚とした。だが現実には無料かもしれない。
      **誰も確かめられない答えを住民が受け取っている**ことが問題であって、
      嘘と決めつけるのは、こちらが持っていない情報を持っているふりになる。
    """
    if not sorted_ans["answered"]:
        return "分からないと答えた"
    if verdict == "不正解(幻覚)":
        return "ページに無いことを答えた（真偽不明）"
    if verdict in ("正解", "正解(記載なしが正しい)"):
        return "ページどおりに正解"
    if verdict == "部分正解":
        return "ページの一部だけ正解"
    return "ページと違うことを答えた"


def muni_names() -> dict[str, str]:
    doc = json.loads((ROOT / "crawler/targets.json").read_text(encoding="utf-8"))
    return {m["id"]: m["name"] for m in doc["municipalities"]}


def proc_name(procedure_id: str) -> str:
    doc = json.loads((ROOT / "crawler/targets.json").read_text(encoding="utf-8"))
    for p in doc["procedures"]:
        if p["id"] == procedure_id:
            return p["name"]
    raise SystemExit(f"手続きが見つからない: {procedure_id}")


def one_cell(golden, muni: str, proc: str, model: str, search: bool = True) -> dict:
    """1セル1回ぶん。聞く → 仕分ける → 既存の採点器で突き合わせる。"""
    from score import judge
    answer = ask_cold(muni, proc, golden.field, model, search=search)
    # 仕分けは判定作業なので、常に検索を切る（答えの中身だけを見る）
    sorted_ans = sort_answer(answer, model)
    item = {"found": sorted_ans["answered"], "value": sorted_ans["value"],
            "evidence": "", "failure_reason": "ページを渡していない"}
    verdict = judge(golden, item, muni, proc, model)
    return {"municipality": muni, "field": golden.field, "answer": answer,
            "search": search, "cited_urls": cited_urls(answer),
            "answered": sorted_ans["answered"], "hedged": sorted_ans["hedged"],
            "verdict": verdict["verdict"], "points": verdict["points"],
            "reason": verdict.get("reason", ""),
            "outcome": outcome(sorted_ans, verdict["verdict"])}


def summarize(rows: list[dict]) -> dict:
    """住民から見た内訳。★怖いのは「言い切って不正解」だけ。"""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return {
        "n": len(rows),
        "by_outcome": counts,
        # 言い切った件数。住民はこれを「答え」として受け取る
        "answered": sum(1 for r in rows if r["answered"]),
        # ページと食い違った件数。ここは自信をもって間違いと言える
        "contradicts_page": counts.get("ページと違うことを答えた", 0)
        + counts.get("ページの一部だけ正解", 0),
        # ページに無いことを答えた件数。真偽は誰にも確かめられない
        "beyond_page": counts.get("ページに無いことを答えた（真偽不明）", 0),
        "hedged": sum(1 for r in rows if r["hedged"]),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--limit", type=int, default=0, help="最初のN件だけ（動作確認用）")
    ap.add_argument("--no-search", action="store_true",
                    help="ウェブ検索を切る（AIの記憶だけで答えさせる）")
    args = ap.parse_args(argv)

    golden = load_golden(args.procedure)
    names = muni_names()
    proc = proc_name(args.procedure)
    cells = sorted(golden.items())
    if args.limit:
        cells = cells[: args.limit]

    rows = []
    for run in range(args.runs):
        for (mid, _field), g in cells:
            muni = names.get(mid, mid)
            try:
                row = one_cell(g, muni, proc, args.model, search=not args.no_search)
            except Exception as exc:                      # noqa: BLE001
                # ★失敗を成功に混ぜない。数えないで記録する
                print(f"  ! {muni}/{g.field}: {exc}", file=sys.stderr)
                continue
            row["run"] = run + 1
            rows.append(row)
            print(f"  {muni} {g.field}: {row['outcome']}")

    doc = {
        "_about": "ページを渡さずに素で聞いたときの答えを、人手の正解データと突き合わせた記録。",
        "measurement_version": MEASUREMENT_VERSION,
        "procedure_id": args.procedure, "procedure": proc,
        "model": args.model, "runs": args.runs,
        "search": not args.no_search,
        "questions": QUESTION,
        "summary": summarize(rows), "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "nosearch" if args.no_search else "search"
    out = OUT_DIR / f"cold-ask_{args.procedure}_{suffix}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['n']}件: " + " / ".join(f"{k} {v}" for k, v in s["by_outcome"].items()))


if __name__ == "__main__":
    main()

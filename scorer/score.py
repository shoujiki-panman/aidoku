"""採点層 (Layer A) — 抽出結果を人手ゴールデンセットと突合し、ルーブリックで採点する。

ネットワークには触らない。入力は extractor/out と golden/*.csv だけ。

ルーブリック（CLAUDE.md §3、Phase 1 の暫定版）:
  情報到達      20点  トップページから到達できたか
  抽出正確性    40点  4項目 × 各10点。1項目の点は 10×(伝わった必須要素数 ÷ 必須要素数)。
                      必須要素は「手続き×項目」ごとの固定スロット表に従い、ゴールデンCSVに人手で書く
  機械可読性    20点  HTML本文で取れた10 + 構造化データあり10
  オンライン明示 20点  窓口/オンライン可否が一意に読み取れるか

判定は LLM（`claude -p`）で行うが、これは採点器そのものなので、
判定結果は必ず人手で見直せるよう reports に全件出す。

**判定器に「正解/部分正解」を選ばせない。** 割れていたのはこの境界だけで、そこには
「住民が困りうる欠落」という主観語しか置かれていなかった。いまは必須要素ひとつずつに
yes/no を答えさせ、点はここで機械的に出す。どれを必須にするかの裁量は人間がCSVで持つ。
verdict ラベル（正解/部分正解/不正解）は下流（report.py・web/assets/app.js）が
5区分をハードコードしているため、点とは切り離して従来どおり返す。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from dataclasses import dataclass, field as dc_field
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXTRACT_DIR = ROOT / "extractor" / "out"
GOLDEN_DIR = Path(__file__).parent / "golden"
OUT_DIR = Path(__file__).parent / "out"
JUDGE_PROMPT = Path(__file__).parent / "judge_prompt.md"

FIELDS = ["必要書類", "窓口オンライン可否", "期限", "手数料"]

ONLINE_CLARITY_POINTS = {"明記": 20, "曖昧": 10, "記載なし": 0}

# 点は要素比から出すので、この辞書はもう配点には使わない。
# 判定ラベルの一覧として残す（下流がこの5文字列を前提にしている）。
VERDICT_POINTS = {
    "正解": 10,
    "正解(記載なしが正しい)": 10,
    "部分正解": 5,
    "不正解": 0,
    "不正解(幻覚)": 0,
}


@dataclass
class GoldenRow:
    municipality_id: str
    procedure_id: str
    field: str
    expected_found: bool
    expected_value: str
    note: str
    source_url: str
    # [(スロット名, 内容), ...]。内容が `-` のスロットは読み込み時に落とす
    required_elements: list[tuple[str, str]] = dc_field(default_factory=list)


def parse_elements(raw: str) -> list[tuple[str, str]]:
    """`スロット名=内容|スロット名=内容` を読む。`-` は分母から外す。

    `-` は「そのサイトがその要求を課していない」の意味。EU eGovernment Benchmark が
    non-applicable を理由つきで採点対象外にしているのと同じ扱い。
    """
    els: list[tuple[str, str]] = []
    for part in (raw or "").split("|"):
        part = part.strip()
        if not part:
            continue
        slot, _, body = part.partition("=")
        body = body.strip()
        if body and body != "-":
            els.append((slot.strip(), body))
    return els


def load_golden(procedure_id: str) -> dict[tuple[str, str], GoldenRow]:
    path = GOLDEN_DIR / f"{procedure_id}.csv"
    if not path.exists():
        raise SystemExit(f"ゴールデンセットがない: {path}")
    rows: dict[tuple[str, str], GoldenRow] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("municipality_id") or r["municipality_id"].startswith("#"):
                continue
            g = GoldenRow(
                municipality_id=r["municipality_id"].strip(),
                procedure_id=r["procedure_id"].strip(),
                field=r["field"].strip(),
                expected_found=r["expected_found"].strip().lower() in ("true", "1", "yes", "y"),
                expected_value=r["expected_value"].strip(),
                note=r.get("note", "").strip(),
                source_url=r.get("source_url", "").strip(),
                required_elements=parse_elements(r.get("required_elements", "")),
            )
            rows[(g.municipality_id, g.field)] = g
    return rows


def judge(golden: GoldenRow, item: dict, muni: str, proc: str, model: str) -> dict:
    """ゴールデンとの突合を1件ぶん判定する。明らかな場合はLLMを呼ばない。"""
    if not golden.expected_found and not item["found"]:
        return {"verdict": "正解(記載なしが正しい)", "points": 10.0,
                "reason": "正解側も記載なしで、正直に見つからないと報告した", "judged_by": "rule"}
    if not golden.expected_found and item["found"]:
        return {"verdict": "不正解(幻覚)", "points": 0.0,
                "reason": "サイトに記載がないのに値を答えた", "judged_by": "rule"}
    if golden.expected_found and not item["found"]:
        return {"verdict": "不正解", "points": 0.0,
                "reason": f"サイトには記載があるのに見つけられなかった（{item['failure_reason']}）",
                "judged_by": "rule"}
    if not golden.required_elements:
        return {"verdict": "未採点", "points": 0.0,
                "reason": "ゴールデンに required_elements が無い", "judged_by": "rule"}

    els_txt = "\n".join(f"{i + 1}. [{s}] {b}"
                        for i, (s, b) in enumerate(golden.required_elements))
    prompt = "\n".join([
        JUDGE_PROMPT.read_text(encoding="utf-8"),
        "\n---\n",
        f"## 対象\n\n- 自治体: {muni}\n- 手続き: {proc}\n- 項目: {golden.field}\n",
        # 正解の全文ではなく、人手で決めた必須要素だけを渡す。
        # 全文を渡すと「どこまで書けていれば十分か」の線引きが判定器に戻ってきてしまう。
        # golden.note は人間向けの注記なので渡さない（渡すと注記まで required 扱いされる）。
        f"\n## 必須要素（この{len(golden.required_elements)}件それぞれについて yes/no を答える）"
        f"\n\n{els_txt}",
        f"\n\n## エージェントの答え\n\n{item['value']}",
        f"\n\n## エージェントが挙げた根拠\n\n{item['evidence'] or '（なし）'}",
    ])
    proc_res = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=300,
    )
    if proc_res.returncode != 0:
        raise RuntimeError(f"claude -p failed: {proc_res.stderr[:300]}")
    text = proc_res.stdout.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    s, e = text.find("{"), text.rfind("}")
    data = json.loads(text[s:e + 1])

    els = data["elements"]
    # 要素数が合わない応答は黙って点にしない。数が違えば分母が変わり、点の意味が壊れる
    if len(els) != len(golden.required_elements):
        raise RuntimeError(
            f"要素数が合わない: 返り {len(els)} != 必須 {len(golden.required_elements)}"
            f"（{muni} / {golden.field}）")
    covered = sum(1 for x in els if x.get("covered") == "yes")
    total = len(els)
    missing = [golden.required_elements[i][0]
               for i, x in enumerate(els) if x.get("covered") != "yes"]
    verdict = "正解" if covered == total else ("不正解" if covered == 0 else "部分正解")
    reason = f"{covered}/{total}要素" + (f"（欠落: {'、'.join(missing)}）" if missing else "")
    return {"verdict": verdict, "points": round(10 * covered / total, 1), "reason": reason,
            "missing": missing, "elements": els, "judged_by": model}


def score_one(ext: dict, golden: dict[tuple[str, str], GoldenRow], model: str) -> dict:
    mid = ext["municipality_id"]
    reached = ext.get("reached", False)
    page = ext.get("page") or {}

    results = []
    accuracy = 0.0
    for field in FIELDS:
        g = golden.get((mid, field))
        if g is None:
            results.append({"field": field, "verdict": "未採点", "reason": "ゴールデンセットに行がない",
                            "points": 0.0, "judged_by": "rule", "missing": []})
            continue
        item = ext["items"].get(field) or {"found": False, "value": "", "evidence": "",
                                           "failure_reason": "到達失敗", "source": None}
        v = judge(g, item, ext["municipality"], ext["procedure"], model) if reached else {
            "verdict": "不正解", "points": 0.0, "reason": "ページに到達できなかった",
            "judged_by": "rule"}
        pts = v["points"]
        accuracy += pts
        results.append({
            "field": field, "verdict": v["verdict"], "reason": v.get("reason", ""),
            "points": pts, "judged_by": v.get("judged_by", ""),
            "missing": v.get("missing", []),
            "elements": v.get("elements", []),
            "expected_found": g.expected_found, "expected_value": g.expected_value,
            "agent_found": item["found"], "agent_value": item["value"],
            "failure_reason": item.get("failure_reason"),
        })

    accuracy = round(accuracy, 1)
    reach_pts = 20 if reached else 0
    html_ok = bool(reached and not page.get("is_pdf"))
    jsonld_ok = bool(page.get("has_jsonld"))
    machine_pts = (10 if html_ok else 0) + (10 if jsonld_ok else 0)
    # オンライン明示は、抽出時に観測した online_clarity を機械的に点へ変えるだけ。
    # 以前は「窓口オンライン可否」のLLM判定を流用していたが、同じ判定が抽出正確性(10点)と
    # ここ(20点)の両方を動かすため、判定が1回ゆらぐだけで合計が15点動いていた（実測）。
    online_clarity = (ext.get("online_clarity") or "記載なし") if reached else "記載なし"
    online_pts = ONLINE_CLARITY_POINTS.get(online_clarity, 0)
    total = round(reach_pts + accuracy + machine_pts + online_pts, 1)

    return {
        "municipality": ext["municipality"], "municipality_id": mid,
        "procedure": ext["procedure"], "procedure_id": ext["procedure_id"],
        "page_url": page.get("url"), "hops": page.get("hops"),
        "followed_urls": ext.get("followed_urls", []),
        "breakdown": {"情報到達": reach_pts, "抽出正確性": accuracy,
                      "機械可読性": machine_pts, "オンライン明示": online_pts},
        "machine": {"html": html_ok, "jsonld": jsonld_ok},
        "online_clarity": online_clarity,
        "total": total,
        "fields": results,
        "page_notes": ext.get("page_notes", ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--municipality", "-m", action="append")
    ap.add_argument("--model", default="claude-sonnet-5")
    args = ap.parse_args()

    golden = load_golden(args.procedure)
    files = sorted(EXTRACT_DIR.glob(f"extract_*_{args.procedure}.json"))
    if args.municipality:
        files = [f for f in files if any(f"extract_{m}_" in f.name for m in args.municipality)]
    if not files:
        raise SystemExit("抽出結果がない。先に extractor/extract.py を実行すること")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in files:
        ext = json.loads(f.read_text(encoding="utf-8"))
        res = score_one(ext, golden, args.model)
        out = OUT_DIR / f"score_{res['municipality_id']}_{res['procedure_id']}.json"
        out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        b = res["breakdown"]
        print(f"[{res['municipality']}] {res['total']:>5}点 "
              f"(到達{b['情報到達']} 正確{b['抽出正確性']} 可読{b['機械可読性']} オンライン{b['オンライン明示']})")


if __name__ == "__main__":
    main()

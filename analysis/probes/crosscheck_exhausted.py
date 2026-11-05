"""「書いていない」を、Claude 以外のモデルに読ませても同じになるかを調べる。

**なぜ要るか**: 虱潰しの `stopped=exhausted` は Claude だけが判定している。
同じモデルにしか聞いていないと、読み落としの癖が結論に混ざっても見えない。

**やること**（`plans/exhausted-crosscheck.md`）:

    Codex に同じプロンプトと本文を渡す → 根拠は同じ check_one で機械検査
    「見つけた」16件を陽性対照にする   → 見つけられないなら Codex の「無い」は当てにしない
    Codex が見つけた判定は Claude に再度聞く → 1回ごとのぶれと、系統の食い違いを分ける

★公開データは書き換えない。食い違いは人が読むまで「Claude の誤り」と書かない。

    python3 analysis/probes/crosscheck_exhausted.py --cache <crawler/cache> --check
    python3 analysis/probes/crosscheck_exhausted.py --cache <crawler/cache> -j 4
    python3 analysis/probes/crosscheck_exhausted.py --cache <crawler/cache> --recheck
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))

import reread_fee  # noqa: E402
from reread_field import ASK, proc_rules  # noqa: E402

from evidence_check import VERIFIED_VERDICTS, check_one  # noqa: E402
from extractor.fact_extract import MAX_TEXT_CHARS, call_claude  # noqa: E402
from extractor.response_contract import parse_json_reply  # noqa: E402

OUT = ROOT / "analysis" / "out" / "crosscheck-exhausted.json"
CLAUDE_MODEL = "claude-sonnet-5"
# 陽性対照の合格線。計画に書いた値（結果を見る前に固定）。
MIN_CONTROL_FOUND = 12


def targets(rows_by_procedure: dict[str, list[dict]]) -> list[dict]:
    """判定の一覧。exhausted は読んだ全ページ、found は見つけた1ページ（陽性対照）。

    ★error が付いたページは Claude が読めていないので、比べる相手にしない。
    """
    out = []
    for procedure, rows in rows_by_procedure.items():
        for row in rows:
            for field in row["fields"]:
                stopped = field["stopped"]
                if stopped == "found":
                    urls = [field["url"]]
                elif stopped == "exhausted":
                    urls = [p["url"] for p in field["looked"] if not p.get("error")]
                else:
                    continue
                for url in urls:
                    out.append({"procedure": procedure, "municipality_id": row["municipality_id"],
                                "municipality": row["municipality"], "field": field["field"],
                                "url": url, "group": "control" if stopped == "found" else "exhausted"})
    return out


def target_key(t: dict) -> str:
    return "|".join((t["procedure"], t["municipality_id"], t["field"], t["url"]))


def judge(reply: dict, text: str) -> dict:
    """モデルの返答を、虱潰しと同じ基準で判定する。"""
    check = check_one(reply.get("evidence"), text)
    return {"found": bool(reply.get("found")), "value": str(reply.get("value") or ""),
            "evidence": str(reply.get("evidence") or ""), "why_not": str(reply.get("why_not") or ""),
            "evidence_verdict": check["verdict"],
            "verified": bool(reply.get("found")) and check["verdict"] in VERIFIED_VERDICTS}


def call_codex(prompt: str, timeout: int = 600) -> str:
    """Codex に1回聞く。★読み取り専用で、リポジトリの外から動かす（本文は外部の文章）。"""
    with tempfile.TemporaryDirectory() as work:
        answer = Path(work) / "answer.txt"
        done = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral",
             "--color", "never", "-o", str(answer), "-"],
            input=prompt, capture_output=True, text=True, timeout=timeout, cwd=work, check=False)
        if done.returncode != 0 or not answer.exists():
            raise RuntimeError(f"codex が失敗: {done.returncode} {done.stderr[-200:]}")
        return answer.read_text("utf-8")


def ask(target: dict, names: dict[str, str], call) -> dict:
    """1判定。★本文が取れない・応答が壊れたものは error にして、「無い」に混ぜない。"""
    text = reread_fee.cache_text(target["url"])
    if not text:
        return {"error": "本文が取れない"}
    proc = names[target["procedure"]]
    proc_desc, not_this = proc_rules(proc, target["field"], target["municipality"])
    prompt = ASK.format(muni=target["municipality"], proc=proc, field=target["field"], proc_desc=proc_desc,
                        not_this=not_this, url=target["url"], text=text[:MAX_TEXT_CHARS])
    try:
        return judge(parse_json_reply(call(prompt)), text)
    except Exception as exc:                                   # noqa: BLE001
        return {"error": str(exc)[:200]}


def classify(claude_again: dict | None) -> str:
    """Codex が見つけた判定を分ける。"""
    if claude_again is None or claude_again.get("error"):
        return "未確認"
    return "1回ごとのぶれ" if claude_again.get("verified") else "系統の食い違い"


def summarize(items: list[dict]) -> dict:
    """★件数は判定（ページ×項目）と、結論の単位（自治体×項目）の両方で出す。"""
    control = [i for i in items if i["group"] == "control"]
    exhausted = [i for i in items if i["group"] == "exhausted"]
    hits = [i for i in exhausted if (i.get("codex") or {}).get("verified")]
    pair = lambda i: (i["procedure"], i["municipality_id"], i["field"])  # noqa: E731
    control_found = sum(1 for i in control if (i.get("codex") or {}).get("verified"))
    labels: dict[str, int] = {}
    for hit in hits:
        label = classify(hit.get("claude_again"))
        labels[label] = labels.get(label, 0) + 1
    return {
        "control": len(control), "control_found": control_found,
        "control_passed": control_found >= MIN_CONTROL_FOUND,
        "exhausted_judgments": len(exhausted),
        "exhausted_pairs": len({pair(i) for i in exhausted}),
        "codex_errors": sum(1 for i in items if (i.get("codex") or {}).get("error")),
        "unjudged": sum(1 for i in items if not i.get("codex")),
        "codex_found_judgments": len(hits),
        "codex_found_pairs": len({pair(i) for i in hits}),
        "by_label": labels,
    }


def load_rows() -> dict[str, list[dict]]:
    out = {}
    for path in sorted(glob.glob(str(ROOT / "analysis" / "out" / "sweep_*.json"))):
        doc = json.loads(Path(path).read_text("utf-8"))
        out[doc["procedure"]] = doc["rows"]
    return out


def save(items: dict[str, dict]) -> None:
    rows = list(items.values())
    doc = {"_about": "plans/exhausted-crosscheck.md。公開データではない。食い違いは人が読むまで誤りと書かない。",
           "claude_model": CLAUDE_MODEL, "summary": summarize(rows), "items": rows}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(OUT)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", required=True, type=Path, help="crawler/cache の場所")
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--check", action="store_true", help="呼ばずに規模だけ見る")
    ap.add_argument("--recheck", action="store_true", help="Codex が見つけた判定を Claude に聞き直す")
    args = ap.parse_args(argv)
    reread_fee.CACHE = args.cache

    rows = load_rows()
    names = {p: reread_fee.procedure_name(p) for p in rows}
    items = {target_key(t): t for t in targets(rows)}
    if OUT.exists():
        for old in json.loads(OUT.read_text("utf-8"))["items"]:
            if target_key(old) in items:
                items[target_key(old)] = old

    if args.check:
        no_text = [k for k, t in items.items() if not reread_fee.cache_text(t["url"])]
        print(json.dumps({**summarize(list(items.values())), "no_text": len(no_text)}, ensure_ascii=False))
        print("\n".join(no_text[:10]))
        return

    if args.recheck:
        todo, slot, call = ([t for t in items.values() if t["group"] == "exhausted"
                             and (t.get("codex") or {}).get("verified") and not t.get("claude_again")],
                            "claude_again", lambda p: call_claude(p, CLAUDE_MODEL))
    else:
        # ★error は次回もう一度聞く。
        todo, slot, call = ([t for t in items.values() if not t.get("codex") or t["codex"].get("error")],
                            "codex", call_codex)

    lock = threading.Lock()

    def work(target: dict) -> None:
        got = ask(target, names, call)
        with lock:
            target[slot] = got
            save(items)
            mark = "error" if got.get("error") else ("found" if got.get("verified") else "none")
            print(f"{mark:5} {target['group'][:4]} {target['municipality_id']} {target['field']} {target['url']}",
                  flush=True)

    with ThreadPoolExecutor(args.j) as pool:
        list(pool.map(work, todo))
    save(items)
    print(json.dumps(summarize(list(items.values())), ensure_ascii=False))


if __name__ == "__main__":
    main()

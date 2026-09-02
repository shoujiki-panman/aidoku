"""いま何がどうなっているかを、データから機械的に出す。**LLMは呼ばない。**

**なぜ要るか**: `STATUS.md` は手で書くので古くなる（2026-08-31 時点で13日前のまま）。
その結果、セッションのたびに「何が終わっていて何が残っているか」を調べ直していた。
**調べ直しの手間そのものを無くす。**

出すのは5つ。どれも**その場でファイルを読んで数える**（貯めた要約を信じない）。

    ① 見張り      いつ確認したか・何件変わったか
    ② 測定条件    手続きごとに揃っているか（揃わないと公開できない）
    ③ 虱潰し      見つけた／書いていない／言えない
    ④ 読めない底  何で塞がっているか
    ⑤ 公開データ  いつのものか・条件の記録があるか

最後に **次にやること**を、上の状態から機械的に導く。人の判断を混ぜない。

    python3 analysis/status.py           # 人が読む形
    python3 analysis/status.py --json    # 機械が読む形
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "analysis" / "out"
WEB = ROOT / "web" / "data"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "extractor"))

PROCEDURES = ("tennyu", "jidouteate", "sodaigomi")

# 見張りがこれより古ければ、古いと言う。毎朝回るので2日空けば異常。
WATCH_STALE_DAYS = 2
# 状態の履歴。**1日1行**（同じ日は二度追記しない）。
DEFAULT_HISTORY = ROOT / "web" / "data" / "history" / "status.jsonl"


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                      # noqa: BLE001
        return None


def _age_days(stamp: str | None) -> float | None:
    """いつの話かを日数で。**分からなければ None**（0日にしない）。"""
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((datetime.now(timezone.utc) - when).total_seconds() / 86400, 1)


def _from_main(relative: str) -> dict | None:
    """`origin/main` にある版。**見張りは main にコミットされる。**

    ★作業は積み上げブランチの上で進むので、手元の `web/data/site-status.json` は
      枝を切った日のまま止まる。手元だけ見て「見張りが止まっている」と言うのは嘘。
      実測で7.7日前と出したが、main では1日前だった。
    """
    try:
        raw = subprocess.run(["git", "show", f"origin/main:{relative}"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
    except Exception:                                      # noqa: BLE001
        return None
    if raw.returncode != 0:
        return None
    try:
        return json.loads(raw.stdout)
    except Exception:                                      # noqa: BLE001
        return None


def ref_age_days() -> float | None:
    """手元の `origin/main` が指しているコミットの古さ。

    ★`_from_main` は `origin/main` を読むが、**その参照自体が古いことがある**
      （`git fetch` していないだけ）。実測で「見張りが3.7日前・止まっている」と
      誤報した。`git fetch origin main` の後は0.7日前で、止まっていなかった。
      ネットには出ないので**どちらかは判定できない**。両方を候補として出す。
    """
    try:
        got = subprocess.run(["git", "log", "-1", "--format=%cI", "origin/main"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
    except Exception:                                      # noqa: BLE001
        return None
    return _age_days(got.stdout.strip()) if got.returncode == 0 else None


def newest(*docs: dict | None) -> dict | None:
    """`checked_at` がいちばん新しいもの。無いものは捨てる。"""
    dated = [d for d in docs if d and d.get("checked_at")]
    return max(dated, key=lambda d: d["checked_at"]) if dated else None


def watch() -> dict:
    """① 見張り。変わったページを見つけるが、**測り直しには繋がっていない。**"""
    doc = newest(_load(WEB / "site-status.json"), _from_main("web/data/site-status.json"))
    if not doc:
        return {"ok": False, "note": "site-status.json が無い"}
    summary = doc.get("summary") or {}
    age = _age_days(doc.get("checked_at"))
    stale = age is not None and age > WATCH_STALE_DAYS
    ref_age = ref_age_days()
    return {
        "ok": True,
        "checked_at": doc.get("checked_at"),
        "age_days": age,
        "stale": stale,
        "ref_age_days": ref_age,
        # ★参照が古ければ、見張りが止まったのではなく fetch していないだけかもしれない。
        "maybe_unfetched": bool(stale and ref_age is not None and ref_age > 0.5),
        "pages": summary.get("total"),
        "changed": summary.get("changed"),
        "gone": summary.get("gone"),
    }


def current_conditions() -> dict[str, object] | None:
    """いまの測定条件。**ファイルから計算する**（記録された値を信じない）。

    ★以前は `prompt_version` だけを見ていた。OCRを足したとき**プロンプトは
      変わらない**ので、条件が変わったのに「揃っている」と嘘をついた。
      実測で、この画面が「揃っている」と言った手続きを export が拒んだ。
      **測定条件はひとまとまりで効く。1つだけ見て揃ったと言わない。**
    """
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from stale import current
        return current()
    except Exception:                                      # noqa: BLE001
        return None


def conditions(procedure: str, now: dict[str, object] | None) -> dict:
    """② 測定条件。**自治体ごとに揃っていないと公開できない。**

    ★揃っていないまま出すと、別々の条件の結果が1枚の表に並ぶ。
      `export_dashboard.py` はこれを拒む。ここでは拒まれる理由を先に出す。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    from stale import differences
    stale, total, why = [], 0, set()
    for path in sorted(glob.glob(str(ROOT / f"extractor/out/extract_*_{procedure}.json"))):
        doc = _load(Path(path)) or {}
        total += 1
        diff = differences(doc.get("measurement") or {}, now) if now else []
        if diff:
            stale.append(doc.get("municipality_id") or Path(path).stem)
            why.update(diff)
    return {"municipalities": total, "stale": stale, "why": sorted(why),
            "uniform": not stale and total > 0}


def sweep(procedure: str) -> dict:
    """③ 虱潰し。"""
    doc = _load(OUT_DIR / f"sweep_{procedure}.json")
    if not doc:
        return {"ok": False}
    s = doc["summary"]
    return {"ok": True, "fields": s["swept_fields"], "pages": s["pages_read"],
            "found": s["found"], "exhausted": s["exhausted"],
            "unreadable": s.get("unreadable", 0), "errored": s["errored"],
            "budget": s["budget_hit"]}


def blockers() -> dict:
    """④ 読めない底。**塞いでいるURLを数える**（項目ではなく本数）。"""
    urls: set[str] = set()
    for procedure in PROCEDURES:
        doc = _load(OUT_DIR / f"sweep_{procedure}.json")
        for row in (doc or {}).get("rows", []):
            for field in row["fields"]:
                urls.update(field.get("unreadable") or [])
    return {"urls": len(urls)}


def published() -> dict:
    """⑤ 公開データ。**条件の記録が無いものは、そう言う。**"""
    out = {}
    for procedure in PROCEDURES:
        doc = _load(WEB / f"scores-{procedure}.json")
        if not doc:
            out[procedure] = {"ok": False}
            continue
        m = doc.get("measurement") or {}
        out[procedure] = {
            "ok": True,
            "generated_at": doc.get("generated_at"),
            "age_days": _age_days(doc.get("generated_at")),
            # ★model_version が null ＝ どのAIが出した数字か記録が無い
            "has_conditions": bool(m.get("model_version")),
        }
    return out


def next_actions(state: dict) -> list[str]:
    """状態から機械的に導く。**人の判断を混ぜない。**"""
    todo = []
    if state["watch"].get("stale"):
        if state["watch"].get("maybe_unfetched"):
            todo.append(f"見張りが{state['watch']['age_days']}日前。ただし手元の"
                        f"origin/main も{state['watch']['ref_age_days']}日前なので、"
                        "**先に `git fetch origin main`**。それでも古ければ"
                        "`.github/workflows/check-pages.yml` の実行を確認する")
        else:
            todo.append(f"見張りが{state['watch']['age_days']}日前で止まっている。"
                        "`.github/workflows/check-pages.yml` の実行を確認する")
    elif state["watch"].get("changed"):
        todo.append(f"見張りが{state['watch']['changed']}件の変化を見つけている。"
                    "測り直す対象を選ぶ（見張りは自動では測り直さない）")
    for procedure in PROCEDURES:
        cond = state["conditions"][procedure]
        if cond["stale"]:
            todo.append(f"{procedure}: 測定条件が{len(cond['stale'])}自治体ぶん揃っていない"
                        f"（{'・'.join(cond.get('why') or [])}）。公開できない。"
                        "`tools/run_pipeline.sh`")
    for procedure in PROCEDURES:
        sw = state["sweep"][procedure]
        if sw.get("ok") and sw["errored"]:
            todo.append(f"{procedure}: 虱潰しでエラーが{sw['errored']}件。読み直す")
    stale_pub = [p for p, v in state["published"].items()
                 if v.get("ok") and not v["has_conditions"]]
    if stale_pub:
        todo.append(f"公開データに測定条件の記録が無い: {', '.join(stale_pub)}"
                    "（どのAIが出した数字か追えない）")
    return todo or ["止まっているものは無い"]


STATE_SCHEMA = "aidoku-status-1.0"


def snapshot(state: dict, recorded_at: str) -> dict:
    """いまの状態を、履歴1行にする。Pure Function。

    **なぜ要るか**: `status.py` は毎セッション走るが**読むだけで残していない**。
    「いつ条件が崩れたか」「読めない底がいつ増えたか」を後から言えない。
    数だけ残す（区の名前もURLも持たない）。毎日1行でも軽い。
    """
    return {
        "schema": STATE_SCHEMA,
        "recorded_at": recorded_at,
        # ★重複判定はここ。毎セッション走るので、時刻で見ると1日に何行も入る。
        "recorded_day": recorded_at[:10],
        "watch_checked_at": state["watch"].get("checked_at"),
        "watch_changed": state["watch"].get("changed"),
        # 条件が揃っていない自治体の数。0 なら公開できる。
        "conditions_stale": {p: len(state["conditions"][p].get("stale") or [])
                             for p in PROCEDURES},
        # found=見つけた / exhausted=読み切った上で書いていない / unreadable=読めない
        "sweep": {p: {k: state["sweep"][p].get(k)
                      for k in ("found", "exhausted", "unreadable", "errored", "pages")}
                  for p in PROCEDURES},
        "blockers": state["blockers"].get("urls"),
        "published_has_conditions": {p: bool(state["published"][p].get("has_conditions"))
                                     for p in PROCEDURES},
    }


def collect() -> dict:
    now = current_conditions()
    return {
        "conditions_now": now,
        "watch": watch(),
        "conditions": {p: conditions(p, now) for p in PROCEDURES},
        "sweep": {p: sweep(p) for p in PROCEDURES},
        "blockers": blockers(),
        "published": published(),
    }


def render(state: dict) -> str:
    lines = ["# AI読 いまの状態（データから機械的に出したもの）", ""]
    w = state["watch"]
    if w.get("ok"):
        mark = "★古い" if w["stale"] else "動いている"
        lines.append(f"## ① 見張り: {mark}（{w['age_days']}日前）")
        lines.append(f"   {w['pages']}ページ確認 / 変わった {w['changed']} / 消えた {w['gone']}")
    else:
        lines.append(f"## ① 見張り: {w.get('note')}")
    lines.append("")

    lines.append("## ② 測定条件（揃っていないと公開できない）")
    for procedure in PROCEDURES:
        c = state["conditions"][procedure]
        mark = ("揃っている" if c["uniform"]
                else f"★{len(c['stale'])}自治体ぶん古い（{'・'.join(c.get('why') or [])}）")
        lines.append(f"   {procedure:10} {c['municipalities']:2}自治体  {mark}")
    lines.append("")

    lines.append("## ③ 虱潰し（候補を全部読んだか）")
    total = {"found": 0, "exhausted": 0, "unreadable": 0, "errored": 0, "pages": 0}
    for procedure in PROCEDURES:
        s = state["sweep"][procedure]
        if not s.get("ok"):
            lines.append(f"   {procedure:10} 未実施")
            continue
        for k in total:
            total[k] += s[k]
        lines.append(f"   {procedure:10} 見つけた{s['found']:2} / 書いていない{s['exhausted']:3} "
                     f"/ 言えない{s['unreadable']:2}")
    lines.append(f"   {'計':10} 見つけた{total['found']:2} / 書いていない{total['exhausted']:3} "
                 f"/ 言えない{total['unreadable']:2}（{total['pages']}ページ読了）")
    lines.append("")

    lines.append(f"## ④ 読めない底: {state['blockers']['urls']}本のURLが塞いでいる")
    lines.append("")

    lines.append("## ⑤ 公開データ")
    for procedure, p in state["published"].items():
        if not p.get("ok"):
            lines.append(f"   {procedure:10} 無い")
            continue
        cond = "条件あり" if p["has_conditions"] else "★条件の記録なし"
        lines.append(f"   {procedure:10} {p['age_days']}日前 / {cond}")
    lines.append("")

    lines.append("## 次にやること")
    for item in next_actions(state):
        lines.append(f"   - {item}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="機械が読む形で出す")
    ap.add_argument("--record", metavar="PATH", nargs="?", const=str(DEFAULT_HISTORY),
                    help="いまの状態を履歴に1行追記する（同じ日は追記しない）")
    args = ap.parse_args(argv)

    state = collect()
    if args.record:
        sys.path.insert(0, str(ROOT))
        from history import append_snapshot
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = snapshot(state, now)
        added = append_snapshot(args.record, row, key_fields=("recorded_day",))
        print(f"{args.record}: " + ("1件追記" if added else "同じ日が既にあるので追記なし"))

    if args.json:
        print(json.dumps({**state, "next": next_actions(state)},
                         ensure_ascii=False, indent=2))
        return
    print(render(state))


if __name__ == "__main__":
    main()

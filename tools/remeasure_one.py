"""1通（analysis/daily_diff.py）で見つけた候補ページを、1コマンドで測り直す。

    python3 tools/remeasure_one.py -m kita -p sodaigomi

★なぜ自動にしないか: daily_diff の「4項目に触れた」目印は語で拾うだけなので、
  飾りの差も拾う（例: 練馬区の児童手当はナビの差だった）。候補を全部 LLM で測ると
  利用上限を飾りの差に使う。だから**本人が1通を見て選び、このコマンドで測る。**

やること（LLM を呼ぶのは 2 と 3 だけ。数分かかる）:
  1. 起点ページ（web/data/scores-<p>.json のその自治体の page_url）を取り直す。
     ★今日のページで読ませるため。**既定キャッシュ（crawler/cache）のその1URLが
       今日の取得で上書きされる。** 取得に失敗すると、fetch の仕様上そのURLの記録も
       失敗の記録になる。リンク先のページはキャッシュのまま（取り直さない）
  2. extractor/extract.py --follow を、出力先を分けて走らせる
  3. scorer/score.py で、その出力を採点する（正解データの行が無い項目は「未採点」）
  4. 前回（公開データ）と今回を、公開データと同じ式（読めた項目×20点＋オンライン明示）で
     並べた Markdown を書き、標準出力にも出す

★書き換えないもの: 公開データ（web/data/*）・extractor/out・scorer/out。
  出力は analysis/out/daily/remeasure/<YYYYMMDD-HHMMSS>-<m>-<p>/ にだけ置く。
  区のサイトの文を含むので公開しない（.gitignore 済み）。

★前回の値は #236 以前の条件（claude -p に道具が開いていた）で測ったもの。
  今回は道具を閉じて測る。MEASUREMENT_VERSION は上げていない（上げると探索結果
  171件との比較が全部止まる）ので、**条件の違いは数字の横に文で書く。**
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT / "analysis"))
from export_dashboard import ITEM_POINTS, build_entry  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

from fact_types import EXTRACTOR_TO_DISPLAY  # noqa: E402

PROCEDURES = ("tennyu", "jidouteate", "sodaigomi")
OUT_BASE = ROOT / "analysis" / "out" / "daily" / "remeasure"
JST = timezone(timedelta(hours=9))
# 並べる順は公開データの breakdown と同じ（4項目 → オンライン明示）
POINT_LABELS = (*EXTRACTOR_TO_DISPLAY.values(), "オンライン明示")
CONDITION_NOTE = ("前回は #236 以前の条件（道具が開いていた）で測った値。"
                  "条件が違うので参考として並べる。")


def previous_entry(scores_doc: dict, municipality_id: str) -> dict | None:
    """公開データ（scores-<p>.json）から、その自治体の1件と前回の測定時刻を取る。"""
    entry = next((m for m in scores_doc.get("municipalities", [])
                  if m.get("id") == municipality_id), None)
    if entry is None:
        return None
    runs = (scores_doc.get("measurement") or {}).get("runs") or []
    run = next((r for r in runs if r.get("municipality_id") == municipality_id), {})
    return {**entry, "run_at": run.get("run_at")}


def point_rows(prev: dict | None, cur: dict) -> list[tuple[str, int | None, int, int | None]]:
    """(項目, 前回, 今回, 差) を項目ごとと合計で。前回が無い項目は None（0 と言わない）。"""
    prev_b = (prev or {}).get("breakdown") or {}
    rows = []
    for label in POINT_LABELS:
        before, after = prev_b.get(label), cur["breakdown"].get(label, 0)
        rows.append((label, before, after, None if before is None else after - before))
    before_total = None if prev is None else prev.get("total")
    after_total = cur["total"]
    rows.append(("合計", before_total, after_total,
                 None if before_total is None else after_total - before_total))
    return rows


def _num(value: int | float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+g}" if signed else f"{value:g}"


def _scorer_lines(scored: dict | None) -> list[str]:
    if scored is None:
        return ["- 採点結果なし（scorer が結果を書かなかった）"]
    b = scored["breakdown"]
    unscored = [f["field"] for f in scored["fields"] if f["verdict"] == "未採点"]
    lines = [f"- 合計 {_num(scored['total'])}点（到達{_num(b['情報到達'])} 正確{_num(b['抽出正確性'])} "
             f"可読{_num(b['機械可読性'])} オンライン{_num(b['オンライン明示'])}）"]
    if unscored:
        lines.append(f"- 正解データ（scorer/golden）に行が無く未採点: {'・'.join(unscored)}。"
                     "この式の合計は上の表と比べられない")
    return lines


def render(*, municipality: str, procedure: str, when: str, page_url: str, fetch_note: str,
           prev: dict | None, cur: dict, scored: dict | None, out_dir: str) -> str:
    """1回の測り直しの報告。LLM を呼ばない。"""
    out = [f"# 測り直し {municipality} {procedure}（{when}）", "",
           f"> {CONDITION_NOTE}", "",
           f"- 起点ページ: {page_url}（{fetch_note}）"]
    if cur.get("page_url") and cur["page_url"] != page_url:
        out.append(f"- ★抽出が読んだ起点は別のページ: {cur['page_url']}（探索結果の最上位が変わった）")
    prev_when = (prev or {}).get("run_at") or "記録なし"
    out += [f"- 前回の測定: {prev_when}（公開データ web/data の値）",
            f"- 出力: {out_dir}", "",
            f"## 公開データと同じ式（読めた項目×{ITEM_POINTS}点＋オンライン明示）", "",
            "| 項目 | 前回 | 今回 | 差 |", "|---|---:|---:|---:|"]
    out += [f"| {label} | {_num(b)} | {_num(a)} | {_num(d, signed=True)} |"
            for label, b, a, d in point_rows(prev, cur)]
    if prev is None:
        out += ["", "前回の記録が公開データに無い。"]
    out += ["", "## scorer（正解データとの突合）", "", *_scorer_lines(scored), "",
            "※区のサイトの文を含むことがある。公開しない（.gitignore 済み）。公開データは書き換えていない"]
    return "\n".join(out) + "\n"


def run_dir(base: Path, now: datetime, municipality_id: str, procedure_id: str) -> Path:
    """1回ぶんの置き場所。時刻つきなので、同じ区を2回測っても前の結果を消さない。"""
    return base / f"{now.strftime('%Y%m%d-%H%M%S')}-{municipality_id}-{procedure_id}"


def _refetch(url: str) -> str:
    result = PoliteFetcher().fetch(url, refresh=True)
    if result.error or result.status != 200 or not result.body_path:
        raise SystemExit(f"起点ページを取り直せなかった: {url} status={result.status} {result.error or ''}")
    return f"{result.fetched_at} に取り直した・{result.status}"


def _run(script: str, *args: str) -> None:
    # ★別プロセスで走らせる。extract.py / score.py は import 時に sys.path を足すので、
    #   同じプロセスで呼ぶと互いのモジュール名（extract と score の定数）が混ざる。
    done = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT, check=False)
    if done.returncode != 0:
        raise SystemExit(f"{script} が止まった（終了コード {done.returncode}）。上の出力を見る")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-m", "--municipality", required=True)
    ap.add_argument("-p", "--procedure", required=True, choices=PROCEDURES)
    ap.add_argument("--model", default="claude-sonnet-5")
    args = ap.parse_args(argv)
    m, p = args.municipality, args.procedure

    scores_doc = json.loads((ROOT / "web" / "data" / f"scores-{p}.json").read_text(encoding="utf-8"))
    prev = previous_entry(scores_doc, m)
    if prev is None or not prev.get("page_url"):
        raise SystemExit(f"公開データに {m} / {p} の起点ページが無い")
    fetch_note = _refetch(prev["page_url"])

    now = datetime.now(JST)
    out_dir = run_dir(OUT_BASE, now, m, p)
    extract_dir, score_dir = out_dir / "extract", out_dir / "score"
    _run("extractor/extract.py", "-m", m, "-p", p, "--follow", "--model", args.model,
         "--out-dir", str(extract_dir))
    _run("scorer/score.py", "-m", m, "-p", p, "--model", args.model,
         "--extract-dir", str(extract_dir), "--out-dir", str(score_dir))

    extract = json.loads((extract_dir / f"extract_{m}_{p}.json").read_text(encoding="utf-8"))
    score_path = score_dir / f"score_{m}_{p}.json"
    scored = json.loads(score_path.read_text(encoding="utf-8")) if score_path.exists() else None
    text = render(municipality=prev["name"],
                  procedure=scores_doc["procedure"], when=now.strftime("%Y-%m-%d %H:%M JST"),
                  page_url=prev["page_url"], fetch_note=fetch_note, prev=prev,
                  cur=build_entry(extract), scored=scored, out_dir=str(out_dir.relative_to(ROOT)))
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

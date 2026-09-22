"""毎朝1通、「前回から本文が変わったページ」を並べる。**LLMは呼ばない。**

★なぜ LLM の前にこれが要るか（2026-09-23 に 45ページを取り直して確かめた）:
  見張り（check_pages）は条件付きGETで 200 が返ると「変わった」とする。本文は読まない。
  取り直して本文を比べると、**45件中8件は本文が同じ**だった。残りも多くは
  「チャットを閉じる」「Foreign Language→Languages」のような飾りの差で、
  住民に効く変化（北区の粗大ごみ手数料のキャッシュレス化、足立区の児童手当の振込日）は一部。
  全部を LLM で測り直すと、利用上限を飾りの差に使うことになる。

やること:
  1. 採点済みページ（check_pages.targets）を取り直す（3秒間隔・robots.txt は fetch 側が守る）
  2. 前回の取得（無ければ採点時のキャッシュ）と**本文**を行単位で比べる
  3. 足された行・消えた行に、4項目（必要書類・窓口オンライン可否・期限・手数料）の語が
     あるかで印を付ける。印のあるページが LLM で測り直す候補
  4. analysis/out/daily/YYYY-MM-DD.md に書く

★出力には区のサイトの文がそのまま入る。区の実文は公開しない方針（#100）なので、
  出力先は .gitignore に入れてある。

    python3 analysis/daily_diff.py                 # 全手続き
    python3 analysis/daily_diff.py -p tennyu       # 手続きを絞る
"""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "crawler"))
import htmlutil  # noqa: E402
from check_pages import targets  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

PROCEDURES = ("tennyu", "jidouteate", "sodaigomi")
DAILY_CACHE = ROOT / "crawler" / "cache-daily"
OUT_DIR = ROOT / "analysis" / "out" / "daily"
JST = timezone(timedelta(hours=9))
SHOW_LINES = 4

# 4項目に触れたかの目印。LLM を呼ばずに「測り直す価値があるか」を仕分けるためだけに使う。
# 点は付けない（採点は scorer の仕事）。見落としは「その他」に残るので消えない。
FIELD_WORDS = {
    "手数料": ("手数料", "無料", "円", "決済", "キャッシュレス", "減免"),
    "必要書類": ("持ち物", "必要なもの", "書類", "本人確認", "委任状", "マイナンバーカード", "在留カード"),
    "期限": ("以内", "期限", "期間", "までに", "振込", "支払"),
    "窓口オンライン可否": ("窓口", "受付時間", "オンライン", "電子申請", "インターネット", "申込"),
}


@dataclass
class PageDiff:
    municipality: str
    procedure: str
    url: str
    status: str                      # "変化" / "同じ" / "比べられない"
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    note: str = ""


def changed_lines(old: str, new: str) -> tuple[list[str], list[str]]:
    """足された行と消えた行。空行と、前後の空白だけの違いは数えない。"""
    a = [s.strip() for s in old.splitlines() if s.strip()]
    b = [s.strip() for s in new.splitlines() if s.strip()]
    added, removed = [], []
    for line in difflib.unified_diff(a, b, lineterm="", n=0):
        if line.startswith(("+++", "---", "@@")):
            continue
        (added if line.startswith("+") else removed).append(line[1:])
    return added, removed


def touched_fields(lines: list[str]) -> list[str]:
    """行のどれかに語が出てくる項目。並びは FIELD_WORDS の順で固定する。"""
    return [name for name, words in FIELD_WORDS.items()
            if any(w in line for line in lines for w in words)]


def compare(target: dict, old_text: str | None, new_text: str | None) -> PageDiff:
    diff = PageDiff(target["municipality"], target["procedure"], target["url"], "比べられない")
    if old_text is None or new_text is None:
        diff.note = "前回か今回の本文が取れなかった"
        return diff
    diff.added, diff.removed = changed_lines(old_text, new_text)
    diff.status = "変化" if diff.added or diff.removed else "同じ"
    diff.fields = touched_fields(diff.added + diff.removed)
    return diff


def _text(result) -> str | None:
    if result is None or not result.body():
        return None
    return htmlutil.parse(result.body(), result.url).text


def check_one(target: dict, base: PoliteFetcher, daily: PoliteFetcher) -> PageDiff:
    """前回の取得（無ければ採点時のキャッシュ）と、今取り直した本文を比べる。"""
    url = target["url"]
    old_text = _text(daily.cached(url)) or _text(base.cached(url))
    try:
        new_text = _text(daily.fetch(url, refresh=True))
    except Exception as exc:  # noqa: BLE001 — 1ページの失敗で1通を止めない
        diff = compare(target, old_text, None)
        diff.note = f"取得に失敗: {exc}"
        return diff
    return compare(target, old_text, new_text)


def _page_block(d: PageDiff) -> list[str]:
    head = f"- **{d.municipality} {d.procedure}** +{len(d.added)} / -{len(d.removed)}行"
    if d.fields:
        head += f"　［{'・'.join(d.fields)}］"
    lines = [head, f"  {d.url}"]
    lines += [f"  + {s[:120]}" for s in d.added[:SHOW_LINES]]
    lines += [f"  - {s[:120]}" for s in d.removed[:SHOW_LINES]]
    return lines


def render(day: str, diffs: list[PageDiff]) -> str:
    """1通の本文。4項目に触れたものを先に、飾りの可能性があるものを後に並べる。"""
    hit = [d for d in diffs if d.status == "変化" and d.fields]
    other = [d for d in diffs if d.status == "変化" and not d.fields]
    same = [d for d in diffs if d.status == "同じ"]
    failed = [d for d in diffs if d.status == "比べられない"]
    out = [f"# AI読 {day}", "",
           f"{len(diffs)}ページを確認。4項目に触れた変化 {len(hit)} / その他の変化 {len(other)} / "
           f"同じ {len(same)} / 比べられない {len(failed)}", ""]
    if not hit and not other:
        out += ["変化なし", ""]
    if hit:
        out += ["## 4項目に触れた変化（測り直す候補）", ""]
        for d in hit:
            out += _page_block(d)
        out.append("")
    if other:
        out += ["## その他の変化（お知らせ欄・ナビの可能性）", ""]
        out += [f"- {d.municipality} {d.procedure} +{len(d.added)} / -{len(d.removed)}行" for d in other]
        out.append("")
    if failed:
        out += ["## 比べられなかった", ""]
        out += [f"- {d.municipality} {d.procedure}: {d.note}" for d in failed]
        out.append("")
    out.append("※区のサイトの文をそのまま含む。公開しない（.gitignore 済み）")
    return "\n".join(out) + "\n"


def out_path(out_dir: Path, now: datetime) -> Path:
    """その日の1通の置き場所。**同じ日の2回目で1通目を消さない。**

    ★2回目は「前回」が1回目になるので、ほぼ「変化なし」になる。上書きすると
      その日いちばん大事な1回目が消える（2026-09-23 に実際に消えた）。
    """
    path = out_dir / f"{now.strftime('%Y-%m-%d')}.md"
    return path if not path.exists() else out_dir / f"{now.strftime('%Y-%m-%d-%H%M%S')}.md"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-p", "--procedure", action="append", choices=PROCEDURES)
    args = ap.parse_args(argv)
    base, daily = PoliteFetcher(), PoliteFetcher(cache_dir=DAILY_CACHE)
    diffs = [check_one(t, base, daily) for t in targets(list(args.procedure or PROCEDURES))]
    now = datetime.now(JST)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = out_path(OUT_DIR, now)
    path.write_text(render(now.strftime("%Y-%m-%d"), diffs), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()

"""採点済みのページが前回から変わったかを確かめ、状態を1本のJSONに書く。

**LLMは呼ばない。本文も読まない。** 送るのは条件付きGETだけで、変わっていなければ
サーバーが 304 を返し本文は転送されない。69ページでも数分で終わる。

設計は Mulmo Control（本人の既存作品）の `mulmo-check-updates` に倣った。

- 確認スクリプトが**1本のJSONを書き**、画面はそれを読むだけ
- 確認は**安いコマンドだけ**（あちらは `npm view`、こちらは条件付きGET）
- `checked_at` を必ず持つ。いつ時点の話かが分かる
- **失敗しても必ずJSONを書く。**空にしない。Node未検出でも書くのと同じ

「変わった」と分かったページを測り直す（LLMを呼ぶ）のは、この後の別工程。
ここは「どれを測り直せばよいか」までしか言わない。

実行:
    python3 crawler/check_pages.py                      # 全手続き
    python3 crawler/check_pages.py -p tennyu            # 手続きを絞る
    python3 crawler/check_pages.py --out web/data/site-status.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from polite_fetch import CheckResult, PoliteFetcher  # noqa: E402

DEFAULT_OUT = ROOT / "web" / "data" / "site-status.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def targets(procedures: list[str]) -> list[dict]:
    """採点済みの公開データから、見張る対象（自治体×手続き×URL）を作る。"""
    rows = []
    for procedure in procedures:
        path = ROOT / "web" / "data" / f"scores-{procedure}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for muni in data["municipalities"]:
            url = muni.get("page_url")
            if not url:
                continue
            rows.append({
                "municipality_id": muni["id"],
                "municipality": muni["name"],
                "procedure_id": procedure,
                "procedure": data["procedure"],
                "url": url,
            })
    return rows


def to_item(target: dict, result: CheckResult) -> dict:
    return {
        **target,
        "status": result.status,
        "changed": result.changed,
        "gone": result.gone,
        "reason": result.reason,
        "checked_at": result.checked_at,
        "error": result.error,
    }


def summarize(items: list[dict]) -> dict:
    changed = [i for i in items if i["changed"] is True]
    unchanged = [i for i in items if i["changed"] is False]
    unknown = [i for i in items if i["changed"] is None]
    # 消えたページは changed の内数。いちばん重大なので別に数える
    gone = [i for i in changed if i.get("gone")]
    edited = [i for i in changed if not i.get("gone")]
    return {
        "total": len(items),
        "changed": len(changed),
        "gone": len(gone),
        "edited": len(edited),
        "unchanged": len(unchanged),
        "unknown": len(unknown),
        # 人が最初に読む1行。Mulmo Control の summary と同じ役割
        "headline": (
            f"{len(items)}ページを確認。"
            + (f"**{len(gone)}件が消えました**。" if gone else "")
            + f"変わっていたのは {len(edited)}件"
            f"（変化なし {len(unchanged)}件／判定できず {len(unknown)}件）"
        ),
    }


def prime(target: dict, fetcher: PoliteFetcher) -> None:
    """比べる土台が無いページを、一度だけ取り直して ETag / Last-Modified を記録する。

    2026-08-17時点のキャッシュはヘッダを保存する前に取ったもので、比較材料が無い。
    ここで一度だけ本文ごと取り直す（3秒間隔は fetch 側が守る）。次回からは
    条件付きGETで済み、変わっていなければ本文は転送されない。
    """
    fetcher.fetch(target["url"], refresh=True)


def run(procedures: list[str], fetcher: PoliteFetcher, prime_missing: bool = False) -> dict:
    items = []
    for target in targets(procedures):
        result = fetcher.check(target["url"])
        if prime_missing and result.changed is None and "記録が無い" in result.reason:
            prime(target, fetcher)
            result = CheckResult(
                url=target["url"], status=0, changed=None, checked_at=now(),
                reason="今回は土台作り（ヘッダを記録した）。次回から変化を判定できる")
        items.append(to_item(target, result))
    return {
        "_about": (
            "採点済みページが前回取得時から変わったかを、条件付きGETだけで確かめた結果。"
            "本文は読んでおらず、点数の測り直しはしていない。"
            "changed=true は『測り直しが必要』という意味であって、悪くなったという意味ではない。"
        ),
        "checked_at": now(),
        "summary": summarize(items),
        "items": items,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-p", "--procedure", action="append", dest="procedures",
                        help="手続きID（繰り返し指定可。既定は公開中の全部）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="取得済みキャッシュの場所（既定は crawler/cache）")
    parser.add_argument("--prime", action="store_true",
                        help="比較材料の無いページを一度だけ取り直してヘッダを記録する"
                             "（初回のみ重い。次回から条件付きGETで済む）")
    args = parser.parse_args(argv)

    procedures = args.procedures or ["tennyu", "jidouteate", "sodaigomi"]
    fetcher = PoliteFetcher(cache_dir=args.cache_dir) if args.cache_dir else PoliteFetcher()

    try:
        report = run(procedures, fetcher, prime_missing=args.prime)
    except Exception as e:  # noqa: BLE001
        # 失敗しても必ず書く。画面が「いつの話か分からない」状態にならないようにする
        report = {
            "_about": "確認そのものに失敗した記録",
            "checked_at": now(),
            "summary": {"total": 0, "changed": 0, "unchanged": 0, "unknown": 0,
                        "headline": f"確認できませんでした: {type(e).__name__}"},
            "items": [],
            "error": f"{type(e).__name__}: {e}",
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(report["summary"]["headline"])
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()

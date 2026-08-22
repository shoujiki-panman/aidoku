"""採点したページが、いつアーカイブされているかを Wayback から引く。

**コピーは持たない**（Issue #99）。過去の姿を残す仕事は国立国会図書館 WARP と
Internet Archive が既にやっている。こちらは「いつの版があるか」だけを持ち、
実物はリンクで渡す。

なぜ要るか: AI読の見張りは 2026-08-17 に始まったばかりで、それ以前の変化を
持っていない。Wayback は 2024-09 からのスナップショットを持っている。
**測っていない期間の「ページが変わったか」を、こちらが取得しに行かずに言える。**

⚠️ ここで「AIが読めたか」は分からない。Waybackが持っているのはHTMLだけで、
そこから手数料が読み取れたかは記録されていない（#99）。**AI読の資産はそちら。**

    python3 analysis/export_archive.py            # web/data/archive.json を作る
    python3 analysis/export_archive.py --dry-run  # 何件引くかだけ見る
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
CDX = "https://web.archive.org/cdx/search/cdx"
UA = "TokyoAgentReadinessBot/0.1 (+https://github.com/shoujiki-panman/aidoku)"
# archive.org への行儀。相手は非営利なので、こちらのクロールと同じ間隔をあける
MIN_INTERVAL_SEC = 3.0
TIMEOUT_SEC = 30


def measured_pages() -> list[dict]:
    """採点したページを、手続き・自治体つきで集める。"""
    out = []
    for f in sorted((ROOT / "web/data").glob("scores-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for m in d.get("municipalities", []):
            if m.get("page_url"):
                out.append({
                    "url": m["page_url"],
                    "municipality_id": m["id"],
                    "municipality": m["name"],
                    "procedure_id": d["procedure_id"],
                    "procedure": d["procedure"],
                })
    return out


def fetch_snapshots(url: str) -> list[dict] | None:
    """そのURLのスナップショット一覧。引けなければ None（推測しない）。"""
    q = urllib.parse.urlencode({
        "url": url, "output": "json", "filter": "statuscode:200",
        "fl": "timestamp,digest", "collapse": "digest",
    })
    req = urllib.request.Request(f"{CDX}?{q}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            rows = json.loads(r.read().decode("utf-8") or "[]")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if not rows or len(rows) < 2:
        return []
    header = rows[0]
    return [dict(zip(header, row, strict=False)) for row in rows[1:]]


def summarize(url: str, snaps: list[dict]) -> dict:
    """1ページぶんの記録。digest で畳んであるので、件数＝中身が変わった回数。"""
    stamps = sorted(s["timestamp"] for s in snaps if s.get("timestamp"))
    return {
        "url": url,
        "snapshots": len(stamps),
        "first": stamps[0] if stamps else None,
        "last": stamps[-1] if stamps else None,
        # 実物はここへ渡す。こちらでコピーは持たない
        "wayback": f"https://web.archive.org/web/*/{url}",
        "timestamps": stamps,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "web/data/archive.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="先頭N件だけ引く（試すとき用）")
    ap.add_argument("--retry-failed", action="store_true",
                    help="前回引けなかったものだけ引き直し、取れている分に足す")
    args = ap.parse_args(argv)

    pages = measured_pages()
    # URLの重複を落とす（同じページを2つの手続きで採点していることがある）
    seen: dict[str, dict] = {}
    for pg in pages:
        seen.setdefault(pg["url"], pg)
    # 取れている分を捨てない。archive.org は時々落ちるので、引き直しは足し算にする
    prev = {}
    out_path = Path(args.out)
    if out_path.exists():
        try:
            old = json.loads(out_path.read_text(encoding="utf-8"))
            prev = {p["url"]: p for p in old.get("pages", []) if p.get("url")}
            prev_failed = list(old.get("failed", []))
        except (json.JSONDecodeError, KeyError):
            prev_failed = []
    else:
        prev_failed = []

    urls = prev_failed if args.retry_failed else list(seen)
    if args.retry_failed and not urls:
        print("前回引けなかったものはありません")
        return
    if args.limit:
        urls = urls[:args.limit]

    print(f"採点したページ {len(pages)}件／URLの実数 {len(seen)}件"
          + (f"（先頭{len(urls)}件だけ）" if args.limit else ""))
    if args.dry_run:
        for u in urls[:5]:
            print(f"  [dry] {u}")
        return

    records, failed = [], []
    for i, u in enumerate(urls, 1):
        if i > 1:
            time.sleep(MIN_INTERVAL_SEC)
        snaps = fetch_snapshots(u)
        if snaps is None:
            failed.append(u)
            print(f"  {i}/{len(urls)} 引けなかった: {u}")
            continue
        rec = summarize(u, snaps)
        rec.update({k: seen[u][k] for k in
                    ("municipality_id", "municipality", "procedure_id", "procedure")})
        records.append(rec)
        print(f"  {i}/{len(urls)} {rec['snapshots']:>3}版 "
              f"{rec['first'] or '-'}〜{rec['last'] or '-'}  {seen[u]['municipality']}")

    # 今回取れたもので上書きし、触っていないものは残す
    merged = dict(prev)
    for r in records:
        merged[r["url"]] = r
    records = sorted(merged.values(), key=lambda r: (r.get("procedure_id", ""), r.get("municipality_id", "")))
    still_failed = [u for u in failed if u not in merged]

    doc = {
        "_about": "採点したページが、いつアーカイブされているか。"
                  "コピーは持たず、実物は Internet Archive へリンクする（Issue #99）。"
                  "ここに『AIが読めたか』は含まれない（Waybackが持つのはHTMLだけ）。",
        "source": "Internet Archive Wayback Machine CDX API",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "n_pages": len(records),
        "n_failed": len(still_failed),
        "failed": still_failed,
        "pages": records,
    }
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(f"\n{args.out}: {len(records)}件（引けなかったもの {len(still_failed)}件）")


if __name__ == "__main__":
    main()

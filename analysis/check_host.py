"""候補と、実際に読んだページに、区の外のホストがどれだけ混ざっているか。

**なぜ要るか**: METHOD §4-3 は「同一ホストしか選べないのだから、除外された側は見えない」
と書いていた。だが `link_filter` が `page_host in href`（**URL全体への部分一致**）だったため、
**同一ホスト制限はそもそも効いていなかった。**

    https://b.hatena.ne.jp/entry/https://www.city.adachi.tokyo.jp/gomi/...
    https://translation2.j-server.com/...?url=https://www.city.adachi.tokyo.jp/

区のホスト名を中に含むだけの別ホストが、同一ホストとして通っていた。

**LLMは呼ばない**（探索結果と抽出結果を読むだけ）。判定にも点数にも使わない。

    python3 analysis/check_host.py
"""

from __future__ import annotations

import argparse
import glob
import json
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "analysis" / "out"

VERSION = "check-host-0.1"


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url or "").netloc


def off_host(top_url: str, urls: list[str]) -> list[str]:
    """トップと**ホストが違う**ものだけ。部分一致ではなく完全一致で見る。"""
    top = host_of(top_url)
    return [u for u in urls if host_of(u) and host_of(u) != top]


def candidate_rows() -> tuple[Counter, set, int]:
    """候補一覧に混ざっている別ホスト。（ホスト別件数, またがる組, 候補総数）"""
    hosts: Counter = Counter()
    groups: set = set()
    total = 0
    for path in sorted(glob.glob(str(ROOT / "crawler/out/discovery_*.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        urls = [c["url"] for c in doc.get("candidates", [])]
        total += len(urls)
        for url in off_host(doc["top_url"], urls):
            hosts[host_of(url)] += 1
            groups.add((doc["municipality"], doc["procedure_id"]))
    return hosts, groups, total


def read_rows() -> list[dict]:
    """**実際に読んだ**別ホスト。起点に選んだものと、追従して開いたもの。"""
    tops = {}
    for path in glob.glob(str(ROOT / "crawler/out/discovery_*.json")):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        tops[(doc["municipality"], doc["procedure_id"])] = doc["top_url"]

    out = []
    for path in sorted(glob.glob(str(ROOT / "extractor/out/extract_*.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        key = (doc["municipality"], doc["procedure_id"])
        if not doc.get("reached") or key not in tops:
            continue
        top = tops[key]
        entry = (doc.get("page") or {}).get("url", "")
        for url in off_host(top, [entry]):
            out.append({"municipality": key[0], "procedure": key[1],
                        "how": "起点", "url": url})
        for url in off_host(top, list(doc.get("followed_urls") or [])):
            out.append({"municipality": key[0], "procedure": key[1],
                        "how": "追従", "url": url})
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    hosts, groups, total = candidate_rows()
    read = read_rows()
    doc = {
        "_about": "同一ホスト制限が効いていなかったことの記録。判定には使わない。",
        "version": VERSION,
        "summary": {
            "candidates": total, "off_host_candidates": sum(hosts.values()),
            "groups_affected": len(groups),
            "by_host": dict(hosts.most_common()),
            "read_off_host": len(read),
            "read_as_entry": sum(1 for r in read if r["how"] == "起点"),
        },
        "read_rows": read,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "off_host.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = doc["summary"]
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return
    print(f"候補 {s['candidates']}本中 別ホスト {s['off_host_candidates']}本"
          f" / {s['groups_affected']}組にまたがる")
    for host, n in list(s["by_host"].items())[:10]:
        print(f"  {n:>4}  {host}")
    print(f"\n実際に読んだ別ホスト {s['read_off_host']}件"
          f"（うち起点にしたもの {s['read_as_entry']}件）")
    for row in read:
        print(f"  {row['how']} {row['municipality']} {row['procedure']}  {row['url'][:70]}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

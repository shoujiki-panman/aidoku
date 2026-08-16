"""情報到達の測定 — 自治体トップページから手続きページまで、何ホップで辿り着けるか。

エージェントが人間の勘なしにページを見つけられるかを測るので、検索エンジンは使わず、
トップページのリンク文字列と URL だけを頼りにビーム探索する（深さ2まで）。

出力: out/discovery_<自治体>_<手続き>.json
  - candidates: スコア順の候補ページ（hops つき）
  - fetch_log: 実際に取得したURLとキャッシュヒットの記録（再現性のため）
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path

from htmlutil import normalize, parse
from polite_fetch import PoliteFetcher

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from measurement import build_discovery_measurement, utc_timestamp  # noqa: E402

OUT_DIR = Path(__file__).parent / "out"
TARGETS = Path(__file__).parent / "targets.json"

# 各深さで「何ページ展開し、1ページから何本追うか」。行儀の都合で全体の取得数も上限で縛る。
# 深さ3まで潜るのは、多くの自治体で トップ→くらし→戸籍住民→転入届 の3階層構成のため。
MAX_DEPTH = 3
BEAM = {1: (1, 6), 2: (3, 4), 3: (4, 3)}  # depth: (展開する親の数, 親1つあたり追うリンク数)
MAX_FETCHES = 26

# リンクを追う価値がないもの
NEGATIVE_HINTS = ("english", "chinese", "korean", "/en/", "/foreign", "yasashii", "rss", "sitemap")


@dataclass
class Candidate:
    url: str
    link_text: str
    hops: int
    score: int
    parent: str
    status: int | None = None
    is_pdf: bool = False
    text_len: int = 0
    has_jsonld: bool = False


def score_link(link_text: str, url: str, kw: dict) -> int:
    """リンク文字列とURLだけで、手続きページらしさを点数化する。"""
    s = 0
    blob = f"{link_text} {url}".lower()
    for word in kw["strong"]:
        if word in link_text:
            s += 10
    for word in kw["weak"]:
        if word in link_text:
            s += 3
    for word in kw["url_hints"]:
        if word in url.lower():
            s += 4
    for word in NEGATIVE_HINTS:
        if word in blob:
            s -= 8
    if url.lower().endswith(".pdf"):
        s -= 2  # PDFは減点。機械可読性の採点でも不利に扱う
    return s


def link_filter(top_url: str, allow_subdomains: bool):
    """リンクを辿ってよいかを判定する関数を作る。

    既定は「そのページと同じホストだけ」。23区はこれで足りる
    （2026-08-13 時点、採点した69ページすべてがトップと同じホスト）。

    東京都は局ごとにホストが分かれている（tax. / seikatubunka. / kyoiku. …）ので、
    同じホストだけに限ると**トップページから1歩も進めない。**それは都のサイトの
    性質ではなく、こちらの制限。住民のAIはサブドメインの境目で止まらない。
    そこで targets.json 側で `allow_subdomains: true` を立てた自治体だけ、
    親ドメイン配下（`*.metro.tokyo.lg.jp`）を辿れるようにする。

    フラグ（コマンドライン引数）ではなく設定に置くのは、**つけ忘れると
    結果が変わるのに、あとから見て分からなくなる**ため。
    """
    if not allow_subdomains:
        return lambda page_host, href: page_host in href

    # www. を落として親ドメインを作る。www.metro.tokyo.lg.jp → metro.tokyo.lg.jp
    top_host = urllib.parse.urlsplit(top_url).netloc
    parent = top_host[4:] if top_host.startswith("www.") else top_host

    def allowed(page_host: str, href: str) -> bool:
        host = urllib.parse.urlsplit(href).netloc
        return host == parent or host.endswith("." + parent)

    return allowed


def discover(muni: dict, proc: dict, fetcher: PoliteFetcher, measurement: dict) -> dict:
    kw = proc["keywords"]
    can_follow = link_filter(muni["top_url"], bool(muni.get("allow_subdomains")))
    seen: set[str] = set()
    candidates: list[Candidate] = []
    fetch_log: list[dict] = []
    fetches = 0

    def get(url: str):
        nonlocal fetches
        r = fetcher.fetch(url)
        fetches += 1
        fetch_log.append({
            "url": url, "status": r.status, "from_cache": r.from_cache,
            "blocked_by_robots": r.blocked_by_robots, "error": r.error,
        })
        return r

    top_url = muni["top_url"]
    seen.add(normalize(top_url))
    top = get(top_url)
    if not top.body_path:
        return {
            "municipality": muni["name"], "municipality_id": muni["id"],
            "procedure": proc["name"], "procedure_id": proc["id"], "top_url": top_url,
            "error": top.error or "トップページを取得できなかった",
            "candidates": [], "fetch_log": fetch_log, "measurement": measurement,
        }

    def harvest(page_url: str, body: str, hops: int, limit: int) -> list[Candidate]:
        links, _, _ = parse(body, page_url)
        host = page_url.split("/")[2]
        # 同じページに同じ先へのリンクが複数あるのは普通なので、最高得点の1件に畳む
        best: dict[str, Candidate] = {}
        for ln in links:
            if not ln.href.startswith("http") or not can_follow(host, ln.href):
                continue  # 既定は同一ホスト。allow_subdomains のときだけ親ドメイン配下
            n = normalize(ln.href)
            if n in seen:
                continue
            sc = score_link(ln.text, ln.href, kw)
            if sc <= 0:
                continue
            prev = best.get(n)
            if prev is None or sc > prev.score:
                best[n] = Candidate(url=n, link_text=ln.text, hops=hops, score=sc, parent=page_url)
        scored = sorted(best.values(), key=lambda c: -c.score)
        picked = scored[:limit]
        for c in picked:
            seen.add(c.url)
        return picked

    def visit(c: Candidate) -> str | None:
        """候補ページを1件取得し、機械可読性の材料を記録する。本文を返す（取れなければ None）。"""
        r = get(c.url)
        c.status = r.status
        c.is_pdf = "pdf" in (r.content_type or "").lower() or c.url.lower().endswith(".pdf")
        candidates.append(c)
        if not r.body_path or c.is_pdf:
            return None
        body = r.body()
        _, text, jsonld = parse(body, c.url)
        c.text_len = len(text)
        c.has_jsonld = bool(jsonld)
        return body

    # 深さごとに「有望な親を展開 → 子を取得」を繰り返す
    frontier: list[tuple[Candidate, str]] = [(Candidate(top_url, "(top)", 0, 0, ""), top.body())]
    for depth in range(1, MAX_DEPTH + 1):
        n_parents, n_links = BEAM[depth]
        next_frontier: list[tuple[Candidate, str]] = []
        for parent, parent_body in sorted(frontier, key=lambda pb: -pb[0].score)[:n_parents]:
            for c in harvest(parent.url, parent_body, hops=depth, limit=n_links):
                if fetches >= MAX_FETCHES:
                    break
                body = visit(c)
                if body is not None:
                    next_frontier.append((c, body))
            if fetches >= MAX_FETCHES:
                break
        if fetches >= MAX_FETCHES or not next_frontier:
            break
        frontier = next_frontier

    candidates.sort(key=lambda c: (-c.score, c.hops))
    return {
        "municipality": muni["name"],
        "municipality_id": muni["id"],
        "procedure": proc["name"],
        "procedure_id": proc["id"],
        "top_url": top_url,
        "measurement": measurement,
        "candidates": [asdict(c) for c in candidates],
        "fetch_log": fetch_log,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--municipality", "-m", action="append", help="自治体ID（省略時は全件）")
    ap.add_argument("--procedure", "-p", default="tennyu")
    args = ap.parse_args()

    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    procs = {p["id"]: p for p in cfg["procedures"]}
    proc = procs[args.procedure]
    munis = [m for m in cfg["municipalities"] if not args.municipality or m["id"] in args.municipality]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetcher = PoliteFetcher()
    measurement = build_discovery_measurement(
        MAX_DEPTH, BEAM, MAX_FETCHES, utc_timestamp()
    )
    for m in munis:
        result = discover(m, proc, fetcher, measurement)
        out = OUT_DIR / f"discovery_{m['id']}_{proc['id']}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        top3 = result["candidates"][:3]
        print(f"[{m['name']}] 候補 {len(result['candidates'])} 件 → {out.name}")
        for c in top3:
            print(f"    {c['score']:>3}点 hop{c['hops']} {c['link_text'][:24]} {c['url']}")


if __name__ == "__main__":
    main()

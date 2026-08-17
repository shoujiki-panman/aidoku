"""取得層 (Layer B) — 行儀のよい fetcher。

守ること (CLAUDE.md §2「やらないこと」):
  - robots.txt を必ず読み、Disallow なら取得しない
  - 同一ドメインへのリクエスト間隔は 3 秒以上
  - User-Agent にプロジェクト名と連絡先を明記
  - 一度取得したページはディスクキャッシュから返す（再取得しない）

標準ライブラリのみで動かす。取得結果は生HTMLとメタJSONの両方を残し、
再実行が完全にキャッシュから再現できる状態にする。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import asdict, dataclass
from pathlib import Path

# 連絡先はユーザーが自分のものに差し替える。空のまま本番クロールしない。
CONTACT = "https://github.com/shoujiki-panman/aidoku"
USER_AGENT = f"TokyoAgentReadinessBot/0.1 (+{CONTACT})"

MIN_INTERVAL_SEC = 3.0
CACHE_DIR = Path(__file__).parent / "cache"


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    fetched_at: str
    from_cache: bool
    blocked_by_robots: bool
    body_path: str | None
    last_modified: str | None = None
    etag: str | None = None
    error: str | None = None

    def body(self) -> str:
        if not self.body_path:
            return ""
        return Path(self.body_path).read_text(encoding="utf-8", errors="replace")


class PoliteFetcher:
    def __init__(self, cache_dir: Path = CACHE_DIR, min_interval: float = MIN_INTERVAL_SEC):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # --- キャッシュ ---

    def _paths(self, url: str) -> tuple[Path, Path]:
        host = urllib.parse.urlparse(url).netloc
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        d = self.cache_dir / host
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.html", d / f"{key}.meta.json"

    def cached(self, url: str) -> FetchResult | None:
        _, meta_path = self._paths(url)
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["from_cache"] = True
        return FetchResult(**meta)

    # --- レート制御 ---

    def _wait(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self._last_request_at[host] = time.monotonic()

    # --- robots.txt ---

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urllib.parse.urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]

        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{origin}/robots.txt"
        try:
            self._wait(parts.netloc)
            req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                rp.parse(_decode(resp).splitlines())
        except urllib.error.HTTPError as e:
            # robots.txt が「無い」(404/410) ときだけ全許可。
            # それ以外（401・403 のアクセス制限、5xx のサーバ不調、429 など）は
            # 「読めなかった」ので保守的に全禁止扱いにする。
            # 読めないことを許可へ倒すと、相手が落ちているときに一番叩くことになる。
            if e.code in (404, 410):
                rp.parse([])
            else:
                rp = None
        except Exception:
            rp = None

        self._robots[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        if rp is None:
            return False
        return rp.can_fetch(USER_AGENT, url)

    def crawl_delay(self, url: str) -> float:
        rp = self._robots_for(url)
        if rp is None:
            return self.min_interval
        try:
            d = rp.crawl_delay(USER_AGENT)
        except Exception:
            d = None
        return max(self.min_interval, float(d)) if d else self.min_interval

    # --- 本体 ---

    def fetch(self, url: str, refresh: bool = False) -> FetchResult:
        if not refresh:
            hit = self.cached(url)
            if hit is not None:
                return hit

        body_path, meta_path = self._paths(url)

        if not self.allowed(url):
            result = FetchResult(
                url=url, final_url=url, status=0, content_type="",
                fetched_at=_now(), from_cache=False, blocked_by_robots=True,
                body_path=None, error="disallowed by robots.txt",
            )
            _write_meta(meta_path, result)
            return result

        host = urllib.parse.urlparse(url).netloc
        delay = self.crawl_delay(url)
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < delay:
                time.sleep(delay - elapsed)
        self._last_request_at[host] = time.monotonic()

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.8,*/*;q=0.5",
                "Accept-Language": "ja",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = _decode(resp)
                result = FetchResult(
                    url=url,
                    final_url=resp.geturl(),
                    status=resp.status,
                    content_type=resp.headers.get("Content-Type", ""),
                    fetched_at=_now(),
                    from_cache=False,
                    blocked_by_robots=False,
                    body_path=str(body_path),
                    last_modified=resp.headers.get("Last-Modified"),
                    etag=resp.headers.get("ETag"),
                )
                body_path.write_text(text, encoding="utf-8")
        except urllib.error.HTTPError as e:
            result = FetchResult(
                url=url, final_url=url, status=e.code, content_type="",
                fetched_at=_now(), from_cache=False, blocked_by_robots=False,
                body_path=None, error=f"HTTP {e.code}",
            )
        except Exception as e:  # noqa: BLE001 — 落とさず理由を残す
            result = FetchResult(
                url=url, final_url=url, status=0, content_type="",
                fetched_at=_now(), from_cache=False, blocked_by_robots=False,
                body_path=None, error=f"{type(e).__name__}: {e}",
            )

        _write_meta(meta_path, result)
        return result


def _decode(resp) -> str:
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    charset = resp.headers.get_content_charset()
    for enc in filter(None, [charset, "utf-8", "cp932", "euc-jp"]):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _write_meta(path: Path, result: FetchResult) -> None:
    data = asdict(result)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="行儀のよい単発フェッチ（キャッシュ優先）")
    ap.add_argument("url")
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して再取得")
    args = ap.parse_args()

    r = PoliteFetcher().fetch(args.url, refresh=args.refresh)
    print(json.dumps(asdict(r), ensure_ascii=False, indent=2))

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

import url_guard
from url_guard import UrlNotAllowed

# 連絡先はユーザーが自分のものに差し替える。空のまま本番クロールしない。
CONTACT = "https://github.com/shoujiki-panman/aidoku"
USER_AGENT = f"TokyoAgentReadinessBot/0.1 (+{CONTACT})"

MIN_INTERVAL_SEC = 3.0

# 1ページの上限。区の手続きページは大きくても数百KB。これを超えるものは
# 読む相手を間違えている（動画・アーカイブ等）ので、途中で切って捨てる。
MAX_BODY_BYTES = 8 * 1024 * 1024

# ページが無くなったと見なすHTTPステータス。
# 404=見つからない / 410=意図的に削除した、とサーバーが明言している。
# 5xx は相手側の一時的な事情のことが多いので、ここには入れない。
GONE_STATUSES = frozenset({404, 410})


class GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """リダイレクト先を1ホップずつ SSRF ガードに通す。

    urllib は 302 を黙って追う。入口のURLだけ調べても、
    「公開ホスト → 169.254.169.254」と飛ばされたら意味が無い。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url_guard.check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener_installed = False


def install_guarded_opener() -> None:
    """既定の opener をガード付きに差し替える（プロセス内で一度だけ）。

    urlopen() を呼ぶ側のコードは変えない。テストが urlopen を差し替える作りを
    壊さずに、リダイレクト追跡だけを守れる。
    """
    global _opener_installed
    if _opener_installed:
        return
    urllib.request.install_opener(urllib.request.build_opener(GuardedRedirectHandler))
    _opener_installed = True


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_fingerprint(html_text: str, url: str) -> str:
    """変化の判定に使う指紋。生HTMLではなく、**抜き出した本文**から作る。

    生HTMLは中身が同じでも毎回変わることがある。2026-08-17の実測では、
    渋谷区のページに Google 検索ウィジェットの `targetId="search-input-31748057"`
    というリクエストごとに変わるIDが入っていて、生HTMLのハッシュは毎回別物になった
    （差分はその1行だけ・本文は同一）。品川区も同様。

    本文だけを見れば、両区とも別々の取得で完全に一致する。
    """
    import htmlutil  # 循環importを避けるため関数内で読む

    try:
        return sha256_of(htmlutil.parse(html_text, url).text)
    except Exception:  # noqa: BLE001 — 解析できない場合は生HTMLに退避する
        return sha256_of(html_text)


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
    content_hash: str | None = None
    error: str | None = None

    def body_hash(self) -> str | None:
        """本文の指紋。記録が無ければキャッシュのファイルから計算する。

        ETag も Last-Modified も返さないサイト（動的生成ページ）で、変化の有無を
        見るために使う。古いキャッシュには記録が無いが、本文は残っているので
        後から計算できる。
        """
        if self.content_hash:
            return self.content_hash
        if not self.body_path or not Path(self.body_path).exists():
            return None
        return content_fingerprint(self.body(), self.url)

    def body(self) -> str:
        """テキスト本文。**テキストでない応答には空を返す。**

        ★PDF や Word のバイト列を文字として返すと、呼ぶ側が化けた文字列を
          「本文」として読んでしまう。読めないものは空にして、
          `body_bytes()` を使わせる。
        """
        if not self.body_path or not is_text_type(self.content_type):
            return ""
        return Path(self.body_path).read_text(encoding="utf-8", errors="replace")

    def body_bytes(self) -> bytes:
        """保存したままのバイト列。PDF / Word を読むのはこちら。"""
        if not self.body_path or not Path(self.body_path).exists():
            return b""
        return Path(self.body_path).read_bytes()


@dataclass
class CheckResult:
    """「前回から変わったか」だけを見た結果。中身は読まない。

    測り直し（重い・LLMを呼ぶ）と、見張り（安い・HTTPだけ）を分けるための型。
    Mulmo Control が `npm view` でバージョンだけ見て中身を落とさないのと同じ考え方。
    """

    url: str
    status: int           # 304=変わっていない / 200=変わった / 404=消えた / 0=確かめられない
    changed: bool | None  # None = 判定できなかった（前回の記録が無い・エラー等）
    checked_at: str
    reason: str           # なぜその判定になったか。人が読む
    gone: bool = False    # ページ自体が無くなった。changed の中でも別扱いにする
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    error: str | None = None


class PoliteFetcher:
    def __init__(self, cache_dir: Path = CACHE_DIR, min_interval: float = MIN_INTERVAL_SEC,
                 resolve=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        # 名前解決の入口。テストはここを差し替えてネットワークに出ない。
        self._resolve = resolve or url_guard.default_resolve
        install_guarded_opener()

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

    # --- 見張り（安い確認） ---

    def check(self, url: str) -> CheckResult:
        """前回取得したときから変わったかだけを確かめる。中身は読まない。

        1. キャッシュに ETag / Last-Modified があれば条件付きGET。変わっていなければ
           サーバーが 304 を返し、**本文は転送されない**
        2. どちらも無いサイト（CDN配下の動的生成ページ。2026-08-17時点で渋谷区・品川区）は
           **本文のハッシュ**で比べる。本文は転送されるが、LLMは呼ばない

        どちらの経路でもキャッシュは書き換えない。測り直しは別の工程。
        """
        # ガードが先。取りに行ってよいURLでないなら、キャッシュも見ない
        blocked = self.guard(url)
        if blocked is not None:
            return CheckResult(url=url, status=0, changed=None, checked_at=_now(),
                               reason=f"取りに行ってよいURLではない（{blocked}）")
        prev = self.cached(url)
        if prev is None:
            return CheckResult(url=url, status=0, changed=None, checked_at=_now(),
                               reason="前回の記録が無い（まだ一度も取得していない）")
        if not self.allowed(url):
            return CheckResult(url=url, status=0, changed=None, checked_at=_now(),
                               reason="robots.txt で許可されていない")

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
            "Accept-Language": "ja",
        }
        # 両方あるときは両方送る。サーバーがどちらで判断してもよいようにする
        if prev.etag:
            headers["If-None-Match"] = prev.etag
        if prev.last_modified:
            headers["If-Modified-Since"] = prev.last_modified

        # ヘッダで比べられないサイトは、本文のハッシュで比べる（動的生成ページ）。
        # 条件付きGETより重い（本文が転送される）が、LLMは呼ばないので確認は安いまま。
        by_hash = not (prev.etag or prev.last_modified)
        prev_hash = prev.body_hash() if by_hash else None
        if by_hash and prev_hash is None:
            return CheckResult(
                url=url, status=0, changed=None, checked_at=_now(),
                reason="前回のETag・Last-Modified・本文のどれも残っていないので比べられない")

        self._wait(urllib.parse.urlparse(url).netloc)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                if by_hash:
                    now_hash = content_fingerprint(_decode(resp), url)
                    same = now_hash == prev_hash
                    return CheckResult(
                        url=url, status=resp.status, changed=not same, checked_at=_now(),
                        reason=("本文のハッシュが前回と同じ（このサイトはETagもLast-Modifiedも返さない）"
                                if same else
                                "本文のハッシュが前回と違う（このサイトはETagもLast-Modifiedも返さない）"),
                        content_hash=now_hash)
                # 200 が返った = 変わった（本文は読まない。測り直しは別の工程）
                return CheckResult(
                    url=url, status=resp.status, changed=True, checked_at=_now(),
                    reason=f"HTTP {resp.status}（前回から変わっている）",
                    etag=resp.headers.get("ETag"),
                    last_modified=resp.headers.get("Last-Modified"))
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return CheckResult(url=url, status=304, changed=False, checked_at=_now(),
                                   reason="304 Not Modified（前回から変わっていない）",
                                   etag=prev.etag, last_modified=prev.last_modified)
            if e.code in GONE_STATUSES:
                # ページが消えた・移動したのは、いちばん重大な変化。
                # 「判定できない」に混ぜると通知されずに見逃す。
                return CheckResult(
                    url=url, status=e.code, changed=True, gone=True, checked_at=_now(),
                    reason=f"HTTP {e.code}（ページが無くなったか、移動した）",
                    error=f"HTTP {e.code}")
            # 5xx などは相手側の一時的な事情のことが多い。消えたと決めつけない
            return CheckResult(url=url, status=e.code, changed=None, checked_at=_now(),
                               reason=f"HTTP {e.code} が返り、変化を判定できない",
                               error=f"HTTP {e.code}")
        except Exception as e:  # noqa: BLE001 — 落とさず理由を残す
            return CheckResult(url=url, status=0, changed=None, checked_at=_now(),
                               reason="通信に失敗して判定できない",
                               error=f"{type(e).__name__}: {e}")

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
        if self.guard(robots_url) is not None:
            self._robots[origin] = None
            return None
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

    def guard(self, url: str) -> str | None:
        """取りに行ってよければ None。だめなら理由の文字列。

        robots の fail-closed が偶然この一部を塞いでいたが、robots.txt が 404 を
        返す内部エンドポイントには通ってしまう（404＝robotsが無い＝全許可）。
        だからここで明示的に見る。
        """
        try:
            url_guard.check_url(url, resolve=self._resolve)
            return None
        except UrlNotAllowed as e:
            return str(e)

    def allowed(self, url: str) -> bool:
        if self.guard(url) is not None:
            return False
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

        blocked = self.guard(url)
        if blocked is not None:
            result = FetchResult(
                url=url, final_url=url, status=0, content_type="",
                fetched_at=_now(), from_cache=False, blocked_by_robots=False,
                body_path=None, error=f"blocked by url guard: {blocked}",
            )
            _write_meta(meta_path, result)
            return result

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
                content_type = resp.headers.get("Content-Type", "")
                raw = _read_raw(resp)
                # ★HTMLはこれまでどおり文字で保存する（既存キャッシュと互換）。
                #   PDF/Word はバイト列のまま保存する。往復で壊れるため。
                as_text = is_text_type(content_type)
                text = decode_body(raw, resp.headers.get_content_charset()) if as_text else ""
                result = FetchResult(
                    url=url,
                    final_url=resp.geturl(),
                    status=resp.status,
                    content_type=content_type,
                    fetched_at=_now(),
                    from_cache=False,
                    blocked_by_robots=False,
                    body_path=str(body_path),
                    last_modified=resp.headers.get("Last-Modified"),
                    etag=resp.headers.get("ETag"),
                    content_hash=(content_fingerprint(text, url) if as_text
                                  else "sha256:" + hashlib.sha256(raw).hexdigest()),
                )
                if as_text:
                    body_path.write_text(text, encoding="utf-8")
                else:
                    body_path.write_bytes(raw)
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


# 本文をテキストとして保存してよい Content-Type。ここに無いものはバイト列で保存する。
TEXT_TYPES = frozenset({
    "application/xhtml+xml", "application/xml", "application/json",
    "application/rss+xml", "application/atom+xml", "application/javascript",
})


def is_text_type(content_type: str) -> bool:
    """テキストとして保存してよいか。

    ★ここを誤ると、PDF や Word のバイト列が decode→encode の往復で壊れる。
      **実際に壊れていた**（29KBのdocxがキャッシュでは51,927バイトに膨らんでいた。
      不正なバイトが U+FFFD 3バイトに置き換わったため）。
      非HTMLを一度も読んでいなかったので、誰も気づかなかった。

    Content-Type が空のときはテキスト扱いにする。古いキャッシュを壊さないため。
    """
    head = content_type.split(";")[0].strip().lower()
    if not head:
        return True
    return head.startswith("text/") or head in TEXT_TYPES


def _read_raw(resp) -> bytes:
    # 上限より1バイト多く読む。ぴったりで切ると「上限ちょうど」と
    # 「上限を超えた」を区別できない。
    raw = resp.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError(f"本文が大きすぎる（上限 {MAX_BODY_BYTES} バイト）")
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw


def decode_body(raw: bytes, charset: str | None) -> str:
    """テキスト本文を文字に直す。文字コードは宣言→utf-8→cp932→euc-jp の順に試す。"""
    for enc in filter(None, [charset, "utf-8", "cp932", "euc-jp"]):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _decode(resp) -> str:
    return decode_body(_read_raw(resp), resp.headers.get_content_charset())


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

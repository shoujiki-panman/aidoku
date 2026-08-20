"""外へ取りに行ってよいURLかを判定する（SSRF対策）。

**ここを通らない取得経路を作らないこと。** 取得層 `polite_fetch.py` の
fetch / check / robots取得は、すべて `check_url` を先に通す。

なぜ要るか: `gennai_app/server.py` の `/invoke` は住民・職員が入れたURLを
そのまま `judge_live()` に渡し、取得層が取りに行く。検証が `^https?://` だけだと
`http://169.254.169.254/...` のような内部宛先をこちらに取りに行かせられる。

判定は3つ:
  1. scheme が http / https か（file: や gopher: を弾く）
  2. ホスト名が解決できるか（**できなければ拒否**。分からないものは通さない）
  3. 解決した**すべての**アドレスが公開アドレスか
     1つでも private / loopback / link-local / multicast / 予約なら拒否する。
     全部見るのは、DNS rebinding で「1件だけ内部」を混ぜる手があるため。

robots.txt の fail-closed（読めなければ取得しない）が偶然この一部を塞いでいたが、
robots が404を返す内部エンドポイントには通ってしまう（404は「robotsが無い」＝
全許可に倒れる仕様のため）。だからここで明示的に塞ぐ。
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse

ALLOWED_SCHEMES = frozenset({"http", "https"})


class UrlNotAllowed(Exception):
    """取りに行ってはいけないURL。理由を message に入れる。"""


def default_resolve(host: str) -> list[str]:
    """ホスト名を、返ってくる**すべての**アドレスへ解決する。"""
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def ip_reason(ip_text: str) -> str | None:
    """このアドレスを拒否する理由。問題なければ None。Pure Function。"""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return f"アドレスとして読めない: {ip_text}"

    # ::ffff:127.0.0.1 のようなIPv4射影は、中のIPv4で判定する
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        inner = ip_reason(str(mapped))
        return None if inner is None else f"IPv4射影アドレス（{inner}）"

    if ip.is_unspecified:
        return f"未指定アドレス: {ip}"
    if ip.is_loopback:
        return f"ループバック: {ip}"
    if ip.is_link_local:
        return f"リンクローカル: {ip}"
    if ip.is_multicast:
        return f"マルチキャスト: {ip}"
    if ip.is_private:
        return f"プライベートアドレス: {ip}"
    if ip.is_reserved:
        return f"予約アドレス: {ip}"
    return None


def check_url(url: str, resolve=default_resolve) -> None:
    """取りに行ってよければ黙って返る。だめなら UrlNotAllowed を投げる。"""
    if not isinstance(url, str) or not url.strip():
        raise UrlNotAllowed("URLが空")
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlNotAllowed(f"http/https以外は取りに行かない: {parts.scheme or '(scheme無し)'}")

    host = parts.hostname
    if not host:
        raise UrlNotAllowed(f"ホスト名が無い: {url}")

    try:
        addrs = resolve(host)
    except Exception as exc:  # 解決できないものは通さない（fail-closed）
        raise UrlNotAllowed(f"名前を解決できない: {host} ({type(exc).__name__})") from exc
    if not addrs:
        raise UrlNotAllowed(f"名前を解決できない: {host}")

    for a in addrs:
        reason = ip_reason(a)
        if reason is not None:
            raise UrlNotAllowed(f"{host} → {reason}")


def is_allowed(url: str, resolve=default_resolve) -> bool:
    """例外を投げずに真偽で返したいとき用。"""
    try:
        check_url(url, resolve=resolve)
        return True
    except UrlNotAllowed:
        return False

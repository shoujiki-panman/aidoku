"""HTML から「リンク」と「本文テキスト」を取り出す最小限のユーティリティ。

外部依存を持たないのは、審査までに環境を壊さないため。精度より再現性を優先する。
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3",
    "h4", "h5", "h6", "table", "dt", "dd", "th", "td",
}


@dataclass
class Link:
    href: str
    text: str


class _Parser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[Link] = []
        self.chunks: list[str] = []
        self._skip_depth = 0
        self._a_href: str | None = None
        self._a_text: list[str] = []
        # 構造化データ (JSON-LD) は機械可読性の採点に使うので別に貯める
        self.jsonld: list[str] = []
        self._in_jsonld = False

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "script" and attrs_d.get("type") == "application/ld+json":
            self._in_jsonld = True
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "a":
            self._a_href = attrs_d.get("href")
            self._a_text = []
        if tag in BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_jsonld = False
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "a" and self._a_href is not None:
            text = re.sub(r"\s+", " ", "".join(self._a_text)).strip()
            href = urllib.parse.urljoin(self.base_url, self._a_href)
            self.links.append(Link(href=href, text=text))
            self._a_href = None
            self._a_text = []
        if tag in BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._in_jsonld:
            self.jsonld.append(data)
            return
        if self._skip_depth:
            return
        self.chunks.append(data)
        if self._a_href is not None:
            self._a_text.append(data)


def parse(html_text: str, base_url: str) -> tuple[list[Link], str, list[str]]:
    """(リンク一覧, 本文テキスト, JSON-LD の生文字列) を返す。"""
    p = _Parser(base_url)
    try:
        p.feed(html_text)
    except Exception:  # 壊れたHTMLでも取れたところまでで進む
        pass
    text = html.unescape("".join(p.chunks))
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return p.links, text.strip(), p.jsonld


def normalize(url: str) -> str:
    """フラグメントと末尾スラッシュのゆれを吸収して、同じページを二度取らないようにする。"""
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))

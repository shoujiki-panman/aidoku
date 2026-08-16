"""HTMLを、本文だけでなくページ構造を保った形へ正規化する。"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "noscript", "svg"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3",
    "h4", "h5", "h6", "table", "dt", "dd", "th", "td",
}
HEADING_TAGS = {f"h{level}": level for level in range(1, 7)}
HEAD_CONTENT_TAGS = {
    "base", "basefont", "bgsound", "link", "meta", "noframes", "noscript",
    "script", "style", "template", "title",
}
PRE_BODY_TAGS = HEAD_CONTENT_TAGS | {"head", "html"}


@dataclass(frozen=True)
class Link:
    href: str
    text: str


@dataclass(frozen=True)
class Heading:
    level: int
    text: str


@dataclass(frozen=True)
class NormalizedPage:
    links: list[Link]
    text: str
    jsonld: list[str]
    title: str | None
    meta: dict[str, str]
    headings: list[Heading]
    date_modified: list[str]
    date_published: list[str]


def clean_inline_text(chunks: Sequence[str]) -> str:
    text = "".join(chunks)
    return re.sub(r"\s+", " ", text).strip()


def clean_body_text(chunks: Sequence[str]) -> str:
    # 本文は従来のparse()と同じく、HTMLParser後にもう一度文字参照を展開する。
    text = html.unescape("".join(chunks))
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


def append_unique_text(target: list[str], value: object) -> None:
    if not isinstance(value, str):
        return
    cleaned = value.strip()
    if cleaned and cleaned not in target:
        target.append(cleaned)


def collect_jsonld_dates(value: object, modified: list[str], published: list[str]) -> None:
    if isinstance(value, list):
        for item in value:
            collect_jsonld_dates(item, modified, published)
        return
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        if key == "@context":
            continue
        if key == "dateModified":
            append_unique_text(modified, child)
        elif key == "datePublished":
            append_unique_text(published, child)
        collect_jsonld_dates(child, modified, published)


def extract_jsonld_dates(blocks: Sequence[str]) -> tuple[list[str], list[str]]:
    modified: list[str] = []
    published: list[str] = []
    for block in blocks:
        try:
            value = json.loads(block)
            collect_jsonld_dates(value, modified, published)
        except (json.JSONDecodeError, RecursionError, TypeError):
            continue
    return modified, published


class _Parser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[Link] = []
        self.chunks: list[str] = []
        self.jsonld: list[str] = []
        self.meta: dict[str, str] = {}
        self.headings: list[Heading] = []
        self.title: str | None = None
        self._skip_depth = 0
        self._head_depth = 0
        self._body_started = False
        self._a_href: str | None = None
        self._a_text: list[str] = []
        self._a_alt_text: list[str] = []
        self._title_text: list[str] | None = None
        self._heading_level: int | None = None
        self._heading_text: list[str] = []
        self._jsonld_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {key.lower(): value for key, value in attrs}
        if self._head_depth and tag not in HEAD_CONTENT_TAGS and tag != "head":
            self._finish_title()
            self._head_depth = 0
        if not self._head_depth and tag not in PRE_BODY_TAGS:
            self._body_started = True
        if tag == "head":
            self._head_depth += 1
            return
        if tag == "title" and (self._head_depth or not self._body_started):
            self._title_text = []
            return
        if tag == "meta":
            self._capture_meta(attrs_d)
            return
        if tag == "script" and self._is_jsonld(attrs_d.get("type")):
            self._jsonld_text = []
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._head_depth:
            return
        if tag == "img":
            self._capture_image_alt(attrs_d.get("alt"))
            return
        if tag == "a":
            self._a_href = attrs_d.get("href")
            self._a_text = []
            self._a_alt_text = []
        if tag in HEADING_TAGS:
            self._finish_heading()
            self._heading_level = HEADING_TAGS[tag]
            self._heading_text = []
        if tag in BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._jsonld_text is not None:
            self._finish_jsonld()
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title" and self._title_text is not None:
            self._finish_title()
            return
        if tag == "head":
            self._finish_title()
            self._head_depth = max(0, self._head_depth - 1)
            return
        if self._head_depth:
            return
        if tag == "a" and self._a_href is not None:
            text = clean_inline_text(self._a_text)
            self.links.append(Link(
                href=urllib.parse.urljoin(self.base_url, self._a_href),
                text=text or clean_inline_text(self._a_alt_text),
            ))
            self._a_href = None
            self._a_text = []
            self._a_alt_text = []
        if self._heading_level is not None and tag in HEADING_TAGS:
            self._finish_heading()
        if tag in BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._jsonld_text is not None:
            self._jsonld_text.append(data)
            return
        if self._title_text is not None:
            self._title_text.append(data)
            return
        if self._head_depth or self._skip_depth:
            return
        self.chunks.append(data)
        if self._a_href is not None:
            self._a_text.append(data)
        if self._heading_level is not None:
            self._heading_text.append(data)

    def finish(self) -> None:
        if self._jsonld_text is not None:
            self._finish_jsonld()
        self._finish_title()
        self._finish_heading()

    def _capture_meta(self, attrs: dict[str, str | None]) -> None:
        key = (attrs.get("name") or attrs.get("property") or "").strip().lower()
        content = (attrs.get("content") or "").strip()
        if content and (key == "description" or key.startswith("og:")):
            self.meta.setdefault(key, content)

    def _finish_title(self) -> None:
        if self._title_text is None:
            return
        title = clean_inline_text(self._title_text)
        if title and self.title is None:
            self.title = title
        self._title_text = None

    def _capture_image_alt(self, value: str | None) -> None:
        alt = (value or "").strip()
        if not alt:
            return
        if self._a_href is not None:
            self._a_alt_text.append(alt)
        if self._heading_level is not None:
            self._heading_text.append(alt)

    def _finish_heading(self) -> None:
        if self._heading_level is None:
            return
        text = clean_inline_text(self._heading_text)
        if text:
            self.headings.append(Heading(level=self._heading_level, text=text))
        self._heading_level = None
        self._heading_text = []

    def _finish_jsonld(self) -> None:
        if self._jsonld_text is None:
            return
        block = "".join(self._jsonld_text)
        if block.strip():
            self.jsonld.append(block)
        self._jsonld_text = None

    @staticmethod
    def _is_jsonld(value: str | None) -> bool:
        return (value or "").split(";", 1)[0].strip().lower() == "application/ld+json"


def parse(html_text: str, base_url: str) -> NormalizedPage:
    """HTMLを、リンク・本文・ページ構造・構造化日時へ正規化する。"""
    parser = _Parser(base_url)
    try:
        parser.feed(html_text)
        if parser._jsonld_text is not None:
            parser.feed("</script>")
        parser.close()
    except Exception:  # 壊れたHTMLでも取れたところまでで進む
        pass
    parser.finish()
    modified, published = extract_jsonld_dates(parser.jsonld)
    return NormalizedPage(
        links=parser.links,
        text=clean_body_text(parser.chunks),
        jsonld=parser.jsonld,
        title=parser.title,
        meta=parser.meta,
        headings=parser.headings,
        date_modified=modified,
        date_published=published,
    )


def normalize(url: str) -> str:
    """フラグメントと末尾スラッシュのゆれを吸収して、同じページを二度取らないようにする。"""
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))

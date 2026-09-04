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

CELL_TAGS = {"td", "th"}
# 結合セルの上限。colspan="9999" のような値で格子を膨らませない
MAX_SPAN = 40
# 表テキストの上限。1つの巨大な表でAIへの入力を食い潰さない
MAX_TABLE_ROWS = 80
MAX_CELL_CHARS = 200


@dataclass(frozen=True)
class Link:
    href: str
    text: str


@dataclass(frozen=True)
class Cell:
    text: str
    header: bool
    colspan: int
    rowspan: int


@dataclass(frozen=True)
class Table:
    caption: str
    rows: list[list[Cell]]


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
    tables: list[Table]


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


def span_value(raw: str | None) -> int:
    """colspan / rowspan を読む。壊れた値でも格子を作れるよう 1..MAX_SPAN に収める。"""
    try:
        span = int((raw or "1").strip())
    except ValueError:
        return 1
    return min(max(span, 1), MAX_SPAN)


def take_carried(carried: dict[int, tuple[Cell, int]], column: int,
                 following: dict[int, tuple[Cell, int]]) -> Cell:
    """rowspan で持ち越されたセルを取り出し、まだ残るなら次の行へ渡す。"""
    held, left = carried[column]
    if left > 1:
        following[column] = (held, left - 1)
    return held


def expand_row(row: Sequence[Cell], carried: dict[int, tuple[Cell, int]],
               ) -> tuple[list[Cell], dict[int, tuple[Cell, int]]]:
    """1行を「1マス1セル」に広げ、次の行へ持ち越す rowspan を返す。

    ★見出しと値は列の位置でしか結びつかない。結合セルを広げずに読むと
      列がずれ、値が隣の見出しにぶら下がる。
    """
    out: list[Cell] = []
    following: dict[int, tuple[Cell, int]] = {}
    column, cells = 0, iter(row)
    cell = next(cells, None)
    while cell is not None or column in carried:
        if column in carried:
            out.append(take_carried(carried, column, following))
            column += 1
            continue
        for _ in range(cell.colspan):
            out.append(cell)
            if cell.rowspan > 1:
                following[column] = (cell, cell.rowspan - 1)
            column += 1
        cell = next(cells, None)
    return out, following


def expand_grid(rows: Sequence[Sequence[Cell]]) -> list[list[Cell]]:
    """表全体を、結合セルのない格子へ広げる。"""
    grid: list[list[Cell]] = []
    carried: dict[int, tuple[Cell, int]] = {}
    for row in rows[:MAX_TABLE_ROWS]:
        expanded, carried = expand_row(row, carried)
        grid.append(expanded)
    return grid


def column_headers(grid: Sequence[Sequence[Cell]]) -> list[str]:
    """先頭行が全部見出しセルなら、それを列の見出しとして使う。

    見出し行が無い表（td だけの表）は空リストを返し、値だけを並べる。
    """
    if not grid or len(grid[0]) < 2:
        return []
    first = grid[0]
    if not all(cell.header for cell in first) or not any(cell.text for cell in first):
        return []
    return [cell.text for cell in first]


def row_line(row: Sequence[Cell], headers: Sequence[str]) -> str:
    """1行を「見出し: 値 / 見出し: 値」に直す。行頭の見出しセルは行の名前にする。"""
    labels: list[str] = []
    pairs: list[str] = []
    for column, cell in enumerate(row):
        if column and cell is row[column - 1]:  # 結合で広げた複製は1回だけ出す
            continue
        if cell.header and not pairs:
            labels.append(cell.text)
            continue
        head = headers[column] if column < len(headers) else ""
        if not cell.text:
            continue
        pairs.append(f"{head}: {cell.text}" if head and head != cell.text else cell.text)
    label = " ".join(text for text in labels if text)
    body = " / ".join(pairs)
    return f"【{label}】{body}".rstrip() if label else body


def table_lines(table: Table) -> list[str]:
    """1つの表を、行ごとに1行のテキストへ直す。"""
    grid = expand_grid(table.rows)
    headers = column_headers(grid)
    lines = [f"（{table.caption}）"] if table.caption else []
    for row in (grid[1:] if headers else grid):
        line = row_line(row, headers)
        if line:
            lines.append(f"- {line}")
    return lines if len(lines) > (1 if table.caption else 0) else []


def tables_text(tables: Sequence[Table]) -> str:
    """表を「行ごとの見出し: 値」に直したテキスト。表が無ければ空文字。"""
    blocks: list[str] = []
    for table in tables:
        lines = table_lines(table)
        if lines:  # 中身の無い表は番号も与えず落とす（入力の無駄になるだけ）
            blocks.append(f"表{len(blocks) + 1}\n" + "\n".join(lines))
    return "\n\n".join(blocks)


class _TableParser(HTMLParser):
    """表だけを、行と結合セルを保ったまま取り出す。入れ子の表は別の表として扱う。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        # 入れ子の表を外側から順に積む。開きかけのセルも表ごとに持たないと、
        # 内側の表の <td> が外側のセルを内側の行へ入れてしまう。
        self._open: list[dict] = []
        self._skip_depth = 0

    @property
    def _top(self) -> dict:
        return self._open[-1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "table":
            self._open.append(
                {"caption": "", "rows": [], "row": None, "cell": None, "chunks": None})
            return
        if not self._open:
            return
        if tag == "caption":
            self._top.update(cell=None, chunks=[], in_caption=True)
        elif tag == "tr":
            self._close_cell()
            self._top["row"] = []
        elif tag in CELL_TAGS:
            self._start_cell(tag, dict(attrs))
        elif tag == "br" and self._top["chunks"] is not None:
            self._top["chunks"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if not self._open:
            return
        if tag in CELL_TAGS:
            self._close_cell()
        elif tag == "caption":
            self._close_caption()
        elif tag == "tr":
            self._close_cell()
            self._close_row()
        elif tag == "table":
            self._close_table()

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not self._open or self._top["chunks"] is None:
            return
        self._top["chunks"].append(data)

    def finish(self) -> None:
        while self._open:  # </table> が閉じていないHTMLでも取れたところまで返す
            self._close_table()

    def _start_cell(self, tag: str, attrs: dict[str, str | None]) -> None:
        self._close_cell()
        if self._top["row"] is None:  # <tr> の無い表でも1行として拾う
            self._top["row"] = []
        self._top["cell"] = {
            "header": tag == "th",
            "colspan": span_value(attrs.get("colspan")),
            "rowspan": span_value(attrs.get("rowspan")),
        }
        self._top["chunks"] = []

    def _close_cell(self) -> None:
        if self._top["cell"] is None:
            return
        text = clean_inline_text(self._top["chunks"] or [])[:MAX_CELL_CHARS]
        self._top["row"].append(Cell(text=text, **self._top["cell"]))
        self._top.update(cell=None, chunks=None)

    def _close_caption(self) -> None:
        if not self._top.get("in_caption"):
            return
        self._top["caption"] = clean_inline_text(self._top["chunks"] or [])[:MAX_CELL_CHARS]
        self._top.update(chunks=None, in_caption=False)

    def _close_row(self) -> None:
        if self._top["row"]:
            self._top["rows"].append(self._top["row"])
        self._top["row"] = None

    def _close_table(self) -> None:
        self._close_cell()
        self._close_row()
        table = self._open.pop()
        if table["rows"]:
            self.tables.append(Table(caption=table["caption"], rows=table["rows"]))
        if self._open and self._top["chunks"] is not None:
            self._top["chunks"].append(" ")  # 入れ子の表の前後の文が繋がらないようにする


def extract_tables(html_text: str) -> list[Table]:
    """HTMLから表だけを取り出す。壊れたHTMLでも取れたところまで返す。"""
    parser = _TableParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # 壊れたHTMLでも取れたところまでで進む
        pass
    parser.finish()
    return parser.tables


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
        tables=extract_tables(html_text),
    )


def normalize(url: str) -> str:
    """フラグメントと末尾スラッシュのゆれを吸収して、同じページを二度取らないようにする。"""
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))

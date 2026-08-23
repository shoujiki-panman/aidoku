"""Page Normalizerの構造保持と壊れた入力への境界テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from htmlutil import (
    MAX_SPAN,
    MAX_TABLE_ROWS,
    Heading,
    extract_jsonld_dates,
    extract_tables,
    parse,
    tables_text,
)


class PageMetadataTest(unittest.TestCase):
    def test_title_meta見出しを本文と分けて返す(self):
        page = parse("""
            <html><head>
              <title> 転入届 &amp; 手続き </title>
              <meta name="DESCRIPTION" content=" 転入手続きの説明 ">
              <meta property="OG:TITLE" content="転入届">
              <meta property="og:url" content="https://example.jp/tennyu">
              <meta name="keywords" content="保存しない">
              <meta name="description" content="後の重複値">
              <style>見せない</style>
            </head><body>
              <h1>転入 <span>届</span></h1>
              <h3><a href="detail.html">必要 書類</a></h3>
              <p>本文 &amp; 案内</p>
              <script>本文へ混ぜない</script>
            </body></html>
        """, "https://example.jp/guide/")

        self.assertEqual(page.title, "転入届 & 手続き")
        self.assertEqual(page.meta, {
            "description": "転入手続きの説明",
            "og:title": "転入届",
            "og:url": "https://example.jp/tennyu",
        })
        self.assertEqual(page.headings, [
            Heading(level=1, text="転入 届"),
            Heading(level=3, text="必要 書類"),
        ])
        self.assertEqual(page.links[0].href, "https://example.jp/guide/detail.html")
        self.assertEqual(page.links[0].text, "必要 書類")
        self.assertIn("本文 & 案内", page.text)
        self.assertNotIn("転入手続きの説明", page.text)
        self.assertNotIn("本文へ混ぜない", page.text)

    def test_h1からh6のlevelと文書順を保つ(self):
        source = "".join(f"<h{level}>見出し{level}</h{level}>" for level in range(1, 7))
        page = parse(source, "https://example.jp/")
        self.assertEqual(
            page.headings,
            [Heading(level=level, text=f"見出し{level}") for level in range(1, 7)],
        )

    def test_画像だけの見出しとリンクはaltを文字列として使う(self):
        page = parse(
            '<h1><img alt="転入届のご案内"></h1>'
            '<a href="/apply"><img alt="オンライン申請"></a>'
            '<a href="/detail">詳しく見る<img alt="外部リンク"></a>'
            '<h2><img alt=" "></h2>',
            "https://example.jp/",
        )
        self.assertEqual(page.headings, [Heading(level=1, text="転入届のご案内")])
        self.assertEqual(page.links[0].text, "オンライン申請")
        self.assertEqual(page.links[1].text, "詳しく見る")

    def test_構造項目の文字参照は1回だけデコードする(self):
        page = parse(
            '<head><title>A &amp; B / A &amp;amp; B</title></head>'
            '<body><h1>A &amp; B / A &amp;amp; B</h1>'
            '<a href="/x">A &amp; B / A &amp;amp; B</a>'
            '<p>A &amp; B / A &amp;amp; B</p></body>',
            "https://example.jp/",
        )
        expected = "A & B / A &amp; B"
        self.assertEqual(page.title, expected)
        self.assertEqual(page.headings, [Heading(level=1, text=expected)])
        self.assertEqual(page.links[0].text, expected)

    def test_本文の文字参照は従来どおり追加でデコードする(self):
        page = parse(
            "<p>A &amp; B / A &amp;amp; B</p>",
            "https://example.jp/",
        )
        self.assertEqual(page.text, "A & B / A & B")

    def test_空のtitle_meta見出しは値を作らない(self):
        page = parse(
            "<head><title> </title><meta name='description'><meta property='og:title' content=''></head>"
            "<body><h2><span> </span></h2><p>本文</p></body>",
            "https://example.jp/",
        )
        self.assertIsNone(page.title)
        self.assertEqual(page.meta, {})
        self.assertEqual(page.headings, [])
        self.assertEqual(page.text, "本文")

    def test_headが閉じていなくてもbody以降を捨てない(self):
        page = parse(
            "<html><head><title>転入届</title>"
            "<body><h1>必要書類</h1><p>本文</p></body></html>",
            "https://example.jp/",
        )
        self.assertEqual(page.title, "転入届")
        self.assertEqual(page.headings, [Heading(level=1, text="必要書類")])
        self.assertEqual(page.text, "必要書類\n\n本文")

    def test_headとbodyの終了開始タグが省略されても本文へ移る(self):
        page = parse(
            "<html><head><title>転入届</title><h1>必要書類</h1><p>本文</p>",
            "https://example.jp/",
        )
        self.assertEqual(page.title, "転入届")
        self.assertEqual(page.headings, [Heading(level=1, text="必要書類")])
        self.assertEqual(page.text, "必要書類\n\n本文")

    def test_head開始タグが省略されてもtitleを本文へ混ぜない(self):
        page = parse(
            "<title>転入届</title><body><h1>必要書類</h1></body>",
            "https://example.jp/",
        )
        self.assertEqual(page.title, "転入届")
        self.assertEqual(page.headings, [Heading(level=1, text="必要書類")])
        self.assertEqual(page.text, "必要書類")

    def test_閉じていないtitleも取得済み文字列を保つ(self):
        for source in ("<head><title>転入届", "<title>転入届"):
            with self.subTest(source=source):
                page = parse(source, "https://example.jp/")
                self.assertEqual(page.title, "転入届")
                self.assertEqual(page.text, "")

    def test_閉じていない見出しも取得済み文字列を保つ(self):
        page = parse("<h1>必要書類", "https://example.jp/")
        self.assertEqual(page.headings, [Heading(level=1, text="必要書類")])
        self.assertEqual(page.text, "必要書類")

    def test_次の見出し開始で未閉鎖の前見出しも確定する(self):
        page = parse("<h1>申請<h2>必要書類</h2>", "https://example.jp/")
        self.assertEqual(page.headings, [
            Heading(level=1, text="申請"),
            Heading(level=2, text="必要書類"),
        ])

    def test_異なるlevelの終了タグでも見出しを閉じる(self):
        page = parse("<h1>申請</h2><p>本文</p>", "https://example.jp/")
        self.assertEqual(page.headings, [Heading(level=1, text="申請")])
        self.assertEqual(page.text, "申請\n\n本文")


class JsonLdDateTest(unittest.TestCase):
    def test_object_array_graphの日時を順序通り重複なく取る(self):
        page = parse("""
            <script type="application/ld+json">
              {"dateModified":"2026-08-16", "@graph":[
                {"datePublished":"2026-08-01"},
                {"nested":{"dateModified":"2026-08-17"}}
              ]}
            </script>
            <script type="application/ld+json; charset=utf-8">
              [{"dateModified":"2026-08-16"}, {"datePublished":"2026-08-02"}]
            </script>
            <script type="application/ld+json">{broken</script>
            <script>{"dateModified":"保存しない"}</script>
        """, "https://example.jp/")
        self.assertEqual(len(page.jsonld), 3)
        self.assertEqual(page.date_modified, ["2026-08-16", "2026-08-17"])
        self.assertEqual(page.date_published, ["2026-08-01", "2026-08-02"])

    def test_文字列でない日時と壊れたJSONを無視する(self):
        deeply_nested = "[" * 2000 + "0" + "]" * 2000
        modified, published = extract_jsonld_dates([
            '{"dateModified": 123, "datePublished": null, "nested": {'
            '"dateModified": "", "datePublished": "   "}}',
            '{"dateModified": ["2026-08-16"]}',
            "not json",
            deeply_nested,
        ])
        self.assertEqual(modified, [])
        self.assertEqual(published, [])

    def test_contextの語彙定義を更新日時として扱わない(self):
        modified, published = extract_jsonld_dates([
            '{"@context":{"dateModified":"https://schema.org/dateModified",'
            '"datePublished":"https://schema.org/datePublished"},'
            '"@type":"Article","dateModified":"2026-08-16"}',
        ])
        self.assertEqual(modified, ["2026-08-16"])
        self.assertEqual(published, [])

    def test_閉じていないJSONLDも生文字列を失わない(self):
        page = parse(
            '<script type="application/ld+json">{"dateModified":"2026-08-16"}',
            "https://example.jp/",
        )
        self.assertEqual(page.date_modified, ["2026-08-16"])
        self.assertEqual(len(page.jsonld), 1)

    def test_JSONLDの前後空白を生文字列のまま保つ(self):
        raw = '\n  {"dateModified":"2026-08-16"}\n '
        page = parse(
            f'<script type="application/ld+json">{raw}</script>',
            "https://example.jp/",
        )
        self.assertEqual(page.jsonld, [raw])

    def test_JSONLDのMIMEは大文字小文字とcharset表記を許容する(self):
        page = parse(
            '<script type="Application/LD+JSON; Charset=UTF-8">'
            '{"datePublished":"2026-08-01"}</script>',
            "https://example.jp/",
        )
        self.assertEqual(page.date_published, ["2026-08-01"])


def table_text(html_text: str) -> str:
    """表だけを取り出して「見出し: 値」へ直す。テストの見通し用。"""
    return tables_text(extract_tables(html_text))


class 表読みTest(unittest.TestCase):
    """自治体ページの表の壊れ方を、ここで固定する。

    必要書類・手数料・期限は表に入っていることがあり、本文として平らに渡すと
    「どの見出しの列の値か」が消える。消さずに読めることを1つずつ止める。
    """

    def test_見出し行のある表を行ごとの見出しと値にする(self):
        text = table_text(
            "<table><caption>転入の手続き</caption>"
            "<tr><th>区分</th><th>手数料</th><th>期限</th></tr>"
            "<tr><th>国内転入</th><td>無料</td><td>14日以内</td></tr>"
            "</table>")
        self.assertEqual(text, "表1\n（転入の手続き）\n"
                               "- 【国内転入】手数料: 無料 / 期限: 14日以内")

    def test_見出しのcolspanは覆う列ぶんに広げる(self):
        # 広げないと列が1つずれ、「14日以内」が手数料の値として読まれる
        text = table_text(
            "<table>"
            "<tr><th colspan='2'>手数料</th><th>期限</th></tr>"
            "<tr><td>国内転入</td><td>無料</td><td>14日以内</td></tr>"
            "</table>")
        self.assertEqual(
            text, "表1\n- 手数料: 国内転入 / 手数料: 無料 / 期限: 14日以内")

    def test_値のcolspanは同じ値を繰り返さない(self):
        text = table_text(
            "<table>"
            "<tr><th>区分</th><th>手数料</th><th>期限</th></tr>"
            "<tr><th>国外転入</th><td colspan='2'>窓口へお問い合わせください</td></tr>"
            "</table>")
        self.assertEqual(
            text, "表1\n- 【国外転入】手数料: 窓口へお問い合わせください")

    def test_rowspanは次の行へ持ち越す(self):
        text = table_text(
            "<table>"
            "<tr><th>区分</th><th>手数料</th></tr>"
            "<tr><th>国内転入</th><td rowspan='2'>無料</td></tr>"
            "<tr><th>国外転入</th></tr>"
            "</table>")
        self.assertEqual(text, "表1\n"
                               "- 【国内転入】手数料: 無料\n"
                               "- 【国外転入】手数料: 無料")

    def test_見出し行の無い表は値だけを並べる(self):
        text = table_text(
            "<table><tr><td>粗大ごみ</td><td>400円</td></tr></table>")
        self.assertEqual(text, "表1\n- 粗大ごみ / 400円")

    def test_空のセルは行から落とす(self):
        text = table_text(
            "<table>"
            "<tr><th>区分</th><th>手数料</th><th>期限</th></tr>"
            "<tr><th>国内転入</th><td></td><td>14日以内</td></tr>"
            "</table>")
        self.assertEqual(text, "表1\n- 【国内転入】期限: 14日以内")

    def test_中身の無い表は番号ごと落とす(self):
        text = table_text(
            "<table><tr><td></td><td></td></tr></table>"
            "<table><tr><td>粗大ごみ</td></tr></table>")
        self.assertEqual(text, "表1\n- 粗大ごみ")

    def test_入れ子の表は別の表として読む(self):
        # 外側のセルへ内側の行を混ぜない。混ぜると見出しの対応が壊れる
        text = table_text(
            "<table><tr><td>案内"
            "<table><tr><th>手数料</th><td>無料</td></tr></table>"
            "つづき</td></tr></table>")
        self.assertEqual(text, "表1\n- 【手数料】無料\n\n表2\n- 案内 つづき")

    def test_閉じていない表も取れたところまで返す(self):
        text = table_text("<table><tr><th>手数料</th><td>無料</td>")
        self.assertEqual(text, "表1\n- 【手数料】無料")

    def test_巨大なcolspanで格子を膨らませない(self):
        cells = extract_tables(
            "<table><tr><td colspan='9999'>爆</td></tr></table>")[0].rows[0]
        self.assertEqual(cells[0].colspan, MAX_SPAN)

    def test_壊れたcolspanは1として扱う(self):
        cells = extract_tables(
            "<table><tr><td colspan='いち'>壊れ</td><td colspan=''>空</td>"
            "</tr></table>")[0].rows[0]
        self.assertEqual([cell.colspan for cell in cells], [1, 1])

    def test_scriptの中身を表へ入れない(self):
        text = table_text(
            "<table><tr><td>無料<script>混ぜない</script></td></tr></table>")
        self.assertEqual(text, "表1\n- 無料")

    def test_長すぎる表はMAX_TABLE_ROWS行で切る(self):
        rows = "<tr><td>行</td></tr>" * (MAX_TABLE_ROWS + 10)
        text = table_text(f"<table>{rows}</table>")
        self.assertEqual(text.count("\n- 行"), MAX_TABLE_ROWS)

    def test_parseは表も一緒に返す(self):
        page = parse(
            "<p>本文</p><table><tr><th>手数料</th><td>無料</td></tr></table>",
            "https://example.jp/")
        self.assertEqual(tables_text(page.tables), "表1\n- 【手数料】無料")
        self.assertIn("無料", page.text)  # 本文側の見え方は変えない


if __name__ == "__main__":
    unittest.main()

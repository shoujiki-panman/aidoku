from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "analysis"))
from read_ledger import (  # noqa: E402
    REASONS,
    classify,
    merge_counts,
    read_urls,
    tally,
    with_missing_reads,
)

HTML = "https://example.lg.jp/tennyu.html"
OTHER = "https://example.lg.jp/tenshutsu.html"
PDF = "https://example.lg.jp/form.pdf"


class Classify(unittest.TestCase):
    def test_読んだものが最優先(self):
        self.assertEqual(classify(HTML, 200, True, {HTML}, set()), "read")

    def test_読んだPDFはnon_htmlに落とさない(self):
        # 順番を入れ替えると壊れる。読んだ事実が型の判定に負けてはいけない。
        self.assertEqual(classify(PDF, 200, True, {PDF}, set()), "read")

    def test_未読のPDFはnon_html(self):
        self.assertEqual(classify(PDF, 200, True, set(), set()), "non_html")

    def test_一覧に載せたが未読(self):
        self.assertEqual(classify(HTML, 200, True, set(), {HTML}), "shown_not_chosen")

    def test_一覧にも載せていない(self):
        self.assertEqual(classify(HTML, 200, True, set(), {OTHER}), "never_shown")

    def test_取得できていない_status0(self):
        self.assertEqual(classify(HTML, 0, True, set(), {HTML}), "unfetchable")

    def test_取得できていない_statusなし(self):
        self.assertEqual(classify(HTML, None, True, set(), {HTML}), "unfetchable")

    def test_取得できていない_本文が手元に無い(self):
        # status 200 でも本文が無ければ読めない。両方見ないと取りこぼす。
        self.assertEqual(classify(HTML, 200, False, set(), {HTML}), "unfetchable")

    def test_取得できていなくても読んだなら_read(self):
        self.assertEqual(classify(HTML, 0, False, {HTML}, set()), "read")


class Tally(unittest.TestCase):
    def test_0本の印も必ず出す(self):
        counts = tally([{"mark": "read"}])
        self.assertEqual(set(counts), set(REASONS))
        self.assertEqual(counts["read"], 1)
        self.assertEqual(counts["never_shown"], 0)

    def test_空でも印は5つ(self):
        self.assertEqual(tally([]), dict.fromkeys(REASONS, 0))

    def test_合算(self):
        rows = [{"counts": tally([{"mark": "read"}])},
                {"counts": tally([{"mark": "read"}, {"mark": "never_shown"}])}]
        total = merge_counts(rows)
        self.assertEqual(total["read"], 2)
        self.assertEqual(total["never_shown"], 1)
        self.assertEqual(total["non_html"], 0)


class MissingReads(unittest.TestCase):
    def extract(self) -> dict:
        return {"page": {"url": HTML, "link_text": "転入届", "hops": 2},
                "followed_urls": [OTHER]}

    def test_読んだのに候補に無いURLを足す(self):
        # ★ここが抜けていて、読んだ41本が台帳では34本になった。
        out = with_missing_reads([], {HTML, OTHER}, self.extract())
        self.assertEqual({e["url"] for e in out}, {HTML, OTHER})
        self.assertTrue(all(e["mark"] == "read" for e in out))

    def test_既にある候補は二重に足さない(self):
        entries = [{"url": OTHER, "mark": "shown_not_chosen"}]
        out = with_missing_reads(entries, {HTML, OTHER}, self.extract())
        self.assertEqual([e["url"] for e in out], [HTML, OTHER])

    def test_起点ページにはリンク文字が付く(self):
        out = with_missing_reads([], {HTML}, self.extract())
        self.assertEqual(out[0]["link_text"], "転入届")
        self.assertEqual(out[0]["hops"], 2)

    def test_リンク先には起点の情報を付けない(self):
        # 起点の hops をリンク先に付けると、どこから来たか嘘になる。
        out = with_missing_reads([], {OTHER}, self.extract())
        self.assertIsNone(out[0]["link_text"])
        self.assertIsNone(out[0]["hops"])

    def test_足すものが無ければ元のまま(self):
        entries = [{"url": HTML, "mark": "read"}, {"url": OTHER, "mark": "read"}]
        self.assertEqual(with_missing_reads(entries, {HTML, OTHER}, self.extract()), entries)


class ReadUrls(unittest.TestCase):
    def test_起点とリンク先を合わせる(self):
        got = read_urls({"page": {"url": HTML}, "followed_urls": [OTHER]})
        self.assertEqual(got, {HTML, OTHER})

    def test_リンク先が無い場合(self):
        self.assertEqual(read_urls({"page": {"url": HTML}}), {HTML})

    def test_リンク先がnull(self):
        self.assertEqual(read_urls({"page": {"url": HTML}, "followed_urls": None}), {HTML})


class Reasons(unittest.TestCase):
    def test_印には必ず日本語の理由がある(self):
        # 理由が空欄の印を作らない。空欄が1つでもあると台帳の意味が消える。
        for mark, text in REASONS.items():
            self.assertTrue(text.strip(), mark)

    def test_上限本数を理由に書いてある(self):
        # 「AIが開かなかった」だけだと、こちらが設けた上限がAIの落ち度に見える。
        self.assertIn("上限", REASONS["shown_not_chosen"])

    def test_非HTMLの理由が実態と合っている(self):
        """★以前は「PDF/Word/Excel のため弾いた」と書いていた。

        いまは弾いていない（字形の対応表で読み、抽出にも流している）。
        台帳だけ古い理由を書き続けると、直したことが伝わらない。
        道具を直したら、理由文も一緒に直す。
        """
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parent))
        from extractor.fact_extract import NON_HTML_READING
        reason = REASONS["non_html"]
        if NON_HTML_READING == "none":
            self.assertIn("弾いた", reason)
        else:
            self.assertNotIn("弾いた", reason)

    def test_取得できない理由に一番多い原因を書く(self):
        # 実測では大半が robots.txt による拒否（区自身の拒否ではなく、
        # 共有ボタンや外部の変換サービス）。「取得失敗」だけだと原因を誤解する。
        self.assertIn("robots", REASONS["unfetchable"])


if __name__ == "__main__":
    unittest.main()

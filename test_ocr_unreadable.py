"""`analysis/probes/ocr_unreadable.py` — 読めない画像PDFを OCR で読んでみた記録。

★**判定には使わない。** macOS でしか動かない道具なので、測定条件に混ぜてはいけない。
  誤りと分かった結果の置き場と同じで、**読むのは人だけ。**

★では何のために読むのか: **住民のAIは絵も読める。** うちの読み取り器が字しか
  扱えないだけで、住民の側では読めている可能性がある。「うちが読めない」を
  「区が書いていない」に混ぜないための材料。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis" / "probes"))
from ocr_unreadable import (  # noqa: E402
    MIN_KANA,
    cached,
    summarize,
    unreadable_urls,
)


def row(**kw) -> dict:
    base = {"url": "https://x/a.pdf", "fields": ["tennyu/A区/手数料"], "reason": "",
            "ocr_ok": True, "chars": 100, "kana": 30, "head": "本文"}
    return {**base, **kw}


class 対象の集め方(unittest.TestCase):
    def sweep(self, doc: dict) -> dict[str, list[str]]:
        import ocr_unreadable as mod
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "sweep_tennyu.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            original, mod.OUT_DIR = mod.OUT_DIR, out
            try:
                return unreadable_urls()
            finally:
                mod.OUT_DIR = original

    def test_読めない候補と項目を結びつける(self):
        got = self.sweep({"rows": [{"municipality": "A区", "fields": [
            {"field": "手数料", "unreadable": ["https://x/a.pdf"]}]}]})
        self.assertEqual(got, {"https://x/a.pdf": ["tennyu/A区/手数料"]})

    def test_同じURLが複数項目を塞いでいたらまとめる(self):
        got = self.sweep({"rows": [{"municipality": "A区", "fields": [
            {"field": "手数料", "unreadable": ["https://x/a.pdf"]},
            {"field": "期限", "unreadable": ["https://x/a.pdf"]}]}]})
        self.assertEqual(len(got["https://x/a.pdf"]), 2)

    def test_読めない候補が無ければ空(self):
        got = self.sweep({"rows": [{"municipality": "A区", "fields": [
            {"field": "手数料"}]}]})
        self.assertEqual(got, {})

    def test_虱潰しの結果が無くても落ちない(self):
        import ocr_unreadable as mod
        with tempfile.TemporaryDirectory() as tmp:
            original, mod.OUT_DIR = mod.OUT_DIR, Path(tmp)
            try:
                self.assertEqual(unreadable_urls(), {})
            finally:
                mod.OUT_DIR = original


class キャッシュの引き方(unittest.TestCase):
    def test_取得していなければNone(self):
        self.assertIsNone(cached("https://example.invalid/never-fetched.pdf"))


class 集計(unittest.TestCase):
    def test_読めた本数と字数を数える(self):
        got = summarize([row(chars=100), row(ocr_ok=False, chars=0)])
        self.assertEqual(got["files"], 2)
        self.assertEqual(got["ocr_readable"], 1)
        self.assertEqual(got["ocr_unreadable"], 1)
        self.assertEqual(got["chars_total"], 100)

    def test_読めなかったものの字数は足さない(self):
        # ★読めていないのに字数だけ増えると、成果を大きく見せることになる。
        got = summarize([row(ocr_ok=False, chars=999)])
        self.assertEqual(got["chars_total"], 0)

    def test_塞いでいた項目を重複なく並べる(self):
        got = summarize([row(fields=["a", "b"]), row(fields=["b"])])
        self.assertEqual(got["fields_touched"], ["a", "b"])

    def test_空でも落ちない(self):
        self.assertEqual(summarize([])["files"], 0)


class 実データ(unittest.TestCase):
    """★実物で確かめる。作った入力だけでは思い込みが素通りする。"""

    def doc(self) -> dict:
        path = ROOT / "analysis" / "out" / "ocr_unreadable.json"
        if not path.exists():
            self.skipTest("未生成")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_判定に使わないと書いてある(self):
        # ★ここが消えたら、いつか誰かが点数に混ぜる。
        self.assertIn("判定には使わない", self.doc()["_about"])
        self.assertIn("作品本体には入れない", self.doc()["tool"])

    def test_読めた分には仮名がある(self):
        for r in self.doc()["rows"]:
            if r["ocr_ok"]:
                with self.subTest(url=r["url"][-30:]):
                    self.assertGreaterEqual(r["kana"], MIN_KANA)

    def test_画像PDFが実際に読めた(self):
        # 墨田区の収集カレンダー・中野区の委任状など。すべて0字だったもの。
        self.assertGreaterEqual(self.doc()["summary"]["ocr_readable"], 3)


if __name__ == "__main__":
    unittest.main()

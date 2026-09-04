"""`analysis/probes/check_unread.py` — 読ませなかったページに手がかりがあったかを機械的に見る道具。

LLMを呼ばないので、ここで手がかりが出た区は**こちらの読み落としの疑いが確定する**。
判定はしない。人が読んで確かめるための材料を切り出すだけ。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis" / "probes"))
from check_unread import FIELD_HINTS, hits, read_urls  # noqa: E402


class 手がかりの切り出し(unittest.TestCase):
    def test_語の前後を1行ぶん出す(self):
        text = "転入の手続きです。" * 5 + "手数料は無料です。" + "詳しくは窓口へ。" * 5
        got = hits(text, [r"手数料"])
        self.assertEqual(len(got), 1)
        self.assertIn("手数料は無料です", got[0])

    def test_1語につき1件だけ(self):
        # ★同じ語が何度出ても1件。人が読める量に保つため。
        got = hits("手数料。" * 20, [r"手数料"])
        self.assertEqual(len(got), 1)

    def test_語ごとに別の件として出す(self):
        got = hits("手数料の案内。登録は無料です。", [r"手数料", r"無料"])
        self.assertEqual(len(got), 2)

    def test_無ければ空(self):
        self.assertEqual(hits("引越しの案内", [r"手数料"]), [])

    def test_改行や連続空白は1つにまとめる(self):
        # 切り出した文字列をそのまま人に見せるので、生の空白を残さない。
        got = hits("案内\n\n  手数料  \n について", [r"手数料"])
        self.assertNotIn("\n", got[0])
        self.assertNotIn("  ", got[0])

    def test_見出し語は4項目ぶんある(self):
        self.assertEqual(set(FIELD_HINTS), {"手数料", "必要書類", "期限", "窓口オンライン可否"})


class 開いたURL(unittest.TestCase):
    def read(self, doc: dict) -> dict[str, set[str]]:
        import check_unread as mod
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "extractor" / "out"
            out.mkdir(parents=True)
            (out / "extract_a_tennyu.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            original, mod.ROOT = mod.ROOT, root
            try:
                return read_urls("tennyu")
            finally:
                mod.ROOT = original

    def test_起点と追従を合わせて返す(self):
        got = self.read({"municipality": "A区", "page": {"url": "u0"},
                         "followed_urls": ["u1", "u2"]})
        self.assertEqual(got["A区"], {"u0", "u1", "u2"})

    def test_到達できなかった区は空集合(self):
        """★`page` が null の区で落ちていた（粗大ごみ 江戸川区・八王子市）。

        `analysis/sweep.py` の `reached()` で直したのと同じ誤り。
        「読んでいない」と「たどり着けなかった」を混ぜない。
        """
        got = self.read({"municipality": "B区", "page": None, "reached": False})
        self.assertEqual(got["B区"], set())

    def test_追従が無くても落ちない(self):
        got = self.read({"municipality": "C区", "page": {"url": "u0"}})
        self.assertEqual(got["C区"], {"u0"})


class 出力先(unittest.TestCase):
    def test_他の道具と同じ_analysis_out_に置く(self):
        # ★ここだけ analysis/ 直下に書いていた。出力の置き場が2か所あると探せない。
        src = (ROOT / "analysis" / "probes" / "check_unread.py").read_text(encoding="utf-8")
        self.assertIn('out_dir = ROOT / "analysis" / "out"', src)


if __name__ == "__main__":
    unittest.main()

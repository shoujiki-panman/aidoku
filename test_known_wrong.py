"""`analysis/out/known-wrong/` — 後から誤りと分かった結果の置き場。

**残す理由**: AI読の欠陥はどれも「間違った数字が、正しい形をして出てきた」もの。
実物が無いと、次に同じ形をした数字を見抜けない。

**守ること**: **どのファイルも入力にしない。** 読むのは人だけ。
ここが判定に混ざると、直したはずの誤りが黙って戻る。それを機械で止める。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "analysis" / "out" / "known-wrong"

# 中身を読む側のコード。ここに `known-wrong` が現れてはいけない。
CODE_DIRS = ("analysis", "crawler", "extractor", "evaluator", "web")

# 例外。置き場の説明と、この検査そのもの。
ALLOWED = {"analysis/out/known-wrong/README.md", "test_known_wrong.py"}


def sources() -> list[Path]:
    out = []
    for name in CODE_DIRS:
        directory = ROOT / name
        if directory.exists():
            out.extend(p for p in directory.rglob("*.py") if "known-wrong" not in str(p))
    out.extend(ROOT.glob("*.py"))
    return out


class 置き場(unittest.TestCase):
    def test_説明が置いてある(self):
        # ★何が間違っていたかが書かれていないと、ただの古いファイルになる。
        readme = ARCHIVE / "README.md"
        self.assertTrue(readme.exists(), "known-wrong に README.md が要る")
        text = readme.read_text(encoding="utf-8")
        self.assertIn("判定には絶対に使いません", text)

    def test_中身が空でない(self):
        found = [p.name for p in ARCHIVE.iterdir() if p.name != "README.md"]
        self.assertTrue(found, "残すと決めた記録が消えている")

    def test_説明に載っていないファイルを置かない(self):
        # ★由来の書かれていないファイルが増えると、置き場そのものが信用できなくなる。
        text = (ARCHIVE / "README.md").read_text(encoding="utf-8")
        for path in ARCHIVE.iterdir():
            if path.name == "README.md":
                continue
            with self.subTest(name=path.name):
                self.assertIn(path.name, text)


class 入力にしない(unittest.TestCase):
    def test_どのコードからも読んでいない(self):
        """★ここを読むコードが1本でもあれば、直した誤りが黙って戻る。"""
        offenders = []
        for path in sources():
            rel = path.relative_to(ROOT).as_posix()
            if rel in ALLOWED:
                continue
            if "known-wrong" in path.read_text(encoding="utf-8", errors="replace"):
                offenders.append(rel)
        self.assertEqual(offenders, [], f"間違いの置き場を読んでいる: {offenders}")


if __name__ == "__main__":
    unittest.main()

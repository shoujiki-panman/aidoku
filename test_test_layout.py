"""テストファイルの並びを検査する。

★`if __name__ == "__main__": unittest.main()` の**後ろ**にテストを足すと、
  直接実行したときに **後半が定義される前に走って、黙って抜ける。**
  `unittest discover` はモジュールを import するだけなので**通ってしまう**。
  だから気づけない。実際に2ファイルで起きた（追記したテスト13件と10件が
  直接実行では走っていなかった）。

  テストが走っていないことを、テストで検出する。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = 'if __name__ == "__main__":'
SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git"}


def test_files() -> list[Path]:
    return sorted(p for p in ROOT.rglob("test_*.py")
                  if not SKIP_DIRS & set(p.relative_to(ROOT).parts))


class テストの並び(unittest.TestCase):
    def test_mainブロックの後ろにコードを置かない(self):
        for path in test_files():
            lines = path.read_text(encoding="utf-8").splitlines()
            index = next((i for i, line in enumerate(lines)
                          if line.startswith(MAIN)), None)
            if index is None:
                continue
            after = [line for line in lines[index + 2:] if line.strip()]
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(after, [], f"{MAIN} の後ろにコードがある")

    def test_mainブロックは1つだけ(self):
        # ★行頭で数える。文字列として数えると、この番人自身の docstring や
        #   定数まで数えて自分で落ちる。実際に落ちた。
        for path in test_files():
            lines = path.read_text(encoding="utf-8").splitlines()
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertLessEqual(sum(1 for x in lines if x.startswith(MAIN)), 1)

    def test_検査対象を1つ以上見つけている(self):
        # ★探し方が壊れて0件になると、この番人が黙って無力になる。
        self.assertGreater(len(test_files()), 5)


if __name__ == "__main__":
    unittest.main()

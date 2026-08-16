"""手元HTMLの実験もPage Normalizerの新APIを使えることを固定する。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run import build_prompt  # noqa: E402


class BuildPromptTest(unittest.TestCase):
    def test_本文リンクJSONLDを従来どおり渡す(self):
        prompt, meta = build_prompt(
            """
                <script type="application/ld+json">{"name":"転入届"}</script>
                <h1>転入届</h1><p>本文</p><a href="/detail">詳細</a>
            """,
            "https://example.jp/tennyu", "テスト区", "転入届",
        )
        self.assertIn("本文", prompt)
        self.assertIn("詳細 → https://example.jp/detail", prompt)
        self.assertIn('{"name":"転入届"}', prompt)
        self.assertTrue(meta["has_jsonld"])
        self.assertEqual(meta["n_links"], 1)


if __name__ == "__main__":
    unittest.main()

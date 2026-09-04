from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from never_looked import (  # noqa: E402
    MARKS,
    followed,
    mark_for,
    missing_fields,
    offered,
    summarize,
)


def extract(*, follow: int = 0, found: dict[str, bool] | None = None,
            n_links: int = 40) -> dict:
    found = found or {"必要書類": True, "期限": True, "窓口/オンライン可否": True, "手数料": True}
    return {
        "municipality": "A区", "municipality_id": "a",
        "page": {"url": "https://x.example/a", "n_links": n_links},
        "followed_urls": [f"https://x.example/{i}" for i in range(follow)],
        "items": {k: {"found": v} for k, v in found.items()},
    }


class 印(unittest.TestCase):
    def test_1本も開かなければ_never_looked(self):
        self.assertEqual(mark_for(extract(follow=0), 2), "never_looked")

    def test_上限まで開けば_looked_and_absent(self):
        self.assertEqual(mark_for(extract(follow=2), 2), "looked_and_absent")

    def test_上限を超えて開いても_looked_and_absent(self):
        self.assertEqual(mark_for(extract(follow=3), 2), "looked_and_absent")

    def test_途中まで開けば_partly_looked(self):
        self.assertEqual(mark_for(extract(follow=1), 2), "partly_looked")

    def test_上限1のとき1本は使い切り(self):
        self.assertEqual(mark_for(extract(follow=1), 1), "looked_and_absent")

    def test_印には日本語の説明がある(self):
        for mark, text in MARKS.items():
            with self.subTest(mark=mark):
                self.assertTrue(text.strip())


class 読み取り(unittest.TestCase):
    def test_取れなかった項目を並べる(self):
        got = missing_fields(extract(found={"a": True, "b": False, "c": False}))
        self.assertEqual(got, ["b", "c"])

    def test_全部取れていれば空(self):
        self.assertEqual(missing_fields(extract()), [])

    def test_itemsが無くても落ちない(self):
        self.assertEqual(missing_fields({}), [])

    def test_追従の本数(self):
        self.assertEqual(followed(extract(follow=2)), 2)
        self.assertEqual(followed({"followed_urls": None}), 0)
        self.assertEqual(followed({}), 0)

    def test_渡したリンク数(self):
        self.assertEqual(offered(extract(n_links=40)), 40)
        self.assertEqual(offered({}), 0)
        self.assertEqual(offered({"page": {}}), 0)


def row(name: str, mark: str, missing: list[str], all_missing: bool) -> dict:
    return {"municipality": name, "municipality_id": name, "mark": mark,
            "missing_fields": missing, "all_missing": all_missing, "followed": 0,
            "links_offered": 40}


class 集計(unittest.TestCase):
    def test_全項目記載なしかつ未追従を数える(self):
        """★これが METHOD.md §6 の「言ってはいけない」に実データの裏を付ける数字。

        「4項目とも0点の区を『その区が書いていない』と言うこと」は禁止されていた。
        禁止は正しかった。実際に世田谷区は1本も開かずに4項目とも記載なしと答え、
        追試では窓口が書いてあった。
        """
        rows = [row("世田谷区", "never_looked", ["a", "b"], True),
                row("港区", "looked_and_absent", [], False),
                row("A区", "never_looked", ["a"], False)]
        got = summarize(rows)
        self.assertEqual(got["all_missing_never_looked"], 1)
        self.assertEqual(got["all_missing_never_looked_names"], ["世田谷区"])

    def test_取れない項目があって未追従の区を数える(self):
        rows = [row("A区", "never_looked", ["a"], False),
                row("B区", "never_looked", [], False)]      # 全部取れていれば数えない
        self.assertEqual(summarize(rows)["missing_without_looking"], 1)

    def test_印は3つとも必ず出す(self):
        got = summarize([row("A区", "never_looked", [], False)])
        self.assertEqual(set(got["by_mark"]), set(MARKS))
        self.assertEqual(got["by_mark"]["looked_and_absent"], 0)

    def test_空でも落ちない(self):
        got = summarize([])
        self.assertEqual(got["municipalities"], 0)
        self.assertEqual(got["all_missing_never_looked"], 0)


class 実データ(unittest.TestCase):
    def test_公開済みの3手続きで検出できている(self):
        # ★数字が動いたら気づけるように固定する。動くこと自体は悪くないが、
        #   黙って動くと「直った」と読み違える。
        for procedure, expected in (("tennyu", 1), ("jidouteate", 7), ("sodaigomi", 3)):
            path = ROOT / f"analysis/out/never-looked_{procedure}.json"
            if not path.exists():
                self.skipTest(f"未生成: {path.name}")
            doc = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(procedure=procedure):
                self.assertEqual(doc["summary"]["all_missing_never_looked"], expected)


if __name__ == "__main__":
    unittest.main()

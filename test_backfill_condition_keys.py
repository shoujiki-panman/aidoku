from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "analysis" / "probes"))
from backfill_condition_keys import (  # noqa: E402
    fill,
    index_stale_keys,
    missing_keys,
    process_scores,
)

from measurement import CONDITION_KEYS  # noqa: E402


class MissingKeys(unittest.TestCase):
    def test_足りないキーを順番どおりに返す(self):
        block = {"recording_status": "legacy_unknown"}
        self.assertEqual(missing_keys(block), list(CONDITION_KEYS))

    def test_全部あれば空(self):
        self.assertEqual(missing_keys(dict.fromkeys(CONDITION_KEYS)), [])


class Fill(unittest.TestCase):
    def test_足りないキーをnullで足す(self):
        block = {"recording_status": "legacy_unknown"}
        added = fill(block)
        self.assertEqual(set(added), set(CONDITION_KEYS))
        self.assertTrue(all(block[key] is None for key in CONDITION_KEYS))

    def test_既にある値を上書きしない(self):
        # ★ここを壊すと、測った条件が null に潰れて記録が消える。
        block = dict.fromkeys(CONDITION_KEYS)
        block["link_order"] = "score_desc"
        block["max_links"] = 40
        fill(block)
        self.assertEqual(block["link_order"], "score_desc")
        self.assertEqual(block["max_links"], 40)

    def test_余計なキーを消さない(self):
        block = {"recording_status": "recorded", "runs": [1, 2]}
        fill(block)
        self.assertEqual(block["runs"], [1, 2])
        self.assertEqual(block["recording_status"], "recorded")

    def test_二度目は何も足さない(self):
        block = {}
        fill(block)
        self.assertEqual(fill(block), [])


class IndexKeys(unittest.TestCase):
    def test_一覧に無いキーを返す(self):
        doc = {"provenance": {"condition_keys": list(CONDITION_KEYS[:-1])}}
        self.assertEqual(index_stale_keys(doc), [CONDITION_KEYS[-1]])

    def test_一覧が最新なら空(self):
        doc = {"provenance": {"condition_keys": list(CONDITION_KEYS)}}
        self.assertEqual(index_stale_keys(doc), [])

    def test_provenanceが無くても落ちない(self):
        self.assertEqual(index_stale_keys({}), list(CONDITION_KEYS))


class ProcessScores(unittest.TestCase):
    def write(self, doc: dict) -> Path:
        path = Path(tempfile.mkdtemp()) / "scores-test.json"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    def test_checkでは書き換えない(self):
        path = self.write({"measurement": {"recording_status": "legacy_unknown"}})
        before = path.read_text(encoding="utf-8")
        added = process_scores(path, write=False)
        self.assertEqual(set(added), set(CONDITION_KEYS))
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_書くと足りないキーが入る(self):
        path = self.write({"measurement": {"recording_status": "legacy_unknown"}})
        process_scores(path, write=True)
        block = json.loads(path.read_text(encoding="utf-8"))["measurement"]
        self.assertTrue(all(key in block for key in CONDITION_KEYS))

    def test_measurementが無いファイルは落とす(self):
        # 黙って素通しすると、署名が落ちるファイルを見逃す。
        path = self.write({"summary": {}})
        with self.assertRaises(SystemExit):
            process_scores(path, write=False)

    def test_足すものが無ければファイルに触らない(self):
        path = self.write({"measurement": dict.fromkeys(CONDITION_KEYS)})
        before = path.read_text(encoding="utf-8")
        self.assertEqual(process_scores(path, write=True), [])
        self.assertEqual(path.read_text(encoding="utf-8"), before)


class PublishedFiles(unittest.TestCase):
    def test_公開済みJSONに不足キーが無い(self):
        # ★キーを足したのに走らせ忘れると、外部ツールが KeyError で落ちる。
        #   手作業を3回やった。4回目をここで止める。
        root = Path(__file__).resolve().parent
        for path in sorted(root.glob("web/data/scores-*.json")):
            with self.subTest(path=path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(missing_keys(doc["measurement"]), [])

    def test_indexの条件キー一覧が最新(self):
        root = Path(__file__).resolve().parent
        doc = json.loads((root / "web/data/index.json").read_text(encoding="utf-8"))
        self.assertEqual(index_stale_keys(doc), [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apply_evidence_check import InvalidInput, aggregate, annotate_result, input_urls, run
from polite_fetch import PoliteFetcher


class FakeResult:
    def __init__(self, text: str):
        self.body_path = str(Path(__file__))
        self._text = text

    def body(self) -> str:
        return f"<html><body>{self._text}</body></html>"


class FakeFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def cached(self, url: str):
        text = self.pages.get(url)
        return FakeResult(text) if text is not None else None


def sample_result() -> dict:
    return {
        "page": {"url": "https://example.test/base"},
        "reached": True,
        "followed_urls": ["https://example.test/detail"],
        "items": {
            "期限": {"found": True, "evidence": "届出は14日以内に行ってください"},
            "手数料": {"found": False, "evidence": "記載なし"},
        },
    }


def write_cached_page(fetcher: PoliteFetcher, url: str, html: str) -> None:
    """PoliteFetcher が読む実際のディスク形式でfixtureを置く。"""
    body_path, meta_path = fetcher._paths(url)
    body_path.write_text(html, encoding="utf-8")
    meta = {
        "url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "fetched_at": "2026-08-16T00:00:00+0900",
        "from_cache": False,
        "blocked_by_robots": False,
        "body_path": str(body_path),
        "error": None,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


class URL範囲(unittest.TestCase):
    def test_本体と追跡ページを順番に返す(self):
        self.assertEqual(input_urls(sample_result()), [
            "https://example.test/base", "https://example.test/detail"
        ])

    def test_reachedなのに基点URLが無ければinvalid_input(self):
        result = sample_result()
        result["page"] = None
        checked = annotate_result(result, FakeFetcher({}))
        self.assertEqual(checked["evidence_check_status"], "invalid_input")
        self.assertEqual(checked["items"]["期限"]["evidence_check"]["verdict"], "not_checked")

    def test_followed_urlsが配列でなければinvalid_input(self):
        for value in (0, "", {}):
            with self.subTest(value=value):
                result = sample_result()
                result["followed_urls"] = value
                checked = annotate_result(result, FakeFetcher({}))
                self.assertEqual(checked["evidence_check_status"], "invalid_input")

    def test_followed_urlsの要素が不正ならinvalid_input(self):
        result = sample_result()
        result["followed_urls"] = [42]
        checked = annotate_result(result, FakeFetcher({}))
        self.assertEqual(checked["evidence_check_status"], "invalid_input")

    def test_ホストの無いURLはinvalid_input(self):
        for url in ("https://", "https://[bad", "https://bad host/path"):
            with self.subTest(url=url):
                result = sample_result()
                result["page"] = {"url": url}
                checked = annotate_result(result, FakeFetcher({}))
                self.assertEqual(checked["evidence_check_status"], "invalid_input")


class 既存結果への適用(unittest.TestCase):
    def test_追跡ページの引用も照合できる(self):
        original = sample_result()
        checked = annotate_result(original, FakeFetcher({
            "https://example.test/base": "転入届の案内",
            "https://example.test/detail": "届出は14日以内に行ってください",
        }))
        self.assertEqual(checked["evidence_check_status"], "complete")
        self.assertEqual(checked["items"]["期限"]["evidence_check"]["verdict"], "exact")
        self.assertNotIn("evidence_check", original["items"]["期限"])

    def test_キャッシュ欠損はmissingにしない(self):
        checked = annotate_result(sample_result(), FakeFetcher({
            "https://example.test/base": "転入届の案内",
        }))
        self.assertEqual(checked["evidence_check_status"], "cache_missing")
        self.assertEqual(checked["items"]["期限"]["evidence_check"]["verdict"], "not_checked")
        self.assertEqual(checked["evidence_summary"]["checked"], 0)

    def test_到達失敗は対象外(self):
        checked = annotate_result({"reached": False, "items": {}}, FakeFetcher({}))
        self.assertEqual(checked["evidence_check_status"], "not_applicable")

    def test_items内の項目が不正ならinvalid_input(self):
        result = sample_result()
        result["items"]["期限"] = None
        result["items"]["窓口"] = {
            "found": True,
            "evidence": "各総合支所の窓口で受け付けます",
        }
        checked = annotate_result(result, FakeFetcher({}))
        self.assertEqual(checked["evidence_check_status"], "invalid_input")
        self.assertEqual(checked["items"]["期限"]["evidence_check"]["verdict"],
                         "not_checked")
        self.assertEqual(checked["items"]["窓口"]["evidence_check"]["verdict"],
                         "not_checked")
        self.assertEqual(checked["items"]["手数料"]["evidence_check"]["verdict"],
                         "not_applicable")
        self.assertEqual(checked["evidence_summary"]["not_checked"], 2)

    def test_items自体が不正でも元の値を保持する(self):
        result = sample_result()
        result["items"] = ["keep-me"]
        checked = annotate_result(result, FakeFetcher({}))
        self.assertEqual(checked["evidence_check_status"], "invalid_input")
        self.assertEqual(checked["items"], ["keep-me"])
        self.assertEqual(checked["evidence_summary"]["not_checked"], 0)

    def test_不正なreachedはinvalid_input(self):
        for value in (None, 0, "false"):
            with self.subTest(value=value):
                result = sample_result()
                result["reached"] = value
                checked = annotate_result(result, FakeFetcher({}))
                self.assertEqual(checked["evidence_check_status"], "invalid_input")
                self.assertEqual(
                    checked["items"]["期限"]["evidence_check"]["verdict"],
                    "not_checked",
                )
                records = aggregate([checked])["records"]
                self.assertEqual(records["reached"], 0)
                self.assertEqual(records["unreached"], 0)
                self.assertEqual(records["invalid_input"], 1)

    def test_partialはverifiedに数えない(self):
        result = sample_result()
        result["followed_urls"] = []
        result["items"]["期限"]["evidence"] = "あ" * 15 + "宇宙人が申請します"
        checked = annotate_result(result, FakeFetcher({
            "https://example.test/base": "あ" * 15 + "本人が申請します",
        }))
        summary = aggregate([checked])
        self.assertEqual(summary["items"]["verified"], 0)
        self.assertEqual(summary["items"]["partial"], 1)

    def test_集計(self):
        complete = annotate_result(sample_result(), FakeFetcher({
            "https://example.test/base": "転入届の案内",
            "https://example.test/detail": "届出は14日以内に行ってください",
        }))
        summary = aggregate([complete, {"reached": False,
                                        "evidence_check_status": "not_applicable", "items": {}}])
        self.assertEqual(summary["source_files"], 2)
        self.assertEqual(summary["records"]["cache_complete"], 1)
        self.assertEqual(summary["records"]["unreached"], 1)
        self.assertEqual(summary["items"]["verified"], 1)


class 一括適用(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.extract_dir = self.root / "extract"
        self.out_dir = self.root / "checked"
        self.summary_path = self.root / "summary.json"
        self.extract_dir.mkdir()
        self.source = self.extract_dir / "sample.json"
        self.source.write_text(json.dumps(sample_result(), ensure_ascii=False), encoding="utf-8")
        self.fetcher = FakeFetcher({
            "https://example.test/base": "転入届の案内",
            "https://example.test/detail": "届出は14日以内に行ってください",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixtureを読み派生JSONと集計を書く(self):
        original = self.source.read_text(encoding="utf-8")
        summary = run(self.extract_dir, self.out_dir, self.summary_path, self.fetcher)
        self.assertEqual(summary["source_files"], 1)
        self.assertTrue((self.out_dir / "sample.json").exists())
        self.assertTrue(self.summary_path.exists())
        self.assertEqual(self.source.read_text(encoding="utf-8"), original)

    def test_実キャッシュ形式と複数JSONを一括適用できる(self):
        second = self.extract_dir / "second.json"
        second.write_text(json.dumps(sample_result(), ensure_ascii=False), encoding="utf-8")
        cache_dir = self.root / "cache"
        real_fetcher = PoliteFetcher(cache_dir=cache_dir)
        write_cached_page(real_fetcher, "https://example.test/base",
                          "<html><body>転入届の案内</body></html>")
        write_cached_page(real_fetcher, "https://example.test/detail",
                          "<html><body>届出は14日以内に行ってください</body></html>")

        summary = run(self.extract_dir, self.out_dir, self.summary_path, real_fetcher)

        self.assertEqual(summary["source_files"], 2)
        self.assertEqual(summary["items"]["verified"], 2)
        self.assertTrue((self.out_dir / "sample.json").exists())
        self.assertTrue((self.out_dir / "second.json").exists())

    def test_出力先が入力dirなら書く前に拒否する(self):
        original = self.source.read_text(encoding="utf-8")
        with self.assertRaises(SystemExit):
            run(self.extract_dir, self.extract_dir, self.summary_path, self.fetcher)
        self.assertEqual(self.source.read_text(encoding="utf-8"), original)

    def test_集計先が入力ファイルなら書く前に拒否する(self):
        original = self.source.read_text(encoding="utf-8")
        with self.assertRaises(SystemExit):
            run(self.extract_dir, self.out_dir, self.source, self.fetcher)
        self.assertEqual(self.source.read_text(encoding="utf-8"), original)
        self.assertFalse(self.out_dir.exists())

    def test_集計先が派生JSONなら書く前に拒否する(self):
        colliding_summary = self.out_dir / self.source.name
        with self.assertRaises(SystemExit):
            run(self.extract_dir, self.out_dir, colliding_summary, self.fetcher)
        self.assertFalse(self.out_dir.exists())

    def test_後半のJSONが壊れていても部分出力を残さない(self):
        broken = self.extract_dir / "z-broken.json"
        broken.write_text("{broken", encoding="utf-8")
        with self.assertRaises(InvalidInput):
            run(self.extract_dir, self.out_dir, self.summary_path, self.fetcher)
        self.assertFalse(self.out_dir.exists())
        self.assertFalse(self.summary_path.exists())

    def test_JSONのrootが配列でも部分出力を残さない(self):
        invalid_root = self.extract_dir / "z-invalid-root.json"
        invalid_root.write_text('["bad"]', encoding="utf-8")
        with self.assertRaisesRegex(InvalidInput, "オブジェクトでない"):
            run(self.extract_dir, self.out_dir, self.summary_path, self.fetcher)
        self.assertFalse(self.out_dir.exists())
        self.assertFalse(self.summary_path.exists())

    def test_入力が空なら明示的に失敗する(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(SystemExit):
            run(empty, self.out_dir, self.summary_path, self.fetcher)


if __name__ == "__main__":
    unittest.main()

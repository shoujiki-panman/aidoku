"""読解層のテスト — 「どのページを採点するか」を固定する。

台東区が Word 文書（.docx）を診断ページに選び、ZIP/XML のバイナリを採点していた
（2026-08-05 実測・0点 → 本来のHTMLページで80点）。pick_page の docstring は
「スコア最上位のHTMLページ」と書いてあるのに、実装は PDF しか除外していなかった。
バイナリは text_len が大きくなるので「本文200字以上」の条件もすり抜ける。

LLM（`claude -p`）は呼ばない。呼ばずに決まる経路だけを対象にしている。
標準ライブラリのみ。

実行: python3 -m unittest discover -s extractor -p 'test_*.py'
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from extractor import batch as extraction_batch  # noqa: E402
from extractor import extract, fact_extract  # noqa: E402
from extractor.extract import is_non_html, pick_page  # noqa: E402
from fact_types import EXTRACTOR_KEYS  # noqa: E402
from extractor.fact_extract import (  # noqa: E402
    build_input, parse_json_reply, run_test_case, run_test_cases,
)
from extractor.response_contract import normalize_item, requested_urls  # noqa: E402
from extractor.result_contract import (  # noqa: E402
    failed_test_cases, legacy_items, successful_result, unreachable_result,
)
from measurement import MeasurementError, build_discovery_measurement  # noqa: E402
from measurement_cases import TestCase, test_cases_for  # noqa: E402

VALID_PROMPT_VERSION = "sha256:" + "0" * 64


def candidate(url: str, **kw) -> dict:
    base = {"url": url, "status": 200, "is_pdf": False, "text_len": 5000, "score": 10}
    base.update(kw)
    return base


def discovery_measurement() -> dict:
    return build_discovery_measurement(
        3, {1: (1, 6), 2: (3, 4), 3: (4, 3)}, 26,
        "2026-08-16T00:00:00+00:00",
    )


class CachedPage:
    body_path = "cached.html"

    def __init__(self, body: str = "<h1>転入届</h1><p>本文</p>"):
        self._body = body

    def body(self) -> str:
        return self._body


class FakeFetcher:
    def __init__(self, body: str = '<p>本文</p><a href="/docs">必要書類</a>'):
        self.body = body
        self.fetched: list[str] = []

    def cached(self, _url: str) -> CachedPage:
        return CachedPage(self.body)

    def fetch(self, url: str) -> CachedPage:
        self.fetched.append(url)
        return CachedPage(f"<p>{url}の本文</p>")


def page() -> dict:
    return {"url": "https://example.jp/service", "hops": 1, "link_text": "手続き"}


def discovery() -> dict:
    return {
        "municipality": "練馬区", "municipality_id": "nerima",
        "procedure": "転入届", "procedure_id": "tennyu",
        "measurement": discovery_measurement(),
    }


def llm_reply(value: str = "値", *, source: str = "html",
              follow_urls: list[str] | None = None, note: str = "") -> str:
    return json.dumps({
        "item": {
            "found": True, "value": value, "evidence": "本文からの引用です",
            "evidence_location": "h1: 転入届", "confidence": 0.8,
            "source": source, "failure_reason": None,
        },
        "follow_urls": follow_urls or [],
        "page_notes": note,
    }, ensure_ascii=False)


def follow_request(url: str) -> str:
    return json.dumps({
        "item": {
            "found": False, "value": "", "evidence": "", "source": None,
            "evidence_location": None, "confidence": 0.4,
            "failure_reason": "リンク先にあり",
        },
        "follow_urls": [url], "page_notes": "リンク先にあり",
    }, ensure_ascii=False)


def failure_reply(reason: str) -> str:
    return json.dumps({
        "item": {
            "found": False, "value": "", "evidence": "", "source": None,
            "evidence_location": None, "confidence": 0.7,
            "failure_reason": reason,
        },
        "follow_urls": [], "page_notes": "",
    }, ensure_ascii=False)


class FactTypeCallTest(unittest.TestCase):
    def test_promptは1つのfact_typeだけを指定する(self):
        case = TestCase("tennyu", "documents", "練馬区の必要書類は何か", "1.0")
        fetcher = FakeFetcher(
            '<script type="application/ld+json">{"name":"転入届"}</script>'
            '<p>本文</p><a href="/docs">必要書類</a>')
        prompt, meta, allowed = build_input(
            page(), "練馬区", "転入届", case, fetcher)
        self.assertIn("fact_type: documents", prompt)
        self.assertIn("出力対象: 必要書類", prompt)
        self.assertIn(case.question, prompt)
        self.assertIn('{"name":"転入届"}', prompt)
        self.assertNotIn("窓口オンライン可否", prompt)
        self.assertNotIn("items", prompt)
        self.assertIn('"evidence_location"', prompt)
        self.assertIn('"confidence": 0.0', prompt)
        self.assertIn("採点", prompt)
        self.assertTrue(meta["has_jsonld"])
        self.assertEqual(allowed, {"https://example.jp/docs"})

    def test_最終結果の引用を読んだ本文と照合する(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        fetcher = FakeFetcher("<p>本文からの引用です</p>")
        with mock.patch.object(
                fact_extract, "call_claude", return_value=llm_reply()):
            record, _, _ = run_test_case(
                page(), "練馬区", "転入届", case, fetcher, "model", False)
        self.assertEqual(record["result"]["evidence_check"]["verdict"], "exact")
        self.assertIsNone(record["result"]["failure_type"])
        self.assertEqual(record["result"], record["attempts"][-1]["result"])
        self.assertEqual(record["evidence_summary"]["verified"], 1)

    def test_本文に無い引用をwrong_evidenceへ分類する(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        fetcher = FakeFetcher("<p>実際に取得したページの本文だけがあります。</p>")
        response = json.dumps({
            "item": {
                "found": True,
                "value": "値",
                "evidence": "本文には存在しない十分に長い捏造された引用文です。",
                "evidence_location": "h2: 必要書類",
                "confidence": 0.9,
                "source": "html",
                "failure_reason": None,
            },
            "follow_urls": [],
            "page_notes": "",
        }, ensure_ascii=False)
        with mock.patch.object(
                fact_extract, "call_claude", return_value=response):
            record, _, _ = run_test_case(
                page(), "練馬区", "転入届", case, fetcher, "model", False)
        self.assertEqual(
            record["result"]["evidence_check"]["verdict"], "missing")
        self.assertEqual(record["result"]["failure_type"], "wrong_evidence")
        self.assertEqual(record["result"], record["attempts"][-1]["result"])

    def test_全fact_typeのpromptに他項目のIDと質問を混ぜない(self):
        cases = test_cases_for("tennyu", "練馬区")
        for case in cases:
            with self.subTest(fact_type=case.fact_type):
                prompt, _, _ = build_input(
                    page(), "練馬区", "転入届", case, FakeFetcher())
                for other in cases:
                    if other == case:
                        continue
                    self.assertNotIn(f"- fact_type: {other.fact_type}\n", prompt)
                    self.assertNotIn(other.question, prompt)

    def test_4fact_typeを4回別々に呼ぶ(self):
        cases = test_cases_for("tennyu", "練馬区")
        seen: list[str] = []

        def reply(prompt: str, _model: str) -> str:
            fact_type = next(line.split(": ", 1)[1] for line in prompt.splitlines()
                             if line.startswith("- fact_type: "))
            seen.append(fact_type)
            return llm_reply(value=f"{fact_type}の値", note=fact_type)

        with mock.patch.object(fact_extract, "call_claude", side_effect=reply):
            records, _, _ = run_test_cases(
                page(), "練馬区", "転入届", cases, FakeFetcher(), "model", False)

        self.assertEqual(seen, ["documents", "channel", "deadline", "fee"])
        self.assertEqual(len(records), 4)
        self.assertEqual(records[2]["result"]["value"], "deadlineの値")
        self.assertTrue(all(len(record["attempts"]) == 1 for record in records))
        self.assertTrue(all(record["attempts"][0]["llm_called"] for record in records))
        self.assertEqual(list(legacy_items(records)), EXTRACTOR_KEYS)

    def test_followはTestCaseごとのURLだけで再実行する(self):
        cases = test_cases_for("tennyu", "練馬区")[:2]
        calls = {case.fact_type: 0 for case in cases}

        def reply(prompt: str, _model: str) -> str:
            fact_type = next(line.split(": ", 1)[1] for line in prompt.splitlines()
                             if line.startswith("- fact_type: "))
            calls[fact_type] += 1
            url = f"https://example.jp/{fact_type}"
            if calls[fact_type] == 1:
                return follow_request(url)
            self.assertIn(f"リンク先ページの本文（{url}）", prompt)
            other = "channel" if fact_type == "documents" else "documents"
            self.assertNotIn(f"リンク先ページの本文（https://example.jp/{other}）", prompt)
            return llm_reply(value="リンク先", source="linked_page")

        fetcher = FakeFetcher(
            '<a href="/documents">必要書類</a><a href="/channel">申請方法</a>')
        with mock.patch.object(fact_extract, "call_claude", side_effect=reply):
            records, _, extra = run_test_cases(
                page(), "練馬区", "転入届", cases, fetcher, "model", True)

        self.assertEqual(calls, {"documents": 2, "channel": 2})
        self.assertEqual(fetcher.fetched, [
            "https://example.jp/documents", "https://example.jp/channel"])
        self.assertEqual([r["followed_urls"] for r in records], [
            ["https://example.jp/documents"], ["https://example.jp/channel"]])
        self.assertEqual([[a["stage"] for a in r["attempts"]] for r in records], [
            ["initial", "follow"], ["initial", "follow"]])
        self.assertEqual(records[0]["result"]["value"], "リンク先")
        self.assertEqual(records[0]["result"], records[0]["attempts"][-1]["result"])
        self.assertTrue(all(
            attempt["llm_called"] for record in records for attempt in record["attempts"]))
        self.assertEqual([url for url, _ in extra], fetcher.fetched)

    def test_壊れた応答は失敗したTestCaseを示す(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        with mock.patch.object(fact_extract, "call_claude", return_value='{"items": {}}'):
            with self.assertRaisesRegex(RuntimeError, "tennyu/documents"):
                run_test_case(
                    page(), "練馬区", "転入届", case,
                    FakeFetcher(), "model", False)

    def test_followは最大2件を超えた応答を取得前に拒否する(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        urls = [f"https://example.jp/{name}" for name in ("a", "b", "c")]
        body = "".join(f'<a href="/{name}">{name}</a>' for name in ("a", "b", "c"))
        fetcher = FakeFetcher(body)
        reply = json.dumps({
            "item": {"found": False, "value": "", "evidence": "", "source": None,
                     "evidence_location": None, "confidence": 0.5,
                     "failure_reason": "リンク先にあり"},
            "follow_urls": urls, "page_notes": "",
        }, ensure_ascii=False)
        with mock.patch.object(fact_extract, "call_claude", return_value=reply):
            with self.assertRaisesRegex(RuntimeError, "最大2件"):
                run_test_case(
                    page(), "練馬区", "転入届", case, fetcher, "model", True)
        self.assertEqual(fetcher.fetched, [])

    def test_初回応答はlinked_pageを根拠にできない(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        with mock.patch.object(
                fact_extract, "call_claude",
                return_value=llm_reply(source="linked_page")):
            with self.assertRaisesRegex(RuntimeError, "含まれないsource"):
                run_test_case(
                    page(), "練馬区", "転入届", case,
                    FakeFetcher(), "model", False)

    def test_空白だけのJSONLDは根拠として扱わない(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        prompt, meta, _ = fact_extract.compose_input(
            page(), "練馬区", "転入届", case, [], "本文", ["  \n"])
        self.assertFalse(meta["has_jsonld"])
        self.assertIn("構造化データ (JSON-LD)\n\n（なし）", prompt)
        with self.assertRaisesRegex(ValueError, "含まれないsource"):
            normalize_item(
                json.loads(llm_reply(source="jsonld")),
                fact_extract.allowed_sources(meta),
            )

    def test_found_trueでfollow要求を出したら取得前に拒否する(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        fetcher = FakeFetcher()
        with mock.patch.object(
                fact_extract, "call_claude",
                return_value=llm_reply(follow_urls=["https://example.jp/docs"])):
            with self.assertRaisesRegex(RuntimeError, "follow_urlsの有無"):
                run_test_case(
                    page(), "練馬区", "転入届", case, fetcher, "model", True)
        self.assertEqual(fetcher.fetched, [])

    def test_リンク先にありなら初回にURLが必要(self):
        data = json.loads(follow_request("https://example.jp/docs"))
        data["follow_urls"] = []
        with self.assertRaisesRegex(ValueError, "follow_urlsの有無"):
            fact_extract.validated_attempt(
                data, frozenset({"html"}), "initial", [])

    def test_PDF内のみはURLを追わず失敗結果として残す(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        fetcher = FakeFetcher('<a href="/guide.pdf">必要書類PDF</a>')
        with mock.patch.object(
                fact_extract, "call_claude",
                return_value=failure_reply("PDF内のみ")) as call:
            record, _, _ = run_test_case(
                page(), "練馬区", "転入届", case, fetcher, "model", True)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(fetcher.fetched, [])
        self.assertEqual(record["result"]["failure_reason"], "PDF内のみ")

    def test_PDFのURLをfollow指定した応答は取得前に拒否する(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        fetcher = FakeFetcher('<a href="/guide.pdf">必要書類PDF</a>')
        with mock.patch.object(
                fact_extract, "call_claude",
                return_value=follow_request("https://example.jp/guide.pdf")):
            with self.assertRaisesRegex(RuntimeError, "PDF/Office"):
                run_test_case(
                    page(), "練馬区", "転入届", case, fetcher, "model", True)
        self.assertEqual(fetcher.fetched, [])

    def test_HTMLリンクがPDFへredirectしたら本文をparseしない(self):
        case = TestCase("tennyu", "documents", "質問", "1.0")
        fetcher = FakeFetcher('<a href="/guide">必要書類</a>')
        redirected = CachedPage("PDF binary")
        redirected.final_url = "https://example.jp/download"
        redirected.content_type = "application/pdf"

        def fetch(url):
            fetcher.fetched.append(url)
            return redirected

        fetcher.fetch = fetch
        with mock.patch.object(
                fact_extract, "call_claude",
                return_value=follow_request("https://example.jp/guide")) as call:
            record, _, extra = run_test_case(
                page(), "練馬区", "転入届", case, fetcher, "model", True)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(extra, [])
        self.assertEqual(record["followed_urls"], [])
        self.assertEqual(record["result"]["failure_reason"], "PDF内のみ")
        self.assertIsNone(record["result"]["confidence"])
        self.assertIsNone(record["result"]["evidence_location"])
        self.assertEqual(record["attempts"][-1]["stage"], "follow_fetch")
        self.assertFalse(record["attempts"][-1]["llm_called"])
        self.assertEqual(record["result"], record["attempts"][-1]["result"])
        self.assertEqual(
            record["attempts"][-1]["attachment_urls"],
            ["https://example.jp/guide"],
        )

    def test_follow応答のURL拡張子とMIMEを独立に検証する(self):
        fetched = CachedPage()
        cases = (
            ("https://example.jp/guide.pdf", "text/html", True),
            ("https://example.jp/guide", "application/pdf", True),
            ("https://example.jp/guide", "application/vnd.ms-excel", True),
            ("https://example.jp/guide", "application/vnd.ms-powerpoint", True),
            ("https://example.jp/guide", "application/rtf", True),
            ("https://example.jp/guide", "application/vnd.oasis.opendocument.text", True),
            ("https://example.jp/guide", "text/html; charset=utf-8", False),
            ("https://example.jp/guide", "application/xhtml+xml", False),
            ("https://example.jp/guide", "TEXT/HTML; CHARSET=UTF-8", False),
            ("https://example.jp/guide", "APPLICATION/XHTML+XML", False),
        )
        for final_url, content_type, expected in cases:
            with self.subTest(final_url=final_url, content_type=content_type):
                fetched.final_url = final_url
                fetched.content_type = content_type
                self.assertEqual(
                    fact_extract._fetched_non_html(
                        fetched, "https://example.jp/requested"),
                    expected,
                )


class ResponseContractTest(unittest.TestCase):
    def test_itemとfoundの型を検証する(self):
        for data in ({}, {"item": []}, {"item": {"found": "true"}}):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    normalize_item(data)

    def test_foundと値_根拠_source_failureの整合を検証する(self):
        invalid = [
            {"found": True, "value": "", "evidence": "引用", "source": "html",
             "failure_reason": None},
            {"found": True, "value": "値", "evidence": "", "source": "html",
             "failure_reason": None},
            {"found": True, "value": "値", "evidence": "引用", "source": None,
             "failure_reason": None},
            {"found": True, "value": "値", "evidence": "引用", "source": "html",
             "failure_reason": "記載なし"},
            {"found": False, "value": "", "evidence": "", "source": "html",
             "failure_reason": "記載なし"},
            {"found": False, "value": "", "evidence": "", "source": None,
             "failure_reason": None},
            {"found": False, "value": "14日", "evidence": "引用", "source": None,
             "failure_reason": "記載なし"},
            {"found": False, "value": "", "evidence": "", "source": None,
             "failure_reason": "任意文字"},
            {"found": True, "value": "値", "evidence": "引用", "source": "memory",
             "failure_reason": None},
            {"found": True, "value": "値", "evidence": "引用", "source": "pdf",
             "failure_reason": None},
        ]
        for item in invalid:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    normalize_item({"item": {
                        **item,
                        "evidence_location": (
                            "h2: 必要書類" if item.get("found") is True else None),
                        "confidence": 0.5,
                    }})

    def test_found_falseの正規応答は受理する(self):
        item = normalize_item({"item": {
            "found": False, "value": "", "evidence": "", "source": None,
            "evidence_location": None, "confidence": 0.25,
            "failure_reason": "記載なし",
        }})
        self.assertFalse(item["found"])
        self.assertEqual(item["confidence"], 0.25)
        self.assertIsNone(item["evidence_location"])
        self.assertEqual(item["failure_reason"], "記載なし")
        self.assertEqual(item["failure_type"], "fact_missing")

    def test_confidenceと引用箇所を結果へ残す(self):
        item = normalize_item(json.loads(llm_reply()))
        self.assertEqual(item["confidence"], 0.8)
        self.assertEqual(item["evidence_location"], "h1: 転入届")

    def test_confidenceは0以上1以下の有限な数値だけ受理する(self):
        for value in (0, 1, 0.25):
            with self.subTest(valid=value):
                data = json.loads(llm_reply())
                data["item"]["confidence"] = value
                self.assertEqual(normalize_item(data)["confidence"], float(value))
        for value in (None, True, False, "0.5", -0.01, 1.01,
                      float("nan"), float("inf"), float("-inf"), 10 ** 10000):
            with self.subTest(invalid=value):
                data = json.loads(llm_reply())
                data["item"]["confidence"] = value
                with self.assertRaisesRegex(ValueError, "confidence"):
                    normalize_item(data)

    def test_confidenceの欠落を既定値で隠さない(self):
        data = json.loads(llm_reply())
        del data["item"]["confidence"]
        with self.assertRaisesRegex(ValueError, "confidence"):
            normalize_item(data)

    def test_回答ありは引用箇所必須_回答なしは引用箇所禁止(self):
        for location in (None, "", "  "):
            with self.subTest(found=True, location=location):
                data = json.loads(llm_reply())
                data["item"]["evidence_location"] = location
                with self.assertRaisesRegex(ValueError, "evidence_location"):
                    normalize_item(data)
        data = json.loads(failure_reply("記載なし"))
        data["item"]["evidence_location"] = "h2: 必要書類"
        with self.assertRaisesRegex(ValueError, "evidence_location"):
            normalize_item(data)

    def test_引用箇所のキーを省略できない(self):
        for reply in (llm_reply(), failure_reply("記載なし")):
            with self.subTest(reply=reply):
                data = json.loads(reply)
                del data["item"]["evidence_location"]
                with self.assertRaisesRegex(ValueError, "evidence_location"):
                    normalize_item(data)

    def test_引用箇所は文字列だけ受理する(self):
        data = json.loads(llm_reply())
        data["item"]["evidence_location"] = ["h1"]
        with self.assertRaisesRegex(ValueError, "evidence_location"):
            normalize_item(data)

    def test_follow_urlsは配列とHTTP形式を要求する(self):
        for data in ({"follow_urls": "https://example.jp/"},
                     {"follow_urls": [None]}, {"follow_urls": ["javascript:x"]}):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    requested_urls(data, {"https://example.jp/a"})

    def test_提示していないfollow_urlを拒否する(self):
        with self.assertRaisesRegex(ValueError, "提示していないURL"):
            requested_urls(
                {"follow_urls": ["https://attacker.example/a"]},
                {"https://example.jp/a"},
            )

    def test_壊れたURLを例外にせず拒否する(self):
        for url in ("https://", "https://[bad", "https://example.jp/a b",
                    "https://example.jp/a\n", "https://:80/x",
                    "https://user@:80/x", "https://example.jp:bad/x"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    requested_urls({"follow_urls": [url]}, {url})

    def test_follow_urlsは重複だけ畳む(self):
        allowed = {"https://example.jp/a", "http://example.jp/b"}
        self.assertEqual(requested_urls({"follow_urls": [
            "https://example.jp/a", "https://example.jp/a", "http://example.jp/b"]}, allowed), [
                "https://example.jp/a", "http://example.jp/b"])

    def test_到達失敗も4TestCaseと既存itemsへ残る(self):
        cases = test_cases_for("tennyu", "練馬区")
        records = failed_test_cases(cases, "到達失敗")
        self.assertEqual(len(records), 4)
        items = legacy_items(records)
        self.assertEqual(list(items), EXTRACTOR_KEYS)
        self.assertTrue(all(not item["found"] for item in items.values()))
        self.assertTrue(all(item["failure_reason"] == "到達失敗"
                            for item in items.values()))
        self.assertTrue(all(item["failure_type"] == "page_not_discoverable"
                            for item in items.values()))
        self.assertTrue(all(item["confidence"] is None for item in items.values()))
        self.assertTrue(all(item["evidence_location"] is None
                            for item in items.values()))
        result = unreachable_result(discovery(), cases)
        self.assertFalse(result["reached"])
        self.assertEqual(result["failure_type"], "page_not_discoverable")
        self.assertEqual(result["test_cases"], records)
        self.assertEqual(result["items"], items)

    def test_成功結果は新旧契約を同じ値で持つ(self):
        cases = test_cases_for("tennyu", "練馬区")
        records = []
        for case in cases:
            records.append({
                **case.__dict__,
                "result": normalize_item(json.loads(llm_reply(case.fact_type))),
                "attempts": [],
                "followed_urls": [f"https://example.jp/{case.fact_type}"],
                "page_notes": case.fact_type,
            })
        result = successful_result(
            discovery(), page(), records, {"n_links": 1}, "model",
            {"online_clarity": "明記", "evidence": "引用", "pages": [page()["url"]]},
        )
        self.assertTrue(result["reached"])
        self.assertIsNone(result["failure_type"])
        self.assertEqual(result["items"], legacy_items(records))
        self.assertEqual(result["items"]["期限"]["value"], "deadline")
        self.assertEqual(result["items"]["期限"]["confidence"], 0.8)
        self.assertEqual(
            result["items"]["期限"]["evidence_location"], "h1: 転入届")
        self.assertEqual(len(result["followed_urls"]), 4)
        self.assertEqual(result["page_notes"].splitlines(), [
            "documents", "channel", "deadline", "fee"])

    def test_JSON応答の境界を検証する(self):
        self.assertEqual(parse_json_reply('前置き```json\n{"item": {}}\n```後置き'),
                         {"item": {}})
        for raw in (None, "", "[]", "{broken"):
            with self.subTest(raw=raw):
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    parse_json_reply(raw)


class IsNonHtmlTest(unittest.TestCase):
    def test_office_documents_are_not_html(self):
        for ext in ("docx", "doc", "xlsx", "xls", "pptx", "ppt", "pdf", "zip", "csv", "rtf"):
            with self.subTest(ext=ext):
                self.assertTrue(is_non_html(f"https://example.jp/a/b.{ext}"))

    def test_case_is_ignored(self):
        self.assertTrue(is_non_html("https://example.jp/A/TENNYU.DOCX"))

    def test_html_pages_pass(self):
        for url in ("https://example.jp/a.html", "https://example.jp/a.htm",
                    "https://example.jp/a/", "https://example.jp/a"):
            with self.subTest(url=url):
                self.assertFalse(is_non_html(url))

    def test_query_string_is_not_the_path(self):
        """?file=x.docx は HTML ページ。拡張子はパス側だけを見る。"""
        self.assertFalse(is_non_html("https://example.jp/view.html?file=x.docx"))


class PickPageTest(unittest.TestCase):
    def test_skips_binary_attachment_even_when_top_scored(self):
        """台東区で起きた事象。1位が .docx なら飛ばして次のHTMLを選ぶ。"""
        picked = pick_page({"candidates": [
            candidate("https://example.jp/x.files/tennyu-inin.docx", score=46, text_len=21992),
            candidate("https://example.jp/tennyu.html", score=39, text_len=1635),
        ]})
        self.assertEqual(picked["url"], "https://example.jp/tennyu.html")

    def test_binary_does_not_pass_via_text_len(self):
        """バイナリは text_len が大きいので、長さの条件では止められない。"""
        picked = pick_page({"candidates": [
            candidate("https://example.jp/a.docx", text_len=99999)]})
        self.assertIsNone(picked)

    def test_skips_pdf_and_non_200_and_short_pages(self):
        picked = pick_page({"candidates": [
            candidate("https://example.jp/a.html", is_pdf=True),
            candidate("https://example.jp/b.html", status=404),
            candidate("https://example.jp/c.html", text_len=199),
            candidate("https://example.jp/d.html"),
        ]})
        self.assertEqual(picked["url"], "https://example.jp/d.html")

    def test_returns_none_when_nothing_usable(self):
        self.assertIsNone(pick_page({"candidates": []}))


class ExtractionFlowTest(unittest.TestCase):
    def test_到達失敗はLLMを呼ばずTestCaseを残す(self):
        disc = {**discovery(), "candidates": []}
        with mock.patch.object(extract, "run_test_cases") as run:
            result = extract.extract_one(disc, FakeFetcher(), "model", False)
        run.assert_not_called()
        self.assertFalse(result["reached"])
        self.assertEqual(len(result["test_cases"]), 4)
        self.assertEqual(result["measurement"]["recording_status"], "recorded")
        self.assertEqual(result["evidence_summary"]["not_applicable"], 4)

    def test_到達成功は独立抽出後にclarityを1回だけ呼ぶ(self):
        disc = {**discovery(), "candidates": [candidate(page()["url"], hops=1,
                                                         link_text="手続き")]}
        cases = test_cases_for("tennyu", "練馬区")
        records = failed_test_cases(cases, "記載なし")
        clarity = {"online_clarity": "明記", "evidence": "引用", "pages": [page()["url"]]}
        with mock.patch.object(
                extract, "run_test_cases", return_value=(records, {"n_links": 1}, [])) as run, \
                mock.patch.object(extract, "judge_clarity", return_value=clarity) as judge:
            result = extract.extract_one(disc, FakeFetcher(), "model", False)
        run.assert_called_once()
        judge.assert_called_once()
        self.assertTrue(result["reached"])
        self.assertEqual(result["test_cases"], records)
        self.assertEqual(result["measurement"]["recording_status"], "recorded")


class MainBatchTest(unittest.TestCase):
    MUNICIPALITIES = {"edogawa": "江戸川区", "nerima": "練馬区"}

    def write_discovery(self, root: Path, municipality_id: str,
                        embedded_id: str | None = None) -> Path:
        path = root / f"discovery_{municipality_id}_tennyu.json"
        actual_id = embedded_id or municipality_id
        data = {
            "municipality": self.MUNICIPALITIES.get(actual_id, "練馬区"),
            "municipality_id": actual_id,
            "procedure": "転入届", "procedure_id": "tennyu",
            "candidates": [],
            "measurement": discovery_measurement(),
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_後半失敗なら前半の既存出力も変更しない(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery_dir, out_dir = root / "discovery", root / "out"
            discovery_dir.mkdir()
            out_dir.mkdir()
            self.write_discovery(discovery_dir, "edogawa")
            self.write_discovery(discovery_dir, "nerima")
            sentinel = out_dir / "extract_edogawa_tennyu.json"
            sentinel.write_text("SENTINEL", encoding="utf-8")

            def build(discovery_data, cases, *_args):
                if discovery_data["municipality_id"] == "nerima":
                    raise RuntimeError("後半失敗")
                return unreachable_result(discovery_data, list(cases))

            with mock.patch.object(extract, "DISCOVERY_DIR", discovery_dir), \
                    mock.patch.object(extract, "OUT_DIR", out_dir), \
                    mock.patch.object(extract, "PoliteFetcher", return_value=object()), \
                    mock.patch.object(extract, "extract_prepared", side_effect=build):
                with self.assertRaisesRegex(RuntimeError, "後半失敗"):
                    extract.main(["--procedure", "tennyu"])

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "SENTINEL")
            self.assertFalse((out_dir / "extract_nerima_tennyu.json").exists())

    def test_後半の測定条件欠落はLLMとwrite前に拒否する(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery_dir, out_dir = root / "discovery", root / "out"
            discovery_dir.mkdir()
            out_dir.mkdir()
            self.write_discovery(discovery_dir, "edogawa")
            invalid = self.write_discovery(discovery_dir, "nerima")
            data = json.loads(invalid.read_text(encoding="utf-8"))
            data.pop("measurement")
            invalid.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            sentinel = out_dir / "extract_edogawa_tennyu.json"
            sentinel.write_text("SENTINEL", encoding="utf-8")

            with mock.patch.object(extract, "DISCOVERY_DIR", discovery_dir), \
                    mock.patch.object(extract, "OUT_DIR", out_dir), \
                    mock.patch.object(extract, "extract_prepared") as build:
                with self.assertRaisesRegex(SystemExit, "探索条件が記録されていない"):
                    extract.main(["--procedure", "tennyu"])

            build.assert_not_called()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "SENTINEL")
            self.assertFalse((out_dir / "extract_nerima_tennyu.json").exists())

    def test_後半のstage_write失敗でも既存出力を変更しない(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = [root / "a.json", root / "b.json"]
            for index, output in enumerate(outputs):
                output.write_text(f"OLD-{index}", encoding="utf-8")
            jobs = [extraction_batch.ExtractionJob({}, (), output) for output in outputs]
            batch = [(job, {}, f"NEW-{index}")
                     for index, job in enumerate(jobs)]
            real_stage = extraction_batch._stage_payload
            calls = 0

            def fail_second(output, payload):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("disk full")
                return real_stage(output, payload)

            with mock.patch.object(
                    extraction_batch, "_stage_payload", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "disk full"):
                    extraction_batch.write_batch(batch)
            self.assertEqual(
                [output.read_text(encoding="utf-8") for output in outputs],
                ["OLD-0", "OLD-1"],
            )
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_後半のreplace失敗でも全既存出力をrollbackする(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = [root / "a.json", root / "b.json"]
            for index, output in enumerate(outputs):
                output.write_text(f"OLD-{index}", encoding="utf-8")
            jobs = [extraction_batch.ExtractionJob({}, (), output) for output in outputs]
            batch = [(job, {}, f"NEW-{index}")
                     for index, job in enumerate(jobs)]
            real_replace = extraction_batch._replace_staged
            calls = 0

            def fail_second(temporary, output):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("replace failed")
                return real_replace(temporary, output)

            with mock.patch.object(
                    extraction_batch, "_replace_staged", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    extraction_batch.write_batch(batch)
            self.assertEqual(
                [output.read_text(encoding="utf-8") for output in outputs],
                ["OLD-0", "OLD-1"],
            )
            self.assertEqual(list(root.glob(".*.tmp")), [])
            self.assertEqual(list(root.glob(".*.bak")), [])

    def test_rollback失敗時は復旧用backupを消さない(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = [root / "a.json", root / "b.json"]
            for index, output in enumerate(outputs):
                output.write_text(f"OLD-{index}", encoding="utf-8")
            jobs = [extraction_batch.ExtractionJob({}, (), output) for output in outputs]
            batch = [(job, {}, f"NEW-{index}")
                     for index, job in enumerate(jobs)]
            real_replace = extraction_batch._replace_staged
            calls = 0

            def fail_second(temporary, output):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("replace failed")
                return real_replace(temporary, output)

            with mock.patch.object(
                    extraction_batch, "_replace_staged", side_effect=fail_second), \
                    mock.patch.object(
                        extraction_batch, "_restore_backup",
                        side_effect=OSError("rollback failed")):
                with self.assertRaisesRegex(RuntimeError, "手動復旧用backup") as raised:
                    extraction_batch.write_batch(batch)
            backups = list(root.glob(".*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertIn(str(backups[0]), str(raised.exception))
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "OLD-0")

    def test_置換後も既存と新規ファイルのmodeを維持する(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing, new = root / "existing.json", root / "new.json"
            existing.write_text("OLD", encoding="utf-8")
            existing.chmod(0o640)
            jobs = [
                extraction_batch.ExtractionJob({}, (), existing),
                extraction_batch.ExtractionJob({}, (), new),
            ]
            extraction_batch.write_batch([
                (jobs[0], {}, "NEW-EXISTING"), (jobs[1], {}, "NEW-FILE")])
            self.assertEqual(stat.S_IMODE(existing.stat().st_mode), 0o640)
            self.assertEqual(
                stat.S_IMODE(new.stat().st_mode),
                extraction_batch._default_file_mode(),
            )

    def test_ファイル名と埋込IDの不一致はLLM前に拒否する(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_discovery(root, "nerima", embedded_id="edogawa")
            with mock.patch.object(extraction_batch, "test_cases_for") as cases:
                with self.assertRaisesRegex(ValueError, "ファイル名と埋込ID"):
                    extraction_batch.load_jobs([path], "tennyu", root / "out")
            cases.assert_not_called()

    def test_出力先重複は事前に拒否する(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_discovery(root, "nerima")
            with self.assertRaisesRegex(ValueError, "出力先が重複"):
                extraction_batch.load_jobs([path, path], "tennyu", root / "out")

    def test_targets上の名前とIDの不一致を拒否する(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_discovery(root, "nerima")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["municipality"] = "江戸川区"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "municipality名とID"):
                extraction_batch.load_jobs([path], "tennyu", root / "out")

    def test_candidateの不正型を到達失敗へ丸めない(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_discovery(root, "nerima")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["candidates"] = [candidate(
                "https://example.jp/page", status="200", hops=1,
                link_text="転入届")]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "statusが不正"):
                extraction_batch.load_jobs([path], "tennyu", root / "out")

    def test_candidateの各必須型と範囲を検証する(self):
        good = candidate(
            "https://example.jp/page", status=0, hops=1, link_text="転入届")
        extraction_batch._validate_candidate(good)
        invalid = (
            {"url": "https://:80/x"}, {"status": True}, {"status": 99},
            {"status": 600}, {"is_pdf": 0}, {"text_len": True},
            {"text_len": -1}, {"hops": True}, {"hops": -1},
            {"link_text": None},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    extraction_batch._validate_candidate({**good, **changes})

    def test_targetsのhyphen入りIDを受理する(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "discovery_tokyo-metro_tennyu.json"
            path.write_text(json.dumps({
                "municipality": "東京都", "municipality_id": "tokyo-metro",
                "procedure": "転入届", "procedure_id": "tennyu",
                "candidates": [],
            }, ensure_ascii=False), encoding="utf-8")
            jobs = extraction_batch.load_jobs([path], "tennyu", root / "out")
            self.assertEqual(jobs[0].discovery["municipality_id"], "tokyo-metro")

    def test_既存discoveryのstatus_0を含め全件preflightできる(self):
        for procedure in ("tennyu", "jidouteate", "sodaigomi", "passport"):
            with self.subTest(procedure=procedure):
                files = sorted((ROOT / "crawler" / "out").glob(
                    f"discovery_*_{procedure}.json"))
                self.assertTrue(files)
                jobs = extraction_batch.load_jobs(
                    files, procedure, ROOT / "extractor" / "out")
                self.assertEqual(len(jobs), len(files))

    def test_直接実行とmodule実行のhelpが両方動く(self):
        commands = (
            [sys.executable, str(ROOT / "extractor" / "extract.py"), "--help"],
            [sys.executable, "-m", "extractor.extract", "--help"],
        )
        for command in commands:
            with self.subTest(command=command):
                completed = subprocess.run(
                    command, cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("--procedure", completed.stdout)


if __name__ == "__main__":
    unittest.main()

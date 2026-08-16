"""独立Test Case結果と、後方互換のextract JSONを相互接続する。"""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from evidence_check import MAX_TEXT_CHARS_PER_PAGE, summarize  # noqa: E402
from fact_types import EXTRACTOR_KEYS, by_id  # noqa: E402
from measurement_cases import TestCase  # noqa: E402


def failed_test_cases(cases: list[TestCase], reason: str) -> list[dict]:
    """到達失敗でもTest Caseを消さず、success rateの分母へ残す。"""
    return [{
        **asdict(test_case),
        "result": {
            "found": False, "value": "", "evidence": "", "source": None,
            "failure_reason": reason,
            "evidence_check": {
                "verdict": "not_applicable", "run": 0,
                "note": "found=false のため照合しない",
            },
        },
        "attempts": [],
        "followed_urls": [],
        "page_notes": "",
    } for test_case in cases]


def legacy_items(records: list[dict]) -> dict:
    """新しいTest Case記録から、採点・画面用の既存items契約を復元する。"""
    items = {}
    for record in records:
        key = by_id(record["fact_type"])["extractor_key"]
        if key in items:
            raise ValueError(f"Test Caseが重複している: {record['fact_type']}")
        items[key] = record["result"]
    missing = [key for key in EXTRACTOR_KEYS if key not in items]
    if missing:
        raise ValueError(f"既存itemsへ復元できないfact_typeがある: {missing}")
    return {key: items[key] for key in EXTRACTOR_KEYS}


def unreachable_result(discovery: dict, cases: list[TestCase],
                       measurement: dict | None = None,
                       model: str | None = None) -> dict:
    records = failed_test_cases(cases, "到達失敗")
    items = legacy_items(records)
    return {
        **_identity(discovery),
        "page": None,
        "reached": False,
        "model": model,
        "measurement": measurement,
        "followed_urls": [],
        "test_cases": records,
        "items": items,
        "page_notes": "",
        "error": "到達失敗",
        "evidence_check_status": "not_applicable",
        "evidence_check_scope": {
            "pages": [], "max_text_chars_per_page": MAX_TEXT_CHARS_PER_PAGE,
        },
        "evidence_summary": _evidence_summary(items),
    }


def successful_result(discovery: dict, page: dict, records: list[dict],
                      meta: dict, model: str, clarity: dict,
                      measurement: dict | None = None) -> dict:
    items = legacy_items(records)
    followed_urls = _combined_followed_urls(records)
    return {
        **_identity(discovery),
        "page": {
            "url": page["url"], "hops": page["hops"],
            "link_text": page["link_text"], **meta,
        },
        "reached": True,
        "model": model,
        "measurement": measurement,
        "followed_urls": followed_urls,
        "online_clarity": clarity["online_clarity"],
        "online_clarity_evidence": clarity["evidence"],
        "online_clarity_pages": clarity["pages"],
        "test_cases": records,
        "items": items,
        "page_notes": _combined_page_notes(records),
        "evidence_check_status": "complete",
        "evidence_check_scope": {
            "pages": [page["url"], *followed_urls],
            "max_text_chars_per_page": MAX_TEXT_CHARS_PER_PAGE,
            "isolated_by_test_case": True,
        },
        "evidence_summary": _evidence_summary(items),
    }


def _evidence_summary(items: dict) -> dict:
    checks = {}
    for key, item in items.items():
        check = item.get("evidence_check")
        if check is None:
            verdict = "not_applicable" if item.get("found") is False else "not_checked"
            check = {"verdict": verdict, "run": 0,
                     "note": "evidence_checkが記録されていない"}
        checks[key] = check
    return summarize(checks)


def _combined_followed_urls(records: list[dict]) -> list[str]:
    return list(dict.fromkeys(
        url for record in records for url in record["followed_urls"]))


def _combined_page_notes(records: list[dict]) -> str:
    notes = dict.fromkeys(
        record["page_notes"] for record in records if record["page_notes"])
    return "\n".join(notes)


def _identity(discovery: dict) -> dict:
    return {
        "municipality": discovery["municipality"],
        "municipality_id": discovery["municipality_id"],
        "procedure": discovery["procedure"],
        "procedure_id": discovery["procedure_id"],
    }

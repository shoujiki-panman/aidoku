"""service×fact_type単位の独立した測定質問を作る。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from fact_types import FACT_TYPES, by_id

TARGETS_PATH = Path(__file__).parent / "crawler" / "targets.json"
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
REQUIRED_FACT_TYPE_IDS = [fact["id"] for fact in FACT_TYPES]


class TestCaseError(ValueError):
    """Test Case定義が欠けている、または中央fact_typeと接続できない。"""


@dataclass(frozen=True)
class TestCase:
    service: str
    fact_type: str
    question: str
    test_case_version: str


def build_test_cases(procedure: dict, municipality: str, version: str) -> list[TestCase]:
    """1手続きのfact_typeを、自治体名入りの独立Test Caseへ展開する。"""
    service = _required_text(procedure, "id")
    service_name = _required_text(procedure, "name")
    if not isinstance(municipality, str) or not municipality.strip():
        raise TestCaseError("自治体名が空")
    municipality = municipality.strip()
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise TestCaseError(f"test_case_versionが不正: {version!r}")

    fact_ids = procedure.get("fact_types")
    if not isinstance(fact_ids, list):
        raise TestCaseError(f"{service}: fact_typesは配列で指定する")
    if not fact_ids:
        raise TestCaseError(f"{service}: 中央fact_typeを使うTest Caseの対象外")
    if any(not isinstance(fact_id, str) or not fact_id.strip() for fact_id in fact_ids):
        raise TestCaseError(f"{service}: fact_typeは空でない文字列にする")
    if len(fact_ids) != len(set(fact_ids)):
        raise TestCaseError(f"{service}: fact_typeが重複している")

    for fact_id in fact_ids:
        try:
            by_id(fact_id)
        except KeyError as exc:
            raise TestCaseError(f"{service}: 未知のfact_type: {fact_id}") from exc
    if fact_ids != REQUIRED_FACT_TYPE_IDS:
        raise TestCaseError(
            f"{service}: 測定対象は中央4 fact_typeを定義順に指定する")

    cases = []
    for fact_id in fact_ids:
        fact = by_id(fact_id)
        fact_question = _required_text(fact, "question")
        cases.append(TestCase(
            service=service,
            fact_type=fact_id,
            question=f"{municipality}の「{service_name}」について、{fact_question}",
            test_case_version=version,
        ))
    return cases


def test_cases_for(service: str, municipality: str,
                   targets_path: Path = TARGETS_PATH) -> list[TestCase]:
    """targets.jsonからserviceを1件だけ引き、そのTest Caseを返す。"""
    doc = json.loads(Path(targets_path).read_text(encoding="utf-8"))
    procedures = doc.get("procedures")
    if not isinstance(procedures, list):
        raise TestCaseError("targets.jsonのproceduresが配列でない")
    matches = [proc for proc in procedures
               if isinstance(proc, dict) and proc.get("id") == service]
    if len(matches) != 1:
        raise TestCaseError(f"serviceは1件だけ必要: {service!r}（{len(matches)}件）")
    return build_test_cases(matches[0], municipality, doc.get("test_case_version"))


def target_identity(municipality_id: str, service: str,
                    targets_path: Path = TARGETS_PATH) -> tuple[str, str]:
    """targets上のIDを表示名へ1件だけ解決する。"""
    doc = json.loads(Path(targets_path).read_text(encoding="utf-8"))
    municipality = _one_by_id(doc.get("municipalities"), municipality_id, "municipality")
    procedure = _one_by_id(doc.get("procedures"), service, "service")
    return _required_text(municipality, "name"), _required_text(procedure, "name")


def _one_by_id(items: object, target_id: str, label: str) -> dict:
    if not isinstance(items, list):
        raise TestCaseError(f"targets.jsonの{label}一覧が配列でない")
    matches = [item for item in items
               if isinstance(item, dict) and item.get("id") == target_id]
    if len(matches) != 1:
        raise TestCaseError(
            f"{label}は1件だけ必要: {target_id!r}（{len(matches)}件）")
    return matches[0]


def _required_text(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TestCaseError(f"{key}は空でない文字列が必要")
    return value.strip()

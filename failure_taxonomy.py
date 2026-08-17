"""失敗を8種の共通語彙へ変換するPure Function。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

TAXONOMY_VERSION = "1.0"

FAILURE_TYPES = (
    "fact_missing",
    "fact_ambiguous",
    "not_retrieved",
    "wrong_evidence",
    "wrong_answer",
    "page_not_discoverable",
    "structure_issue",
    "stale_information",
)

EVALUATOR_FAILURE_TYPES = frozenset({
    "wrong_evidence", "wrong_answer", "structure_issue", "stale_information",
})

LEGACY_FAILURE_REASON_MAP = {
    "記載なし": "fact_missing",
    "電話でのみ確認可": "fact_missing",
    "曖昧": "fact_ambiguous",
    "リンク先にあり": "not_retrieved",
    "PDF内のみ": "not_retrieved",
    "抽出エラー": "not_retrieved",
    "到達失敗": "page_not_discoverable",
}

LEGACY_EXPERIMENT_TYPE_MAP = {
    "target_page_unreachable_from_index": "page_not_discoverable",
}


def classify_failure_reason(reason: object) -> str:
    """抽出側の既存理由を共通分類へ変換する。未知語彙は推測しない。"""
    if not isinstance(reason, str) or not reason:
        raise ValueError(f"failure_reasonが空または文字列でない: {reason!r}")
    try:
        return LEGACY_FAILURE_REASON_MAP[reason]
    except KeyError as exc:
        raise ValueError(f"未定義のfailure_reason: {reason}") from exc


def classify_experiment_failure(value: object) -> str:
    """実験側の旧分類を共通分類へ変換する。共通分類はそのまま返す。"""
    if not isinstance(value, str) or not value:
        raise ValueError(f"実験failure typeが空または文字列でない: {value!r}")
    if value in FAILURE_TYPES:
        return value
    try:
        return LEGACY_EXPERIMENT_TYPE_MAP[value]
    except KeyError as exc:
        raise ValueError(f"未定義の実験failure type: {value}") from exc


def failure_type_for_result(found: object, reason: object) -> str | None:
    """found状態と既存理由から、矛盾のない共通分類を返す。"""
    if type(found) is not bool:
        raise ValueError(f"foundがbooleanでない: {found!r}")
    if found:
        if reason not in (None, ""):
            raise ValueError("found=trueでfailure_reasonが設定されている")
        return None
    return classify_failure_reason(reason)


def derive_failure_type(result: Mapping[str, object]) -> str | None:
    """抽出状態に加え、後段のEvidence Checkを含めて分類する。"""
    failure_type = failure_type_for_result(
        result.get("found"), result.get("failure_reason"))
    if failure_type is not None:
        return failure_type
    check = result.get("evidence_check")
    if check is not None:
        if not isinstance(check, Mapping):
            raise ValueError("evidence_checkがobjectでない")
        if check.get("verdict") == "missing":
            return "wrong_evidence"
    recorded = result.get("failure_type")
    if recorded is None:
        return None
    if recorded in EVALUATOR_FAILURE_TYPES:
        return recorded
    raise ValueError(f"抽出状態から導出できないfailure_type: {recorded!r}")


def annotate_result(result: Mapping[str, object]) -> dict[str, object]:
    """結果を変更せず複製し、導出したfailure_typeを付ける。"""
    failure_type = derive_failure_type(result)
    recorded = result.get("failure_type")
    promoted_by_evidence = recorded is None and failure_type == "wrong_evidence"
    if ("failure_type" in result and recorded != failure_type
            and not promoted_by_evidence):
        raise ValueError(
            "記録済みfailure_typeがfailure_reasonからの導出値と一致しない")
    return {**result, "failure_type": failure_type}


def empty_distribution() -> dict[str, int]:
    """0件の分類も省略しない分布を作る。"""
    return dict.fromkeys(FAILURE_TYPES, 0)


def count_failure_types(values: Iterable[str]) -> dict[str, int]:
    """共通分類を数える。未知の値は黙って追加しない。"""
    counts = empty_distribution()
    for value in values:
        if value not in counts:
            raise ValueError(f"未定義のfailure_type: {value}")
        counts[value] += 1
    return counts

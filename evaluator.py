"""回答・根拠・Ground Truth を4判定で評価するPure Function。"""

from __future__ import annotations

from collections.abc import Mapping

EVALUATOR_VERSION = "1.0"

CHECK_NAMES = (
    "answer_correct",
    "evidence_exists",
    "evidence_supports_answer",
    "ground_truth_matches",
)

CHECK_STATUSES = (
    "pass",
    "fail",
    "not_checked",
    "not_applicable",
)

VERIFIED_EVIDENCE = frozenset({"exact", "normalized"})
UNCERTAIN_EVIDENCE = frozenset({"partial", "too_short", "not_checked"})


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name}がbooleanでない: {value!r}")
    return value


def _optional_boolean(value: object, name: str) -> bool | None:
    if value is None:
        return None
    return _boolean(value, name)


def check(status: str, reason: str, method: str) -> dict[str, str]:
    """1判定のJSON契約を作る。"""
    if status not in CHECK_STATUSES:
        raise ValueError(f"未定義の判定状態: {status!r}")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("判定理由が空または文字列でない")
    if not isinstance(method, str) or not method.strip():
        raise ValueError("判定方法が空または文字列でない")
    return {"status": status, "reason": reason.strip(), "method": method.strip()}


def answer_correct(found: object, expected_found: object = None,
                   reached: object = True) -> dict[str, str]:
    """情報の有無について、AIの回答状態がGround Truthと一致するか。"""
    actual = _boolean(found, "found")
    page_reached = _boolean(reached, "reached")
    if not page_reached:
        return check("fail", "対象ページに到達していない", "reachability")
    expected = _optional_boolean(expected_found, "expected_found")
    if expected is None:
        return check("not_checked", "Ground Truthの情報有無が未登録", "ground_truth")
    if actual == expected:
        return check("pass", "foundがGround Truthの情報有無と一致", "ground_truth")
    return check("fail", "foundがGround Truthの情報有無と不一致", "ground_truth")


def evidence_exists(found: object, evidence_check: object = None) -> dict[str, str]:
    """引用全文が、そのTest Caseで渡した本文に実在するか。"""
    actual = _boolean(found, "found")
    if not actual:
        return check("not_applicable", "found=falseのため引用を要求しない", "text_match")
    if evidence_check is None:
        return check("not_checked", "Evidence Checkが未実施", "text_match")
    if not isinstance(evidence_check, Mapping):
        raise ValueError("evidence_checkがobjectでない")
    verdict = evidence_check.get("verdict")
    if verdict in VERIFIED_EVIDENCE:
        return check("pass", f"Evidence Checkが{verdict}", "text_match")
    if verdict == "missing":
        return check("fail", "引用全文が渡した本文に見当たらない", "text_match")
    if verdict in UNCERTAIN_EVIDENCE:
        return check("not_checked", f"Evidence Checkが{verdict}で全文未確認", "text_match")
    if verdict == "not_applicable":
        raise ValueError("found=trueでEvidence Checkがnot_applicable")
    raise ValueError(f"未定義のEvidence Check verdict: {verdict!r}")


def evidence_supports_answer(found: object, support: object = None) -> dict[str, str]:
    """引用の意味が回答を支えるか。supportは独立Evaluatorのyes/no。"""
    actual = _boolean(found, "found")
    if not actual:
        return check("not_applicable", "found=falseのため回答を支える引用を要求しない", "llm")
    if support is None:
        return check("not_checked", "Evidence支持判定が未実施", "llm")
    if support == "yes":
        return check("pass", "引用が回答を支える", "llm")
    if support == "no":
        return check("fail", "引用が回答を支えない", "llm")
    raise ValueError(f"Evidence支持判定がyes/noでない: {support!r}")


def _validated_elements(elements: object, required_count: int) -> list[Mapping[str, object]]:
    if type(required_count) is not int or required_count < 0:
        raise ValueError(f"required_countが0以上の整数でない: {required_count!r}")
    if not isinstance(elements, list):
        raise ValueError("elementsが配列でない")
    if len(elements) != required_count:
        raise ValueError(f"要素数が不一致: {len(elements)} != {required_count}")
    validated = []
    for index, element in enumerate(elements, start=1):
        if not isinstance(element, Mapping):
            raise ValueError(f"elements[{index - 1}]がobjectでない")
        if element.get("id") != index:
            raise ValueError(f"elements[{index - 1}].idが{index}でない")
        if element.get("covered") not in ("yes", "no"):
            raise ValueError(f"elements[{index - 1}].coveredがyes/noでない")
        validated.append(element)
    return validated


def ground_truth_matches(found: object, expected_found: object = None,
                         elements: object = None,
                         required_count: int = 0) -> dict[str, str]:
    """回答内容が、人手で固定した必須要素を満たすか。"""
    actual = _boolean(found, "found")
    expected = _optional_boolean(expected_found, "expected_found")
    if expected is None:
        return check("not_checked", "Ground Truthが未登録", "required_elements")
    if actual != expected:
        return check("fail", "foundがGround Truthの情報有無と不一致", "required_elements")
    if not expected:
        return check("pass", "情報が無いことがGround Truthと一致", "required_elements")
    if type(required_count) is not int or required_count < 0:
        raise ValueError(f"required_countが0以上の整数でない: {required_count!r}")
    if required_count == 0:
        if elements not in (None, []):
            raise ValueError("必須要素0件なのにelementsが記録されている")
        return check("not_checked", "Ground Truthの必須要素が未登録", "required_elements")
    if elements is None:
        return check("not_checked", "Ground Truth照合が未実施", "required_elements")
    validated = _validated_elements(elements, required_count)
    covered = sum(element["covered"] == "yes" for element in validated)
    if covered == required_count:
        return check("pass", f"必須要素{covered}/{required_count}件を満たす", "required_elements")
    return check("fail", f"必須要素{covered}/{required_count}件だけ満たす", "required_elements")


def overall_status(checks: object) -> str:
    """4判定を集約する。failを優先し、未判定をpassへ丸めない。"""
    if not isinstance(checks, Mapping):
        raise ValueError("checksがobjectでない")
    if set(checks) != set(CHECK_NAMES):
        raise ValueError("checksのキーが4判定と一致しない")
    statuses = []
    for name in CHECK_NAMES:
        result = checks[name]
        if not isinstance(result, Mapping):
            raise ValueError(f"checks.{name}がobjectでない")
        if set(result) != {"status", "reason", "method"}:
            raise ValueError(f"checks.{name}のキーが契約と一致しない")
        status = result.get("status")
        if status not in CHECK_STATUSES:
            raise ValueError(f"checks.{name}.statusが未定義: {status!r}")
        if not isinstance(result.get("reason"), str) or not result["reason"].strip():
            raise ValueError(f"checks.{name}.reasonが空または文字列でない")
        if not isinstance(result.get("method"), str) or not result["method"].strip():
            raise ValueError(f"checks.{name}.methodが空または文字列でない")
        statuses.append(status)
    if "fail" in statuses:
        return "fail"
    if "not_checked" in statuses:
        return "not_checked"
    if "pass" not in statuses:
        return "not_checked"
    return "pass"


def points_for(status: str, maximum: int = 20) -> int | None:
    """検証済みだけを点へ変換する。"""
    if type(maximum) is not int or maximum <= 0:
        raise ValueError(f"maximumが正整数でない: {maximum!r}")
    if status == "pass":
        return maximum
    if status == "fail":
        return 0
    if status == "not_checked":
        return None
    raise ValueError(f"overallに使えない状態: {status!r}")


def evaluate_item(item: object, *, expected_found: object = None,
                  support: object = None, elements: object = None,
                  required_count: int = 0,
                  reached: object = True) -> dict[str, object]:
    """1 fact_typeの4判定を作る。入力を変更しない。"""
    if not isinstance(item, Mapping):
        raise ValueError("itemがobjectでない")
    found = item.get("found")
    results = {
        "answer_correct": answer_correct(found, expected_found, reached),
        "evidence_exists": evidence_exists(found, item.get("evidence_check")),
        "evidence_supports_answer": evidence_supports_answer(found, support),
        "ground_truth_matches": ground_truth_matches(
            found, expected_found, elements, required_count),
    }
    overall = overall_status(results)
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "checks": results,
        "overall": overall,
        "points": points_for(overall),
    }


def evaluation_from_item(item: object) -> dict[str, object]:
    """記録済みevaluationを厳格に読み、欠落時は未検証を作る。"""
    if not isinstance(item, Mapping):
        raise ValueError("itemがobjectでない")
    found = _boolean(item.get("found"), "found")
    recorded = item.get("evaluation")
    if recorded is None:
        return evaluate_item(item)
    if not isinstance(recorded, Mapping):
        raise ValueError("evaluationがobjectでない")
    if set(recorded) != {"evaluator_version", "checks", "overall", "points"}:
        raise ValueError("evaluationのキーが契約と一致しない")
    if recorded.get("evaluator_version") != EVALUATOR_VERSION:
        raise ValueError("evaluationのversionが不一致")
    overall = overall_status(recorded.get("checks"))
    if recorded.get("overall") != overall:
        raise ValueError("evaluation.overallが4判定からの導出値と不一致")
    points = points_for(overall)
    if recorded.get("points") != points:
        raise ValueError("evaluation.pointsがoverallからの導出値と不一致")
    checks = recorded["checks"]
    evidence_statuses = (
        checks["evidence_exists"]["status"],
        checks["evidence_supports_answer"]["status"],
    )
    if found and "not_applicable" in evidence_statuses:
        raise ValueError("found=trueなのにEvidence判定がnot_applicable")
    if not found and evidence_statuses != ("not_applicable", "not_applicable"):
        raise ValueError("found=falseなのにEvidence判定がnot_applicableでない")
    return dict(recorded)

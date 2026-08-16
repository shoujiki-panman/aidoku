"""1つのAI段差について、直す前と直した後を同じ条件で測る。

本測定と違うのはHTMLが手元の再現ページである点だけ。prompt組み立てと
Test Case契約はextractorから借り、1回のLLM呼び出しへ1 fact_typeだけを渡す。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))

from htmlutil import parse  # noqa: E402
from fact_types import EXTRACTOR_KEYS  # noqa: E402
from failure_taxonomy import classify_experiment_failure  # noqa: E402
from measurement_cases import TestCase, test_cases_for  # noqa: E402
from extractor.fact_extract import (  # noqa: E402
    allowed_sources, call_claude, compose_input, validated_attempt,
)
from extractor.response_contract import parse_json_reply, requested_urls  # noqa: E402
from extractor.result_contract import failed_test_cases, legacy_items  # noqa: E402

MEASUREMENT_VERSION = "exp-0.2"
MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class ExperimentPrompt:
    test_case: TestCase
    prompt: str
    allowed_urls: frozenset[str]
    sources: frozenset[str]


def build_prompts(html: str, url: str, muni: str, proc: str,
                  cases: list[TestCase]) -> tuple[list[ExperimentPrompt], dict]:
    """同じHTMLから、fact_typeを混ぜない本測定と同形のpromptを作る。"""
    normalized = parse(html, url)
    prompts, common_meta = [], None
    for test_case in cases:
        prompt, meta, urls = compose_input(
            {"url": url}, muni, proc, test_case,
            normalized.links, normalized.text, normalized.jsonld)
        common_meta = common_meta or meta
        prompts.append(ExperimentPrompt(
            test_case, prompt, frozenset(urls), allowed_sources(meta)))
    if not prompts:
        raise ValueError("Test Caseが0件")
    return prompts, common_meta or {}


def run_trial(prompts: list[ExperimentPrompt], model: str) -> dict:
    """1 trial内で各fact_typeを別々に呼び、旧itemsも同じ結果から作る。"""
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records, errors = [], []
    for definition in prompts:
        current = definition.test_case
        try:
            data = parse_json_reply(call_claude(definition.prompt, model))
            urls = requested_urls(data, set(definition.allowed_urls), max_urls=2)
            attempt = validated_attempt(
                data, definition.sources, "initial", urls)
            records.append({
                **asdict(current),
                "result": attempt["result"],
                "attempts": [attempt],
                "followed_urls": [],
                "page_notes": attempt["page_notes"],
            })
        except Exception as exc:  # 項目単位の失敗も残し、残りの項目は測る
            error = (
                f"{current.service}/{current.fact_type}: "
                f"{type(exc).__name__}: {exc}")[:300]
            failed = failed_test_cases([current], "抽出エラー")[0]
            failed["attempts"] = [{
                "stage": "initial", "llm_called": True,
                "result": failed["result"],
                "requested_urls": [], "page_notes": "", "error": error,
            }]
            failed["error"] = error
            records.append(failed)
            errors.append(error)
    result = {
        "ok": not errors, "started_at": started,
        "test_cases": records, "items": legacy_items(records),
    }
    if errors:
        result["error"] = "; ".join(errors)[:300]
    return result


def check(items: dict, truth: dict) -> dict:
    """Ground Truthの期待文字列が抽出値にすべて含まれるかを見る。"""
    out = {}
    for field in EXTRACTOR_KEYS:
        got = items.get(field) or {}
        expected = truth.get(field) or {}
        must_include = expected.get("must_include") or []
        value = got.get("value") or ""
        out[field] = {
            "found": bool(got.get("found")),
            "value": value[:200],
            "matches_truth": bool(got.get("found")) and all(
                text in value for text in must_include),
            "must_include": must_include,
        }
    return out


def normalized_failure(case: dict) -> dict:
    """caseの旧分類を残したまま共通failure_typeを付ける。"""
    failure = case.get("failure")
    if not isinstance(failure, dict):
        raise ValueError("case.failureがobjectでない")
    return {
        **failure,
        "failure_type": classify_experiment_failure(failure.get("type")),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="setagaya-tennyu",
                        help="experiment/cases/ の下の名前")
    parser.add_argument("--variant", action="append",
                        help="測る版（省略時はcase.jsonの全部）")
    parser.add_argument("--trials", "-n", type=int, default=5)
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args(argv)
    if args.trials < 1:
        parser.error("--trialsは1以上にする")

    case_dir = HERE / "cases" / args.case
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    variants = args.variant or [variant["id"] for variant in case["variants"]]
    cases = test_cases_for(case["service"], case["municipality"])

    out_dir = HERE / "out"
    out_dir.mkdir(exist_ok=True)
    results = []
    for variant_id in variants:
        variant = next(item for item in case["variants"] if item["id"] == variant_id)
        html = (case_dir / variant["file"]).read_text(encoding="utf-8")
        prompts, meta = build_prompts(
            html, case["page_url"], case["municipality"], case["procedure"], cases)
        truth = {**case["ground_truth"], **(
            variant.get("ground_truth_override") or {})}

        print(f"[{variant_id}] {variant['label']} — {args.trials}回", flush=True)
        trials = []
        for index in range(args.trials):
            trial = run_trial(prompts, args.model)
            if trial["ok"]:
                trial["check"] = check(trial["items"], truth)
                matched = sum(
                    1 for field in EXTRACTOR_KEYS
                    if trial["check"][field]["matches_truth"])
                print(f"    {index + 1}回目: {matched}/4 一致", flush=True)
            else:
                print(f"    {index + 1}回目: 失敗 {trial['error'][:60]}", flush=True)
            trials.append(trial)

        succeeded = [trial for trial in trials if trial["ok"]]
        per_field = {
            field: sum(1 for trial in succeeded
                       if trial["check"][field]["matches_truth"])
            for field in EXTRACTOR_KEYS
        }
        results.append({
            "variant": variant_id, "label": variant["label"],
            "intervention": variant.get("intervention"),
            "page_meta": meta, "trials": trials,
            "summary": {
                "trials": args.trials, "succeeded_runs": len(succeeded),
                "per_field_matches": per_field,
                "all_four": sum(
                    1 for trial in succeeded if all(
                        trial["check"][field]["matches_truth"]
                        for field in EXTRACTOR_KEYS)),
            },
        })
        summary = results[-1]["summary"]
        print(
            f"    → 4項目そろった回: {summary['all_four']}/{args.trials}   "
            f"項目別 {per_field}\n", flush=True)

    doc = {
        "case": args.case,
        "measurement_version": MEASUREMENT_VERSION,
        "test_case_version": cases[0].test_case_version,
        "model": args.model,
        "trials_per_variant": args.trials,
        "llm_calls_per_trial": len(cases),
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "page_url": case["page_url"],
        "site_version": case.get("site_version"),
        "ground_truth_source": case.get("ground_truth_source"),
        "failure": normalized_failure(case),
        "results": results,
    }
    output = out_dir / f"{args.case}_{doc['run_at'][:10]}.json"
    output.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {output}")


if __name__ == "__main__":
    main()

"""既存の抽出・実験結果をFailure Taxonomyへ再分類して集計する。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from failure_taxonomy import (  # noqa: E402
    EVALUATOR_FAILURE_TYPES,
    FAILURE_TYPES,
    TAXONOMY_VERSION,
    classify_experiment_failure,
    classify_failure_reason,
    count_failure_types,
    derive_failure_type,
)


def load_json_object(path: Path) -> dict:
    """path付きのエラーでJSON objectを読む。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: JSONを読めない: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSONのrootがobjectでない")
    return value


def summarize_extractor(paths: list[Path]) -> dict:
    """抽出結果を、項目失敗と実行失敗を混ぜずに集計する。"""
    failure_types: list[str] = []
    run_failure_types: list[str] = []
    legacy_reasons: Counter[str] = Counter()
    legacy_contract_anomalies: list[dict[str, object]] = []
    fact_results = 0
    reached_runs = 0
    unreached_runs = 0

    for path in paths:
        result = load_json_object(path)
        reached = result.get("reached")
        if type(reached) is not bool:
            raise ValueError(f"{path}: reachedがbooleanでない")
        if not reached:
            unreached_runs += 1
            reason = result.get("error") or "到達失敗"
            failure_type = classify_failure_reason(reason)
            _verify_recorded_type(path, result, failure_type)
            run_failure_types.append(failure_type)
            continue

        reached_runs += 1
        items = result.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"{path}: itemsがobjectでない")
        fact_results += len(items)
        for key, item in items.items():
            if not isinstance(item, dict):
                raise ValueError(f"{path}: items.{key}がobjectでない")
            found = item.get("found")
            reason = item.get("failure_reason")
            if type(found) is not bool:
                raise ValueError(f"{path}: items.{key}.foundがbooleanでない")
            if found and reason not in (None, ""):
                legacy_contract_anomalies.append({
                    "source": path.name,
                    "location": f"items.{key}",
                    "found": found,
                    "failure_reason": reason,
                })
                failure_type = None
            else:
                failure_type = derive_failure_type(item)
            _verify_recorded_type(path, item, failure_type, f"items.{key}")
            if failure_type is None:
                continue
            if isinstance(reason, str) and reason:
                legacy_reasons[reason] += 1
            elif failure_type not in EVALUATOR_FAILURE_TYPES:
                raise ValueError(f"{path}: items.{key}.failure_reasonが文字列でない")
            failure_types.append(failure_type)

    return {
        "source_files": len(paths),
        "reached_runs": reached_runs,
        "unreached_runs": unreached_runs,
        "fact_results_in_reached_runs": fact_results,
        "fact_failures": len(failure_types),
        "fact_failure_distribution": count_failure_types(failure_types),
        "legacy_reason_distribution": _sorted_counter(legacy_reasons),
        "legacy_contract_anomalies": legacy_contract_anomalies,
        "legacy_contract_anomaly_count": len(legacy_contract_anomalies),
        "run_failures": len(run_failure_types),
        "run_failure_distribution": count_failure_types(run_failure_types),
    }


def summarize_experiment_cases(paths: list[Path]) -> dict:
    """実験ケースに人が記録した段差を集計する。"""
    failure_types: list[str] = []
    legacy_types: Counter[str] = Counter()
    for path in paths:
        case = load_json_object(path)
        failure = case.get("failure")
        if not isinstance(failure, dict):
            raise ValueError(f"{path}: failureがobjectでない")
        legacy_type = failure.get("type")
        failure_type = classify_experiment_failure(legacy_type)
        _verify_recorded_type(path, failure, failure_type, "failure")
        if not isinstance(legacy_type, str):
            raise ValueError(f"{path}: failure.typeが文字列でない")
        legacy_types[legacy_type] += 1
        failure_types.append(failure_type)
    return {
        "source_files": len(paths),
        "failure_events": len(failure_types),
        "failure_distribution": count_failure_types(failure_types),
        "legacy_type_distribution": _sorted_counter(legacy_types),
    }


def summarize_experiment_trials(paths: list[Path]) -> dict:
    """反復実験の各trial × fact_typeを集計する。"""
    failure_types: list[str] = []
    legacy_reasons: Counter[str] = Counter()
    fact_results = 0
    trials = 0
    for path in paths:
        document = load_json_object(path)
        result_groups = document.get("results")
        if not isinstance(result_groups, list):
            raise ValueError(f"{path}: resultsが配列でない")
        for group_index, group in enumerate(result_groups):
            if not isinstance(group, dict) or not isinstance(group.get("trials"), list):
                raise ValueError(f"{path}: results[{group_index}].trialsが配列でない")
            for trial_index, trial in enumerate(group["trials"]):
                if not isinstance(trial, dict) or not isinstance(trial.get("items"), dict):
                    raise ValueError(
                        f"{path}: results[{group_index}].trials[{trial_index}].items"
                        "がobjectでない")
                trials += 1
                fact_results += len(trial["items"])
                for key, item in trial["items"].items():
                    if not isinstance(item, dict):
                        raise ValueError(f"{path}: trial items.{key}がobjectでない")
                    failure_type = derive_failure_type(item)
                    _verify_recorded_type(path, item, failure_type, f"trial items.{key}")
                    if failure_type is None:
                        continue
                    reason = item.get("failure_reason")
                    if isinstance(reason, str) and reason:
                        legacy_reasons[reason] += 1
                    elif failure_type not in EVALUATOR_FAILURE_TYPES:
                        raise ValueError(
                            f"{path}: trial items.{key}.failure_reasonが文字列でない")
                    failure_types.append(failure_type)
    return {
        "source_files": len(paths),
        "trials": trials,
        "fact_results": fact_results,
        "fact_failures": len(failure_types),
        "fact_failure_distribution": count_failure_types(failure_types),
        "legacy_reason_distribution": _sorted_counter(legacy_reasons),
    }


def build_summary(extractor_paths: list[Path], case_paths: list[Path],
                  experiment_paths: list[Path]) -> dict:
    """異なる分母を別オブジェクトに保った決定的な集計を作る。"""
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "failure_types": list(FAILURE_TYPES),
        "units_are_not_additive": True,
        "extractor": summarize_extractor(extractor_paths),
        "experiment_cases": summarize_experiment_cases(case_paths),
        "experiment_trials": summarize_experiment_trials(experiment_paths),
    }


def ensure_output_is_distinct(output: Path, input_paths: list[Path]) -> None:
    """派生集計で一次データを上書きしない。symlinkも実体で比較する。"""
    resolved_output = output.resolve()
    collisions = [path for path in input_paths if path.resolve() == resolved_output]
    if collisions:
        raise ValueError(f"出力先が入力JSONと同じ: {collisions[0]}")


def _verify_recorded_type(path: Path, record: dict,
                          derived: str | None, location: str = "root") -> None:
    if "failure_type" in record and record["failure_type"] != derived:
        raise ValueError(
            f"{path}: {location}.failure_typeが導出値と一致しない: "
            f"{record['failure_type']!r} != {derived!r}")


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractor-dir", type=Path, default=ROOT / "extractor" / "out")
    parser.add_argument("--case-dir", type=Path, default=ROOT / "experiment" / "cases")
    parser.add_argument(
        "--experiment-out-dir", type=Path, default=ROOT / "experiment" / "out")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "analysis" / "out" / "failure-taxonomy-summary.json")
    args = parser.parse_args(argv)

    extractor_paths = sorted(args.extractor_dir.glob("extract_*.json"))
    case_paths = sorted(args.case_dir.glob("*/case.json"))
    experiment_paths = sorted(args.experiment_out_dir.glob("*.json"))
    if not extractor_paths or not case_paths or not experiment_paths:
        parser.error(
            "集計元が0件: extractor/cases/experiment-outの各入力を確認する")
    all_inputs = [*extractor_paths, *case_paths, *experiment_paths]
    try:
        ensure_output_is_distinct(args.output, all_inputs)
    except ValueError as exc:
        parser.error(str(exc))

    summary = build_summary(extractor_paths, case_paths, experiment_paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {args.output}")


if __name__ == "__main__":
    main()

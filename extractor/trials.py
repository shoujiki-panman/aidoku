"""複数回の抽出結果を、元の1回分を壊さず集約するPure Function。"""

from __future__ import annotations

from collections.abc import Sequence

from fact_types import EXTRACTOR_KEYS


def positive_trial_count(value: object) -> int:
    """試行回数を検証する。boolは整数として受理しない。"""
    if type(value) is not int or value < 1:
        raise ValueError("trialsは1以上の整数にする")
    return value


def aggregate_trials(results: Sequence[dict]) -> dict:
    """1回分の結果を番号付きで保持し、項目ごとの成功率を付ける。"""
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        raise ValueError("試行結果は配列にする")
    if not results:
        raise ValueError("試行結果が0件")
    if any(not isinstance(result, dict) for result in results):
        raise ValueError("各試行結果はobjectにする")
    numbered = [
        {**result, "run_number": run_number}
        for run_number, result in enumerate(results, start=1)
    ]
    return {
        **results[-1],
        "trial_count": len(numbered),
        "success_rate": success_rates(numbered),
        "trials": numbered,
    }


def success_rates(trials: Sequence[dict]) -> dict[str, dict[str, int | float]]:
    """各項目のfound=true回数を、同じ分母で数える。"""
    if (not isinstance(trials, Sequence)
            or isinstance(trials, (str, bytes)) or not trials):
        raise ValueError("成功率を計算する試行が0件")
    if any(not isinstance(trial, dict) for trial in trials):
        raise ValueError("成功率を計算する各試行はobjectにする")
    rates = {}
    for key in EXTRACTOR_KEYS:
        found = [_found_value(trial, key, index)
                 for index, trial in enumerate(trials, start=1)]
        successful = sum(found)
        total = len(found)
        rates[key] = {
            "successful_runs": successful,
            "total_runs": total,
            "rate": round(successful / total, 4),
        }
    return rates


def _found_value(trial: dict, key: str, run_number: int) -> bool:
    items = trial.get("items")
    if not isinstance(items, dict):
        raise ValueError(f"run {run_number}: itemsがobjectでない")
    item = items.get(key)
    if not isinstance(item, dict) or type(item.get("found")) is not bool:
        raise ValueError(f"run {run_number}: items.{key}.foundがbooleanでない")
    return item["found"]

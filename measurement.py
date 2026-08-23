"""測定条件を記録し、条件の違う結果が混ざるのを防ぐ。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

MEASUREMENT_VERSION = "aidoku-1.0"

CONDITION_KEYS = (
    "measurement_version",
    "prompt_version",
    "follow",
    "max_follow",
    "max_depth",
    "beam",
    "max_fetches",
    "max_text_chars",
    "max_links",
    "link_order",
    "model",
    "model_version",
)
RUN_KEYS = ("run_at", "discovery_run_at")
MEASUREMENT_KEYS = CONDITION_KEYS + RUN_KEYS
POSITIVE_INT_KEYS = (
    "max_follow",
    "max_depth",
    "max_fetches",
    "max_text_chars",
    "max_links",
)
STRING_KEYS = (
    "measurement_version",
    "link_order",
    "prompt_version",
    "model",
    "model_version",
    "run_at",
    "discovery_run_at",
)


class MeasurementError(ValueError):
    """測定条件が無い、壊れている、または揃っていない。"""


def is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp_error(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return "空または文字列でない"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "ISO 8601形式でない"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "タイムゾーンがない"
    return None


def prompt_version_error(value: object) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return "sha256: に続く64桁の16進数でない"
    return None


def prompt_version(paths: Sequence[Path]) -> str:
    """複数プロンプトの内容から、更新漏れしない版を作る。"""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def beam_value(beam: dict[int, tuple[int, int]]) -> dict[str, dict[str, int]]:
    return {
        str(depth): {"parents": parents, "links": links}
        for depth, (parents, links) in sorted(beam.items())
    }


def discovery_beam_error(value: object, max_depth: int) -> str | None:
    if not isinstance(value, dict):
        return "beam がオブジェクトでない"
    if any(not isinstance(depth, int) or isinstance(depth, bool) for depth in value):
        return "beam の深さが整数でない"
    if set(value) != set(range(1, max_depth + 1)):
        return "beam の深さが max_depth と一致しない"
    for depth, setting in value.items():
        if not isinstance(setting, tuple) or len(setting) != 2:
            return f"beam[{depth}] が2要素のtupleでない"
        if not is_positive_int(setting[0]) or not is_positive_int(setting[1]):
            return f"beam[{depth}] の値が正の整数でない"
    return None


def beam_error(value: object, max_depth: object) -> str | None:
    if not isinstance(value, dict) or not value or not is_positive_int(max_depth):
        return "beam がオブジェクトでない、または空"
    if set(value) != {str(depth) for depth in range(1, max_depth + 1)}:
        return "beam の深さが max_depth と一致しない"
    for depth, setting in value.items():
        if not isinstance(setting, dict) or set(setting) != {"parents", "links"}:
            return f"beam[{depth}] の形が不正"
        if not is_positive_int(setting["parents"]) or not is_positive_int(setting["links"]):
            return f"beam[{depth}] の値が正の整数でない"
    return None


def build_discovery_measurement(max_depth: int, beam: dict[int, tuple[int, int]],
                                max_fetches: int, run_at: str) -> dict:
    if not is_positive_int(max_depth) or not is_positive_int(max_fetches):
        raise MeasurementError("探索条件の上限値が正の整数でない")
    error = discovery_beam_error(beam, max_depth)
    if error:
        raise MeasurementError("探索条件の " + error)
    measurement = {
        "recording_status": "recorded",
        "measurement_version": MEASUREMENT_VERSION,
        "max_depth": max_depth,
        "beam": beam_value(beam),
        "max_fetches": max_fetches,
        "run_at": run_at,
    }
    error = timestamp_error(run_at)
    if error:
        raise MeasurementError("探索条件の run_at が" + error)
    return measurement


def require_discovery_measurement(value: object) -> dict:
    if not isinstance(value, dict) or value.get("recording_status") != "recorded":
        raise MeasurementError(
            "探索条件が記録されていない。crawler/discover.py をやり直す"
        )
    required = ("measurement_version", "max_depth", "beam", "max_fetches", "run_at")
    missing = [key for key in required if value.get(key) is None]
    if missing:
        raise MeasurementError("探索条件が不足している: " + ", ".join(missing))
    if value["measurement_version"] != MEASUREMENT_VERSION:
        raise MeasurementError("探索結果の measurement_version が現在の抽出器と違う")
    if not is_positive_int(value["max_depth"]) or not is_positive_int(value["max_fetches"]):
        raise MeasurementError("探索条件の上限値が正の整数でない")
    error = beam_error(value["beam"], value["max_depth"])
    if error:
        raise MeasurementError("探索条件の " + error)
    error = timestamp_error(value["run_at"])
    if error:
        raise MeasurementError("探索条件の run_at が" + error)
    return value


def build_measurement(discovery: object, *, prompt: str, follow: bool,
                      max_follow: int, max_text_chars: int, max_links: int,
                      link_order: str, model_version: str, run_at: str) -> dict:
    """探索時の実測値と抽出時の設定を1つの記録へまとめる。"""
    source = require_discovery_measurement(discovery)
    measurement = {
        "recording_status": "recorded",
        "measurement_version": MEASUREMENT_VERSION,
        "prompt_version": prompt,
        "follow": follow,
        "max_follow": max_follow,
        "max_depth": source["max_depth"],
        "beam": source["beam"],
        "max_fetches": source["max_fetches"],
        "max_text_chars": max_text_chars,
        "max_links": max_links,
        "link_order": link_order,
        "model": "claude-cli",
        "model_version": model_version,
        "run_at": run_at,
        "discovery_run_at": source["run_at"],
    }
    error = recorded_error(measurement)
    if error:
        raise MeasurementError(error)
    return measurement


def legacy_measurement(model_version: object = None) -> dict:
    """記録開始前の出力を、値を捏造せず明示する。"""
    measurement = dict.fromkeys(MEASUREMENT_KEYS)
    measurement["recording_status"] = "legacy_unknown"
    if isinstance(model_version, str) and model_version:
        measurement["model"] = "claude-cli"
        measurement["model_version"] = model_version
    return measurement


def recorded_error(measurement: dict) -> str | None:
    missing = [key for key in MEASUREMENT_KEYS if key not in measurement]
    if missing:
        return "測定条件が不足している: " + ", ".join(missing)
    if any(not isinstance(measurement[key], str) or not measurement[key]
           for key in STRING_KEYS):
        return "測定条件の文字列項目が空または不正"
    error = prompt_version_error(measurement["prompt_version"])
    if error:
        return "prompt_version が" + error
    for key in RUN_KEYS:
        error = timestamp_error(measurement[key])
        if error:
            return f"{key} が{error}"
    if measurement["follow"] is not True and measurement["follow"] is not False:
        return "follow が真偽値でない"
    if any(not is_positive_int(measurement[key]) for key in POSITIVE_INT_KEYS):
        return "測定条件の上限値が正の整数でない"
    error = beam_error(measurement["beam"], measurement["max_depth"])
    if error:
        return error
    return None


def normalize_measurement(value: object, model_version: object = None) -> dict:
    if value is None:
        return legacy_measurement(model_version)
    if not isinstance(value, dict):
        raise MeasurementError("measurement がオブジェクトでない")
    status = value.get("recording_status")
    if status == "legacy_unknown":
        return legacy_measurement(value.get("model_version") or model_version)
    if status != "recorded":
        raise MeasurementError("measurement.recording_status が不正")
    error = recorded_error(value)
    if error:
        raise MeasurementError(error)
    return {"recording_status": "recorded", **{key: value[key] for key in MEASUREMENT_KEYS}}


def changed_conditions(first: dict, other: dict) -> list[str]:
    return [key for key in CONDITION_KEYS if first[key] != other[key]]


def summarize_measurements(measurements: Sequence[dict]) -> dict:
    """公開データの条件をまとめ、違う条件や新旧混在を拒否する。"""
    if not measurements:
        raise MeasurementError("測定結果が1件もない")
    statuses = {measurement["recording_status"] for measurement in measurements}
    if statuses == {"legacy_unknown"}:
        summary = legacy_measurement()
        summary["comparison_status"] = "legacy_unknown"
        summary["run_at"] = []
        summary["discovery_run_at"] = []
        return summary
    if statuses != {"recorded"}:
        raise MeasurementError(
            "条件記録のある結果と legacy_unknown を混ぜられない"
        )

    first = measurements[0]
    changed = sorted({key for measurement in measurements[1:]
                      for key in changed_conditions(first, measurement)})
    if changed:
        raise MeasurementError("測定条件が揃っていない: " + ", ".join(changed))

    summary = {"recording_status": "recorded", "comparison_status": "compatible"}
    summary.update({key: first[key] for key in CONDITION_KEYS})
    summary["run_at"] = sorted({measurement["run_at"] for measurement in measurements})
    summary["discovery_run_at"] = sorted(
        {measurement["discovery_run_at"] for measurement in measurements}
    )
    return summary


def measurement_signature(measurement: dict) -> str:
    """外部ツールでも同じ条件を比較できる安定した文字列を返す。"""
    conditions = {key: measurement[key] for key in CONDITION_KEYS}
    return json.dumps(conditions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

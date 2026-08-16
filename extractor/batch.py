"""extract batchの入力検証と、build/stage失敗で旧出力を壊さない書き込み。"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from measurement_cases import TestCase, target_identity, test_cases_for

ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")


@dataclass(frozen=True)
class ExtractionJob:
    discovery: dict
    cases: tuple[TestCase, ...]
    output: Path


def load_jobs(files: list[Path], procedure: str, out_dir: Path) -> list[ExtractionJob]:
    """全入力と出力先をLLM呼び出し・write前に検証する。"""
    jobs, outputs = [], set()
    for path in files:
        try:
            discovery = json.loads(path.read_text(encoding="utf-8"))
            _validate_discovery(discovery, path, procedure)
            _validate_identity(discovery)
            cases = tuple(test_cases_for(
                discovery["procedure_id"], discovery["municipality"]))
        except Exception as exc:
            raise ValueError(f"探索結果が不正: {path}: {exc}") from exc
        output = out_dir / (
            f"extract_{discovery['municipality_id']}_{discovery['procedure_id']}.json")
        if output in outputs:
            raise ValueError(f"出力先が重複している: {output}")
        outputs.add(output)
        jobs.append(ExtractionJob(discovery, cases, output))
    return jobs


def _validate_identity(discovery: dict) -> None:
    canonical_muni, canonical_proc = target_identity(
        discovery["municipality_id"], discovery["procedure_id"])
    if discovery["municipality"] != canonical_muni:
        raise ValueError(
            f"municipality名とIDが違う: {discovery['municipality']} != {canonical_muni}")
    if discovery["procedure"] != canonical_proc:
        raise ValueError(
            f"procedure名とIDが違う: {discovery['procedure']} != {canonical_proc}")


def _validate_discovery(discovery: object, path: Path, procedure: str) -> None:
    if not isinstance(discovery, dict):
        raise ValueError("rootはobjectにする")
    for key in ("municipality", "municipality_id", "procedure", "procedure_id"):
        value = discovery.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key}は空でない文字列にする")
    for key in ("municipality_id", "procedure_id"):
        if not ID_PATTERN.fullmatch(discovery[key]):
            raise ValueError(f"{key}が不正: {discovery[key]!r}")
    if discovery["procedure_id"] != procedure:
        raise ValueError(
            f"指定procedureと埋込IDが違う: {procedure} != {discovery['procedure_id']}")
    expected = (
        f"discovery_{discovery['municipality_id']}_{discovery['procedure_id']}.json")
    if path.name != expected:
        raise ValueError(f"ファイル名と埋込IDが違う: {path.name} != {expected}")
    candidates = discovery.get("candidates")
    if not isinstance(candidates, list) or any(
            not isinstance(candidate, dict) for candidate in candidates):
        raise ValueError("candidatesはobjectの配列にする")
    for index, candidate in enumerate(candidates):
        try:
            _validate_candidate(candidate)
        except ValueError as exc:
            raise ValueError(f"candidates[{index}]: {exc}") from exc


def _validate_candidate(candidate: dict) -> None:
    url = candidate.get("url")
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        hostname = parts.hostname if parts is not None else None
        if parts is not None:
            parts.port
    except ValueError as exc:
        raise ValueError(f"urlが不正: {url!r}") from exc
    if (parts is None or parts.scheme not in {"http", "https"}
            or not hostname or any(char.isspace() for char in url)):
        raise ValueError(f"urlが不正: {url!r}")
    status = candidate.get("status")
    if type(status) is not int or not (status == 0 or 100 <= status <= 599):
        raise ValueError(f"statusが不正: {status!r}")
    if type(candidate.get("is_pdf")) is not bool:
        raise ValueError(f"is_pdfが不正: {candidate.get('is_pdf')!r}")
    for key in ("text_len", "hops"):
        value = candidate.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"{key}が不正: {value!r}")
    if not isinstance(candidate.get("link_text"), str):
        raise ValueError(f"link_textが不正: {candidate.get('link_text')!r}")


def build_batch(jobs: list[ExtractionJob],
                build_result: Callable[[ExtractionJob], dict],
                ) -> list[tuple[ExtractionJob, dict, str]]:
    """全件を構築・JSON化し、途中失敗時に既存出力へ触れない。"""
    batch = []
    for job in jobs:
        result = build_result(job)
        serialized = json.dumps(result, ensure_ascii=False, indent=2)
        batch.append((job, result, serialized))
    return batch


def write_batch(batch: list[tuple[ExtractionJob, dict, str]]) -> None:
    """全payloadと旧版backupをstageし、置換失敗時は旧版へ戻す。"""
    staged: list[tuple[Path, Path]] = []
    backups: dict[Path, Path | None] = {}
    replaced: list[Path] = []
    preserved: set[Path] = set()
    try:
        for job, _result, serialized in batch:
            job.output.parent.mkdir(parents=True, exist_ok=True)
            staged.append((_stage_payload(job.output, serialized), job.output))
        for _temporary, output in staged:
            backups[output] = _stage_existing(output) if output.exists() else None
        for temporary, output in staged:
            _replace_staged(temporary, output)
            replaced.append(output)
    except Exception as write_error:
        errors, preserved = _rollback(replaced, backups)
        if errors:
            paths = ", ".join(str(path) for path in sorted(preserved))
            raise RuntimeError(
                f"出力rollbackに失敗。手動復旧用backup: {paths}; "
                f"詳細: {'; '.join(errors)}") from write_error
        raise
    finally:
        for temporary, _output in staged:
            temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None and backup not in preserved:
                backup.unlink(missing_ok=True)


def _stage_payload(output: Path, payload: str) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=output.parent,
                prefix=f".{output.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        if output.exists():
            shutil.copymode(output, temporary)
        else:
            temporary.chmod(_default_file_mode())
        return temporary
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _stage_existing(output: Path) -> Path:
    with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=f".{output.name}.", suffix=".bak",
            delete=False) as handle:
        backup = Path(handle.name)
    try:
        shutil.copyfile(output, backup)
        shutil.copymode(output, backup)
        return backup
    except Exception:
        backup.unlink(missing_ok=True)
        raise


def _replace_staged(temporary: Path, output: Path) -> None:
    temporary.replace(output)


def _restore_backup(backup: Path, output: Path) -> None:
    backup.replace(output)


def _rollback(replaced: list[Path], backups: dict[Path, Path | None],
              ) -> tuple[list[str], set[Path]]:
    errors, preserved = [], set()
    for output in reversed(replaced):
        try:
            backup = backups[output]
            if backup is None:
                output.unlink(missing_ok=True)
            else:
                _restore_backup(backup, output)
        except Exception as exc:
            errors.append(f"{output}: {exc}")
            if backup is not None:
                preserved.add(backup)
    return errors, preserved


def _default_file_mode() -> int:
    current_umask = os.umask(0)
    os.umask(current_umask)
    return 0o666 & ~current_umask

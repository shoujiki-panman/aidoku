"""既存の extractor 出力へ、キャッシュだけを使って evidence check を適用する。

元の ``extractor/out/*.json`` は上書きしない。照合済みコピーと全体集計を生成する。
キャッシュが1ページでも欠ける場合は、誤って missing と断定せず not_checked にする。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "crawler"))

from evidence_check import (  # noqa: E402
    MAX_TEXT_CHARS_PER_PAGE,
    attach_item_check,
    attach_checks_across_pages,
    summarize,
    truncate_page_text,
)
from htmlutil import parse  # noqa: E402
from polite_fetch import CACHE_DIR, PoliteFetcher  # noqa: E402

DEFAULT_EXTRACT_DIR = ROOT / "extractor" / "out"
DEFAULT_OUT_DIR = Path(__file__).parent / "out" / "evidence-checked"
DEFAULT_SUMMARY = Path(__file__).parent / "out" / "evidence-check-summary.json"


class InvalidInput(ValueError):
    """既存出力の形が照合に必要な契約を満たさない。"""


def url_value(value: object) -> object:
    if isinstance(value, dict):
        return value.get("url")
    return value


def has_forbidden_url_char(url: str) -> bool:
    return any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url)


def is_http_url(url: str) -> bool:
    if has_forbidden_url_char(url):
        return False
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc and hostname)


def require_page_url(value: object, message: str) -> str:
    url = url_value(value)
    if isinstance(url, str) and is_http_url(url):
        return url
    raise InvalidInput(message)


def reached_value(result: dict) -> bool:
    reached = result.get("reached")
    if reached is True or reached is False:
        return reached
    raise InvalidInput("reached が真偽値でない")


def page_url(result: dict) -> str:
    return require_page_url(result.get("page"), "reached=true だが基点ページURLが無い")


def followed_url(value: object) -> str:
    return require_page_url(value, "followed_urls に不正なURLがある")


def input_urls(result: dict) -> list[str]:
    """抽出時に本文として読んだURLを、同じ順序で返す。"""
    followed = result.get("followed_urls", [])
    if not isinstance(followed, list):
        raise InvalidInput("followed_urls が配列でない")
    urls = [page_url(result)]
    for value in followed:
        url = followed_url(value)
        if url and url not in urls:
            urls.append(url)
    return urls


def load_evidence_pages(result: dict, fetcher: PoliteFetcher) -> tuple[list[str], list[str], list[str]]:
    """LLMへ渡した本文をキャッシュから復元する。"""
    urls = input_urls(result)
    pages: list[str] = []
    missing: list[str] = []
    for url in urls:
        cached = fetcher.cached(url)
        if cached is None or not cached.body_path or not Path(cached.body_path).exists():
            missing.append(url)
            continue
        _, text, _ = parse(cached.body(), url)
        pages.append(truncate_page_text(text))
    return pages, urls, missing


def unavailable_checks(items: dict, note: str) -> tuple[dict, dict]:
    """入力本文が完全に復元できないときは missing に倒さない。"""
    checked_items = {}
    checks = {}
    for key, item in items.items():
        if isinstance(item, dict) and item.get("found") is False:
            check = {"verdict": "not_applicable", "run": 0,
                     "note": "found=false のため照合しない"}
        else:
            check = {"verdict": "not_checked", "run": 0, "note": note}
        checked_items[key] = attach_item_check(item, check)
        checks[key] = check
    return checked_items, summarize(checks)


def items_error(items: object) -> str | None:
    """items の構造エラーを返す。正常なら None。"""
    if not isinstance(items, dict):
        return "items がオブジェクトでない"
    if any(not isinstance(item, dict) for item in items.values()):
        return "items 内にオブジェクトでない項目がある"
    return None


def evidence_scope(urls: list[str], missing: list[str], error: str | None = None) -> dict:
    scope = {
        "pages": urls,
        "max_text_chars_per_page": MAX_TEXT_CHARS_PER_PAGE,
        "cache_missing_urls": missing,
    }
    if error:
        scope["error"] = error
    return scope


def finish_annotation(out: dict, items: dict, status: str, summary: dict,
                      urls: list[str], missing: list[str], error: str | None = None) -> dict:
    out["items"] = items
    return finish_status(out, status, summary, urls, missing, error)


def finish_status(out: dict, status: str, summary: dict,
                  urls: list[str], missing: list[str], error: str | None = None) -> dict:
    """items を変えず、レコード単位の照合状態だけを付ける。"""
    out["evidence_check_status"] = status
    out["evidence_check_scope"] = evidence_scope(urls, missing, error)
    out["evidence_summary"] = summary
    return out


def unavailable_annotation(out: dict, items: dict, status: str, note: str,
                           urls: list[str], missing: list[str]) -> dict:
    checked_items, summary = unavailable_checks(items, note)
    error = note if status == "invalid_input" else None
    return finish_annotation(out, checked_items, status, summary, urls, missing, error)


def annotate_result(result: dict, fetcher: PoliteFetcher) -> dict:
    """抽出結果を壊さず evidence check フィールドを付けたコピーを返す。"""
    out = deepcopy(result)
    items = result.get("items")
    try:
        reached = reached_value(result)
    except InvalidInput as error:
        if isinstance(items, dict):
            return unavailable_annotation(out, items, "invalid_input", str(error), [], [])
        return finish_status(out, "invalid_input", summarize({}), [], [], str(error))

    if not reached:
        return finish_status(out, "not_applicable", summarize({}), [], [])

    structure_error = items_error(items)
    if structure_error:
        if not isinstance(items, dict):
            return finish_status(
                out, "invalid_input", summarize({}), [], [], structure_error
            )
        return unavailable_annotation(
            out, items, "invalid_input", structure_error, [], []
        )

    try:
        pages, urls, missing = load_evidence_pages(result, fetcher)
    except InvalidInput as error:
        return unavailable_annotation(out, items, "invalid_input", str(error), [], [])

    if missing:
        note = "照合に必要なキャッシュが無い: " + ", ".join(missing)
        return unavailable_annotation(out, items, "cache_missing", note, urls, missing)

    checked_items, summary = attach_checks_across_pages(items, pages)
    return finish_annotation(out, checked_items, "complete", summary, urls, [])


def result_verdicts(result: dict) -> list[str]:
    verdicts = []
    items = result.get("items") or {}
    if not isinstance(items, dict):
        return verdicts
    for item in items.values():
        if not isinstance(item, dict):
            continue
        verdict = (item.get("evidence_check") or {}).get("verdict")
        if verdict:
            verdicts.append(verdict)
    return verdicts


def count_verdicts(results: list[dict]) -> Counter[str]:
    verdicts: Counter[str] = Counter()
    for result in results:
        verdicts.update(result_verdicts(result))
    return verdicts


def record_summary(results: list[dict]) -> dict:
    statuses = Counter(result.get("evidence_check_status") or "unknown" for result in results)
    reached = sum(result.get("reached") is True for result in results)
    unreached = sum(result.get("reached") is False for result in results)
    records_with_missing = sum("missing" in result_verdicts(result) for result in results)
    return {
        "reached": reached,
        "unreached": unreached,
        "cache_complete": statuses["complete"],
        "cache_incomplete": statuses["cache_missing"],
        "invalid_input": statuses["invalid_input"],
        "with_missing_evidence": records_with_missing,
    }


def item_summary(verdicts: Counter[str]) -> dict:
    checked = sum(verdicts[v] for v in ("exact", "normalized", "partial", "missing", "too_short"))
    verified = sum(verdicts[v] for v in ("exact", "normalized"))
    return {
        "checked": checked,
        "verified": verified,
        "partial": verdicts["partial"],
        "missing": verdicts["missing"],
        "too_short": verdicts["too_short"],
        "not_checked": verdicts["not_checked"],
        "not_applicable": verdicts["not_applicable"],
        "verdicts": {key: verdicts[key] for key in
                     ("exact", "normalized", "partial", "missing", "too_short",
                      "not_checked", "not_applicable")},
    }


def aggregate(results: list[dict]) -> dict:
    """全出力の件数を、項目単位とファイル単位で集計する。"""
    verdicts = count_verdicts(results)
    return {
        "source_files": len(results),
        "records": record_summary(results),
        "items": item_summary(verdicts),
    }


def output_conflicts(files: list[Path], out_dir: Path, summary_path: Path) -> list[Path]:
    """入力と出力、または生成予定の出力同士の衝突を返す。"""
    sources = {path.resolve() for path in files}
    outputs = [(out_dir / path.name).resolve() for path in files]
    outputs.append(summary_path.resolve())
    output_counts = Counter(outputs)
    duplicate_outputs = {path for path, count in output_counts.items() if count > 1}
    return sorted((sources & set(outputs)) | duplicate_outputs)


def load_result(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InvalidInput(f"抽出結果JSONが壊れている: {path}: {error.msg}") from error
    if not isinstance(result, dict):
        raise InvalidInput(f"抽出結果がオブジェクトでない: {path}")
    return result


def run(extract_dir: Path, out_dir: Path, summary_path: Path,
        fetcher: PoliteFetcher) -> dict:
    files = sorted(extract_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"抽出結果がない: {extract_dir}")
    conflicts = output_conflicts(files, out_dir, summary_path)
    if conflicts:
        joined = ", ".join(str(path) for path in conflicts)
        raise SystemExit(f"入力または生成物と衝突する出力先は使えない: {joined}")

    checked_results = []
    for path in files:
        checked = annotate_result(load_result(path), fetcher)
        checked_results.append(checked)

    summary = aggregate(checked_results)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path, checked in zip(files, checked_results):
        (out_dir / path.name).write_text(
            json.dumps(checked, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract-dir", type=Path, default=DEFAULT_EXTRACT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()

    try:
        summary = run(args.extract_dir, args.out_dir, args.summary,
                      PoliteFetcher(cache_dir=args.cache_dir))
    except InvalidInput as error:
        parser.error(str(error))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

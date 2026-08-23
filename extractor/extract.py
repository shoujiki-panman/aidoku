"""読解層 — discovery結果をfact_typeごとの独立Test Caseで抽出する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DISCOVERY_DIR = ROOT / "crawler" / "out"
OUT_DIR = Path(__file__).parent / "out"
CLARITY_PROMPT = Path(__file__).parent / "clarity_prompt.md"

sys.path.insert(0, str(ROOT / "crawler"))
from htmlutil import parse  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

sys.path.insert(0, str(ROOT))
from extractor.batch import build_batch, load_jobs, write_batch  # noqa: E402
from extractor.fact_extract import (  # noqa: E402
    LINK_ORDER,
    MAX_FOLLOW,
    MAX_LINKS,
    MAX_TEXT_CHARS,
    PROMPT,
    call_claude,
    parse_json_reply,
    run_test_cases,
)
from extractor.response_contract import is_non_html_url as is_non_html  # noqa: E402
from extractor.result_contract import successful_result, unreachable_result  # noqa: E402
from measurement import (  # noqa: E402
    MeasurementError,
    build_measurement,
    prompt_version,
    utc_timestamp,
)
from measurement_cases import TestCase, test_cases_for  # noqa: E402


def pick_page(discovery: dict) -> dict | None:
    """探索結果から、抽出対象にするスコア最上位のHTMLページを選ぶ。"""
    for candidate in discovery.get("candidates", []):
        if candidate.get("is_pdf") or is_non_html(candidate.get("url") or ""):
            continue
        if candidate.get("status") != 200:
            continue
        if (candidate.get("text_len") or 0) < 200:
            continue
        return candidate
    return None


def judge_clarity(page: dict, muni: str, proc: str, fetcher: PoliteFetcher,
                  model: str,
                  extra_pages: list[tuple[str, str]] | None = None) -> dict:
    """ページの性質としてonline_clarityだけを1回観測する。"""
    cached = fetcher.cached(page["url"])
    if cached is None or not cached.body_path:
        return {"online_clarity": "記載なし", "evidence": "", "pages": []}
    text = parse(cached.body(), page["url"]).text
    parts = [
        CLARITY_PROMPT.read_text(encoding="utf-8"),
        "\n---\n",
        f"## 対象\n\n- 自治体: {muni}\n- 手続き: {proc}\n"
        f"- ページURL: {page['url']}\n",
        f"\n## ページ本文\n\n{text[:MAX_TEXT_CHARS]}\n",
    ]
    for url, page_text in (extra_pages or []):
        parts.append(
            f"\n---\n\n## リンク先ページの本文（{url}）\n\n"
            f"{page_text[:MAX_TEXT_CHARS]}\n")
    if extra_pages:
        parts.append(
            "\n（上のリンク先ページも、このページから1クリックで到達できる範囲です。"
            "同じ手続きの説明として合わせて読んでください。）")
    data = parse_json_reply(call_claude("".join(parts), model))
    clarity = _clarity_value(data.get("online_clarity"))
    evidence = data.get("evidence")
    if evidence is not None and not isinstance(evidence, str):
        raise ValueError("online_clarity.evidenceが文字列でない")
    return {
        "online_clarity": clarity,
        "evidence": (evidence or "").strip(),
        "pages": [page["url"], *(url for url, _ in (extra_pages or []))],
    }


def _clarity_value(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() in {
        "明記", "曖昧", "記載なし",
    } else "記載なし"


def discovery_files(procedure: str, municipalities: list[str] | None) -> list[Path]:
    files = sorted(DISCOVERY_DIR.glob(f"discovery_*_{procedure}.json"))
    if municipalities:
        files = [path for path in files if any(
            f"discovery_{municipality}_" in path.name
            for municipality in municipalities)]
    return files


def extract_one(discovery: dict, fetcher: PoliteFetcher,
                model: str, follow: bool) -> dict:
    cases = test_cases_for(discovery["procedure_id"], discovery["municipality"])
    measurement = measurement_for(
        discovery, follow=follow, model=model,
        prompt=prompt_version([PROMPT, CLARITY_PROMPT]), run_at=utc_timestamp())
    return extract_prepared(
        discovery, tuple(cases), fetcher, model, follow, measurement)


def measurement_for(discovery: dict, *, follow: bool, model: str,
                    prompt: str, run_at: str) -> dict:
    return build_measurement(
        discovery.get("measurement"),
        prompt=prompt,
        follow=follow,
        max_follow=MAX_FOLLOW,
        max_text_chars=MAX_TEXT_CHARS,
        max_links=MAX_LINKS,
        link_order=LINK_ORDER,
        model_version=model,
        run_at=run_at,
    )


def extract_prepared(discovery: dict, cases: tuple[TestCase, ...],
                     fetcher: PoliteFetcher, model: str, follow: bool,
                     measurement: dict) -> dict:
    page = pick_page(discovery)
    if page is None:
        return unreachable_result(discovery, list(cases), measurement, model)
    records, meta, extra = run_test_cases(
        page, discovery["municipality"], discovery["procedure"], list(cases),
        fetcher, model, follow)
    clarity = judge_clarity(
        page, discovery["municipality"], discovery["procedure"],
        fetcher, model, extra_pages=extra)
    return successful_result(
        discovery, page, records, meta, model, clarity, measurement)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--municipality", "-m", action="append")
    parser.add_argument("--procedure", "-p", default="tennyu")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument(
        "--follow", action="store_true",
        help="各Test Caseが指定したリンク先を1階層だけ開いて再抽出する")
    args = parser.parse_args(argv)

    files = discovery_files(args.procedure, args.municipality)
    if not files:
        raise SystemExit("探索結果がない。先に crawler/discover.py を実行すること")
    jobs = load_jobs(files, args.procedure, OUT_DIR)
    run_at = utc_timestamp()
    current_prompt = prompt_version([PROMPT, CLARITY_PROMPT])
    try:
        measurements = {
            job.output: measurement_for(
                job.discovery, follow=args.follow, model=args.model,
                prompt=current_prompt, run_at=run_at)
            for job in jobs
        }
    except MeasurementError as error:
        raise SystemExit(str(error)) from error

    fetcher = PoliteFetcher()
    batch = build_batch(jobs, lambda job: extract_prepared(
        job.discovery, job.cases, fetcher, args.model, args.follow,
        measurements[job.output]))

    write_batch(batch)
    for _job, result, _serialized in batch:
        _print_result(result)


def _print_result(result: dict) -> None:
    if not result["reached"]:
        print(f"[{result['municipality']}] 抽出対象ページなし（到達失敗）")
        return
    found = sum(1 for item in result["items"].values() if item["found"])
    followed = result["followed_urls"]
    tail = f" (+リンク先{len(followed)}件)" if followed else ""
    print(
        f"[{result['municipality']}] hop{result['page']['hops']} "
        f"{found}/{len(result['test_cases'])}項目 抽出"
        f" / オンライン明示={result['online_clarity']}{tail}"
        f" — {result['page']['url']}")


if __name__ == "__main__":
    main()

"""ダッシュボード生成のテスト — 公開している点数の作り方を固定する。

web/data/scores.json は 2026-07-30 に生成されたが生成スクリプトがコミットされて
おらず、1区を測り直すだけでも手で JSON を書き換えるしかない状態だった。
export_dashboard.py はその欠けを埋めたもので、ここでは配点・処方箋・集計を固定する。

LLM は呼ばない。標準ライブラリのみ。

実行: python3 -m unittest discover -s analysis -p 'test_*.py'
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import export_dashboard  # noqa: E402
from export_dashboard import (  # noqa: E402
    MAX_VALUE_CHARS,
    build_entry,
    display_question,
    prepare_public_entries,
    summarize,
)
from measurement import (  # noqa: E402
    MeasurementError,
    build_discovery_measurement,
    build_measurement,
)


def extract(items: dict, clarity: str = "明記", **kw) -> dict:
    base = {
        "municipality": "テスト区", "municipality_id": "test",
        "page": {"url": "https://example.jp/a.html", "hops": 2},
        "followed_urls": [], "online_clarity": clarity, "items": items,
        "page_notes": "",
    }
    base.update(kw)
    return base


def item(found: bool, value: str = "") -> dict:
    return {"found": found, "value": value}


ALL_FOUND = {k: item(True, "あり") for k in
             ("必要書類", "窓口オンライン可否", "期限", "手数料")}
VALID_PROMPT_VERSION = "sha256:" + "0" * 64


class ScoringTest(unittest.TestCase):
    def test_full_marks(self):
        e = build_entry(extract(ALL_FOUND, "明記"))
        self.assertEqual(e["total"], 100)
        self.assertEqual(e["improvements"], [])

    def test_each_item_is_all_or_nothing(self):
        """4項目に部分点は無い。20点か0点しか出ない。"""
        items = dict(ALL_FOUND, 手数料=item(False))
        e = build_entry(extract(items, "明記"))
        self.assertEqual(e["breakdown"]["手数料"], 0)
        self.assertEqual(e["total"], 80)

    def test_clarity_has_three_levels(self):
        for clarity, pt in (("明記", 20), ("曖昧", 10), ("記載なし", 0)):
            with self.subTest(clarity=clarity):
                e = build_entry(extract(ALL_FOUND, clarity))
                self.assertEqual(e["breakdown"]["オンライン明示"], pt)
                self.assertEqual(e["total"], 80 + pt)

    def test_unknown_clarity_scores_zero(self):
        self.assertEqual(build_entry(extract(ALL_FOUND, "?"))["breakdown"]["オンライン明示"], 0)

    def test_missing_items_become_improvements(self):
        items = dict(ALL_FOUND, 期限=item(False), 手数料=item(False))
        e = build_entry(extract(items, "曖昧"))
        self.assertEqual([i["field"] for i in e["improvements"]],
                         ["期限", "手数料", "オンライン明示"])
        # オンライン明示は満点までの差分だけを足せる
        self.assertEqual([i["gain"] for i in e["improvements"]], [20, 20, 10])

    def test_agent_value_is_truncated(self):
        items = dict(ALL_FOUND, 必要書類=item(True, "あ" * 500))
        e = build_entry(extract(items))
        self.assertEqual(len(e["fields"][0]["agent_value"]), MAX_VALUE_CHARS)

    def test_field_label_is_renamed_for_display(self):
        e = build_entry(extract(ALL_FOUND))
        self.assertIn("窓口/オンライン可否", e["breakdown"])
        self.assertNotIn("窓口オンライン可否", e["breakdown"])


class PageStatusTest(unittest.TestCase):
    """対象ページに着けたか確認できたかどうか（#86）。

    4項目が1つも読めないとき、区のページに書かれていないのか、こちらが別の
    ページを採点したのかを区別できない。区別できないものを区への依頼にしない。
    """

    NONE_FOUND = {k: item(False) for k in
                  ("必要書類", "窓口オンライン可否", "期限", "手数料")}

    def test_all_found_is_facts_found(self):
        e = build_entry(extract(ALL_FOUND, "明記"))
        self.assertEqual(e["page_status"]["code"], "facts_found")

    def test_none_found_is_target_unconfirmed(self):
        e = build_entry(extract(self.NONE_FOUND, "記載なし"))
        self.assertEqual(e["page_status"]["code"], "target_unconfirmed")

    def test_one_found_is_facts_found(self):
        """1項目でも読めれば、そのページを採点していると考えられる。"""
        items = dict(self.NONE_FOUND, 手数料=item(True, "無料"))
        e = build_entry(extract(items, "記載なし"))
        self.assertEqual(e["page_status"]["code"], "facts_found")

    def test_online_clarity_does_not_count(self):
        """オンライン明示は4項目に含めない（full_marks と同じ扱い）。"""
        e = build_entry(extract(self.NONE_FOUND, "明記"))
        self.assertEqual(e["page_status"]["code"], "target_unconfirmed")

    def test_unconfirmed_does_not_assert_wrong_page(self):
        """断定しない。こちらが確認できていないという状態だけを言う。"""
        e = build_entry(extract(self.NONE_FOUND, "記載なし"))
        text = e["page_status"]["label"] + e["page_status"]["detail"]
        self.assertIn("確認できていません", e["page_status"]["label"])
        self.assertIn("区別できません", text)

    def test_status_has_label_and_detail(self):
        for items in (ALL_FOUND, self.NONE_FOUND):
            st = build_entry(extract(items))["page_status"]
            self.assertEqual(set(st), {"code", "label", "detail"})
            self.assertTrue(st["label"] and st["detail"])

    def test_notes_are_not_interpreted(self):
        """notes の文面で判定を変えない（構造だけで決める）。"""
        a = build_entry(extract(self.NONE_FOUND, page_notes="別の手続きのページ"))
        b = build_entry(extract(self.NONE_FOUND, page_notes=""))
        self.assertEqual(a["page_status"]["code"], b["page_status"]["code"])

    def test_score_is_unchanged(self):
        """page_status を足しても、公開している点は変わらない。"""
        e = build_entry(extract(self.NONE_FOUND, "記載なし"))
        self.assertEqual(e["total"], 0)


class SummaryTest(unittest.TestCase):
    def test_counts(self):
        full = build_entry(extract(ALL_FOUND, "明記"))
        no_fee = build_entry(extract(dict(ALL_FOUND, 手数料=item(False)), "明記"))
        zero = build_entry(extract({k: item(False) for k in ALL_FOUND}, "記載なし"))
        s = summarize([full, no_fee, zero])
        self.assertEqual(s["max"], 100)
        self.assertEqual(s["min"], 0)
        self.assertEqual(s["full_marks"], 1)
        self.assertEqual(s["zero"], 1)
        self.assertEqual(s["fee_missing"], 2)
        self.assertEqual(s["average"], round((100 + 80 + 0) / 3, 1))

    def test_full_marks_ignores_online_clarity(self):
        """「4項目すべて読めた」はオンライン明示を含まない（港区=1区の定義）。"""
        e = build_entry(extract(ALL_FOUND, "記載なし"))
        self.assertEqual(e["total"], 80)
        self.assertEqual(summarize([e])["full_marks"], 1)


class MeasurementTest(unittest.TestCase):
    def test_旧結果は不明と明示する(self):
        entry = build_entry(extract(ALL_FOUND, model="claude-sonnet-5"))
        self.assertEqual(entry["measurement"]["recording_status"], "legacy_unknown")
        self.assertIsNone(entry["measurement"]["follow"])
        self.assertEqual(entry["measurement"]["model_version"], "claude-sonnet-5")

    def test_新しい測定条件を公開結果へ運ぶ(self):
        discovery = build_discovery_measurement(
            3, {1: (1, 6), 2: (3, 4), 3: (4, 3)}, 26,
            "2026-08-16T00:00:00+00:00",
        )
        record = build_measurement(
            discovery,
            prompt=VALID_PROMPT_VERSION,
            follow=True,
            max_follow=2,
            max_text_chars=18000,
            max_links=40,
            model_version="claude-sonnet-5",
            run_at="2026-08-16T01:00:00+00:00",
        )
        entry = build_entry(extract(ALL_FOUND, measurement=record))
        self.assertEqual(entry["measurement"], record)

    def test_共通条件は先頭に1回だけ置く(self):
        entries = [
            build_entry(extract(ALL_FOUND, municipality_id="a")),
            build_entry(extract(ALL_FOUND, municipality_id="b")),
        ]
        public_entries, measurement = prepare_public_entries(entries)
        self.assertNotIn("measurement", public_entries[0])
        self.assertEqual(measurement["comparison_status"], "legacy_unknown")
        self.assertEqual([run["municipality_id"] for run in measurement["runs"]],
                         ["a", "b"])

    def test_条件の違う公開結果を拒否する(self):
        discovery = build_discovery_measurement(
            3, {1: (1, 6), 2: (3, 4), 3: (4, 3)}, 26,
            "2026-08-16T00:00:00+00:00",
        )
        records = [
            build_measurement(
                discovery,
                prompt=VALID_PROMPT_VERSION,
                follow=follow,
                max_follow=2,
                max_text_chars=18000,
                max_links=40,
                model_version="claude-sonnet-5",
                run_at="2026-08-16T01:00:00+00:00",
            )
            for follow in (True, False)
        ]
        entries = [
            build_entry(extract(ALL_FOUND, municipality_id=str(index), measurement=record))
            for index, record in enumerate(records)
        ]
        with self.assertRaisesRegex(MeasurementError, "follow"):
            prepare_public_entries(entries)


class DisplayQuestionTest(unittest.TestCase):
    def test_画面用質問と測定用TestCaseを混同しない(self):
        proc = {
            "display_question": "{muni}に引っ越します。何が必要ですか？",
            "fact_types": ["documents"],
        }
        self.assertEqual(display_question(proc), proc["display_question"])

    def test_欠落と不正値は既定文にする(self):
        for proc in ({}, {"display_question": None}, {"display_question": " "}):
            with self.subTest(proc=proc):
                self.assertEqual(display_question(proc), "{muni}について教えて。")

    def test_mainの出力もdisplay_questionを使う(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extract_dir = root / "extract"
            extract_dir.mkdir()
            targets = root / "targets.json"
            output = root / "scores.json"
            targets.write_text(json.dumps({
                "municipalities": [{
                    "id": "test", "name": "テスト区", "lg_code": "130000"}],
                "procedures": [{
                    "id": "tennyu", "name": "転入届",
                    "display_question": "画面用の質問", "fact_types": [],
                }],
            }, ensure_ascii=False), encoding="utf-8")
            (extract_dir / "extract_test_tennyu.json").write_text(
                json.dumps(extract(ALL_FOUND), ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(export_dashboard, "TARGETS", targets), \
                    mock.patch.object(export_dashboard, "EXTRACT_DIR", extract_dir):
                export_dashboard.main([
                    "--procedure", "tennyu", "--out", str(output),
                    "--generated-at", "2026-01-01T00:00:00+00:00",
                ])
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["question"],
                "画面用の質問",
            )


if __name__ == "__main__":
    unittest.main()

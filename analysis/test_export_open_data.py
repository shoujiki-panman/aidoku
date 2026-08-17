"""CSVと要約が未検証を0点に変換しないことを固定する。"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import export_open_data  # noqa: E402


def document(total=None) -> dict:
    labels = ["必要書類", "窓口/オンライン可否", "期限", "手数料"]
    return {
        "generated_at": "2026-08-17T00:00:00+00:00",
        "phase": "23区",
        "procedure": "転入届",
        "summary": {
            "average": total,
            "evaluated": 0 if total is None else 1,
            "not_evaluated": 1 if total is None else 0,
            "answered_all_four": 1,
            "answered_zero": 0,
            "fee_missing": 0,
        },
        "municipalities": [{
            "name": "テスト区",
            "total": total,
            "breakdown": {**{label: total for label in labels}, "オンライン明示": 20},
            "answered_count": 4,
            "evaluation_status": "not_checked" if total is None else "evaluated",
            "hops": 2,
            "page_url": "https://example.jp/",
            "fields": [
                {"field": label, "answered": True}
                for label in labels
            ],
        }],
    }


class ExportOpenDataTest(unittest.TestCase):
    def run_export(self, doc: dict) -> tuple[list[list[str]], str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "scores.json"
            output_csv = root / "scores.csv"
            output_text = root / "summary.txt"
            source.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(export_open_data, "SRC", source), \
                    mock.patch.object(export_open_data, "OUT_CSV", output_csv), \
                    mock.patch.object(export_open_data, "OUT_TXT", output_text), \
                    mock.patch.object(export_open_data, "REPO", root):
                export_open_data.main()
            with output_csv.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            return rows, output_text.read_text(encoding="utf-8")

    def test_未検証はCSVで空欄_要約で未検証(self):
        rows, summary = self.run_export(document())
        self.assertEqual(rows[0][2], "検証済み合計点")
        self.assertEqual(rows[1][2], "")
        self.assertEqual(rows[1][3:7], ["", "", "", ""])
        self.assertIn("4判定の点数 未検証", summary)
        self.assertNotIn("None点", summary)
        self.assertNotIn("0点（100点満点）", summary)

    def test_検証済み0点は空欄にしない(self):
        rows, summary = self.run_export(document(0))
        self.assertEqual(rows[1][2], "0")
        self.assertEqual(rows[1][3:7], ["0", "0", "0", "0"])
        self.assertIn("4判定の点数 0点", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""点数の履歴と差分のテスト。ネットワークにもLLMにも触らない。"""

import json
import tempfile
import unittest
from pathlib import Path

import history

COND = {
    "measurement_version": "aidoku-1.0", "prompt_version": "p1", "follow": True,
    "max_follow": 3, "max_depth": 3, "beam": {"1": {"take": 8, "of": 40}},
    "max_fetches": 40, "max_text_chars": 60000, "max_links": 40, "link_order": "score_desc",
    "table_reading": "heading_value",
    "read_breadth": "agent_pick",
    "non_html_reading": "none",
    "model": "claude-cli", "model_version": "claude-sonnet-5",
}


def doc(generated_at, totals, *, recorded=True, model_version="claude-sonnet-5"):
    m = dict(COND, model_version=model_version)
    m["recording_status"] = "recorded" if recorded else "legacy_unknown"
    return {
        "generated_at": generated_at, "procedure_id": "tennyu", "procedure": "転入届",
        "measurement": m, "summary": {"average": sum(totals.values()) / len(totals)},
        "municipalities": [
            {"id": k, "name": f"{k}区", "total": v, "breakdown": {"必要書類": v},
             "hops": 1, "page_status": {"code": "facts_found"}}
            for k, v in totals.items()
        ],
    }


def snap(generated_at, totals, **kw):
    return history.snapshot_from_doc(doc(generated_at, totals, **kw), "2026-08-22T00:00:00+00:00")


class Snapshot(unittest.TestCase):
    def test_必要な項目を持つ(self):
        s = snap("2026-08-01", {"a": 40})
        for k in ("schema", "recorded_at", "generated_at", "procedure_id",
                  "measurement_signature", "recording_status", "summary", "municipalities"):
            self.assertIn(k, s)

    def test_生の引用は持たない(self):
        s = snap("2026-08-01", {"a": 40})
        self.assertNotIn("fields", s["municipalities"][0])
        self.assertNotIn("improvements", s["municipalities"][0])

    def test_measurementが無ければ例外(self):
        with self.assertRaises(ValueError):
            history.snapshot_from_doc({"municipalities": []}, "t")

    def test_idの無い区は落とす(self):
        d = doc("2026-08-01", {"a": 40})
        d["municipalities"].append({"name": "壊れた行"})
        self.assertEqual(len(history.snapshot_from_doc(d, "t")["municipalities"]), 1)


class AppendAndLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name) / "history" / "scores.jsonl"

    def test_追記できる(self):
        self.assertTrue(history.append_snapshot(self.p, snap("2026-08-01", {"a": 40})))
        self.assertTrue(history.append_snapshot(self.p, snap("2026-08-05", {"a": 60})))
        self.assertEqual(len(history.load_snapshots(self.p)), 2)

    def test_同じgenerated_atは二重に入らない(self):
        # 測り直していないのに export を2回流しても水増しされない
        history.append_snapshot(self.p, snap("2026-08-01", {"a": 40}))
        self.assertFalse(history.append_snapshot(self.p, snap("2026-08-01", {"a": 40})))
        self.assertEqual(len(history.load_snapshots(self.p)), 1)

    def test_過去行を書き換えない(self):
        history.append_snapshot(self.p, snap("2026-08-01", {"a": 40}))
        first = self.p.read_text(encoding="utf-8").splitlines()[0]
        history.append_snapshot(self.p, snap("2026-08-05", {"a": 60}))
        self.assertEqual(self.p.read_text(encoding="utf-8").splitlines()[0], first)

    def test_壊れた行は飛ばして読む(self):
        history.append_snapshot(self.p, snap("2026-08-01", {"a": 40}))
        with self.p.open("a", encoding="utf-8") as f:
            f.write("これはJSONではない\n")
        history.append_snapshot(self.p, snap("2026-08-05", {"a": 60}))
        self.assertEqual(len(history.load_snapshots(self.p)), 2)

    def test_ファイルが無ければ空(self):
        self.assertEqual(history.load_snapshots(self.p), [])

    def test_手続きで絞れる(self):
        history.append_snapshot(self.p, snap("2026-08-01", {"a": 40}))
        self.assertEqual(len(history.load_snapshots(self.p, "sodaigomi")), 0)
        self.assertEqual(len(history.load_snapshots(self.p, "tennyu")), 1)


class Attribution(unittest.TestCase):
    """★ここがこの機能の芯。差の原因を軽々しく言わせない。"""

    def test_条件が同じで記録済みならサイト側と言ってよい(self):
        how, _ = history.attribution(snap("2026-08-01", {"a": 40}), snap("2026-08-05", {"a": 60}))
        self.assertEqual(how, "site")

    def test_モデルが変わったら原因は言えない(self):
        a = snap("2026-08-01", {"a": 40})
        b = snap("2026-08-05", {"a": 60}, model_version="別のモデル")
        how, why = history.attribution(a, b)
        self.assertEqual(how, "unknown")
        self.assertIn("測定条件が違う", why)

    def test_条件未記録なら原因は言えない(self):
        a = snap("2026-08-01", {"a": 40}, recorded=False)
        b = snap("2026-08-05", {"a": 60}, recorded=False)
        how, why = history.attribution(a, b)
        self.assertEqual(how, "unknown")
        self.assertIn("legacy_unknown", why)

    def test_片方だけ記録済みでも言えない(self):
        a = snap("2026-08-01", {"a": 40}, recorded=False)
        b = snap("2026-08-05", {"a": 60})
        self.assertEqual(history.attribution(a, b)[0], "unknown")


class Diff(unittest.TestCase):
    def test_原因が言えなくても数字は出す(self):
        # 「分からないから何も見せない」にはしない
        a = snap("2026-08-01", {"a": 40}, recorded=False)
        b = snap("2026-08-05", {"a": 60}, recorded=False)
        d = history.diff(a, b)
        self.assertEqual(d["attribution"], "unknown")
        self.assertEqual(d["municipalities"][0]["delta"], 20)

    def test_差分を数える(self):
        a = snap("2026-08-01", {"a": 40, "b": 60})
        b = snap("2026-08-05", {"a": 60, "b": 60})
        self.assertEqual(history.diff(a, b)["changed_count"], 1)

    def test_新しく増えた区はis_new(self):
        d = history.diff(snap("2026-08-01", {"a": 40}), snap("2026-08-05", {"a": 40, "b": 60}))
        new = [r for r in d["municipalities"] if r["is_new"]]
        self.assertEqual([r["id"] for r in new], ["b"])
        self.assertIsNone(new[0]["delta"])

    def test_page_statusの変化も見える(self):
        a = snap("2026-08-01", {"a": 40})
        b = snap("2026-08-05", {"a": 40})
        b["municipalities"][0]["page_status"] = "target_unconfirmed"
        r = history.diff(a, b)["municipalities"][0]
        self.assertEqual(r["page_status_before"], "facts_found")
        self.assertEqual(r["page_status_after"], "target_unconfirmed")


class Series(unittest.TestCase):
    def test_1区の推移を取り出す(self):
        snaps = [snap("2026-08-01", {"a": 40, "b": 0}), snap("2026-08-05", {"a": 60, "b": 0})]
        s = history.series(snaps, "a")
        self.assertEqual([x["total"] for x in s], [40, 60])

    def test_居ない区は空(self):
        self.assertEqual(history.series([snap("2026-08-01", {"a": 40})], "zzz"), [])


class 測定時刻(unittest.TestCase):
    """★書き出し時刻を測定時刻と呼ばない、を固定する。

    もとの不具合: `measured_on` の元が `generated_at`（エクスポータの実行時刻）で、
    書き出しを流し直すだけで「別の日に測った」記録が増えていた。
    """

    def test_実測時刻が記録されていなければNone(self):
        self.assertIsNone(history.measured_at_of(
            {"recording_status": "legacy_unknown", "run_at": None}))

    def test_記録済みでもrun_atが空ならNone(self):
        self.assertIsNone(history.measured_at_of({"recording_status": "recorded", "run_at": []}))
        self.assertIsNone(history.measured_at_of({"recording_status": "recorded", "run_at": ""}))
        self.assertIsNone(history.measured_at_of({"recording_status": "recorded"}))

    def test_measurementがdictでなくても落ちない(self):
        self.assertIsNone(history.measured_at_of(None))
        self.assertIsNone(history.measured_at_of("2026-08-11T13:52:32+00:00"))

    def test_文字列のrun_atをそのまま使う(self):
        self.assertEqual(
            history.measured_at_of({"recording_status": "recorded",
                                    "run_at": "2026-08-20T01:00:00+00:00"}),
            "2026-08-20T01:00:00+00:00")

    def test_リストのrun_atは測り始めを使う(self):
        # scores-*.json の measurement は summarize_measurements() が作るのでリストになる
        self.assertEqual(
            history.measured_at_of({"recording_status": "recorded", "run_at": [
                "2026-08-20T03:00:00+00:00", "2026-08-20T01:00:00+00:00"]}),
            "2026-08-20T01:00:00+00:00")

    def test_条件未記録の回のmeasured_atはNoneになる(self):
        s = snap("2026-08-01T09:00:00+00:00", {"a": 40}, recorded=False)
        self.assertIsNone(s["measured_at"])

    def test_これ大事_書き出し時刻をmeasured_atに流し込まない(self):
        # 記録済みでも run_at が無ければ measured_at は None。generated_at は別の値のまま
        s = snap("2026-08-01T09:00:00+00:00", {"a": 40})
        self.assertEqual(s["generated_at"], "2026-08-01T09:00:00+00:00")
        self.assertIsNone(s["measured_at"])

    def test_run_atがあればmeasured_atに入る(self):
        d = doc("2026-08-01T09:00:00+00:00", {"a": 40})
        d["measurement"]["run_at"] = ["2026-07-30T11:22:33+00:00"]
        s = history.snapshot_from_doc(d, "t")
        self.assertEqual(s["measured_at"], "2026-07-30T11:22:33+00:00")
        # 書き出し時刻は書き出し時刻のまま。上書きしない
        self.assertEqual(s["generated_at"], "2026-08-01T09:00:00+00:00")

    def test_推移にも両方の時刻を出す(self):
        d = doc("2026-08-01T09:00:00+00:00", {"a": 40})
        d["measurement"]["run_at"] = ["2026-07-30T11:22:33+00:00"]
        row = history.series([history.snapshot_from_doc(d, "t")], "a")[0]
        self.assertEqual(row["measured_at"], "2026-07-30T11:22:33+00:00")
        self.assertEqual(row["generated_at"], "2026-08-01T09:00:00+00:00")


class RealData(unittest.TestCase):
    """実データで通ること。

    ★2026-08-31、転入届は**条件を記録して測り直した**ので `recorded` になった。
      児童手当・粗大ごみはまだ `legacy_unknown`（条件の記録が無い）。
      **混在しているのが正しい現状**なので、どちらかに決め打ちしない。
    """

    def snapshot(self, procedure: str):
        root = Path(__file__).parent
        path = root / f"web/data/scores-{procedure}.json"
        return history.snapshot_from_doc(
            json.loads(path.read_text(encoding="utf-8")), "t")

    def test_実データからスナップショットを作れる(self):
        s = self.snapshot("tennyu")
        self.assertEqual(len(s["municipalities"]), 23)
        self.assertIn(s["recording_status"], ("recorded", "legacy_unknown"))
        self.assertTrue(s["generated_at"])

    def test_条件の記録が無いものは比較を拒否する(self):
        # ★ここが要。記録の無いものどうしは必ず unknown になる。
        s = self.snapshot("jidouteate")
        if s["recording_status"] != "legacy_unknown":
            self.skipTest("この手続きも測り直された")
        self.assertEqual(history.attribution(s, s)[0], "unknown")
        # ★実データには「実際に測った時刻」が残っていない。generated_at で埋めない
        self.assertIsNone(s["measured_at"])


class SiteStatusHistory(unittest.TestCase):
    """毎日自動で貯まる側。変化したものだけ残す。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name) / "site-status.jsonl"

    def report(self, checked_at, items):
        return {"checked_at": checked_at,
                "summary": {"total": len(items), "changed": sum(1 for i in items if i["changed"]),
                            "headline": "テスト"},
                "items": items}

    def test_変化したものだけ残す(self):
        r = self.report("2026-08-19T00:00:00Z", [
            {"municipality_id": "a", "procedure_id": "tennyu", "changed": True,
             "gone": False, "reason": "HTTP 200"},
            {"municipality_id": "b", "procedure_id": "tennyu", "changed": False,
             "gone": False, "reason": "304"},
        ])
        s = history.site_status_snapshot(r)
        self.assertEqual(len(s["changed"]), 1)
        self.assertEqual(s["changed"][0]["municipality_id"], "a")
        self.assertEqual(s["summary"]["headline"], "テスト")

    def test_消えたページも残る(self):
        r = self.report("2026-08-19T00:00:00Z", [
            {"municipality_id": "a", "procedure_id": "tennyu", "changed": True,
             "gone": True, "reason": "404"}])
        self.assertTrue(history.site_status_snapshot(r)["changed"][0]["gone"])

    def test_判定できずは変化に含めない(self):
        # changed が None（比べられなかった）を「変わった」と数えない
        r = self.report("2026-08-19T00:00:00Z", [
            {"municipality_id": "a", "procedure_id": "tennyu", "changed": None,
             "gone": False, "reason": "記録が無い"}])
        self.assertEqual(history.site_status_snapshot(r)["changed"], [])

    def test_checked_atで重複判定する(self):
        r = self.report("2026-08-19T00:00:00Z", [])
        s = history.site_status_snapshot(r)
        self.assertTrue(history.append_snapshot(self.p, s, history.SITE_STATUS_KEY))
        self.assertFalse(history.append_snapshot(self.p, s, history.SITE_STATUS_KEY))
        self.assertEqual(len(history.load_snapshots(self.p)), 1)

    def test_キーが全部空なら例外(self):
        # 点数用のキーで見張りの行を入れると全部 None になり、2件目以降が
        # 黙って捨てられる。事故になる前に落とす
        s = history.site_status_snapshot(self.report("2026-08-19T00:00:00Z", []))
        with self.assertRaises(ValueError):
            history.append_snapshot(self.p, s, history.SCORE_KEY)

    def test_itemsが無くても落ちない(self):
        self.assertEqual(history.site_status_snapshot({"checked_at": "t"})["changed"], [])

    def test_dictでなければ例外(self):
        with self.assertRaises(ValueError):
            history.site_status_snapshot([])


if __name__ == "__main__":
    unittest.main()

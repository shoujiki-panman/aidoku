"""`analysis/status.py` — いまの状態をデータから機械的に出す。

**なぜ要るか**: `STATUS.md` は手で書くので古くなる（13日前で止まっていた）。
そのたびにセッションで調べ直していた。**調べ直しの手間そのものを無くす。**

★ここが嘘をつくと、次のセッションが間違った現在地から始まる。
  台帳（`analysis/read_ledger.py`）と同じで、**記録が嘘をつくのが最悪**。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from status import (  # noqa: E402
    WATCH_STALE_DAYS,
    _age_days,
    conditions,
    newest,
    next_actions,
    render,
    snapshot,
)


def state(**kw) -> dict:
    base = {
        "prompt_version": "sha256:x",
        "watch": {"ok": True, "age_days": 0.5, "stale": False, "pages": 68,
                  "changed": 0, "gone": 0},
        "conditions": {p: {"municipalities": 24, "stale": [], "uniform": True}
                       for p in ("tennyu", "jidouteate", "sodaigomi")},
        "sweep": {p: {"ok": True, "fields": 1, "pages": 1, "found": 0, "exhausted": 1,
                      "unreadable": 0, "errored": 0, "budget": 0}
                  for p in ("tennyu", "jidouteate", "sodaigomi")},
        "blockers": {"urls": 0},
        "published": {p: {"ok": True, "generated_at": "2026-08-30T00:00:00+00:00",
                          "age_days": 1.0, "has_conditions": True}
                      for p in ("tennyu", "jidouteate", "sodaigomi")},
    }
    return {**base, **kw}


class 日数(unittest.TestCase):
    def test_分からなければNone(self):
        # ★0日にしない。「今日確認した」と読まれると嘘になる。
        self.assertIsNone(_age_days(None))
        self.assertIsNone(_age_days("いつか"))

    def test_古い日付は日数になる(self):
        self.assertGreater(_age_days("2020-01-01T00:00:00+00:00"), 1000)


class 新しい方を採る(unittest.TestCase):
    """★見張りは main にコミットされる。手元の枝は切った日で止まる。

    手元だけ見て「見張りが止まっている」と言うのは嘘。実測で7.7日前と出したが、
    main では0.6日前だった。
    """

    def test_新しい方を返す(self):
        old = {"checked_at": "2026-08-22T00:00:00+00:00"}
        new = {"checked_at": "2026-08-30T00:00:00+00:00"}
        self.assertIs(newest(old, new), new)
        self.assertIs(newest(new, old), new)

    def test_日付が無いものは捨てる(self):
        new = {"checked_at": "2026-08-30T00:00:00+00:00"}
        self.assertIs(newest({}, None, new), new)

    def test_どれも無ければNone(self):
        self.assertIsNone(newest(None, {}))


class 測定条件(unittest.TestCase):
    def test_版が分からなければ揃っていないとは言わない(self):
        # ★プロンプトが計算できないときに「全部古い」と出すと、無駄な測り直しを促す。
        got = conditions("__none__", None)
        self.assertEqual(got["stale"], [])


class 次にやること(unittest.TestCase):
    def test_見張りが古ければ最初に出す(self):
        got = next_actions(state(watch={"ok": True, "age_days": 9.0, "stale": True,
                                        "pages": 68, "changed": 3, "gone": 0}))
        self.assertIn("見張り", got[0])

    def test_変化があれば測り直す対象を選べと言う(self):
        got = next_actions(state(watch={"ok": True, "age_days": 0.5, "stale": False,
                                        "pages": 68, "changed": 29, "gone": 0}))
        self.assertIn("29件", got[0])
        # ★見張りは自動では測り直さない。そう書いてあること。
        self.assertIn("自動では測り直さない", got[0])

    def test_条件が揃っていなければ公開できないと言う(self):
        cond = {p: {"municipalities": 24, "stale": [], "uniform": True}
                for p in ("tennyu", "jidouteate", "sodaigomi")}
        cond["sodaigomi"] = {"municipalities": 24, "stale": ["ota", "kita"],
                             "why": ["non_html_reading"], "uniform": False}
        got = next_actions(state(conditions=cond))
        self.assertTrue(any("公開できない" in x and "2自治体" in x for x in got))

    def test_公開データに条件の記録が無ければ言う(self):
        pub = {p: {"ok": True, "generated_at": "x", "age_days": 1.0,
                   "has_conditions": False} for p in ("tennyu",)}
        pub.update({p: {"ok": True, "generated_at": "x", "age_days": 1.0,
                        "has_conditions": True} for p in ("jidouteate", "sodaigomi")})
        got = next_actions(state(published=pub))
        self.assertTrue(any("追えない" in x for x in got))

    def test_止まっていなければそう言う(self):
        self.assertEqual(next_actions(state()), ["止まっているものは無い"])

    def test_虱潰しのエラーを拾う(self):
        sw = {p: {"ok": True, "fields": 1, "pages": 1, "found": 0, "exhausted": 1,
                  "unreadable": 0, "errored": 0, "budget": 0}
              for p in ("tennyu", "jidouteate", "sodaigomi")}
        sw["tennyu"]["errored"] = 2
        got = next_actions(state(sweep=sw))
        self.assertTrue(any("エラーが2件" in x for x in got))


class 表示(unittest.TestCase):
    def test_5つの見出しが出る(self):
        text = render(state())
        for head in ("① 見張り", "② 測定条件", "③ 虱潰し", "④ 読めない底", "⑤ 公開データ"):
            self.assertIn(head, text)

    def test_古い見張りには印が付く(self):
        text = render(state(watch={"ok": True, "age_days": WATCH_STALE_DAYS + 1,
                                   "stale": True, "pages": 68, "changed": 1, "gone": 0}))
        self.assertIn("★古い", text)

    def test_条件の記録が無いものに印が付く(self):
        pub = {p: {"ok": True, "generated_at": "x", "age_days": 1.0,
                   "has_conditions": False} for p in ("tennyu", "jidouteate", "sodaigomi")}
        self.assertIn("★条件の記録なし", render(state(published=pub)))

    def test_見張りが無くても落ちない(self):
        text = render(state(watch={"ok": False, "note": "site-status.json が無い"}))
        self.assertIn("site-status.json が無い", text)


class 状態を履歴に残す(unittest.TestCase):
    """**なぜ要るか**: `status.py` は毎セッション走るが読むだけだった。
    「いつ条件が崩れたか」「読めない底がいつ増えたか」を後から言えない。"""

    def snap(self, **kw) -> dict:
        return snapshot(state(**kw), "2026-09-02T16:00:00+00:00")

    def test_日で重複判定する(self):
        # ★毎セッション走るので、時刻で見ると1日に何行も入る。
        self.assertEqual(self.snap()["recorded_day"], "2026-09-02")

    def test_条件が崩れた数を残す(self):
        cond = {p: {"municipalities": 24, "stale": ["a", "b"], "uniform": False}
                for p in ("tennyu", "jidouteate", "sodaigomi")}
        self.assertEqual(self.snap(conditions=cond)["conditions_stale"]["tennyu"], 2)

    def test_読めない底の本数を残す(self):
        self.assertEqual(self.snap(blockers={"urls": 7})["blockers"], 7)

    def test_虱潰しの数を残す(self):
        got = self.snap()["sweep"]["tennyu"]
        self.assertEqual(got["exhausted"], 1)
        self.assertIn("unreadable", got)

    def test_区の名前もURLも持たない(self):
        """★数だけ残す。名前まで持つと、履歴が公開データの複製になる。"""
        import json
        text = json.dumps(self.snap(), ensure_ascii=False)
        self.assertNotIn("http", text)
        self.assertNotIn("municipality", text)

    def test_公開データに条件があるかを残す(self):
        pub = {p: {"ok": True, "generated_at": "x", "age_days": 1.0,
                   "has_conditions": False} for p in ("tennyu", "jidouteate", "sodaigomi")}
        self.assertFalse(self.snap(published=pub)["published_has_conditions"]["tennyu"])


class 参照が古いだけのとき(unittest.TestCase):
    """**なぜ要るか**: `origin/main` を fetch していないと、見張りが止まって見える。
    実測で「3.7日前・止まっている」と誤報し、動いているワークフローを調べに行った。"""

    def test_fetchを先に促す(self):
        w = {"ok": True, "age_days": 3.7, "stale": True, "pages": 68, "changed": 29,
             "gone": 0, "ref_age_days": 3.7, "maybe_unfetched": True}
        todo = " ".join(next_actions(state(watch=w)))
        self.assertIn("git fetch origin main", todo)

    def test_参照が新しければワークフローを疑う(self):
        w = {"ok": True, "age_days": 3.7, "stale": True, "pages": 68, "changed": 29,
             "gone": 0, "ref_age_days": 0.1, "maybe_unfetched": False}
        todo = " ".join(next_actions(state(watch=w)))
        self.assertIn("check-pages.yml", todo)
        self.assertNotIn("git fetch", todo)


class 実データ(unittest.TestCase):
    def test_いまのリポジトリで動く(self):
        # ★作った入力だけでは、実際のファイルの形が変わったときに気づけない。
        import status as mod
        text = mod.render(mod.collect())
        self.assertIn("次にやること", text)


if __name__ == "__main__":
    unittest.main()

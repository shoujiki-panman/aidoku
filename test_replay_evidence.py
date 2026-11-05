"""`analysis/probes/replay_evidence.py` — 保存済みの引用の再判定。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis" / "probes"))
from replay_evidence import apply_replay, no_llm, replay  # noqa: E402

PAGE = "届出に必要なもの。届出人。本人であることを確認できるものをお持ちください。"


def visit(evidence, found=True, verified=False):
    return {"url": "u", "found": found, "verified": verified, "evidence": evidence,
            "evidence_check": {"verdict": "partial"}}


class 判定し直す(unittest.TestCase):
    def test_断片に分ければ本文にある引用は通る(self):
        got = replay({"k": visit("届出に必要なもの。本人であることを確認できるものをお持ちください。")}, lambda _: PAGE)
        self.assertEqual((got[0]["before"], got[0]["after"], got[0]["now_verified"]), ("partial", "segmented", True))

    def test_本文にない引用は通らない(self):
        self.assertFalse(replay({"k": visit("届出に必要なもの。住民税の納税証明書をお持ちください。")},
                                lambda _: PAGE)[0]["now_verified"])

    def test_通っていた判定と無かった判定は対象にしない(self):
        visits = {"a": visit("x", verified=True), "b": visit("x", found=False)}
        self.assertEqual(replay(visits, lambda _: PAGE), [])

    def test_本文が取れなければ通さない(self):
        got = replay({"k": visit(PAGE)}, lambda _: None)
        self.assertEqual((got[0]["after"], got[0]["now_verified"]), ("not_checked", False))

    def test_記録以外の値は読み飛ばす(self):
        self.assertEqual(replay({"schema": 1}, lambda _: PAGE), [])


class 反映する(unittest.TestCase):
    def test_通るようになった判定だけ直す(self):
        ok = visit("届出に必要なもの。本人であることを確認できるものをお持ちください。")
        ng = visit("届出に必要なもの。住民税の納税証明書をお持ちください。")
        self.assertEqual(apply_replay({"ok": ok, "ng": ng}, lambda _: PAGE), ["ok"])
        self.assertEqual((ok["verified"], ok["evidence_check"]["verdict"]), (True, "segmented"))
        self.assertEqual((ng["verified"], ng["evidence_check"]["verdict"]), (False, "partial"))

    def test_二度反映しても変わらない(self):
        visits = {"ok": visit("届出に必要なもの。本人であることを確認できるものをお持ちください。")}
        apply_replay(visits, lambda _: PAGE)
        self.assertEqual(apply_replay(visits, lambda _: PAGE), [])

    def test_記録に無ければLLMを呼ばずに止める(self):
        with self.assertRaises(SystemExit):
            no_llm("page")


if __name__ == "__main__":
    unittest.main()

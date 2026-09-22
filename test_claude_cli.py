"""`claude -p` を道具を閉じた状態で呼んでいるかを固定する。

LLM は呼ばない。subprocess.run を差し替えて、渡した引数と cwd だけを見る。
"""

import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import claude_cli

ROOT = Path(__file__).resolve().parent


class LockedCmdTest(unittest.TestCase):
    def test_default_closes_every_tool(self):
        cmd = claude_cli.locked_cmd("m")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", cmd)

    def test_named_tools_are_the_only_ones_open(self):
        cmd = claude_cli.locked_cmd("m", tools=["WebSearch", "WebFetch"])
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,WebFetch")
        self.assertIn("--strict-mcp-config", cmd)

    def test_system_prompt_is_passed_only_when_given(self):
        self.assertNotIn("--system-prompt", claude_cli.locked_cmd("m"))
        cmd = claude_cli.locked_cmd("m", system="S")
        self.assertEqual(cmd[cmd.index("--system-prompt") + 1], "S")


class RunLockedTest(unittest.TestCase):
    def _run(self, returncode=0):
        done = subprocess.CompletedProcess([], returncode, stdout="out", stderr="err")
        with mock.patch.object(claude_cli.subprocess, "run", return_value=done) as run:
            result = claude_cli.run_locked("p", "m")
        return result, run

    def test_runs_outside_the_repository(self):
        # リポジトリの中だと CLAUDE.md と scorer/golden（正解）が見える
        _, run = self._run()
        cwd = Path(run.call_args.kwargs["cwd"]).resolve()
        self.assertEqual(cwd, claude_cli.NEUTRAL_DIR.resolve())
        self.assertNotIn(ROOT, [cwd, *cwd.parents])

    def test_failure_is_raised_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            self._run(returncode=1)


class NoBareCallTest(unittest.TestCase):
    """claude_cli を通さずに `claude -p` を組み立てている .py が無いこと。"""

    def test_every_call_goes_through_claude_cli(self):
        bare = re.compile(r'\[\s*"claude"\s*,\s*"-p"')
        offenders = []
        for path in ROOT.rglob("*.py"):
            rel = path.relative_to(ROOT)
            if rel.parts[0] in {".git", "node_modules"} or path.name == "claude_cli.py":
                continue
            if bare.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(rel))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

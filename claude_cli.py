"""測定で `claude -p` を呼ぶときの共通の口。ツールを塞いだ状態で呼ぶ。

★なぜ要るか（2026-09-23 に確かめた）:
  抽出（extractor）も採点（scorer）も `claude -p` をそのまま呼んでいた。
  既定では Bash・WebFetch・MCP が全部開いていて、cwd はリポジトリ。
  つまり**渡したページ以外を取りに行けたし、scorer/golden（正解）も読めた。**
  cold_ask の「検索なし」も WebSearch/WebFetch だけを塞いでいて、Bash の curl は通っていた。
  測っているのは「渡した文面から読めるか」なので、道具は全部閉じる。

★cwd も中立な場所にする。リポジトリの中で走らせると CLAUDE.md を読み、
  「私はAI読の開発ツールです」と答えてしまう（cold_ask で実際に起きた）。
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

NEUTRAL_DIR = Path(tempfile.gettempdir()) / "aidoku-claude-neutral"
DEFAULT_TIMEOUT = 300


def locked_cmd(model: str, *, tools: Sequence[str] = (), system: str | None = None) -> list[str]:
    """`claude -p` の引数。tools に名前の無い道具は使えない（既定は全部閉じる）。"""
    cmd = ["claude", "-p", "--model", model, "--output-format", "text",
           "--tools", ",".join(tools), "--strict-mcp-config"]
    if system is not None:
        cmd += ["--system-prompt", system]
    return cmd


def run_locked(prompt: str, model: str, *, tools: Sequence[str] = (), system: str | None = None,
               timeout: int = DEFAULT_TIMEOUT) -> str:
    """道具を閉じ、中立な cwd で1回呼ぶ。失敗は黙らずに例外にする。"""
    NEUTRAL_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        locked_cmd(model, tools=tools, system=system),
        input=prompt, capture_output=True, text=True, timeout=timeout, cwd=NEUTRAL_DIR,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {proc.stderr[:500]}")
    return proc.stdout

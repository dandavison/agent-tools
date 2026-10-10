#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest"]
# ///
"""Tests for agent, using fake claude and codex executables."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SCRIPT_PATH = REPO / "bin" / "agent"

CONFIG = """
[accounts.personal]
CLAUDE_CONFIG_DIR = "/tmp/claude-personal"

[[models]]
name = "opus"
cli = "claude"
model = "claude-opus-5-5"

[[models]]
name = "luna"
cli = "codex"
model = "gpt-6-luna"
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "agent-models.toml").write_text(CONFIG)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for cli in ["claude", "codex"]:
        (bin_dir / cli).write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$@" > "{bin_dir}/{cli}.argv"\n'
            f'echo "${{CLAUDE_CONFIG_DIR:-}}" > "{bin_dir}/{cli}.env"\n'
        )
        (bin_dir / cli).chmod(0o755)
    (bin_dir / "agent-pick").symlink_to(REPO / "bin" / "agent-pick")
    return tmp_path


def run(
    home: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    base_env = {k: v for k, v in os.environ.items() if k != "AGENT_MODEL"}
    return subprocess.run(
        [str(SCRIPT_PATH), *args],
        capture_output=True,
        check=False,
        text=True,
        stdin=subprocess.DEVNULL,
        env={
            **base_env,
            "PATH": f"{home / 'bin'}:{os.environ['PATH']}",
            "AGENT_MODELS": str(home / "agent-models.toml"),
            **(env or {}),
        },
    )


def argv(home: Path, cli: str) -> list[str]:
    return (home / "bin" / f"{cli}.argv").read_text().splitlines()


def test_starts_cli_with_model_and_passes_args(home: Path) -> None:
    result = run(home, "-m", "opus", "--resume", "abc")
    assert result.returncode == 0, result.stderr
    assert argv(home, "claude") == ["--model", "claude-opus-5-5", "--resume", "abc"]


def test_personal_sets_account_env(home: Path) -> None:
    result = run(home, "--personal", "-m", "opus")
    assert result.returncode == 0, result.stderr
    assert (home / "bin" / "claude.env").read_text().strip() == "/tmp/claude-personal"


def test_agent_model_env_overrides_m(home: Path) -> None:
    result = run(home, "-m", "opus", env={"AGENT_MODEL": "luna"})
    assert result.returncode == 0, result.stderr
    assert argv(home, "codex") == ["--model", "gpt-6-luna"]

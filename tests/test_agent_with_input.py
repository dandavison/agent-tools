#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest"]
# ///
"""Tests for agent-with-input, using fake tmux, claude and codex executables."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SCRIPT_PATH = REPO / "bin" / "agent-with-input"

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

FAKE_TMUX = """\
case "$1" in
    load-buffer) cat > /dev/null ;;
    display-message) echo /dev/null ;;
    capture-pane) echo "Claude Code" ;;
esac
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "agent-models.toml").write_text(CONFIG)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "tmux").write_text(f"#!/usr/bin/env bash\n{FAKE_TMUX}")
    (bin_dir / "tmux").chmod(0o755)
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
    return subprocess.run(
        [str(SCRIPT_PATH), *args],
        capture_output=True,
        check=False,
        text=True,
        input="the input",
        env={
            **{k: v for k, v in os.environ.items() if k != "AGENT_MODEL"},
            "PATH": f"{home / 'bin'}:{os.environ['PATH']}",
            "AGENT_MODELS": str(home / "agent-models.toml"),
            "TMUX": "fake",
            "TMUX_PANE": "%0",
            **(env or {}),
        },
    )


def argv(home: Path, cli: str) -> list[str]:
    return (home / "bin" / f"{cli}.argv").read_text().splitlines()


def test_m_starts_picked_cli_with_model(home: Path) -> None:
    result = run(home, "-m", "luna")
    assert result.returncode == 0, result.stderr
    assert argv(home, "codex") == ["--model", "gpt-6-luna"]


def test_personal_sets_account_env(home: Path) -> None:
    result = run(home, "--personal", "-m", "opus")
    assert result.returncode == 0, result.stderr
    assert argv(home, "claude") == ["--model", "claude-opus-5-5"]
    assert (home / "bin" / "claude.env").read_text().strip() == "/tmp/claude-personal"


def test_agent_model_env_overrides_m(home: Path) -> None:
    result = run(home, "-m", "opus", env={"AGENT_MODEL": "luna"})
    assert result.returncode == 0, result.stderr
    assert argv(home, "codex") == ["--model", "gpt-6-luna"]


def test_explicit_agent_is_not_picked(home: Path) -> None:
    result = run(home, "--", "codex", "x")
    assert result.returncode == 0, result.stderr
    assert argv(home, "codex") == ["x"]


def test_failed_pick_starts_nothing(home: Path) -> None:
    result = run(home, "-m", "nonexistent")
    assert result.returncode != 0
    assert not (home / "bin" / "claude.argv").exists()

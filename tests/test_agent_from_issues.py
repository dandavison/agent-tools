#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest"]
# ///
"""Tests for agent-from-issues, using fake gh-issue-to-md and agent-with-input executables."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "bin" / "agent-from-issues"

CONFIG = """
default_repo = "owl/notes"

[labels]
"owl/notes" = "my notes repo"
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in [
        ("gh-issue-to-md", 'echo "content of $1"'),
        (
            "agent-with-input",
            f'cat > {tmp_path}/prompt; printf "%s\\n" "$@" > {tmp_path}/agent',
        ),
    ]:
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    (tmp_path / "agent-from-issues.toml").write_text(CONFIG)
    return tmp_path


def run(
    home: Path, *args: str, config: bool = True
) -> subprocess.CompletedProcess[str]:
    config_path = home / ("agent-from-issues.toml" if config else "missing.toml")
    return subprocess.run(
        [str(SCRIPT_PATH), *args],
        capture_output=True,
        check=False,
        text=True,
        env={
            **os.environ,
            "PATH": f"{home / 'bin'}:{os.environ['PATH']}",
            "AGENT_FROM_ISSUES_CONFIG": str(config_path),
        },
    )


def test_issue_number_uses_default_repo_and_label(home: Path) -> None:
    result = run(home, "7", "--", "fake-agent")
    assert result.returncode == 0, result.stderr
    prompt = (home / "prompt").read_text()
    assert "Here is the content of issue #7 from my notes repo:" in prompt
    assert "content of https://github.com/owl/notes/issues/7" in prompt
    assert (home / "agent").read_text().splitlines() == ["--", "fake-agent"]


def test_url_without_label_uses_repo_name(home: Path) -> None:
    result = run(home, "https://github.com/macaw/nest/issues/3", "--", "fake-agent")
    assert result.returncode == 0, result.stderr
    assert "issue #3 from macaw/nest:" in (home / "prompt").read_text()


def test_issue_number_without_default_repo_fails(home: Path) -> None:
    result = run(home, "7", "--", "fake-agent", config=False)
    assert result.returncode != 0
    assert "default_repo" in result.stderr


def test_model_args_go_to_agent_with_input(home: Path) -> None:
    result = run(home, "--personal", "-m", "opus", "7")
    assert result.returncode == 0, result.stderr
    assert (home / "agent").read_text().splitlines() == ["--personal", "-m", "opus"]

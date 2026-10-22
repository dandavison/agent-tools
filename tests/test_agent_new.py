"""Tests for agent-new, using fake agent-prepare-session, agent and agent-with-input."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SCRIPT_PATH = REPO / "bin" / "agent-new"

FAKE_PREPARE_SESSION = """\
printf '%s|' "$@" >> "$HOME/prepare.calls"; echo >> "$HOME/prepare.calls"
echo "the report"
[[ -n "${NO_RECIPE:-}" ]] && exit 0
cd "$HOME/src/temporalio-etc/log"
echo "$*" >> recipes/meeting.toml
git add recipes/meeting.toml && git commit -qm recipe
"""

FAKE_AGENT = 'printf "context of %s" "$2"\n'

FAKE_WITH_INPUT = """\
printf '%s\\n' "$@" > "$HOME/with-input.argv"
cat > "$HOME/with-input.stdin"
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    log = tmp_path / "src" / "temporalio-etc" / "log"
    (log / "recipes").mkdir(parents=True)
    git = ["git", "-C", str(log), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git[:3], "init", "-q"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in [
        ("agent-prepare-session", FAKE_PREPARE_SESSION),
        ("agent", FAKE_AGENT),
        ("agent-with-input", FAKE_WITH_INPUT),
    ]:
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}")
        (bin_dir / name).chmod(0o755)
    return tmp_path


def run(
    home: Path, *args: str, input: str = "\n", env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT_PATH), *args],
        capture_output=True,
        check=False,
        text=True,
        input=input,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{home / 'bin'}:{os.environ['PATH']}",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            **(env or {}),
        },
    )


def recipe(home: Path) -> str:
    return str(home / "src" / "temporalio-etc" / "log" / "recipes" / "meeting.toml")


def test_description_prepares_then_enter_starts_session(home: Path) -> None:
    result = run(home, "prepare for the meeting")
    assert result.returncode == 0, result.stderr
    assert "the report" in result.stdout
    assert (home / "prepare.calls").read_text() == "prepare for the meeting|\n"
    assert (home / "with-input.stdin").read_text() == f"context of {recipe(home)}"


def test_typed_changes_revise_recipe_before_starting(home: Path) -> None:
    result = run(home, "prepare for the meeting", input="add issue 12\n\n")
    assert result.returncode == 0, result.stderr
    assert (home / "prepare.calls").read_text() == (
        f"prepare for the meeting|\n{recipe(home)}|add issue 12|\n"
    )
    assert (home / "with-input.stdin").read_text() == f"context of {recipe(home)}"


def test_recipe_path_starts_without_preparing(home: Path) -> None:
    result = run(home, recipe(home))
    assert result.returncode == 0, result.stderr
    assert not (home / "prepare.calls").exists()
    assert (home / "with-input.stdin").read_text() == f"context of {recipe(home)}"


def test_no_committed_recipe_fails_without_starting(home: Path) -> None:
    result = run(home, "prepare for the meeting", env={"NO_RECIPE": "1"})
    assert result.returncode != 0
    assert "no recipe" in result.stderr
    assert not (home / "with-input.stdin").exists()


def test_model_options_go_to_with_input(home: Path) -> None:
    result = run(home, "--personal", "-m", "opus", recipe(home))
    assert result.returncode == 0, result.stderr
    assert (home / "with-input.argv").read_text() == "--personal\n-m\nopus\n"


def test_eof_at_prompt_exits_without_starting(home: Path) -> None:
    result = run(home, recipe(home), input="")
    assert result.returncode != 0
    assert not (home / "with-input.stdin").exists()

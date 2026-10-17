"""Tests for the agent CLI, using fake claude, codex and agent-* executables."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
AGENT = Path(sys.executable).parent / "agent"

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

WRAPPED = ["with-input", "from-issues", "run", "pick", "prices-refresh", "mlx-serve"]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "agent-models.toml").write_text(CONFIG)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for cli in ["claude", "codex"] + [f"agent-{w}" for w in WRAPPED if w != "pick"]:
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
        [str(AGENT), *args],
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


def test_bare_agent_starts_cli_with_model(home: Path) -> None:
    result = run(home, "-m", "opus")
    assert result.returncode == 0, result.stderr
    assert argv(home, "claude") == ["--model", "claude-opus-5-5"]


def test_start_passes_args(home: Path) -> None:
    result = run(home, "start", "-m", "opus", "--resume", "abc")
    assert result.returncode == 0, result.stderr
    assert argv(home, "claude") == ["--model", "claude-opus-5-5", "--resume", "abc"]


def test_bare_agent_passes_option_args(home: Path) -> None:
    result = run(home, "-m", "opus", "-r")
    assert result.returncode == 0, result.stderr
    assert argv(home, "claude") == ["--model", "claude-opus-5-5", "-r"]


def test_bare_agent_passes_option_args_with_values(home: Path) -> None:
    result = run(home, "-m", "opus", "--resume", "abc")
    assert result.returncode == 0, result.stderr
    assert argv(home, "claude") == ["--model", "claude-opus-5-5", "--resume", "abc"]


def test_personal_sets_account_env(home: Path) -> None:
    result = run(home, "start", "--personal", "-m", "opus")
    assert result.returncode == 0, result.stderr
    assert (home / "bin" / "claude.env").read_text().strip() == "/tmp/claude-personal"


def test_agent_model_env_overrides_m(home: Path) -> None:
    result = run(home, "-m", "opus", env={"AGENT_MODEL": "luna"})
    assert result.returncode == 0, result.stderr
    assert argv(home, "codex") == ["--model", "gpt-6-luna"]


def test_help_documents_every_subcommand_in_full(home: Path) -> None:
    result = run(home, "--help")
    assert result.returncode == 0, result.stderr
    for subcommand in ["start", *WRAPPED]:
        assert f"\n  {subcommand}\n" in result.stdout, subcommand
    assert "agent from-issues [-R OWNER/REPO]" in result.stdout


@pytest.mark.parametrize("subcommand", [w for w in WRAPPED if w != "pick"])
def test_subcommand_runs_its_script_with_args(home: Path, subcommand: str) -> None:
    result = run(home, subcommand, "-m", "opus", "--", "x")
    assert result.returncode == 0, result.stderr
    assert argv(home, f"agent-{subcommand}") == ["-m", "opus", "--", "x"]


def test_ctrl_c_in_pick_exits_without_traceback(home: Path) -> None:
    pick = home / "bin" / "agent-pick"
    pick.unlink()
    pick.write_text("#!/usr/bin/env bash\nexit 130\n")
    pick.chmod(0o755)
    result = run(home)
    assert result.returncode == 130
    assert "Traceback" not in result.stderr
    assert not (home / "bin" / "claude.argv").exists()

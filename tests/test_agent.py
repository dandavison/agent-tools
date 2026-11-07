"""Tests for the agent CLI, using fake claude, codex and agent-* executables."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
AGENT = Path(sys.executable).parent / "agent"
LIBEXEC = REPO / "src" / "agent_tools" / "libexec"
PATH_WITHOUT_SCRIPTS = ":".join(
    d for d in os.environ["PATH"].split(":") if not (Path(d) / "agent-pick").exists()
)

CONFIG = """
[accounts.work]
paths = ["ROOT/work"]

[accounts.personal]
paths = ["ROOT/personal"]
env = { CLAUDE_CONFIG_DIR = "/tmp/claude-personal" }

[[models]]
name = "opus"
cli = "claude"
model = "claude-opus-5-5"

[[models]]
name = "sonnet"
cli = "claude"
model = "claude-sonnet-5-5"
efforts = ["low", "high", "max"]
effort = "high"

[[models]]
name = "terra"
cli = "codex"
model = "gpt-6-terra"
efforts = ["low", "xhigh"]

[[models]]
name = "luna"
cli = "codex"
model = "gpt-6-luna"
"""

WRAPPED = [
    "with-input",
    "from-issues",
    "run",
    "pick",
    "prices-refresh",
    "mlx-serve",
    "prepare-session",
    "new",
    "exfiltrate",
    "suggest-command",
]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "agent-models.toml").write_text(CONFIG.replace("ROOT", str(tmp_path)))
    (tmp_path / "work").mkdir()
    (tmp_path / "personal").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    libexec = tmp_path / "libexec"
    libexec.mkdir()
    scripts = [f"agent-{w}" for w in WRAPPED if w != "pick"]
    for dir, cli in [(bin_dir, "claude"), (bin_dir, "codex")] + [
        (libexec, s) for s in scripts
    ]:
        (dir / cli).write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$@" > "{bin_dir}/{cli}.argv"\n'
            f'echo "${{CLAUDE_CONFIG_DIR:-}}" > "{bin_dir}/{cli}.env"\n'
        )
        (dir / cli).chmod(0o755)
    (libexec / "agent-pick").symlink_to(LIBEXEC / "agent-pick")
    return tmp_path


def run(
    home: Path,
    *args: str,
    env: dict[str, str] | None = None,
    fake_scripts: bool = True,
    cwd: str = "work",
) -> subprocess.CompletedProcess[str]:
    base_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ["AGENT_MODEL", "AGENT_EXEC_PATH"]
    }
    exec_path = {"AGENT_EXEC_PATH": str(home / "libexec")} if fake_scripts else {}
    return subprocess.run(
        [str(AGENT), *args],
        capture_output=True,
        check=False,
        text=True,
        cwd=home / cwd,
        stdin=subprocess.DEVNULL,
        env={
            **base_env,
            "PATH": f"{home / 'bin'}:{PATH_WITHOUT_SCRIPTS}",
            "AGENT_MODELS": str(home / "agent-models.toml"),
            **exec_path,
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
    result = run(home, "start", "--personal", "-m", "opus", cwd="personal")
    assert result.returncode == 0, result.stderr
    assert (home / "bin" / "claude.env").read_text().strip() == "/tmp/claude-personal"


@pytest.mark.parametrize("script", ["with-input", "from-issues", "run", "new"])
@pytest.mark.parametrize("personal", ["--personal", "-p"])
def test_personal_before_script_goes_to_script(
    home: Path, script: str, personal: str
) -> None:
    result = run(home, personal, "-m", "opus", script, "x")
    assert result.returncode == 0, result.stderr
    assert argv(home, f"agent-{script}") == ["--personal", "-m", "opus", "x"]


@pytest.mark.parametrize("script", ["prices-refresh", "exfiltrate"])
@pytest.mark.parametrize("option", [["-p"], ["-m", "opus"]])
def test_option_before_script_without_it_fails(
    home: Path, script: str, option: list[str]
) -> None:
    result = run(home, *option, script)
    assert result.returncode != 0
    assert not (home / "bin" / f"agent-{script}.argv").exists()


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


def test_runs_its_own_scripts_without_them_on_path(home: Path) -> None:
    result = run(home, "-m", "opus", fake_scripts=False)
    assert result.returncode == 0, result.stderr
    assert argv(home, "claude") == ["--model", "claude-opus-5-5"]


@pytest.mark.parametrize(
    ("subcommand", "args"), [("with-input", ["401"]), ("new", []), ("from-issues", [])]
)
def test_usage_names_the_subcommand(
    home: Path, subcommand: str, args: list[str]
) -> None:
    result = run(home, subcommand, *args, fake_scripts=False)
    assert result.returncode == 1
    assert result.stderr.startswith(f"Usage: agent {subcommand} "), result.stderr


def test_agent_is_the_only_installed_executable() -> None:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert list(pyproject["project"]["scripts"]) == ["agent"]


@pytest.mark.parametrize("name", ["prepare-session", "exfiltrate", "suggest-command"])
def test_procedure_is_a_prompt_script_run_by_agent_run(name: str) -> None:
    script = LIBEXEC / f"agent-{name}"
    assert os.access(script, os.X_OK)
    assert script.read_text().startswith("#!/usr/bin/env -S agent run ")


def test_ctrl_c_in_pick_exits_without_traceback(home: Path) -> None:
    pick = home / "libexec" / "agent-pick"
    pick.unlink()
    pick.write_text("#!/usr/bin/env bash\nexit 130\n")
    pick.chmod(0o755)
    result = run(home)
    assert result.returncode == 130
    assert "Traceback" not in result.stderr
    assert not (home / "bin" / "claude.argv").exists()


@pytest.mark.parametrize("words", ["agent -m ", "agent start -m "])
def test_m_completes_model_names(home: Path, words: str) -> None:
    result = run(
        home,
        env={
            "_AGENT_COMPLETE": "bash_complete",
            "COMP_WORDS": words,
            "COMP_CWORD": str(len(words.split())),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "plain,opus",
        "plain,sonnet",
        "plain,terra",
        "plain,luna",
    ]


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("agent sessions se", {"search", "serve"}),
        ("agent sessions search --s", {"--since"}),
    ],
)
def test_sessions_completes_its_commands_and_options(
    home: Path, words: str, expected: set[str]
) -> None:
    result = run(
        home,
        env={
            "_AGENT_COMPLETE": "bash_complete",
            "COMP_WORDS": words,
            "COMP_CWORD": str(len(words.split()) - 1),
        },
    )
    assert result.returncode == 0, result.stderr
    assert expected <= {line.split(",")[-1] for line in result.stdout.splitlines()}


def test_sessions_runs_agent_sessions_with_its_help(home: Path) -> None:
    result = run(home, "sessions", "--help")
    assert result.returncode == 0, result.stderr
    assert (
        "Find and resume the sessions you have had with coding agents." in result.stdout
    )


def test_sessions_keeps_agent_sessions_exit_codes(home: Path) -> None:
    result = run(home, "sessions", "search")
    assert result.returncode == 2
    assert "QUERY" in result.stderr


def test_help_lists_sessions(home: Path) -> None:
    result = run(home, "--help")
    assert "\n  sessions\n" in result.stdout


def test_print_prompt_prints_a_procedure_instead_of_running_it(home: Path) -> None:
    result = run(
        home, "exfiltrate", "--print-prompt", "batch cancel", fake_scripts=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("You exfiltrate a topic")
    assert result.stdout.rstrip().endswith("Arguments: batch cancel")
    assert not (home / "bin" / "claude.argv").exists()


@pytest.mark.parametrize("script", ["with-input", "from-issues", "run", "new"])
@pytest.mark.parametrize("work", ["--work", "-w"])
def test_work_before_script_goes_to_script(home: Path, script: str, work: str) -> None:
    result = run(home, work, "-m", "opus", script, "x")
    assert result.returncode == 0, result.stderr
    assert argv(home, f"agent-{script}") == ["--work", "-m", "opus", "x"]


def test_session_in_unmatched_path_fails(home: Path) -> None:
    (home / "other").mkdir()
    result = run(home, "-m", "opus", cwd="other")
    assert result.returncode != 0
    assert not (home / "bin" / "claude.argv").exists()


@pytest.mark.parametrize(("flag", "cwd"), [("-p", "work"), ("-w", "personal")])
def test_session_account_flag_contradicting_path_fails(
    home: Path, flag: str, cwd: str
) -> None:
    result = run(home, flag, "-m", "opus", cwd=cwd)
    assert result.returncode != 0
    assert not (home / "bin" / "claude.argv").exists()


def test_effort_goes_to_cli(home: Path) -> None:
    result = run(home, "-m", "sonnet", "-e", "high", "-r")
    assert result.returncode == 0, result.stderr
    assert argv(home, "claude") == [
        "--model",
        "claude-sonnet-5-5",
        "--effort",
        "high",
        "-r",
    ]


@pytest.mark.parametrize("script", ["with-input", "from-issues", "run", "new"])
def test_effort_before_script_goes_to_script(home: Path, script: str) -> None:
    result = run(home, "-e", "high", script, "x")
    assert result.returncode == 0, result.stderr
    assert argv(home, f"agent-{script}") == ["-e", "high", "x"]

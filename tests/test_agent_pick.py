#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest"]
# ///
"""Tests for agent-pick."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).parent.parent / "src" / "agent_tools" / "libexec" / "agent-pick"
)

CONFIG = """
[accounts.work]
paths = ["ROOT/work"]

[accounts.personal]
paths = ["ROOT/personal", "ROOT/also-personal"]
env = { CLAUDE_CONFIG_DIR = "~/.claude-personal", CODEX_HOME = "/tmp/codex-personal" }

[[models]]
name = "opus"
cli = "claude"
model = "claude-opus-5-5"

[[models]]
name = "luna"
cli = "codex"
model = "gpt-6-luna"
openrouter = "openai/gpt-6-luna"

[[models]]
name = "qwen-local"
cli = "pi"
model = "mlx/qwen"
health = "http://127.0.0.1:1/v1/models"
"""


OPENROUTER_MODELS = {
    "data": [
        {
            "id": "openai/gpt-6-luna",
            "pricing": {
                "prompt": "0.0000001",
                "completion": "0.0000005",
                "input_cache_read": "0.00000001",
                "input_cache_write": "0.000000125",
            },
        }
    ]
}


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "agent-models.toml"
    path.write_text(CONFIG.replace("ROOT", str(tmp_path)))
    for d in ["work", "personal", "also-personal", "other"]:
        (tmp_path / d).mkdir()
    (tmp_path / "openrouter-models.json").write_text(json.dumps(OPENROUTER_MODELS))
    return path


def run(
    config: Path,
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT_PATH), *args],
        capture_output=True,
        check=False,
        text=True,
        cwd=cwd or config.parent / "work",
        env={
            **{k: v for k, v in os.environ.items() if k != "AGENT_MODEL"},
            "AGENT_MODELS": str(config),
            "AGENT_PRICES": str(config.parent / "openrouter-models.json"),
            **(env or {}),
        },
    )


def test_pick_by_name(config: Path) -> None:
    result = run(config, "luna")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "name": "luna",
        "cli": "codex",
        "model": "gpt-6-luna",
        "account": "work",
        "env": {},
        "price": {
            "input": 0.10,
            "cached_input": 0.01,
            "cache_write": 0.125,
            "output": 0.50,
        },
    }


def test_price_is_null_without_openrouter_id(config: Path) -> None:
    result = run(config, "opus")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["price"] is None


@pytest.mark.parametrize("personal", ["--personal", "-p"])
def test_personal_sets_account_env(config: Path, personal: str) -> None:
    result = run(config, personal, "opus", cwd=config.parent / "personal")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["env"] == {
        "CLAUDE_CONFIG_DIR": str(Path("~/.claude-personal").expanduser()),
        "CODEX_HOME": "/tmp/codex-personal",
    }


def test_list_excludes_unhealthy_local_model(config: Path) -> None:
    result = run(config, "--list")
    assert result.returncode == 0, result.stderr
    assert [line.split()[0] for line in result.stdout.splitlines()] == ["opus", "luna"]


def test_unhealthy_local_model_by_name_fails(config: Path) -> None:
    result = run(config, "qwen-local")
    assert result.returncode != 0
    assert "qwen-local" in result.stderr


def test_unknown_name_fails(config: Path) -> None:
    result = run(config, "nope")
    assert result.returncode != 0
    assert "nope" in result.stderr


def test_agent_model_env_overrides_name(config: Path) -> None:
    result = run(config, "opus", env={"AGENT_MODEL": "luna"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["name"] == "luna"


def test_missing_price_cache_fails(config: Path) -> None:
    (config.parent / "openrouter-models.json").unlink()
    result = run(config, "luna")
    assert result.returncode != 0
    assert "agent prices-refresh" in result.stderr


def test_ctrl_c_in_fzf_exits_without_traceback(config: Path) -> None:
    fzf = config.parent / "fzf"
    fzf.write_text("#!/usr/bin/env bash\nkill -INT $PPID\nsleep 1\nexit 130\n")
    fzf.chmod(0o755)
    result = subprocess.run(
        [str(SCRIPT_PATH)],
        capture_output=True,
        check=False,
        text=True,
        cwd=config.parent / "work",
        env={
            **{k: v for k, v in os.environ.items() if k != "AGENT_MODEL"},
            "PATH": f"{config.parent}:{os.environ['PATH']}",
            "AGENT_MODELS": str(config),
            "AGENT_PRICES": str(config.parent / "openrouter-models.json"),
        },
    )
    assert result.returncode == 130
    assert "Traceback" not in result.stderr


WORK_ORG = "11111111-1111-1111-1111-111111111111"
PERSONAL_ORG = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def home(config: Path) -> Path:
    config.write_text(
        config.read_text()
        .replace("[accounts.work]\n", f'[accounts.work]\nclaude_org = "{WORK_ORG}"\n')
        .replace(
            "[accounts.personal]\n",
            f'[accounts.personal]\nclaude_org = "{PERSONAL_ORG}"\n',
        )
    )
    (config.parent / ".claude-personal").mkdir()
    return config.parent


def log_in(store: Path, org: str) -> None:
    store.write_text(json.dumps({"oauthAccount": {"organizationUuid": org}}))


@pytest.mark.parametrize(
    ("personal", "store", "org"),
    [
        ([], ".claude.json", WORK_ORG),
        (["-p", "--anywhere"], ".claude-personal/.claude.json", PERSONAL_ORG),
    ],
)
def test_claude_store_logged_in_to_its_org_is_picked(
    home: Path, personal: list[str], store: str, org: str
) -> None:
    log_in(home / store, org)
    result = run(home / "agent-models.toml", *personal, "opus", env={"HOME": str(home)})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("personal", "store", "org"),
    [
        ([], ".claude.json", PERSONAL_ORG),
        (["-p", "--anywhere"], ".claude-personal/.claude.json", WORK_ORG),
    ],
)
def test_claude_store_logged_in_to_other_org_fails(
    home: Path, personal: list[str], store: str, org: str
) -> None:
    log_in(home / store, org)
    result = run(home / "agent-models.toml", *personal, "opus", env={"HOME": str(home)})
    assert result.returncode != 0
    assert org in result.stderr
    assert "/login" in result.stderr


def test_claude_store_not_logged_in_is_picked(home: Path) -> None:
    result = run(home / "agent-models.toml", "opus", env={"HOME": str(home)})
    assert result.returncode == 0, result.stderr


def test_codex_ignores_claude_store_org(home: Path) -> None:
    log_in(home / ".claude.json", PERSONAL_ORG)
    result = run(home / "agent-models.toml", "luna", env={"HOME": str(home)})
    assert result.returncode == 0, result.stderr


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.mark.parametrize(
    ("dir", "account"),
    [
        ("work", "work"),
        ("work/sub/dir", "work"),
        ("personal", "personal"),
        ("also-personal/x", "personal"),
    ],
)
def test_account_is_chosen_by_path(config: Path, dir: str, account: str) -> None:
    cwd = config.parent / dir
    cwd.mkdir(parents=True, exist_ok=True)
    result = run(config, "opus", cwd=cwd)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["account"] == account


def test_worktree_account_is_its_main_checkouts(config: Path) -> None:
    repo = config.parent / "personal" / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "commit", "-q", "--allow-empty", "-m", "x")
    worktree = config.parent / "other" / "task"
    git(repo, "worktree", "add", "-q", str(worktree))
    result = run(config, "opus", cwd=worktree)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["account"] == "personal"


def test_unmatched_path_without_account_flag_fails(config: Path) -> None:
    result = run(config, "opus", cwd=config.parent / "other")
    assert result.returncode != 0
    assert "-p" in result.stderr and "-w" in result.stderr


@pytest.mark.parametrize(
    ("flag", "account"),
    [
        ("-p", "personal"),
        ("--personal", "personal"),
        ("-w", "work"),
        ("--work", "work"),
    ],
)
def test_account_flag_chooses_account_for_unmatched_path(
    config: Path, flag: str, account: str
) -> None:
    result = run(config, flag, "opus", cwd=config.parent / "other")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["account"] == account


@pytest.mark.parametrize(("flag", "dir"), [("-p", "work"), ("-w", "personal")])
def test_account_flag_contradicting_path_fails(
    config: Path, flag: str, dir: str
) -> None:
    result = run(config, flag, "opus", cwd=config.parent / dir)
    assert result.returncode != 0
    assert str(config.parent / dir) in result.stderr


@pytest.mark.parametrize(
    ("flag", "dir", "account"), [("-p", "work", "personal"), ("-w", "personal", "work")]
)
def test_anywhere_lets_account_flag_override_path(
    config: Path, flag: str, dir: str, account: str
) -> None:
    result = run(config, flag, "--anywhere", "opus", cwd=config.parent / dir)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["account"] == account


def test_both_account_flags_fail(config: Path) -> None:
    result = run(config, "-p", "-w", "opus", cwd=config.parent / "other")
    assert result.returncode != 0

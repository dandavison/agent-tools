"""Tests for agent quiz, using fake claude, agent sessions and fzf."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
AGENT = Path(sys.executable).parent / "agent"

CONFIG = """
[[models]]
name = "opus"
cli = "claude"
model = "claude-opus-5-5"

[[models]]
name = "sonnet"
cli = "claude"
model = "claude-sonnet-5-5"
efforts = ["low", "high", "max"]

[[models]]
name = "terra"
cli = "codex"
model = "gpt-6-terra"
efforts = ["low", "xhigh"]
"""

RECIPE = """
purpose = "Prepare for the design review."
budget = 1000
provenance = "Chosen by hand."
related_sessions = ["claude:aaaa", "claude:bbbb"]
exclusions = []

[[sources]]
uri = "path:notes.md"
"""

FAKE_CLAUDE = """\
#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
argv, stdin = sys.argv[1:], sys.stdin.read()
home = Path(os.environ["QUIZ_HOME"])
with (home / "claude.calls").open("a") as f:
    f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "stdin": stdin}) + "\\n")
if "--resume" in argv:
    sid = argv[argv.index("--resume") + 1]
    sid = "fork1" if "--fork-session" in argv else sid
else:
    sid = "prep1"
counter = home / f"{sid}.n"
n = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(n))
who = "existing" if sid == "fork1" else "prepared"
total = (50.0 if who == "existing" else 0.0) + 0.1 * n
print(json.dumps({"session_id": sid, "result": f"{who} answers: {stdin.strip()[-12:]}",
                  "total_cost_usd": total}))
"""

FAKE_AGENT = """\
#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
home = Path(os.environ["QUIZ_HOME"])
assert sys.argv[1] == "sessions"
argv = sys.argv[1:]
if argv[1:2] == ["show"] and "--json" in argv:
    id = argv[2]
    print(json.dumps({"id": id, "agent": "claude", "native_id": id.split(":")[1],
                      "title": f"title of {id}", "model": "claude-opus-5-5",
                      "ended_at": "1792510162", "context_tokens": "107013",
                      "cwd": str(home / "work"), "path": str(home / "t.jsonl")}))
else:
    print("turns of", " ".join(argv[1:]))
"""

FAKE_FZF = """\
#!/usr/bin/env bash
input=$(cat)
printf '%s\\n' "$input" > "$QUIZ_HOME/fzf.stdin"
head -1 <<< "$input"
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "agent-models.toml").write_text(CONFIG)
    (tmp_path / "recipe.toml").write_text(RECIPE)
    (tmp_path / "notes.md").write_text("the notes\n")
    (tmp_path / "work").mkdir()
    (tmp_path / "t.jsonl").write_text('{"type": "cost-state", "totalCostUSD": 50.0}\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in [
        ("claude", FAKE_CLAUDE),
        ("agent", FAKE_AGENT),
        ("fzf", FAKE_FZF),
    ]:
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    (bin_dir / "agent-pick").symlink_to(
        REPO / "src" / "agent_tools" / "libexec" / "agent-pick"
    )
    return tmp_path


def quiz(
    home: Path,
    recipe: str = "recipe.toml",
    input: str = "what is X?\nwhat is Y?\n\n",
    model: tuple[str, ...] = ("-m", "opus"),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(AGENT), "quiz", *model, str(home / recipe)],
        capture_output=True,
        check=False,
        text=True,
        input=input,
        cwd=home,
        env={
            **{k: v for k, v in os.environ.items() if k != "AGENT_MODEL"},
            "PATH": f"{home / 'bin'}:{os.environ['PATH']}",
            "AGENT_MODELS": str(home / "agent-models.toml"),
            "QUIZ_HOME": str(home),
        },
    )


def calls(home: Path) -> list[dict]:
    return [
        json.loads(line) for line in (home / "claude.calls").read_text().splitlines()
    ]


def test_the_picker_offers_the_recipes_related_sessions(home: Path) -> None:
    assert quiz(home).returncode == 0
    lines = (home / "fzf.stdin").read_text().splitlines()
    assert [line.split("\t")[0] for line in lines] == ["claude:aaaa", "claude:bbbb"]


def test_the_prepared_session_starts_from_the_recipes_context(home: Path) -> None:
    result = quiz(home)
    assert result.returncode == 0, result.stderr
    first = calls(home)[0]
    assert "--resume" not in first["argv"]
    assert first["argv"][first["argv"].index("--model") + 1] == "claude-opus-5-5"
    assert "Prepare for the design review." in first["stdin"]
    assert "the notes" in first["stdin"]


def test_each_question_goes_to_both_sessions_and_the_existing_one_is_forked(
    home: Path,
) -> None:
    assert quiz(home).returncode == 0
    asked = [c for c in calls(home)[1:]]
    prepared = [c for c in asked if "prep1" in c["argv"]]
    existing = [c for c in asked if "prep1" not in c["argv"]]
    assert [c["stdin"] for c in prepared] == ["what is X?", "what is Y?"]
    assert [c["stdin"] for c in existing] == ["what is X?", "what is Y?"]
    first, second = existing
    assert first["argv"][first["argv"].index("--resume") + 1] == "aaaa"
    assert "--fork-session" in first["argv"]
    assert first["cwd"] == str(home / "work")
    assert second["argv"][second["argv"].index("--resume") + 1] == "fork1"
    assert "--fork-session" not in second["argv"]


def test_answers_are_shown_head_to_head_with_what_each_turn_cost(home: Path) -> None:
    result = quiz(home)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert out.index("prepared answers: what is X?") < out.index(
        "existing answers: what is X?"
    )
    assert out.index("existing answers: what is X?") < out.index(
        "prepared answers: what is Y?"
    )
    assert "$0.10" in out
    assert "$50.10" not in out


def test_a_recipe_without_related_sessions_says_so(home: Path) -> None:
    (home / "bare.toml").write_text(
        RECIPE.replace('related_sessions = ["claude:aaaa", "claude:bbbb"]\n', "")
    )
    result = quiz(home, "bare.toml")
    assert result.returncode != 0
    assert "related_sessions" in result.stderr
    assert not (home / "claude.calls").exists()


def test_every_turn_of_both_sessions_uses_the_effort(home: Path) -> None:
    result = quiz(home, model=("-m", "sonnet", "-e", "high"))
    assert result.returncode == 0, result.stderr
    for call in calls(home):
        argv = call["argv"]
        assert argv[argv.index("--effort") + 1] == "high"

"""SKILL.md's CLI reference is generated, so it must match the CLI."""

from pathlib import Path

from agent_tools.skill import MARKER, reference

SKILL = Path(__file__).parent.parent / "SKILL.md"


def test_skill_ends_with_the_current_cli_reference() -> None:
    text = SKILL.read_text()
    assert MARKER in text, "run `make skill`"
    assert text.split(MARKER, 1)[1] == reference(), "run `make skill`"


def test_reference_has_every_agent_and_agent_sessions_command() -> None:
    text = reference()
    for command in ["run", "ctx", "new", "quiz", "overview", "prepare-session", "sessions"]:
        assert f"\n  {command}\n" in text, command
    for command in ["search", "show", "cat", "tree", "resume", "attend", "serve"]:
        assert f"### `agent sessions {command}" in text, command

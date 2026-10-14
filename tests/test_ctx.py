"""Tests for agent ctx, using fake gh-issue-to-md, agent-sessions, slack-to-md and tracecli."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

AGENT = Path(sys.executable).parent / "agent"

SLACK_URL = "https://temporaltechnologies.slack.com/archives/C07ABC/p1728000000000000"
ISSUE_URL = "https://github.com/temporalio/dandavison-log/issues/212"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Each fake resolver prints a heading containing its argv, then a code block."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ["gh-issue-to-md", "agent-sessions", "slack-to-md", "tracecli"]:
        (bin_dir / tool).write_text(
            "#!/usr/bin/env bash\n"
            f'echo "# {tool} $*"\n'
            'echo "body"\n'
            "echo '```'\n"
            "echo '# not a heading'\n"
            "echo '```'\n"
        )
        (bin_dir / tool).chmod(0o755)
    return tmp_path


def ctx(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(AGENT), "ctx", *args],
        capture_output=True,
        check=False,
        text=True,
        cwd=home,
        env={**os.environ, "PATH": f"{home / 'bin'}:{os.environ['PATH']}"},
    )


def test_sources_are_included_raw_in_order_after_a_manifest(home: Path) -> None:
    result = ctx(
        home, "--purpose", "implement batch cancel", "issue:212", "session:7e90"
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "implement batch cancel" in out
    manifest = out.index("| issue:212 | raw |")
    assert manifest < out.index("| session:7e90 | raw |")
    issue = out.index("## issue:212\n")
    session = out.index("## session:7e90\n")
    assert manifest < issue < out.index("### gh-issue-to-md 212\n") < session
    assert session < out.index("### agent-sessions cat 7e90\n")


def test_headings_are_demoted_outside_code_blocks(home: Path) -> None:
    result = ctx(home, "issue:212")
    assert result.returncode == 0, result.stderr
    assert "\n### gh-issue-to-md 212\n" in result.stdout
    assert "\n# not a heading\n" in result.stdout


@pytest.mark.parametrize(
    "source, heading",
    [
        (ISSUE_URL, f"gh-issue-to-md {ISSUE_URL}"),
        (f"issue:{ISSUE_URL}", f"gh-issue-to-md {ISSUE_URL}"),
        (SLACK_URL, f"slack-to-md {SLACK_URL}"),
        (f"slack:{SLACK_URL}", f"slack-to-md {SLACK_URL}"),
        ("meeting:budget review", "tracecli transcript budget review"),
    ],
)
def test_source_is_resolved_by_its_tool(home: Path, source: str, heading: str) -> None:
    result = ctx(home, source)
    assert result.returncode == 0, result.stderr
    assert f"\n### {heading}\n" in result.stdout


def test_path_source_includes_each_matching_file(home: Path) -> None:
    (home / "notes").mkdir()
    (home / "notes" / "a.md").write_text("# A\nalpha\n")
    (home / "notes" / "b.md").write_text("bravo\n")
    result = ctx(home, "path:notes/*.md")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert out.index("### notes/a.md\n") < out.index("#### A\nalpha\n")
    assert out.index("alpha") < out.index("### notes/b.md\n") < out.index("bravo")


def test_manifest_reports_tokens_against_budget(home: Path) -> None:
    result = ctx(home, "--budget", "1000", "issue:212")
    assert result.returncode == 0, result.stderr
    assert "/ 1000" in result.stdout


def test_over_budget_fails_with_manifest_and_no_output(home: Path) -> None:
    result = ctx(home, "--budget", "5", "issue:212", "session:7e90")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "| issue:212 | raw |" in result.stderr
    assert "/ 5" in result.stderr


def test_session_point_is_rejected(home: Path) -> None:
    result = ctx(home, "session:7e90@9f3c")
    assert result.returncode != 0
    assert "session:7e90@9f3c" in result.stderr


def test_unknown_scheme_is_rejected(home: Path) -> None:
    result = ctx(home, "nope:1")
    assert result.returncode != 0
    assert "nope:1" in result.stderr


def test_failing_resolver_fails_and_names_the_source(home: Path) -> None:
    (home / "bin" / "tracecli").write_text("#!/usr/bin/env bash\nexit 3\n")
    result = ctx(home, "issue:212", "meeting:standup")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "meeting:standup" in result.stderr

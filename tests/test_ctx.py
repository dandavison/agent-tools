"""Tests for agent ctx, using fake gh, agent-sessions, slack-to-md and tracecli."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

AGENT = Path(sys.executable).parent / "agent"

SLACK_URL = "https://temporaltechnologies.slack.com/archives/C07ABC/p1728000000000000"
ISSUE_URL = "https://github.com/temporalio/dandavison-log/issues/212"

ISSUE = {
    "title": "Batch cancel",
    "created_at": "2026-10-01T09:00:00Z",
    "body": "# Plan\nbody\n```\n# not a heading\n```",
}
COMMENTS = [
    {
        "id": 1001,
        "user": {"login": "dandavison"},
        "created_at": "2026-10-02T09:00:00Z",
        "body": "first comment",
    },
    {
        "id": 1002,
        "user": {"login": "moe"},
        "created_at": "2026-10-03T09:00:00Z",
        "body": "second comment",
    },
]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Fake gh serves issue 212 of the log repo; the other fake resolvers print a
    heading containing their argv, then a code block."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ["agent-sessions", "slack-to-md", "tracecli"]:
        (bin_dir / tool).write_text(
            "#!/usr/bin/env bash\n"
            f'echo "# {tool} $*"\n'
            'echo "body"\n'
            "echo '```'\n"
            "echo '# not a heading'\n"
            "echo '```'\n"
        )
        (bin_dir / tool).chmod(0o755)
    api = tmp_path / "api" / "repos" / "temporalio" / "dandavison-log" / "issues"
    api.mkdir(parents=True)
    (api / "212.json").write_text(json.dumps(ISSUE))
    (api / "212-comments.json").write_text(json.dumps([COMMENTS]))
    (bin_dir / "gh").write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{bin_dir}/gh.calls"\n'
        'path="${@: -1}"\n'
        f'cat "{tmp_path}/api/${{path%/comments}}$([[ $path == */comments ]] && echo -comments).json"\n'
    )
    (bin_dir / "gh").chmod(0o755)
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
    assert manifest < issue < out.index("### Batch cancel\n") < session
    assert session < out.index("### agent-sessions cat 7e90\n")


def test_headings_are_demoted_outside_code_blocks(home: Path) -> None:
    result = ctx(home, "issue:212")
    assert result.returncode == 0, result.stderr
    assert "\n#### Plan\n" in result.stdout
    assert "\n# not a heading\n" in result.stdout


@pytest.mark.parametrize(
    "source, heading",
    [
        (SLACK_URL, f"slack-to-md {SLACK_URL}"),
        (f"slack:{SLACK_URL}", f"slack-to-md {SLACK_URL}"),
        ("meeting:budget review", "tracecli transcript budget review"),
    ],
)
def test_source_is_resolved_by_its_tool(home: Path, source: str, heading: str) -> None:
    result = ctx(home, source)
    assert result.returncode == 0, result.stderr
    assert f"\n### {heading}\n" in result.stdout


@pytest.mark.parametrize("source", ["issue:212", ISSUE_URL, f"issue:{ISSUE_URL}"])
def test_issue_is_its_body_then_each_comment_with_its_id(
    home: Path, source: str
) -> None:
    result = ctx(home, source)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert out.index("### Batch cancel\n") < out.index("\nbody\n")
    first = out.index("@dandavison on 2026-10-02T09:00:00Z (issuecomment-1001)\n")
    second = out.index("@moe on 2026-10-03T09:00:00Z (issuecomment-1002)\n")
    assert out.index("\nbody\n") < first < out.index("first comment") < second
    assert second < out.index("second comment")


@pytest.mark.parametrize(
    "source", ["issue:212#issuecomment-1002", f"{ISSUE_URL}#issuecomment-1002"]
)
def test_issue_comment_source_is_that_comment_alone(home: Path, source: str) -> None:
    result = ctx(home, source)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert f"| {source} | raw |" in out
    assert "### Batch cancel\n" in out
    assert "(issuecomment-1002)" in out and "second comment" in out
    assert "\nbody\n" not in out
    assert "first comment" not in out and "issuecomment-1001" not in out


def test_issue_with_exclusions_omits_those_comments(home: Path) -> None:
    result = ctx(home, "issue:212 exclude=issuecomment-1002")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "| issue:212 exclude=issuecomment-1002 | raw |" in out
    assert "\nbody\n" in out and "first comment" in out
    assert "second comment" not in out and "(issuecomment-1002)" not in out


def test_excluding_several_comments(home: Path) -> None:
    result = ctx(home, "issue:212 exclude=issuecomment-1001,issuecomment-1002")
    assert result.returncode == 0, result.stderr
    assert "first comment" not in result.stdout
    assert "second comment" not in result.stdout


@pytest.mark.parametrize(
    "source",
    [
        "issue:212#issuecomment-9999",
        "issue:212 exclude=issuecomment-9999",
        "issue:212 exclude=1001",
        "issue:212 whole=yes",
        "issue:212#issuecomment-1001 exclude=issuecomment-1002",
    ],
)
def test_comment_selection_that_matches_nothing_is_rejected(
    home: Path, source: str
) -> None:
    result = ctx(home, source)
    assert result.returncode != 0
    assert result.stdout == ""
    assert source in result.stderr


@pytest.mark.parametrize(
    "source, argv",
    [
        ("session:7e90", "cat 7e90"),
        ("session:7e90 --whole", "cat 7e90 --whole"),
        ("session:7e90 --tools --whole", "cat 7e90 --tools --whole"),
        ("session:7e90@9f3c", "cat 7e90@9f3c --upto"),
    ],
)
def test_session_source_is_read_by_agent_sessions_cat(
    home: Path, source: str, argv: str
) -> None:
    result = ctx(home, source)
    assert result.returncode == 0, result.stderr
    assert f"| {source} | raw |" in result.stdout
    assert f"\n### agent-sessions {argv}\n" in result.stdout


def test_unknown_session_option_is_rejected(home: Path) -> None:
    result = ctx(home, "session:7e90 --last")
    assert result.returncode != 0
    assert "session:7e90 --last" in result.stderr


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


RECIPE = '''
purpose = """
Implement batch cancel. First state your understanding and open questions.
"""
budget = 1000
provenance = "issue:212 was re-read on 2026-10-18; it holds no excluded material."

[[sources]]
uri = "issue:212 exclude=issuecomment-1002"
provenance = "issuecomment-1002 is by Moe."

[[sources]]
uri = "session:7e90 --whole"

[[sources]]
uri = "path:notes/*.md"

[[exclusions]]
what = "Anything Moe said or wrote"
reason = "B must design independently of Moe's prototype."
'''


def write_recipe(home: Path, text: str = RECIPE) -> Path:
    recipes = home / "recipes"
    recipes.mkdir(exist_ok=True)
    (recipes / "notes").mkdir(exist_ok=True)
    (recipes / "notes" / "a.md").write_text("alpha\n")
    path = recipes / "batch-cancel.toml"
    path.write_text(text)
    return path


def test_recipe_builds_its_sources_with_purpose_and_exclusions(home: Path) -> None:
    result = ctx(home, str(write_recipe(home)))
    assert result.returncode == 0, result.stderr
    out = result.stdout
    purpose = out.index("Implement batch cancel. First state your understanding")
    exclusion = out.index("Anything Moe said or wrote")
    assert "B must design independently of Moe's prototype." in out
    manifest = out.index("| issue:212 exclude=issuecomment-1002 | raw |")
    assert purpose < exclusion < manifest
    assert manifest < out.index("| session:7e90 --whole | raw |")
    assert "/ 1000" in out
    assert "first comment" in out and "second comment" not in out
    assert "\n### agent-sessions cat 7e90 --whole\n" in out


def test_recipe_paths_are_relative_to_the_recipe(home: Path) -> None:
    recipe = write_recipe(home)
    result = ctx(home / "bin", str(recipe))
    assert result.returncode == 0, result.stderr
    assert "\nalpha\n" in result.stdout


def test_recipe_provenance_is_not_given_to_the_agent(home: Path) -> None:
    result = ctx(home, str(write_recipe(home)))
    assert result.returncode == 0, result.stderr
    assert "re-read on 2026-10-18" not in result.stdout
    assert "issuecomment-1002 is by Moe." not in result.stdout


def test_same_recipe_builds_same_context(home: Path) -> None:
    recipe = str(write_recipe(home))
    assert ctx(home, recipe).stdout == ctx(home, recipe).stdout


def test_recipe_over_budget_fails(home: Path) -> None:
    recipe = write_recipe(home, RECIPE.replace("budget = 1000", "budget = 5"))
    result = ctx(home, str(recipe))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "/ 5" in result.stderr


@pytest.mark.parametrize(
    "edit",
    [
        lambda r: r.replace("budget = 1000", ""),
        lambda r: r.replace('purpose = """', 'aim = """'),
        lambda r: r.replace('provenance = "issue:212 was', 'notes = "issue:212 was'),
        lambda r: r.replace('reason = "B must', 'why = "B must'),
        lambda r: r.replace("[[sources]]", "[[source]]"),
        lambda r: r + '\nunknown = "x"\n',
    ],
)
def test_malformed_recipe_is_rejected(home: Path, edit) -> None:
    recipe = write_recipe(home, edit(RECIPE))
    result = ctx(home, str(recipe))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "batch-cancel.toml" in result.stderr


def test_recipe_cannot_be_combined_with_other_sources(home: Path) -> None:
    result = ctx(home, str(write_recipe(home)), "issue:212")
    assert result.returncode != 0
    assert result.stdout == ""

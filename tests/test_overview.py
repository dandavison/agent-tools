"""Tests for agent overview, using fake agent-run and open."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from agent_tools.overview import headings, source_url

AGENT = Path(sys.executable).parent / "agent"

RECIPE = """
purpose = "Prepare for the design review."
budget = 1000
provenance = "Chosen by hand."

[[sources]]
uri = "path:notes.md"

[[sources]]
uri = "path:plan.md"

[[exclusions]]
what = "The vendor's proposal."
reason = "Design independently."
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "recipe.toml").write_text(RECIPE)
    (tmp_path / "notes.md").write_text("# Goals\ntext\n## Risks\nmore\n")
    (tmp_path / "plan.md").write_text("# Steps\n" + "x" * 400)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "agent-run").write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s " "$@" >> "{bin_dir}/agent-run.calls"; echo >> "{bin_dir}/agent-run.calls"\n'
        'cat > /dev/null; echo "summary of source"\n'
    )
    (bin_dir / "open").write_text(
        f'#!/usr/bin/env bash\necho "$1" > "{bin_dir}/open.argv"\n'
    )
    for name in ["agent-run", "open"]:
        (bin_dir / name).chmod(0o755)
    return tmp_path


def overview(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(AGENT), "overview", *args, str(home / "recipe.toml")],
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, "PATH": f"{home / 'bin'}:{os.environ['PATH']}"},
    )


def page_data(home: Path) -> dict:
    page = Path((home / "bin" / "open.argv").read_text().strip())
    match = re.search(r"const DATA = (.*);\n", page.read_text())
    assert match, "no DATA block"
    return json.loads(match[1])


def test_opens_a_page_with_recipe_and_sources(home: Path) -> None:
    result = overview(home)
    assert result.returncode == 0, result.stderr
    data = page_data(home)
    assert data["recipe"] == str(home / "recipe.toml")
    assert data["purpose"] == "Prepare for the design review."
    assert data["budget"] == 1000
    assert data["provenance"] == "Chosen by hand."
    assert data["exclusions"] == [
        {"what": "The vendor's proposal.", "reason": "Design independently."}
    ]
    assert [s["uri"] for s in data["sources"]] == ["path:notes.md", "path:plan.md"]


def test_each_source_has_tokens_headings_and_a_summary(home: Path) -> None:
    assert overview(home).returncode == 0
    notes, plan = page_data(home)["sources"]
    assert plan["tokens"] > notes["tokens"] > 0
    assert [h["text"] for h in notes["headings"]] == [
        "# notes.md",
        "## Goals",
        "### Risks",
    ]
    assert notes["summary"].startswith("summary of")


def test_summaries_use_haiku_without_tools_by_default(home: Path) -> None:
    assert overview(home).returncode == 0
    calls = (home / "bin" / "agent-run.calls").read_text().splitlines()
    assert calls == ["-m haiku --no-tools "] * 2


def test_m_chooses_the_summary_model(home: Path) -> None:
    assert overview(home, "-m", "sonnet").returncode == 0
    calls = (home / "bin" / "agent-run.calls").read_text().splitlines()
    assert calls == ["-m sonnet --no-tools "] * 2


def test_page_escapes_script_end_tags(home: Path) -> None:
    (home / "notes.md").write_text("# </script><b>x</b>\n")
    assert overview(home).returncode == 0
    page = Path((home / "bin" / "open.argv").read_text().strip()).read_text()
    assert page.count("</script>") == 1


SLACK = "https://temporaltechnologies.slack.com/archives/C07ABC/p1728000000000000"
LOG = "https://github.com/temporalio/dandavison-log/issues"


@pytest.mark.parametrize(
    "uri, url",
    [
        ("issue:395", f"{LOG}/395"),
        ("issue:416#issuecomment-62", f"{LOG}/416#issuecomment-62"),
        ("issue:416 exclude=issuecomment-62", f"{LOG}/416"),
        ("https://github.com/o/r/issues/5", "https://github.com/o/r/issues/5"),
        (f"slack:{SLACK}", SLACK),
        (SLACK, SLACK),
        ("path:notes.md", "http://wormhole:7117/file/BASE/notes.md:1?land-in=editor"),
        ("path:*.md", None),
        ("session:claude:7e90 --whole", None),
        ("meeting:design review", None),
    ],
)
def test_sources_link_to_where_they_live(uri: str, url: str | None) -> None:
    base = Path("/base")
    expected = url.replace("BASE", "base") if url else None
    assert source_url(uri, base) == expected


def test_issue_comment_headings_link_to_their_comments() -> None:
    text = "# Title\n### @dandavison on 2026-10-02T09:00:00Z (issuecomment-62)\nhi\n"
    assert headings(text, f"{LOG}/416") == [
        {"text": "# Title", "url": None},
        {
            "text": "### @dandavison on 2026-10-02T09:00:00Z (issuecomment-62)",
            "url": f"{LOG}/416#issuecomment-62",
        },
    ]


def test_page_links_the_recipe_and_each_source(home: Path) -> None:
    assert overview(home).returncode == 0
    data = page_data(home)
    recipe = home / "recipe.toml"
    assert data["recipe_url"] == f"http://wormhole:7117/file/{recipe}:1?land-in=editor"
    assert data["sources"][0]["url"] == (
        f"http://wormhole:7117/file/{home / 'notes.md'}:1?land-in=editor"
    )

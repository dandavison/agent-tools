"""Tests for agent overview, using fake agent-run and open."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert notes["headings"] == ["# notes.md", "## Goals", "### Risks"]
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

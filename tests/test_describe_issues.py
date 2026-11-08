"""Tests for agent describe-issues, using a fake gh."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

AGENT = Path(sys.executable).parent / "agent"

ISSUES = {
    "temporalio/dandavison-log/issues/7": (
        {"title": "Streaming", "body": "# Streaming: overview\n\nbody"},
        [
            {"body": "# Vercel\n\nnotes"},
            {"body": "untitled reply"},
            {"body": "# Cloudflare\n# not a title"},
        ],
    ),
    "macaw/nest/issues/3": ({"title": "Nest", "body": "no title"}, []),
}


@pytest.fixture
def home(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for path, (issue, comments) in ISSUES.items():
        file = tmp_path / "api" / "repos" / f"{path}.json"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(issue))
        file.with_name(f"{file.stem}-comments.json").write_text(json.dumps([comments]))
    (bin_dir / "gh").write_text(
        "#!/usr/bin/env bash\n"
        'path="${@: -1}"\n'
        f'cat "{tmp_path}/api/${{path%/comments}}$([[ $path == */comments ]] && echo -comments).json"\n'
    )
    (bin_dir / "gh").chmod(0o755)
    return tmp_path


def describe(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(AGENT), "describe-issues", *args],
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, "PATH": f"{home / 'bin'}:{os.environ['PATH']}"},
    )


def test_each_issue_title_is_followed_by_its_body_and_comment_titles_indented(
    home: Path,
) -> None:
    result = describe(home, "7", "https://github.com/macaw/nest/issues/3")
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "#7 Streaming\n"
        "    Streaming: overview\n"
        "    Vercel\n"
        "    Cloudflare\n"
        "macaw/nest#3 Nest\n"
    )


def test_an_invalid_issue_is_an_error(home: Path) -> None:
    result = describe(home, "nope")
    assert result.returncode != 0
    assert "nope" in result.stderr

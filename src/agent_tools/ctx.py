"""Build an agent's context from sources within a token budget.

Every source is included raw. Compression is not implemented: if the sources exceed the
budget, nothing is output.
"""

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from glob import glob
from pathlib import Path

HEADING = re.compile(r"^#{1,6}\s")
FENCE = re.compile(r"^\s*(```|~~~)")


class SourceError(Exception):
    pass


class OverBudget(Exception):
    def __init__(self, manifest: str):
        super().__init__(manifest)
        self.manifest = manifest


@dataclass
class Source:
    uri: str
    text: str

    @property
    def tokens(self) -> int:
        return len(self.text) // 4


def build(uris: list[str], purpose: str | None, budget: int | None) -> str:
    with ThreadPoolExecutor() as pool:
        sources = list(pool.map(lambda uri: Source(uri, resolve(uri)), uris))
    manifest = format_manifest(sources, budget)
    if budget is not None and sum(s.tokens for s in sources) > budget:
        raise OverBudget(manifest)
    preamble = f"Purpose: {purpose}\n\n" if purpose else ""
    sections = "".join(f"## {s.uri}\n\n{demote(s.text, 2)}\n" for s in sources)
    return f"# Context\n\n{preamble}{manifest}\n{sections}"


def resolve(uri: str) -> str:
    scheme, _, ref = uri.partition(":")
    if re.match(r"https://github\.com/[^/]+/[^/]+/issues/\d+", uri):
        return run(uri, ["gh-issue-to-md", uri])
    if re.match(r"https://[^/]+\.slack\.com/", uri):
        return run(uri, ["slack-to-md", uri])
    match scheme:
        case "issue":
            return run(uri, ["gh-issue-to-md", ref])
        case "session":
            if "@" in ref:
                raise SourceError(
                    f"{uri}: a session point is not supported: agent-sessions cat"
                    " gives only the turn containing a point"
                )
            return run(uri, ["agent-sessions", "cat", ref])
        case "slack":
            return run(uri, ["slack-to-md", ref])
        case "meeting":
            return run(uri, ["tracecli", "transcript", ref])
        case "path":
            return read_files(uri, ref)
        case _:
            raise SourceError(f"{uri}: unknown source")


def run(uri: str, argv: list[str]) -> str:
    result = subprocess.run(argv, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise SourceError(
            f"{uri}: {argv[0]} exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout


def read_files(uri: str, pattern: str) -> str:
    paths = sorted(glob(pattern, recursive=True))
    if not paths:
        raise SourceError(f"{uri}: no files match")
    return "".join(f"# {p}\n\n{demote(Path(p).read_text(), 1)}\n" for p in paths)


def format_manifest(sources: list[Source], budget: int | None) -> str:
    rows = "".join(f"| {s.uri} | raw | {s.tokens} |\n" for s in sources)
    total = sum(s.tokens for s in sources)
    limit = f" / {budget}" if budget is not None else ""
    return (
        "| source | included | tokens |\n|-|-|-|\n"
        f"{rows}\nTotal: {total}{limit} tokens (estimated as characters / 4).\n"
    )


def demote(markdown: str, levels: int) -> str:
    lines = []
    in_code = False
    for line in markdown.splitlines(keepends=True):
        if FENCE.match(line):
            in_code = not in_code
        elif not in_code and HEADING.match(line):
            line = "#" * levels + line
        lines.append(line)
    return "".join(lines)

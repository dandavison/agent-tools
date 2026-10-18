"""Build an agent's context from sources within a token budget, or from a recipe.

The same sources always produce the same context: choosing them is done elsewhere.
Every source is included raw. Compression is not implemented: if the sources exceed the
budget, nothing is output.
"""

import json
import re
import subprocess
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from glob import glob
from pathlib import Path

HEADING = re.compile(r"^#{1,6}\s")
FENCE = re.compile(r"^\s*(```|~~~)")
ISSUE = re.compile(
    r"(?:issue:)?(?:(?P<n>\d+)|https://github\.com/(?P<repo>[^/]+/[^/]+)/issues/(?P<url_n>\d+))"
    r"(?:#(?P<comment>issuecomment-\d+))?$"
)
LOG_REPO = "temporalio/dandavison-log"
SESSION_OPTIONS = {"--whole", "--tools"}


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


@dataclass
class Exclusion:
    what: str
    reason: str


@dataclass
class Recipe:
    """A saved context. `provenance` records how sources were checked; it is for
    whoever maintains the recipe, and is not part of the context."""

    purpose: str
    budget: int
    provenance: str
    sources: list[str]
    exclusions: tuple[Exclusion, ...]


def build(
    uris: list[str],
    purpose: str | None,
    budget: int | None,
    exclusions: tuple[Exclusion, ...] = (),
    base: Path = Path(),
) -> str:
    with ThreadPoolExecutor() as pool:
        sources = list(pool.map(lambda uri: Source(uri, resolve(uri, base)), uris))
    manifest = format_manifest(sources, budget)
    if budget is not None and sum(s.tokens for s in sources) > budget:
        raise OverBudget(manifest)
    preamble = f"Purpose: {purpose.strip()}\n\n" if purpose else ""
    sections = "".join(f"## {s.uri}\n\n{demote(s.text, 2)}\n" for s in sources)
    return (
        f"# Context\n\n{preamble}{format_exclusions(exclusions)}{manifest}\n{sections}"
    )


def build_recipe(path: Path) -> str:
    recipe = load_recipe(path)
    return build(
        recipe.sources,
        recipe.purpose,
        recipe.budget,
        recipe.exclusions,
        path.parent,
    )


def load_recipe(path: Path) -> Recipe:
    try:
        data = tomllib.loads(path.read_text())
        check_keys(data, {"purpose", "budget", "provenance", "sources", "exclusions"})
        for source in data["sources"]:
            check_keys(source, {"uri"}, frozenset({"provenance"}))
        for exclusion in data["exclusions"]:
            check_keys(exclusion, {"what", "reason"})
        return Recipe(
            purpose=data["purpose"],
            budget=data["budget"],
            provenance=data["provenance"],
            sources=[source["uri"] for source in data["sources"]],
            exclusions=tuple(Exclusion(**e) for e in data["exclusions"]),
        )
    except (OSError, tomllib.TOMLDecodeError, ValueError, TypeError) as e:
        raise SourceError(f"{path}: {e}") from e


def check_keys(
    table: object, required: set[str], optional: frozenset[str] = frozenset()
) -> None:
    if not isinstance(table, dict):
        raise TypeError(f"expected a table, got {table!r}")
    if missing := required - table.keys():
        raise ValueError(f"missing {', '.join(sorted(missing))}")
    if unknown := table.keys() - required - optional:
        raise ValueError(f"unknown {', '.join(sorted(unknown))}")


def resolve(uri: str, base: Path) -> str:
    scheme, _, ref = uri.partition(":")
    if scheme == "issue" or uri.startswith("https://github.com/"):
        return read_issue(uri)
    if re.match(r"https://[^/]+\.slack\.com/", uri):
        return run(uri, ["slack-to-md", uri])
    match scheme:
        case "session":
            return read_session(uri, ref)
        case "slack":
            return run(uri, ["slack-to-md", ref])
        case "meeting":
            return run(uri, ["tracecli", "transcript", ref])
        case "path":
            return read_files(uri, ref, base)
        case _:
            raise SourceError(f"{uri}: unknown source")


def read_issue(uri: str) -> str:
    """The issue's body and comments, or one comment (`#issuecomment-ID`), or all but
    some (`exclude=issuecomment-ID,...`)."""
    ref, *options = uri.split()
    match = ISSUE.match(ref)
    if not match:
        raise SourceError(f"{uri}: not an issue")
    excluded = set()
    for option in options:
        key, _, ids = option.partition("=")
        if key != "exclude" or match["comment"]:
            raise SourceError(f"{uri}: unknown option {option}")
        excluded |= set(ids.split(","))
    number = match["n"] or match["url_n"]
    api = f"repos/{match['repo'] or LOG_REPO}/issues/{number}"
    issue = json.loads(run(uri, ["gh", "api", api]))
    pages = json.loads(
        run(uri, ["gh", "api", "--paginate", "--slurp", f"{api}/comments"])
    )
    comments = {f"issuecomment-{c['id']}": c for page in pages for c in page}
    selected = {match["comment"]} if match["comment"] else set(comments) - excluded
    if missing := (selected | excluded) - comments.keys():
        raise SourceError(f"{uri}: no {', '.join(sorted(missing))} in the issue")
    shown = [(id, c) for id, c in comments.items() if id in selected]
    return format_issue(number, issue, shown, body=not match["comment"])


def format_issue(
    number: str, issue: dict, comments: list[tuple[str, dict]], body: bool
) -> str:
    text = (
        f"---\nnumber: {number}\ndate: {issue['created_at'][:10]}\n"
        f"title: {json.dumps(issue['title'])}\n---\n\n# {issue['title']}\n\n"
    )
    if body and issue.get("body"):
        text += f"{issue['body']}\n\n"
    if comments:
        text += "---\n\n## Comments\n\n"
    for id, comment in comments:
        text += (
            f"### @{comment['user']['login']} on {comment['created_at']} ({id})\n\n"
            f"{comment.get('body') or ''}\n\n"
        )
    return text


def read_session(uri: str, ref: str) -> str:
    """`@POINT` gives the session up to the end of the turn that point falls in."""
    ref, *options = ref.split()
    if unknown := set(options) - SESSION_OPTIONS:
        raise SourceError(f"{uri}: unknown option {', '.join(sorted(unknown))}")
    upto = ["--upto"] if "@" in ref else []
    return run(uri, ["agent-sessions", "cat", ref, *upto, *options])


def run(uri: str, argv: list[str]) -> str:
    result = subprocess.run(argv, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise SourceError(
            f"{uri}: {argv[0]} exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout


def read_files(uri: str, pattern: str, base: Path) -> str:
    paths = sorted(glob(pattern, root_dir=base, recursive=True))
    if not paths:
        raise SourceError(f"{uri}: no files match")
    return "".join(f"# {p}\n\n{demote((base / p).read_text(), 1)}\n" for p in paths)


def format_exclusions(exclusions: tuple[Exclusion, ...]) -> str:
    if not exclusions:
        return ""
    rules = "".join(
        f"- {e.what.strip()} Reason: {e.reason.strip()}\n" for e in exclusions
    )
    return (
        "Excluded. Do not read or look for the following, even where these sources"
        f" link to it:\n\n{rules}\n"
    )


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

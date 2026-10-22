"""What a session was started from: the context `agent ctx` built and `agent with-input` pasted.

Claude records the paste whole, inside `<pasted_content>`. The context starts
`# Context`, then, if a recipe built it, `Recipe: <path> @ <commit>`, and lists
its sources in a manifest table.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from agent_tools.ctx import ISSUE, LOG_REPO

# `agent with-input` follows the paste with a `--` line, after which the cursor is left.
PASTED = re.compile(
    r'\s*<pasted_content id="(?P<id>[^"]*)">\n(?P<context># Context\n.*?)'
    r'</pasted_content id="(?P=id)">\s*(?:--(?:\n|$))?(?P<typed>.*)',
    re.S,
)
RECIPE = re.compile(r"# Context\n\nRecipe: (?P<path>.+?) (?:@ (?P<commit>\w+)|\(not committed\))\n")
MANIFEST = re.compile(
    r"^\| source \| included \| tokens \|\n\|-\|-\|-\|\n(?P<rows>(?:\|.*\|\n)*)", re.M
)


@dataclass(frozen=True, slots=True)
class Source:
    uri: str
    tokens: int


@dataclass(frozen=True, slots=True)
class Context:
    recipe: Path | None
    commit: str | None
    sources: list[Source]
    typed: str


@dataclass(frozen=True, slots=True)
class ContextSource:
    """A source of a context a session was given, as the index holds it."""

    session_id: str
    uri: str
    recipe: str | None

    @property
    def identity(self) -> str:
        return identity(self.uri)


def parse(text: str) -> Context | None:
    pasted = PASTED.match(text)
    if not pasted:
        return None
    context = pasted["context"]
    recipe = RECIPE.match(context)
    manifest = MANIFEST.search(context)
    return Context(
        recipe=Path(recipe["path"]) if recipe else None,
        commit=recipe["commit"] if recipe else None,
        sources=[_source(row) for row in manifest["rows"].splitlines()] if manifest else [],
        typed=pasted["typed"],
    )


def used(session_id: str, texts: list[str]) -> list[ContextSource]:
    """The sources of every context pasted into these messages of one session."""
    return [
        ContextSource(session_id, s.uri, built.recipe.stem if built.recipe else None)
        for text in texts
        if (built := parse(text))
        for s in built.sources
    ]


def identity(uri: str) -> str:
    """What a source is a part of: an issue, whichever comments of it; a Slack thread.

    Itself a source uri, in the form a recipe would use for the whole of it.
    """
    ref = uri.split()[0].removeprefix("slack:")
    if issue := ISSUE.match(ref.split("#")[0]):
        number, repo = issue["n"] or issue["url_n"], issue["repo"] or LOG_REPO
        return (
            f"issue:{number}" if repo == LOG_REPO else f"https://github.com/{repo}/issues/{number}"
        )
    return ref.split("?")[0]


def _source(row: str) -> Source:
    uri, _included, tokens = row[2:-2].rsplit(" | ", 2)
    return Source(uri, int(tokens))

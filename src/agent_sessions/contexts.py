"""What a session was given: the context `agent ctx` built, and issues pasted into it.

A context is what `agent with-input` pasted, which Claude records whole, inside
`<pasted_content>`. It starts `# Context`, then, if a recipe built it,
`Recipe: <path> @ <commit>`, and lists its sources in a manifest table.

An issue as `gh-issue-to-md` writes it starts with YAML front matter giving its
number and, since 2026-10-22, its url; without one it is an issue of the log repo.
"""

import re
import time
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
SLACK_THREAD = re.compile(
    r"https://(?P<workspace>[^/]+\.slack\.com)/archives/(?P<channel>\w+)/p(?P<ts>\d+)$"
)
FRONT_MATTER = re.compile(r"^---\nnumber: (?P<n>\d+)\n(?:url: (?P<url>\S+)\n)?", re.M)


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
    """A source a session was given at a turn, as the index holds it.

    `kind` is `context`, a source in the manifest of a context, or `pasted`, an
    issue pasted in on its own.
    """

    session_id: str
    uuid: str
    kind: str
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


def used(session_id: str, said: list[tuple[str, str]]) -> list[ContextSource]:
    """What one session was given in these user messages, each `(uuid, text)`."""
    return [source for uuid, text in said for source in _given(session_id, uuid, text)]


def pasted_issues(text: str) -> list[str]:
    """The issues in a message, as source uris."""
    return [
        identity(m["url"]) if m["url"] else f"issue:{m['n']}" for m in FRONT_MATTER.finditer(text)
    ]


def outside(text: str) -> str:
    """What a message holds besides a context: the issues inside one were not pasted alone."""
    built = parse(text)
    return built.typed if built else text


def slack_channel(uri: str) -> tuple[str, str] | None:
    """The workspace and channel of a Slack thread."""
    thread = SLACK_THREAD.match(identity(uri))
    return (thread["workspace"], thread["channel"]) if thread else None


def label(uri: str, channel_name: str | None) -> str:
    """A Slack thread as a person knows it: its channel, and when it started."""
    thread = SLACK_THREAD.match(identity(uri))
    if not thread:
        raise ValueError(f"{uri} is not a Slack thread")
    started = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(thread["ts"][:-6])))
    return f"#{channel_name or thread['channel']} · {started}"


def shown(uri: str, channels: dict[tuple[str, str], str | None]) -> str | None:
    """How a source is shown when its uri means nothing to a person; a Slack thread's label."""
    channel = slack_channel(uri)
    return label(uri, channels.get(channel)) if channel else None


def _given(session_id: str, uuid: str, text: str) -> list[ContextSource]:
    built = parse(text)
    recipe = built.recipe.stem if built and built.recipe else None
    return [
        *(
            ContextSource(session_id, uuid, "context", s.uri, recipe)
            for s in (built.sources if built else [])
        ),
        *(
            ContextSource(session_id, uuid, "pasted", uri, None)
            for uri in pasted_issues(outside(text))
        ),
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

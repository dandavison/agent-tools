"""A browser page summarising a recipe's sources, for reviewing a large context."""

import json
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from agent_tools.ctx import (
    FENCE,
    HEADING,
    ISSUE,
    LOG_REPO,
    Source,
    SourceError,
    load_recipe,
    resolve,
)

TEMPLATE = Path(__file__).with_name("overview.html")
PROMPT = (
    "The text after the line of dashes is one source in an agent's context. In two or three"
    " plain sentences, say what it is and what it contributes. Output only the sentences."
    "\n\n----------\n\n"
)
SLACK = re.compile(r"https://[^/]+\.slack\.com/")
COMMENT_HEADING = re.compile(r"^### @\S+ on \S+ \((issuecomment-\d+)\)$")
# Fits a 200k-token model. A longer source is summarised from its start only, and the
# page says so.
MAX_SUMMARISED_CHARS = 600_000


def write_overview(recipe_path: Path, model: str) -> Path:
    recipe = load_recipe(recipe_path)
    with ThreadPoolExecutor() as pool:
        sources = list(
            pool.map(
                lambda uri: Source(uri, resolve(uri, recipe_path.parent)),
                recipe.sources,
            )
        )
        summaries = list(pool.map(lambda s: summarise(s, model), sources))
    data = {
        "name": recipe_path.stem,
        "recipe": str(recipe_path),
        "recipe_url": wormhole_url(recipe_path),
        "purpose": recipe.purpose,
        "budget": recipe.budget,
        "provenance": recipe.provenance,
        "exclusions": [asdict(e) for e in recipe.exclusions],
        "model": model,
        "sources": [
            describe(s, summary, source_url(s.uri, recipe_path.parent))
            for s, summary in zip(sources, summaries)
        ],
    }
    page = Path(tempfile.mkdtemp(prefix="agent-overview-")) / f"{recipe_path.stem}.html"
    page.write_text(render(data))
    return page


def describe(source: Source, summary: str, url: str | None) -> dict:
    return {
        "uri": source.uri,
        "url": url,
        "tokens": source.tokens,
        "summarised_tokens": min(len(source.text), MAX_SUMMARISED_CHARS) // 4,
        "summary": summary,
        "headings": headings(source.text, url),
    }


def source_url(uri: str, base: Path) -> str | None:
    scheme, _, ref = uri.partition(":")
    if scheme == "issue" or uri.startswith("https://github.com/"):
        return issue_url(uri.split()[0])
    if scheme == "slack":
        return ref
    if SLACK.match(uri):
        return uri
    if scheme == "path" and not any(c in ref for c in "*?["):
        return wormhole_url(base / ref)
    return None


def issue_url(ref: str) -> str | None:
    match = ISSUE.match(ref)
    if not match:
        return None
    number = match["n"] or match["url_n"]
    url = f"https://github.com/{match['repo'] or LOG_REPO}/issues/{number}"
    return f"{url}#{match['comment']}" if match["comment"] else url


def wormhole_url(path: Path) -> str:
    return f"http://wormhole:7117/file/{path}:1?land-in=editor"


def summarise(source: Source, model: str) -> str:
    result = subprocess.run(
        ["agent-run", "-m", model, "--no-tools"],
        input=PROMPT + source.text[:MAX_SUMMARISED_CHARS],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise SourceError(
            f"{source.uri}: summary failed: agent-run exited {result.returncode}:"
            f" {result.stderr.strip()}"
        )
    return result.stdout.strip()


def headings(markdown: str, url: str | None) -> list[dict]:
    """Each heading, linked to its comment where it heads an issue comment."""
    issue = url.split("#")[0] if url else None
    found = []
    in_code = False
    for line in markdown.splitlines():
        if FENCE.match(line):
            in_code = not in_code
        elif not in_code and HEADING.match(line):
            text = line.strip()
            comment = COMMENT_HEADING.match(text)
            link = f"{issue}#{comment[1]}" if issue and comment else None
            found.append({"text": text, "url": link})
    return found


def render(data: dict) -> str:
    script_safe = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.read_text().replace(
        "const DATA = null;", f"const DATA = {script_safe};"
    )

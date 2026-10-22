"""A browser page summarising a recipe's sources, for reviewing a large context."""

import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from agent_tools.ctx import (
    FENCE,
    HEADING,
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
        "purpose": recipe.purpose,
        "budget": recipe.budget,
        "provenance": recipe.provenance,
        "exclusions": [asdict(e) for e in recipe.exclusions],
        "model": model,
        "sources": [
            {
                "uri": s.uri,
                "tokens": s.tokens,
                "summarised_tokens": min(len(s.text), MAX_SUMMARISED_CHARS) // 4,
                "summary": summary,
                "headings": headings(s.text),
            }
            for s, summary in zip(sources, summaries)
        ],
    }
    page = Path(tempfile.mkdtemp(prefix="agent-overview-")) / f"{recipe_path.stem}.html"
    page.write_text(render(data))
    return page


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


def headings(markdown: str) -> list[str]:
    found = []
    in_code = False
    for line in markdown.splitlines():
        if FENCE.match(line):
            in_code = not in_code
        elif not in_code and HEADING.match(line):
            found.append(line.strip())
    return found


def render(data: dict) -> str:
    script_safe = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.read_text().replace(
        "const DATA = null;", f"const DATA = {script_safe};"
    )

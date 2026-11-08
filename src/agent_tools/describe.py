"""Outline GitHub issues: each issue's title, then the titles of its body and comments."""

import json
import re
from concurrent.futures import ThreadPoolExecutor

from agent_tools.ctx import ISSUE, LOG_REPO, SourceError, run

TITLE = re.compile(r"# (.+)")


def describe_issues(refs: list[str]) -> str:
    with ThreadPoolExecutor() as pool:
        return "".join(pool.map(describe_issue, refs))


def describe_issue(ref: str) -> str:
    match = ISSUE.match(ref)
    if not match or match["comment"]:
        raise SourceError(f"{ref}: not an issue")
    number = match["n"] or match["url_n"]
    repo = match["repo"] or LOG_REPO
    api = f"repos/{repo}/issues/{number}"
    issue = json.loads(run(ref, ["gh", "api", api]))
    pages = json.loads(
        run(ref, ["gh", "api", "--paginate", "--slurp", f"{api}/comments"])
    )
    bodies = [issue.get("body"), *(c.get("body") for page in pages for c in page)]
    label = f"#{number}" if repo == LOG_REPO else f"{repo}#{number}"
    lines = [f"{label} {issue['title']}", *(f"    {t}" for t in titles(bodies))]
    return "".join(f"{line}\n" for line in lines)


def titles(bodies: list[str | None]) -> list[str]:
    """First-line H1s; bodies without one are omitted."""
    matches = (TITLE.match(body or "") for body in bodies)
    return [m[1].strip() for m in matches if m]

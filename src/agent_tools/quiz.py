"""Ask a session prepared from a recipe and an existing session the same questions, so
that what each knows can be compared."""

import json
import os
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from agent_tools.ctx import SourceError, build_recipe, load_recipe

PREVIEW = "agent sessions show {1} --turns --format human | tail -n 30 | cut -c1-200"


@dataclass
class Session:
    """A headless claude session, resumed for each question."""

    label: str
    args: list[str]
    cwd: str
    env: dict[str, str]
    spent: float

    def ask(self, question: str) -> tuple[str, float]:
        result = subprocess.run(
            ["claude", "-p", *self.args, "--output-format", "json"],
            input=question,
            capture_output=True,
            check=False,
            text=True,
            cwd=self.cwd,
            env=self.env,
        )
        if result.returncode != 0:
            raise SourceError(
                f"{self.label}: claude exited {result.returncode}: {result.stderr}"
            )
        summary = json.loads(result.stdout)
        # A resumed session reports its running total, not what this turn cost.
        total = float(summary.get("total_cost_usd") or 0)
        cost, self.spent = total - self.spent, total
        model_args = (
            self.args[: self.args.index("--resume")]
            if "--resume" in self.args
            else self.args
        )
        self.args = [*model_args, "--resume", summary["session_id"]]
        return summary.get("result", ""), cost


def quiz(recipe_path: Path, pick: Callable[[bool], dict]) -> None:
    recipe = load_recipe(recipe_path)
    if not recipe.related_sessions:
        raise SourceError(
            f"{recipe_path}: no related_sessions to compare with;"
            " add them with agent prepare-session"
        )
    existing = choose(recipe.related_sessions)
    prepared = Session("prepared", *start(pick(False), os.getcwd()), spent=0.0)
    show([(prepared, prepared.ask(build_recipe(recipe_path)))])
    other = forked(existing, pick(existing["agent"] == "claude-personal"))
    while question := read_question():
        with ThreadPoolExecutor() as pool:
            answers = list(pool.map(lambda s: s.ask(question), [prepared, other]))
        show(list(zip([prepared, other], answers)))


def choose(ids: list[str]) -> dict:
    sessions = [describe(id) for id in ids]
    lines = "".join(
        f"{s['id']}\t{date.fromtimestamp(int(s['ended_at']))}"
        f"\t{int(s['context_tokens']) // 1000}k\t{s['title']}\n"
        for s in sessions
    )
    result = subprocess.run(
        [
            "fzf",
            "--delimiter=\t",
            "--header=The existing session to compare with",
            f"--preview={PREVIEW}",
            "--preview-window=down:60%:wrap",
        ],
        input=lines,
        stdout=subprocess.PIPE,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    chosen = result.stdout.split("\t")[0]
    return next(s for s in sessions if s["id"] == chosen)


def describe(id: str) -> dict:
    result = subprocess.run(
        ["agent", "sessions", "show", id, "--json"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise SourceError(f"{id}: agent sessions show exited {result.returncode}")
    return json.loads(result.stdout)


def start(pick: dict, cwd: str) -> tuple[list[str], str, dict[str, str]]:
    if pick["cli"] != "claude":
        raise SourceError(f"{pick['name']}: quiz supports claude models only")
    return pick["args"], cwd, {**os.environ, **pick["env"]}


def forked(session: dict, pick: dict) -> Session:
    """The existing session, forked on its first question so that it is not changed."""
    args, cwd, env = start(pick, session["cwd"])
    return Session(
        f"existing {session['native_id'][:8]}: {session['title']}",
        [*args, "--resume", session["native_id"], "--fork-session"],
        cwd,
        env,
        spent=spent(Path(session["path"])),
    )


def spent(transcript: Path) -> float:
    """The session's running total, as its transcript last recorded it."""
    totals = [
        float(record["totalCostUSD"])
        for line in transcript.read_text().splitlines()
        if (record := json.loads(line)).get("type") == "cost-state"
    ]
    return totals[-1] if totals else 0.0


def read_question() -> str:
    try:
        return input("\nQuestion for both (empty to finish): ").strip()
    except EOFError:
        return ""


def show(answers: list[tuple[Session, tuple[str, float]]]) -> None:
    for session, (text, cost) in answers:
        print(f"\n━━ {session.label} · ${cost:.2f} ━━\n\n{text}", flush=True)

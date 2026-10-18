"""The agent command line."""

import inspect
import json
import os
import subprocess
from pathlib import Path

import click

from agent_tools.ctx import OverBudget, SourceError, build, build_recipe

SCRIPTS = {
    "with-input": """Start an interactive agent with its input pre-filled from stdin.

    \b
    agent with-input [--personal] [-m MODEL] [-- AGENT [ARG...]] < FILE
    Requires tmux. Nothing is submitted.""",
    "from-issues": """Start an interactive agent with GitHub issues pre-filled in its input.

    \b
    agent from-issues [-R OWNER/REPO] [--personal] [-m MODEL] ISSUE... [-- AGENT [ARG...]]
    ISSUE is a number or URL. Reads ~/.config/agent-from-issues.toml.""",
    "run": """Run a prompt non-interactively; the answer goes to stdout.

    \b
    agent run [--personal] [-m MODEL] [--no-tools]                prompt from stdin
    agent run [--personal] [-m MODEL] [--no-tools] FILE [ARG...]  prompt script""",
    "pick": """Choose a model ($AGENT_MODEL, else NAME, else fzf) and print it as JSON.

    \b
    agent pick [--personal] [--list] [NAME]""",
    "prices-refresh": "Cache OpenRouter's model list, used for codex costs.",
    "prepare-session": """Prepare a context recipe for a new session described in plain language.

    \b
    agent prepare-session "DESCRIPTION OF THE SESSION"
    agent prepare-session RECIPE.draft.toml "REPLY TO THE DRAFT"
    Each run stops at a draft for approval. The last prints the command that starts
    the session; it never starts it.""",
    "mlx-serve": """Serve a local MLX model over an OpenAI-compatible API.

    \b
    agent mlx-serve [MLX_LM_SERVER_ARG...]
    Env: MLX_MODEL, MLX_PORT, MLX_MAX_TOKENS.""",
}


class Script(click.Command):
    """Runs agent-NAME with its arguments untouched, except a lone --help."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args == ["--help"]:
            return super().parse_args(ctx, args)
        ctx.args = args
        return []


class Agent(click.Group):
    """Lists every subcommand's full help, so that one --help documents the whole tool.

    Arguments starting with "-" that are not agent options go to start, so that e.g.
    `agent -r` resumes.
    """

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if args[0].startswith("-"):
            return "start", start, args
        return super().resolve_command(ctx, args)

    def format_commands(
        self, ctx: click.Context, formatter: click.HelpFormatter
    ) -> None:
        with formatter.section("Commands"):
            for name in self.list_commands(ctx):
                command = self.commands[name]
                formatter.write_text(name)
                with formatter.indentation():
                    formatter.write_text(inspect.cleandoc(command.help or ""))
                formatter.write_paragraph()


@click.group(
    cls=Agent,
    invoke_without_command=True,
    context_settings={"ignore_unknown_options": True},
)
@click.option(
    "-m",
    "model",
    help="Model name from ~/.config/agent-models.toml.",
    shell_complete=lambda ctx, param, incomplete: model_names(incomplete),
)
@click.option("-p", "--personal", is_flag=True, help="Use the personal account.")
@click.pass_context
def cli(ctx: click.Context, model: str | None, personal: bool) -> None:
    """Start agent sessions and run prompts on a chosen model.

    With no subcommand, start an interactive session, passing other options to the
    model's CLI (e.g. `agent -r`). The model is $AGENT_MODEL if set, else -m MODEL, else
    chosen with fzf.
    """
    if ctx.invoked_subcommand is None:
        start_session(model, personal, [])


@cli.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
)
@click.option(
    "-m",
    "model",
    help="Model name from ~/.config/agent-models.toml.",
    shell_complete=lambda ctx, param, incomplete: model_names(incomplete),
)
@click.option("-p", "--personal", is_flag=True, help="Use the personal account.")
@click.pass_context
def start(ctx: click.Context, model: str | None, personal: bool) -> None:
    """Start an interactive session, passing other arguments to the model's CLI.

    \b
    agent start -m opus --resume abc
    """
    agent = ctx.find_root().params
    start_session(model or agent["model"], personal or agent["personal"], ctx.args)


@cli.command("ctx")
@click.argument("sources", nargs=-1, required=True)
@click.option("--purpose", help="What the context is for.")
@click.option("--budget", type=int, help="Maximum tokens.")
def ctx_command(
    sources: tuple[str, ...], purpose: str | None, budget: int | None
) -> None:
    """Print an agent's context, built from SOURCES or a RECIPE.toml, as Markdown.

    It starts with a manifest of the sources and their token counts. Every source is
    included raw; if they exceed --budget, the manifest goes to stderr and nothing is
    output. Quote a source that has options.

    \b
    issue:N | issue:URL | GITHUB_ISSUE_URL         the body and comments (N: log repo)
    issue:N#issuecomment-ID                        one comment
    "issue:N exclude=issuecomment-ID,..."          all but those comments
    session:ID ["--whole"] ["--tools"]             agent-sessions cat (without --whole,
                                                   only what followed the last compaction)
    session:ID@POINT                               the session up to that point's turn
    slack:URL | SLACK_URL                          slack-to-md
    meeting:QUERY                                  tracecli transcript
    path:GLOB                                      matching files
    \b
    agent ctx --purpose "implement batch cancel" --budget 80000 issue:212 \\
        session:claude:7e90a7c6 | agent with-input
    \b
    A recipe holds purpose, budget, sources, exclusions and provenance; relative
    paths in it are relative to it. Recipes are in ~/src/temporalio-etc/log/recipes.
    \b
    agent ctx ~/src/temporalio-etc/log/recipes/batch-cancel.toml | agent with-input
    """
    recipe = next((Path(s) for s in sources if s.endswith(".toml")), None)
    if recipe and (len(sources) > 1 or purpose or budget):
        raise click.UsageError("a recipe takes no other sources, --purpose or --budget")
    try:
        text = build_recipe(recipe) if recipe else build(list(sources), purpose, budget)
        click.echo(text, nl=False)
    except OverBudget as e:
        click.echo(e.manifest, err=True, nl=False)
        raise click.ClickException("over budget; compression is not implemented") from e
    except SourceError as e:
        raise click.ClickException(str(e)) from e


def script_command(name: str, help: str) -> click.Command:
    def run(ctx: click.Context) -> None:
        os.execvp(f"agent-{name}", [f"agent-{name}", *ctx.args])

    return Script(name, callback=click.pass_context(run), help=help)


for name, help in SCRIPTS.items():
    cli.add_command(script_command(name, help))


def start_session(model: str | None, personal: bool, args: list[str]) -> None:
    pick = pick_model(model, personal)
    os.environ.update(pick["env"])
    os.execvp(pick["cli"], [pick["cli"], "--model", pick["model"], *args])


def pick_model(model: str | None, personal: bool) -> dict:
    argv = [
        "agent-pick",
        *(["--personal"] if personal else []),
        *([model] if model else []),
    ]
    result = subprocess.run(argv, check=False, stdout=subprocess.PIPE, text=True)
    if result.returncode:
        raise SystemExit(result.returncode)
    return json.loads(result.stdout)


def model_names(prefix: str) -> list[str]:
    stdout = subprocess.run(
        ["agent-pick", "--list"], check=True, stdout=subprocess.PIPE, text=True
    ).stdout
    names = [line.split()[0] for line in stdout.splitlines()]
    return [name for name in names if name.startswith(prefix)]


def main() -> None:
    cli()

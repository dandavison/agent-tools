"""The agent command line."""

import inspect
import json
import os
import subprocess
from pathlib import Path

import click

import agent_sessions.cli
from agent_tools.ctx import OverBudget, SourceError, build, build_recipe
from agent_tools.describe import describe_issues
from agent_tools.overview import write_overview
from agent_tools.quiz import quiz

LIBEXEC = os.environ.get("AGENT_EXEC_PATH", str(Path(__file__).parent / "libexec"))

SCRIPTS = {
    "with-input": """Start an interactive agent with its input pre-filled from stdin.

    \b
    agent with-input [-p|--personal|-w|--work] [-m MODEL] [--name NAME] [-- AGENT [ARG...]] < FILE
    Requires tmux. Nothing is submitted.""",
    "from-issues": """Start an interactive agent with GitHub issues pre-filled in its input.

    \b
    agent from-issues [-R OWNER/REPO] [-p|--personal|-w|--work] [-m MODEL] ISSUE... [-- AGENT [ARG...]]
    ISSUE is a number or URL. Reads ~/.config/agent-from-issues.toml.""",
    "run": """Run a prompt non-interactively; the answer goes to stdout.

    \b
    agent run [-p|-w] [-m MODEL] [--no-tools]                prompt from stdin
    agent run [-p|-w] [-m MODEL] [--no-tools] FILE [ARG...]  prompt script
    agent run --print-prompt FILE [ARG...]                           print its prompt instead""",
    "pick": """Choose a model ($AGENT_MODEL, else NAME, else fzf) and print it as JSON.

    \b
    agent pick [-p|-w] [--anywhere] [--list] [NAME]""",
    "prices-refresh": "Cache OpenRouter's model list, used for codex costs.",
    "prepare-session": """Prepare a context recipe for a new session described in plain language.

    \b
    agent prepare-session "DESCRIPTION OF THE SESSION"
    agent prepare-session RECIPE.toml "CHANGES"
    Each run commits the recipe in the log repo and prints the command that starts
    the session; it never starts it.""",
    "new": """Prepare a session from a description, then start it on Enter.

    \b
    agent new [-p|--personal|-w|--work] [-m MODEL] "DESCRIPTION OF THE SESSION"
    agent new [-p|--personal|-w|--work] [-m MODEL] RECIPE.toml
    Runs prepare-session and shows its report. Enter starts the session with the
    recipe's context; typed changes revise the recipe first. Requires tmux.""",
    "exfiltrate": """Get the sessions that discussed a topic to write what they know into log issues.

    \b
    agent exfiltrate [--print-prompt] "TOPIC, and optionally sessions and a target issue"
    A prompt script. Never asks a session open in a terminal; reports it instead.
    --print-prompt prints the procedure, for an agent to follow itself.""",
    "suggest-command": """Suggest a zsh command line that does what stdin describes.

    \b
    agent suggest-command < DESCRIPTION
    A prompt script, used by Ctrl-X Ctrl-A in shell/agent.zsh.""",
    "mlx-serve": """Serve a local MLX model over an OpenAI-compatible API.

    \b
    agent mlx-serve [MLX_LM_SERVER_ARG...]
    Env: MLX_MODEL, MLX_PORT, MLX_MAX_TOKENS.""",
}


class Script(click.Command):
    """Runs libexec/agent-NAME with its arguments untouched, except a lone --help."""

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
@click.option(
    "-e",
    "effort",
    help="Effort, from the model's efforts in ~/.config/agent-models.toml.",
)
@click.option("-p", "--personal", is_flag=True, help="Use the personal account.")
@click.option("-w", "--work", is_flag=True, help="Use the work account.")
@click.pass_context
def cli(
    ctx: click.Context,
    model: str | None,
    effort: str | None,
    personal: bool,
    work: bool,
) -> None:
    """Start agent sessions and run prompts on a chosen model.

    With no subcommand, start an interactive session, passing other options to the
    model's CLI (e.g. `agent -r`). The model is $AGENT_MODEL if set, else -m MODEL, else
    chosen with fzf; then the effort is $AGENT_EFFORT if set, else -e EFFORT, else chosen
    with fzf, for a model with efforts. The account is chosen by the repo's directory (see [accounts] in
    agent-models.toml); -p/-w must agree with it, and are required where it has no account.
    """
    if ctx.invoked_subcommand is None:
        start_session(model, effort, account_flag(personal, work), [])
    elif (
        model or effort or personal or work
    ) and ctx.invoked_subcommand not in TAKES_MODEL_OPTIONS:
        raise click.UsageError(
            f"-m, -e, -p and -w do not apply to {ctx.invoked_subcommand}"
        )


@cli.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
)
@click.option(
    "-m",
    "model",
    help="Model name from ~/.config/agent-models.toml.",
    shell_complete=lambda ctx, param, incomplete: model_names(incomplete),
)
@click.option(
    "-e",
    "effort",
    help="Effort, from the model's efforts in ~/.config/agent-models.toml.",
)
@click.option("-p", "--personal", is_flag=True, help="Use the personal account.")
@click.option("-w", "--work", is_flag=True, help="Use the work account.")
@click.pass_context
def start(
    ctx: click.Context,
    model: str | None,
    effort: str | None,
    personal: bool,
    work: bool,
) -> None:
    """Start an interactive session, passing other arguments to the model's CLI.

    \b
    agent start -m opus --resume abc
    """
    agent = ctx.find_root().params
    flag = account_flag(personal or agent["personal"], work or agent["work"])
    start_session(model or agent["model"], effort or agent["effort"], flag, ctx.args)


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
    session:ID ["--whole"] ["--tools"]             agent sessions cat (without --whole,
                                                   only what followed the last compaction)
    session:ID@POINT                               the session up to that point's turn
    slack:URL | SLACK_URL                          slack-fetch
    meeting:QUERY                                  tracecli transcript
    path:GLOB                                      matching files
    \b
    agent ctx --purpose "implement batch cancel" --budget 80000 issue:212 \\
        session:claude:7e90a7c6 | agent with-input
    \b
    A recipe holds purpose, budget, sources, exclusions, provenance and optionally
    related_sessions (for agent quiz); relative paths in it are relative to it. Recipes are in ~/src/temporalio-etc/log/recipes.
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


@cli.command("describe-issues")
@click.argument("issues", nargs=-1, required=True)
def describe_issues_command(issues: tuple[str, ...]) -> None:
    """Print each issue's title, then the first-line H1s of its body and comments,
    indented.

    \b
    agent describe-issues 394 389 https://github.com/OWNER/REPO/issues/12
    ISSUE is a number (log repo) or URL.
    """
    try:
        click.echo(describe_issues(list(issues)), nl=False)
    except SourceError as e:
        raise click.ClickException(str(e)) from e


@cli.command("overview")
@click.argument("recipe", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-m",
    "model",
    default="haiku",
    show_default=True,
    help="Model that summarises each source.",
    shell_complete=lambda ctx, param, incomplete: model_names(incomplete),
)
def overview_command(recipe: Path, model: str) -> None:
    """Open a browser page summarising a RECIPE.toml: purpose, size against the budget,
    exclusions, provenance, and each source's tokens, headings and a short summary.

    \b
    agent overview ~/src/temporalio-etc/log/recipes/batch-cancel.toml
    The page is written to a temporary directory; its path is printed.
    """
    try:
        page = write_overview(recipe.absolute(), model)
    except SourceError as e:
        raise click.ClickException(str(e)) from e
    click.echo(page)
    subprocess.run(["open", str(page)], check=True)


@cli.command("quiz")
@click.argument("recipe", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-m",
    "model",
    help="Model for both sessions, from ~/.config/agent-models.toml.",
    shell_complete=lambda ctx, param, incomplete: model_names(incomplete),
)
@click.option(
    "-e",
    "effort",
    help="Effort, from the model's efforts in ~/.config/agent-models.toml.",
)
@click.option("-p", "--personal", is_flag=True, help="Use the personal account.")
def quiz_command(
    recipe: Path, model: str | None, effort: str | None, personal: bool
) -> None:
    """Ask a session prepared from RECIPE.toml and an existing session the same
    questions, and show their answers one after the other.

    \b
    agent quiz -m opus ~/src/temporalio-etc/log/recipes/batch-cancel.toml
    The existing session is chosen with fzf from the recipe's related_sessions, and
    forked, so it is not changed. Each answer shows what its turn cost.
    """
    try:
        agent = click.get_current_context().find_root().params
        model, personal = model or agent["model"], personal or agent["personal"]
        chosen = {"effort": effort or agent["effort"]}

        def pick(other: bool) -> dict:
            # The forked session must use the existing session's account, wherever the
            # recipe is; both sessions use the effort chosen for the first.
            account = "personal" if personal or other else "work"
            pick = pick_model(model, chosen["effort"], account, anywhere=True)
            chosen["effort"] = pick["effort"]
            return pick

        quiz(recipe.absolute(), pick)
    except SourceError as e:
        raise click.ClickException(str(e)) from e


cli.add_command(agent_sessions.cli.main, "sessions")


def script_command(name: str, help: str) -> click.Command:
    def run(ctx: click.Context) -> None:
        agent = ctx.find_root().params
        options = [
            *(["--personal"] if agent["personal"] else []),
            *(["--work"] if agent["work"] else []),
            *(["-m", agent["model"]] if agent["model"] else []),
            *(["-e", agent["effort"]] if agent["effort"] else []),
        ]
        os.execvp(f"agent-{name}", [f"agent-{name}", *options, *ctx.args])

    return Script(name, callback=click.pass_context(run), help=help)


# Subcommands that accept agent's own -m, -e, -p and -w.
TAKES_MODEL_OPTIONS = {"start", "quiz", "with-input", "from-issues", "run", "new"}

for name, help in SCRIPTS.items():
    cli.add_command(script_command(name, help))


def account_flag(personal: bool, work: bool) -> str | None:
    if personal and work:
        raise click.UsageError("-p and -w are mutually exclusive")
    return "personal" if personal else "work" if work else None


def start_session(
    model: str | None, effort: str | None, account: str | None, args: list[str]
) -> None:
    pick = pick_model(model, effort, account)
    os.environ.update(pick["env"])
    os.execvp(pick["cli"], [pick["cli"], *pick["args"], *args])


def pick_model(
    model: str | None,
    effort: str | None,
    account: str | None,
    anywhere: bool = False,
) -> dict:
    argv = [
        "agent-pick",
        *(["-e", effort] if effort else []),
        *([f"--{account}"] if account else []),
        *(["--anywhere"] if anywhere else []),
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
    os.environ["PATH"] = f"{LIBEXEC}:{os.environ['PATH']}"
    cli()

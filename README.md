# agent-tools

Run prompts on a model you choose (claude, codex, or a local model via pi) from the shell, from
executable prompt scripts, and from the zsh prompt. Specific to my setup.

## Examples

Ask from the zsh prompt by ending the line with `|`, or `| MODEL`:

```
what is the difference between git rebase --onto and git rebase -i? |
explain SO_REUSEPORT in two sentences | luna
```

Type a description and press Ctrl-X Ctrl-A, or end it with `|` and press Tab; it is replaced by a
command to review and run. Undo (Ctrl-_) restores the description, which is also saved in atuin
history:

```
kill whatever is listening on port 8080
```

Write a command in English (`~/bin/commit-msg`):

```
#!/usr/bin/env -S agent-run -m luna
Write a git commit message for the diff in the input. The first line says what problem the
change solves.
```

```
git diff --staged | commit-msg                       # answer on stdout, cost on stderr
git diff --staged | AGENT_MODEL=opus commit-msg      # override the model
```

Start an interactive session:

```
agent                                                # pick a model with fzf
agent --personal -m opus                             # personal account, no menu
agent start -m opus --resume abc                     # pass arguments to the agent CLI
```

Run a prompt directly:

```
agent run                                            # pick a model with fzf, type a prompt
{ echo "Why does this fail?"; go test ./... 2>&1; } | agent run -m haiku
agent run --personal -m opus < prompt.md             # use the personal account
```

Start an interactive agent with GitHub issues pasted into its input:

```
agent from-issues -R myorg/myrepo 12 15
```

Start an interactive agent whose input is built from sources (issues, sessions, Slack
threads, meetings, files), with a manifest of what went in. `agent ctx --help` lists the
source types:

```
agent ctx --purpose "implement batch cancel" --budget 80000 \
    issue:212 session:claude:7e90a7c6 meeting:"design review" | agent with-input
```

Describe a session in plain language (its purpose, what it should know, what it must not
see) and have an agent prepare a saved recipe for it, checking exclusions by provenance and
stopping for approval. It prints the command that starts the session; it never starts it:

```
agent prepare-session "implement phase 1 of streams without seeing Moe's work"
agent ctx ~/src/temporalio-etc/log/recipes/streams-implementer.toml | agent with-input
```

Serve a local model; while it runs, `qwen-local` is offered as a model:

```
agent mlx-serve
```

## Building context

`agent ctx` builds a session's context from chosen sources, and `agent prepare-session` has an
agent choose them, checking exclusions by provenance. [`SKILL.md`](SKILL.md) gives the
principles and the process.

Dashed boxes are commands; dashed arrows return output to whoever ran them. Render with
`d2 --layout=tala`.

```d2
direction: right

prep: agent prepare-session\n(agent-run prompt script) {
  top: 0
  left: 0
  style.stroke-dash: 3
}

a: Agent A\n(agent-tools skill) {
  top: 350
  left: 0
}

you: You {
  top: 650
  left: 30
  shape: person
  width: 120
  height: 140
}

draft: <name>.draft.toml {
  top: 200
  left: 650
  shape: document
}

recipe: recipes/<name>.toml\n(log repo, committed) {
  top: 400
  left: 630
  shape: document
}

ctx: agent ctx\n(deterministic) {
  top: 680
  left: 660
  style.stroke-dash: 3
}

sources: Sources {
  top: 0
  left: 1150
  issues: Log issues\n(hub, INDEX.md) {shape: page; style.multiple: true}
  sessions: Session transcripts\n(agent-sessions) {shape: page; style.multiple: true}
  other: Slack threads,\nmeetings, files {shape: page; style.multiple: true}
}

context: Context Markdown\n(purpose, exclusions,\nmanifest, sources) {
  top: 680
  left: 1150
  shape: document
}

b: Session B\n(agent with-input) {
  top: 680
  left: 1650
}

you -> a: 1. description of B\n5. reply (approval or changes)
a -> prep: 2. run with description\n6. run with draft + reply
prep -> sources: "3. read sources, check provenance,\npost filtered copies and\nscratch files to log issues"
prep -> draft: 4a. write
prep -> a: 4b. report: manifest,\nexclusions, questions {style.stroke-dash: 3}
a -> you: 4c. report\n8. command {style.stroke-dash: 3}
draft -> recipe: 7. finalize on approval
you -> ctx: 9. agent ctx <recipe> | agent with-input
recipe -> ctx: 10a. sources, budget,\npurpose, exclusions
sources -> ctx: 10b. resolved raw
ctx -> context: 11. output
context -> b: 12. pasted as first input
b -> sources.issues: 13. write back what it learned
```

## Tools

`agent --help` documents every subcommand. Most subcommands run a script in `bin/`, which can
also be run directly as `agent-<subcommand>`.

| | |
|-|-|
| `agent [start]` | Start an interactive session. Model: `$AGENT_MODEL`, else `-m`, else fzf. |
| `agent run` | Run a prompt or prompt script. Model: `$AGENT_MODEL`, else `-m`, else fzf. |
| `agent pick` | Choose a model from `config/agent-models.toml`. |
| `agent prices-refresh` | Cache OpenRouter's model list, used for codex costs. |
| `agent ctx` | Build an agent's context from sources or a recipe within a token budget. No compression yet. |
| `agent prepare-session` | The prompt script that prepares a recipe. |
| `agent with-input` | Start an interactive agent with its input pre-filled from stdin. |
| `agent from-issues` | Same, from GitHub issues. Reads `~/.config/agent-from-issues.toml`. |
| `agent mlx-serve` | Serve a local MLX model over an OpenAI-compatible API. |
| `agent-suggest-command` | The prompt script behind Ctrl-X Ctrl-A. |
| `shell/agent.zsh` | The `\|` trigger, `\|` Tab, and Ctrl-X Ctrl-A. |

## Install

```
make install    # symlink bin/ and prompts/ into ~/bin, config/agent-models.toml into ~/.config;
                # install agent with uv tool
make test
```

Then source `shell/agent.zsh` from your zshrc. To teach an agent these tools, link this repo
as a skill, e.g. `ln -s ~/src/agent-tools ~/.claude/skills/agent-tools`.

Requires `uv`, `fzf`, `jq`, `rlwrap`, `tmux`, `atuin`, and whichever of `claude`, `codex`, `pi` you
configure. `agent-from-issues` also needs `gh-issue-to-md` from
[dandavison/tools](https://github.com/dandavison/tools).

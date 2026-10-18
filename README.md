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

A model call is stateless: a session's context is a list of messages that can be built from
any sources, and a past transcript is only one of them. `agent ctx` treats context as a
function of sources, a token budget and a purpose.

Principles:

- The durable unit is a topic, held in a log issue. Sessions are disposable: what a session
  learns is written back to the issue, and a new session is built from the issue rather than
  by resuming or forking an old one.
- Prefer written-down sources (log issues) to session transcripts. Use a transcript only for
  material that was never written down.
- Choosing sources needs judgement; building the context does not. An agent chooses the
  sources, and `agent ctx` builds the context from them deterministically. A recipe file saves
  the choice, so a session can be rebuilt later.
- Exclusions are checked by provenance, not keywords: material written by a session that saw
  excluded material is itself excluded. Where only part of a source is excluded, a filtered
  copy is posted to a log issue and used instead. Traces that cannot be removed are recorded.
- Every source must be permanent (a log issue, a git repo), not a scratch file.
- The context starts with a manifest of its sources and their sizes, so omissions are
  visible.

Process:

1. Describe the session you want to an agent: its purpose, what it should know, and what it
   must not see.
2. The agent runs `agent prepare-session`, which finds the topic's hub issue, looks for newer
   meetings and Slack threads, applies the exclusions, and checks the budget. It stops for
   your approval of the exclusions and the manifest, then saves the recipe.
3. You start the session yourself with `agent ctx <recipe> | agent with-input`. Its first job
   is to state its understanding and open questions.
4. The session writes back what it learns to the topic's issue. When it grows too large,
   rebuild it from the recipe, which now picks up the written-back state.

Limits: sources go in raw, and nothing is compressed when they exceed the budget. An exclusion
is an instruction to the session, not a mechanism: links in its sources could still lead it to
excluded material.

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
| `agent prepare-session` | The prompt script that prepares a recipe. Skill: `skills/prepare-session`. |
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

Then source `shell/agent.zsh` from your zshrc.

Requires `uv`, `fzf`, `jq`, `rlwrap`, `tmux`, `atuin`, and whichever of `claude`, `codex`, `pi` you
configure. `agent-from-issues` also needs `gh-issue-to-md` from
[dandavison/tools](https://github.com/dandavison/tools).

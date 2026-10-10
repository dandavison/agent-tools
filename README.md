# agent-tools

Run prompts on a model you choose (claude, codex, or a local model via pi) from the shell, from
executable prompt scripts, and from the zsh prompt. Specific to my setup.

## Examples

Ask from the zsh prompt by ending the line with `|`, or `| MODEL`:

```
which amazonian birds visit clay licks, and why? |
explain hoatzin digestion in two sentences | luna
```

Type a description and press Ctrl-X Ctrl-A; it is replaced by a command to review and run. Undo
(Ctrl-_) restores the description, which is also saved in atuin history:

```
find photos of toucans over 5MB in ~/Pictures
```

Write a command in English (`~/bin/species`):

```
#!/usr/bin/env -S agent-run -m luna
List every bird species in the input, one per line, with its scientific name.
```

```
species < field-notes.md                           # answer on stdout, cost on stderr
AGENT_MODEL=qwen-local species < field-notes.md    # override the model
```

Start an interactive session:

```
agent                                              # pick a model with fzf
agent --personal -m opus                           # personal account, no menu
```

Run a prompt directly:

```
agent-run                                          # pick a model with fzf, type a prompt
echo "Is the harpy eagle endangered?" | agent-run -m haiku
agent-run --personal -m opus < prompt.md           # use the personal account
```

Start an interactive agent with GitHub issues pasted into its input:

```
agent-from-issues -R macaw/field-guide 12 15
```

Serve a local model; while it runs, `qwen-local` is offered as a model:

```
mlx-serve
```

## Tools

| | |
|-|-|
| `agent` | Start an interactive session. Model: `$AGENT_MODEL`, else `-m`, else fzf. |
| `agent-run` | Run a prompt or prompt script. Model: `$AGENT_MODEL`, else `-m`, else fzf. |
| `agent-pick` | Choose a model from `config/agent-models.toml`. |
| `agent-prices-refresh` | Cache OpenRouter's model list, used for codex costs. |
| `agent-with-input` | Start an interactive agent with its input pre-filled from stdin. |
| `agent-from-issues` | Same, from GitHub issues. Reads `~/.config/agent-from-issues.toml`. |
| `mlx-serve` | Serve a local MLX model over an OpenAI-compatible API. |
| `agent-suggest-command` | The prompt script behind Ctrl-X Ctrl-A. |
| `shell/agent.zsh` | The `\|` trigger and Ctrl-X Ctrl-A. |

## Install

```
make install    # symlink bin/ and prompts/ into ~/bin, config/agent-models.toml into ~/.config
make test
```

Then source `shell/agent.zsh` from your zshrc.

Requires `uv`, `fzf`, `jq`, `rlwrap`, `tmux`, `atuin`, and whichever of `claude`, `codex`, `pi` you
configure. `agent-from-issues` also needs `gh-issue-to-md` from
[dandavison/tools](https://github.com/dandavison/tools).

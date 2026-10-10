# agent-tools

Tooling for running prompts and prompt scripts on a chosen model (claude, codex, or a local
model via pi), from the command line and from zsh. It is specific to my setup.

- `bin/agent-pick`: choose a model from `config/agent-models.toml` (fzf, or by name).
- `bin/agent-run`: run a prompt, or an executable prompt script, on that model. The answer goes
  to stdout, progress and cost to stderr.
- `bin/agent-prices-refresh`: cache OpenRouter's model list, which supplies prices.
- `bin/agent-with-input`, `bin/agent-from-issues`: start an interactive agent with its input
  pre-filled.
- `bin/mlx-serve`: serve a local MLX model over an OpenAI-compatible API, for pi and qwen
  (`config/pi`, `config/qwen`).
- `prompts/`: prompt scripts, e.g. `agent-suggest-command`.
- `shell/agent.zsh`: text ending in `|` or `| MODEL` is sent to agent-run; Ctrl-X Ctrl-A replaces
  the input with a suggested command.

A prompt script:

```
#!/usr/bin/env -S agent-run -m luna
Summarise my commits in this repo since yesterday as 3 bullet points.
```

`$AGENT_MODEL` overrides `-m`; with neither, agent-run asks via fzf.

`make install` symlinks `bin/*` and `prompts/*` into `~/bin` and the model config into
`~/.config`. `make test` runs the tests. `config/pi` and `config/qwen` are symlinked by my
devenv repo.

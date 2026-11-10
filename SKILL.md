---
name: agent-tools
description: |
  The `agent` CLI: run prompts on a chosen model, build a session's context from sources and
  recipes, prepare, compare and start sessions, and find past sessions (`agent sessions`).
  Also the log repo procedures: exfiltrate, gather-context, map-sessions.
argument-hint: "exfiltrate|gather-context|map-sessions|prepare-session <topic or description>"
---

# agent-tools

When invoked with arguments, the first word chooses the procedure below (exfiltrate,
gather-context, map-sessions, prepare-session) and the rest is its topic or description.

The full help of every command is at the end of this file, so you do not need `--help`.

## What you may run

- `agent run -m MODEL` runs a prompt non-interactively; the answer goes to stdout. Pass `-m`
  (or set `AGENT_MODEL`): without a terminal there is no model menu.
- `agent ctx` prints a context as Markdown. It only reads.
- `agent prepare-session` prepares a context recipe (below).
- `agent overview RECIPE.toml` opens a page summarising a recipe's sources in the browser.
- `agent sessions` finds and reads past sessions (below). `agent sessions resume` and
  `agent sessions attend` start agents; run them only when asked.

Never run `agent`, `agent start`, `agent new`, `agent quiz`, `agent with-input` or
`agent from-issues`. They start interactive sessions, which the user starts. Give the user
the command instead.

## Building context

A model call is stateless: a session's context is a list of messages that can be built from
any sources, and a past transcript is only one of them. `agent ctx` treats context as a
function of sources, a token budget and a purpose.

Principles:

- The durable unit is a topic, held in log issues. What a session learns is written back to
  them (see Exfiltrate below), so that a new session can be built from them.
- Continue a live session while the task is the same and its context is well below the
  limit. Start a new one from its recipe when the purpose changes, the context is large or
  full of dead ends, or the session has sat idle. Do not revive an idle session for a new
  purpose.
- Prefer written-down sources (log issues) to session transcripts. Use a transcript only for
  material that was never written down.
- Choosing sources needs judgement; building the context does not. An agent chooses the
  sources, and `agent ctx` builds the context from them deterministically. A recipe file saves
  the choice, so a session can be rebuilt later.
- Exclusions are checked by provenance, not keywords: material written by a session that saw
  excluded material is itself excluded. Where only part of a source is excluded, a filtered
  copy is posted to a log issue and used instead. Traces that cannot be removed are recorded.
- Every source must be permanent (a log issue, a git repo), not a scratch file.
- A context starts with the recipe and commit that built it, then a manifest of its sources
  and their sizes. It is the session's first message, so the transcript records where the
  session came from; `agent sessions ls --source` and `--recipe` find sessions by it.

Limits: sources go in raw, and nothing is compressed when they exceed the budget. An exclusion
is an instruction to the session, not a mechanism: links in its sources could still lead it to
excluded material.

## Preparing a session

When the user describes a session they want (its purpose, what it should know, what it must
not see), the procedure is a script; do not do its steps yourself.

1. Run `agent prepare-session "<the user's description, in their words>"`. It takes
   minutes. Run it in the background if your harness allows.
2. It writes the recipe, commits it in the log repo (not pushed), and ends with a report and
   the command that starts the session. The commit is the approval: the user reviews it with
   git. Show the user the report and the command. Never run the command, and never start the
   session any other way.
3. To change a recipe, pass the user's words on verbatim:
   `agent prepare-session <recipe path> "<their words>"`. It commits again.

The report lists the existing sessions on the topic and whether each has written back what it
learned; the recipe records them as `related_sessions`. Suggest exfiltrating any that have not.

The script asks before one kind of action only: posting a filtered copy or a scratch file to a
log issue, which an exclusion can need. It reports what it would post; pass the user's answer
on as in step 3. Never approve a posting on the user's behalf.

When the prepare-session prompt's rules change, offer to update existing recipes ("update to
the current rules"). The user describes what they want in their own words; you write and run
the commands.

The user starts the session with `agent new <recipe>`, which also offers `agent quiz`: the same
questions put to the new session and to one of the recipe's `related_sessions`, answers side by
side. The session's first job is to state its understanding and open questions, and wait. If
the user types a request after the context before sending, it states its understanding briefly
and then does the request. The latest state (a handoff) comes first in its context. It writes
back what it learns to the topic's issue. When it grows too large, it is rebuilt from its
recipe, which then picks up the written-back state.

## Past sessions

`agent sessions` indexes the transcripts of Claude Code
sessions and finds, reads and resumes them.

    agent sessions search "worktree relocation" -p wormhole   # find it
    agent sessions show <id> --turns                          # read what was said
    agent sessions cat <id> --tools                           # and what was run
    agent sessions ls --source issue:413                      # built from, or pasted, issue 413

- Output adapts to the caller: you get TSV with nothing truncated, and full ids and
  timestamps. Add `--json` for a structured payload, `-q` for bare ids. Hints and errors go to
  stderr; only data goes to stdout. Exit codes: 0 found something, 1 found nothing, 2 called
  wrong.
- Ids round-trip: whatever `search` prints is accepted by every other command, and any
  unambiguous prefix will do.
- Every command prints the next one to run, with the id filled in.
- Matching is case-insensitive and stemmed. Tool calls and their output are not indexed, so
  `search` matches what was said, not what was run.
- Context size is the peak the session reached, not a sum of its turns.
- `-p` takes several project globs, space-separated.
- The index is a cache over transcript files, refreshed by `agent sessions sync`. Do not sync
  unprompted: it is the user's call, and results are usually fine without it.
- `agent sessions serve` serves the index in a browser. `/genealogy/<id>` shows a lineage of
  forked sessions as a tree, each with the context it started from; the list page links to the
  genealogy of everything a search finds. Point the user at these pages rather than
  reconstructing lineages yourself.
- `agent sessions tree <id>` records a fork of a fork against the wrong parent. The genealogy
  page builds trees from shared turns and is right.

## Log repo

I store notes / AI agent discussions / plans etc in the github issues of temporalio/dandavison-log.
I sync the issues to markdown files stored in the repo; my local clone is ~/src/temporalio-etc/log.

### Exfiltrate

Exfiltrate means to extract from agent conversations their knowledge/understanding/beliefs/wisdom
etc regarding a certain topic and post it to issue(s) in my log repo.

Run `agent exfiltrate --print-prompt "<my words: the topic, and any sessions or target issue I
named>"` and follow the procedure it prints, ending with its report. If I ask for it in a
subagent, give the subagent that command. It never asks a session that is open in a terminal,
because that would close my pane; it lists those with a prompt for me to paste into them.

With a target issue, everything goes to that issue, whatever the sessions posted to before.
Without one, each session writes to the issues it has been posting to on the topic, or to a new
issue if there are none.


### Gather-context

When I ask you to gather-context on a topic, do the following:

1. Exfiltrate the topic (`agent exfiltrate`).
2. Open a new issue and write a placeholder topic summary in the body.
3. Derive search queries from the topic: key entities, technical terms, people, timeframes.
4. Search each source below in a parallel subagent, so that your own context stays clean. Each
   subagent reads everything relevant in full and returns what it found, with links, dates and
   people:
   - Slack: /agent-slack, exhaustively.
   - Notion: Notion MCP, including `notion-query-meeting-notes`.
   - Meetings: `tracecli` transcripts, and transcript issues in the log repo.
   - Google docs: fetch them as markdown if you can, or if not ask me to help.
   - Code: thorough and careful research in all relevant repos (`~/src/temporalio`,
     `~/src/temporal-all/repos`), fetching latest branches and including in-progress PRs.
   - Temporal docs MCP, and the `oncall` repo for Temporal Cloud operations, when relevant.
5. Fetch to disk the full content of every log issue written to by the exfiltrate using gh-issue-fetch.
6. Read all of it and write a synthesis as a comment(s) in the new issue: the key findings
   first, then the evidence by source, with links.

At any point, if slack/notion etc are unavailable, stop and ask me; do not skip/fallback -- this
will result in inferior results.


### Map-sessions

Map-sessions means to find all agent sessions relevant to a given topic, understand their
genealogical relationships, which log issues they are writing to, understand at a high level what
has been discussed in each lineage, and produce this information as a page of html including tables
and visualizations, as you see fit. This page should allow me to understand which session to reuse
for a certain purpose, or which sessions to extract information from, etc.

Start from the genealogy page of a search for the topic (`agent sessions serve`, above), which
shows the lineages and the context each session started from. Build the page from
`templates/map-sessions.html` in this skill's directory: copy it, set `<title>`
and `<h1>`, and replace the `META`, `PHASES`, `S` and `LINEAGES` data blocks (the comment above them
gives their shape). Do not change the styling or rendering code. Use the genealogy page for
the trees, and parallel subagents to summarise lineages; for a forked child, summarise only what
happened after the fork. Write the html to the map-sessions/ dir in my log repo.

<!-- Everything below is generated by `make skill` from the commands' help. -->

## `agent` commands

```
Usage: agent [OPTIONS] [COMMAND] [ARGS]...

  Start agent sessions and run prompts on a chosen model.

  With no subcommand, start an interactive session, passing other options to the model's CLI (e.g.
  `agent -r`). The model is $AGENT_MODEL if set, else -m MODEL, else chosen with fzf; then the
  effort is $AGENT_EFFORT if set, else -e EFFORT, else chosen with fzf, for a model with efforts.
  The account is chosen by the repo's directory (see [accounts] in agent-models.toml); -p/-w must
  agree with it, and are required where it has no account.

Options:
  -m TEXT         Model name from ~/.config/agent-models.toml.
  -e TEXT         Effort, from the model's efforts in ~/.config/agent-models.toml.
  -p, --personal  Use the personal account.
  -w, --work      Use the work account.
  --help          Show this message and exit.

Commands:
  ctx
    Print an agent's context, built from SOURCES or a RECIPE.toml, as Markdown.

    It starts with a manifest of the sources and their token counts. Every source is included raw;
    if they exceed --budget, the manifest goes to stderr and nothing is output. Quote a source that
    has options.

    issue:N | issue:URL | GITHUB_ISSUE_URL         the body and comments (N: log repo)
    issue:N#issuecomment-ID                        one comment
    "issue:N exclude=issuecomment-ID,..."          all but those comments
    session:ID ["--whole"] ["--tools"]             agent sessions cat (without --whole,
                                                   only what followed the last compaction)
    session:ID@POINT                               the session up to that point's turn
    slack:URL | SLACK_URL                          slack-fetch
    notion:URL | NOTION_URL                        notion-fetch
    meeting:QUERY                                  tracecli transcript
    path:GLOB                                      matching files
    
    agent ctx --purpose "implement batch cancel" --budget 80000 issue:212 \
        session:claude:7e90a7c6 | agent with-input
    
    A recipe holds purpose, budget, sources, exclusions, provenance and optionally
    related_sessions (for agent quiz); relative paths in it are relative to it. Recipes are in ~/src/temporalio-etc/log/recipes.
    
    agent ctx ~/src/temporalio-etc/log/recipes/batch-cancel.toml | agent with-input

  describe-issues
    Print each issue's title, then the first-line H1s of its body and comments, indented.

    agent describe-issues 394 389 https://github.com/OWNER/REPO/issues/12
    ISSUE is a number (log repo) or URL.

  exfiltrate
    Get the sessions that discussed a topic to write what they know into log issues.

    agent exfiltrate [--print-prompt] "TOPIC, and optionally sessions and a target issue"
    A prompt script. Never asks a session open in a terminal; reports it instead.
    --print-prompt prints the procedure, for an agent to follow itself.

  from-issues
    Start an interactive agent with GitHub issues pre-filled in its input.

    agent from-issues [-R OWNER/REPO] [-p|--personal|-w|--work] [-m MODEL] ISSUE... [-- AGENT [ARG...]]
    ISSUE is a number or URL. Reads ~/.config/agent-from-issues.toml.

  mlx-serve
    Serve a local MLX model over an OpenAI-compatible API.

    agent mlx-serve [MLX_LM_SERVER_ARG...]
    Env: MLX_MODEL, MLX_PORT, MLX_MAX_TOKENS.

  new
    Prepare a session from a description, then start it on Enter.

    agent new [-p|--personal|-w|--work] [-m MODEL] "DESCRIPTION OF THE SESSION"
    agent new [-p|--personal|-w|--work] [-m MODEL] RECIPE.toml
    Runs prepare-session and shows its report. Enter starts the session with the
    recipe's context; typed changes revise the recipe first. Requires tmux.

  overview
    Open a browser page summarising a RECIPE.toml: purpose, size against the budget, exclusions,
    provenance, and each source's tokens, headings and a short summary.

    agent overview ~/src/temporalio-etc/log/recipes/batch-cancel.toml
    The page is written to a temporary directory; its path is printed.

  pick
    Choose a model ($AGENT_MODEL, else NAME, else fzf) and print it as JSON.

    agent pick [-p|-w] [--anywhere] [--list] [NAME]

  prepare-session
    Prepare a context recipe for a new session described in plain language.

    agent prepare-session "DESCRIPTION OF THE SESSION"
    agent prepare-session RECIPE.toml "CHANGES"
    Each run commits the recipe in the log repo and prints the command that starts
    the session; it never starts it.

  prices-refresh
    Cache OpenRouter's model list, used for codex costs.

  quiz
    Ask a session prepared from RECIPE.toml and an existing session the same questions, and show
    their answers one after the other.

    agent quiz -m opus ~/src/temporalio-etc/log/recipes/batch-cancel.toml
    The existing session is chosen with fzf from the recipe's related_sessions, and
    forked, so it is not changed. Each answer shows what its turn cost.

  run
    Run a prompt non-interactively; the answer goes to stdout.

    agent run [-p|-w] [-m MODEL] [--no-tools]                prompt from stdin
    agent run [-p|-w] [-m MODEL] [--no-tools] FILE [ARG...]  prompt script
    agent run --print-prompt FILE [ARG...]                           print its prompt instead

  sessions
    Find and resume the sessions you have had with coding agents.

    `sync` brings the index up to date with the transcript files on disk; every other command reads.

  start
    Start an interactive session, passing other arguments to the model's CLI.

    agent start -m opus --resume abc

  suggest-command
    Suggest a zsh command line that does what stdin describes.

    agent suggest-command < DESCRIPTION
    A prompt script, used by Ctrl-X Ctrl-A in shell/agent.zsh.

  with-input
    Start an interactive agent with its input pre-filled from stdin.

    agent with-input [-p|--personal|-w|--work] [-m MODEL] [--name NAME] [-- AGENT [ARG...]] < FILE
    Requires tmux. Nothing is submitted.
```

## `agent sessions` commands

### `agent sessions agent [PROMPT]`

Start a coding agent that already knows this tool.

- `--with` — Which coding agent to start.
- `--model` — Which model it should run, named as that agent names it.

```
$ agent sessions agent                                    # pi, knowing this tool
$ agent sessions agent --with qwen
$ agent sessions agent --model anthropic/claude-opus-5
$ agent sessions agent "pick up the compaction work"      # your own first task
```

### `agent sessions attend`

Answer prompts left on the control channel, until interrupted.

- `--interval` — Seconds between polls. A poll that finds nothing costs no rate limit.
- `--once` — One pass, rather than staying up.
- `--verbose` — Say something on every poll, not just events.
- `--reset` — Clear the breaker and say what tripped it.
- `--no-limits` — Disable the breaker, spend ceilings, rate, resubmission and staleness checks.

### `agent sessions cat ID[@POINT]`

Print a session as markdown, read from the transcript itself.

- `--tools` — Include tool calls and their output.
- `--whole` — Include branches that were abandoned.
- `--last` — Only the most recent turn.
- `--upto` — Everything up to the end of the point's turn.

```
$ agent sessions cat claude:7e90a7c6 --tools         # the whole thing
$ agent sessions cat claude:7e90a7c6 --last          # only the turn just had
$ agent sessions cat claude:7e90a7c6@9f3c1d20        # only the turn around a point
$ agent sessions cat claude:7e90a7c6@9f3c1d20 --upto # everything up to that turn's end
```

### `agent sessions forget ID`

Take a session out of the index, and its transcript out of the agent's reach.

```
$ agent sessions forget claude:7e90a7c6       # by the id Claude prints as it exits
$ agent sessions forget 7e90a7c6              # or any unambiguous prefix of it
```

### `agent sessions issue ID`

Put a session on the control channel, so it can be carried on from anywhere.

```
$ agent sessions issue claude:7e90a7c6      # reach it from a phone
```

### `agent sessions ls`

List sessions, most recent first. No text matching; use `search` for that.

- `-p, --project` — Only these wormhole projects: space-separated globs; a name with no wildcard includes its tasks.
- `--agent` — Only this agent.
- `--since` — Only agent-sessions touched within e.g. 36h, 10d, 2w.
- `--min-context` — Only agent-sessions whose context reached e.g. 500k.
- `--source` — Only sessions whose context included this source, e.g. issue:413 (any part of the issue). Repeatable: all of them.
- `--recipe` — Only sessions whose context this recipe built.
- `--any-source` — Any of the sources and recipe, not all.
- `-n, --limit` — How many at most.
- `--sort` — Order by recency, peak context, or number of turns.

### `agent sessions rename ID TITLE`

Give a session a title of my own, in place of the one it was given.

### `agent sessions resume ID[@POINT]`

Pick a session back up, in the worktree it belongs to.

- `--fork` — Branch into a new session, leaving this one as it is.
- `--remote` — Hand it to the agent's remote control, for a phone.

```
$ agent sessions resume claude:7e90a7c6             # where it was left
$ agent sessions resume claude:7e90a7c6 --fork      # branch, leaving it as it is
$ agent sessions resume claude:7e90a7c6@9f3c1d20    # from a point inside it
$ agent sessions resume claude:7e90a7c6 --remote    # to carry on from a phone
```

### `agent sessions search QUERY`

Find agent-sessions whose text matches QUERY. Best match first, one per line.

- `-p, --project` — Only these wormhole projects: space-separated globs; a name with no wildcard includes its tasks.
- `--agent` — Only this agent.
- `--since` — Only agent-sessions touched within e.g. 36h, 10d, 2w.
- `--min-context` — Only agent-sessions whose context reached e.g. 500k.
- `--source` — Only sessions whose context included this source, e.g. issue:413 (any part of the issue). Repeatable: all of them.
- `--recipe` — Only sessions whose context this recipe built.
- `--any-source` — Any of the sources and recipe, not all.
- `-n, --limit` — How many at most.

```
$ agent sessions search compaction                    # case-insensitive, and stemmed:
                                                # matches Compaction, compacted
$ agent sessions search "worktree relocation"         # both words, in any order
$ agent sessions search '"worktree relocation"'       # the exact phrase
$ agent sessions search 'nexus OR chasm'              # either
$ agent sessions search 'activity NOT workflow'       # one but not the other
$ agent sessions search 'reloc*'                      # prefix of the STEM: relocat*
                                                # would find nothing
$ agent sessions search compaction -p temporal --since 2w
$ agent sessions search compaction --min-context 500k -n 5
$ agent sessions search compaction -q | head -1       # bare id, to pipe
```

### `agent sessions serve`

Serve the index in a browser, where a link is enough to resume.

- `--port` — Which port to listen on.
- `--host` — Which address to bind.
- `--lan` — Serve to the rest of the network, for a phone.
- `--attend` — Answer the control channel too.
- `--verbose` — Say something on every poll, not just events.
- `--open` — Open a browser at it.

### `agent sessions show ID`

Show one session and the history of my turns in it.

- `--turns` — Just my turns, without the header.

### `agent sessions skills`

Manage the agent-sessions skill, so an agent knows this tool from turn one.

### `agent sessions status`

Report index health: session counts, and whether a sync is due.

### `agent sessions sync`

Bring the index into line with the transcript files. Safe to re-run.

- `--agent` — Only read this agent's transcripts. Repeatable. Defaults to all.

### `agent sessions tree ID`

Show where a session branched, where it was compacted, and what forked off it.

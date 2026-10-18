---
name: agent-tools
description: |
  The `agent` CLI: run prompts non-interactively on a chosen model, build a session's context
  from issues, sessions, Slack, meetings and files (`agent ctx`), and prepare a new session
  with chosen context (`agent prepare-session`). Use when asked to run a prompt on another
  model, to build or rebuild a context, or to set up a session for a purpose.
  Triggers: "agent run", "agent ctx", "prepare a session", "set me up to",
  "start a session that", "context recipe"
---

# agent-tools

`agent --help` documents every subcommand in full. Read it before using one.

## What you may run

- `agent run -m MODEL` runs a prompt non-interactively; the answer goes to stdout. Pass `-m`
  (or set `AGENT_MODEL`): without a terminal there is no model menu.
- `agent ctx` prints a context as Markdown. It only reads.
- `agent prepare-session` prepares a context recipe (below).

Never run `agent`, `agent start`, `agent with-input` or `agent from-issues`. They start
interactive sessions, which the user starts. Give the user the command instead.

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

Limits: sources go in raw, and nothing is compressed when they exceed the budget. An exclusion
is an instruction to the session, not a mechanism: links in its sources could still lead it to
excluded material.

## Preparing a session

When the user describes a session they want (its purpose, what it should know, what it must
not see), the procedure is a script; do not do its steps yourself.

1. Run `agent prepare-session "<the user's description, in their words>"`. It takes
   minutes. Run it in the background if your harness allows.
2. It ends with a draft recipe and a report. Show the user the report. Do not approve anything
   on their behalf.
3. Pass the user's reply on verbatim: `agent prepare-session <draft path> "<their reply>"`.
   Repeat until it prints a saved recipe path and a command.
4. Give the user that command. Never run it, and never start the session any other way.

The session's first job is to state its understanding and open questions. It writes back
what it learns to the topic's issue. When it grows too large, it is rebuilt from its recipe,
which then picks up the written-back state:

    agent ctx ~/src/temporalio-etc/log/recipes/<name>.toml | agent with-input

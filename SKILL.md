---
name: agent-tools
description: |
  The `agent` CLI: run prompts non-interactively on a chosen model, build a session's context
  from issues, sessions, Slack, meetings and files (`agent ctx`), and prepare a new session
  with chosen context (`agent prepare-session`). Use when asked to run a prompt on another
  model, to build or rebuild a context, or to set up a session for a purpose. Also work with
  the log repo (temporalio/dandavison-log): exfiltrate, gather-context, map-sessions.
  Triggers: "agent run", "agent ctx", "prepare a session", "set me up to",
  "start a session that", "context recipe", "log", "exfiltrate", "gather-context",
  "assemble context", "context brief", "map-sessions"
argument-hint: "exfiltrate|gather-context|map-sessions|prepare-session <topic or description>"
---

# agent-tools

`agent --help` documents every subcommand in full. Read it before using one.

When invoked with arguments, the first word chooses the procedure below (exfiltrate,
gather-context, map-sessions, prepare-session) and the rest is its topic or description.

## What you may run

- `agent run -m MODEL` runs a prompt non-interactively; the answer goes to stdout. Pass `-m`
  (or set `AGENT_MODEL`): without a terminal there is no model menu.
- `agent ctx` prints a context as Markdown. It only reads.
- `agent prepare-session` prepares a context recipe (below).

Never run `agent`, `agent start`, `agent new`, `agent with-input` or `agent from-issues`.
They start interactive sessions, which the user starts. Give the user the command instead.

## Building context

A model call is stateless: a session's context is a list of messages that can be built from
any sources, and a past transcript is only one of them. `agent ctx` treats context as a
function of sources, a token budget and a purpose.

Principles:

- The durable unit is a topic, held in a log issue. Sessions are disposable: what a session
  learns is written back to the issue (see Exfiltrate below), and a new session is built from
  the issue rather than by resuming or forking an old one.
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
2. It writes the recipe, commits it in the log repo (not pushed), and ends with a report and
   the command that starts the session. The commit is the approval: the user reviews it with
   git. Show the user the report and the command. Never run the command, and never start the
   session any other way.
3. To change a recipe, pass the user's words on verbatim:
   `agent prepare-session <recipe path> "<their words>"`. It commits again.

The script asks before one kind of action only: posting a filtered copy or a scratch file to a
log issue, which an exclusion can need. It reports what it would post; pass the user's answer
on as in step 3. Never approve a posting on the user's behalf.

When the prepare-session prompt's rules change, offer to update existing recipes ("update to
the current rules"). The user describes what they want in their own words; you write and run
the commands.

The session's first job is to state its understanding and open questions, and wait. If the
user types a request after the context before sending, it states its understanding briefly
and then does the request. The latest state (a handoff) comes first in its context. It writes back
what it learns to the topic's issue. When it grows too large, it is rebuilt from its recipe,
which then picks up the written-back state:

    agent ctx ~/src/temporalio-etc/log/recipes/<name>.toml | agent with-input

## Log repo

I store notes / AI agent discussions / plans etc in the github issues of temporalio/dandavison-log.
I sync the issues to markdown files stored in the repo; my local clone is ~/src/temporalio-etc/log.

### Exfiltrate

Exfiltrate means to extract from agent conversations their knowledge/understanding/beliefs/wisdom
etc regarding a certain topic and post it to issue(s) in my log repo.

There are two forms of "exfiltrate": either I will ask you to exfiltrate to a certain target issue
number, or I will ask you to exfiltrate without specifying an issue number.

You will be using the /agent-sessions skill to find sessions and interact with them.

Run agent-sessions sync before you start.

#### Exfiltrate without a target issue number

When I ask you to "exfiltrate" agent discussion on a certain topic, do the following:

1. Use /agent-sessions to find relevant agent sessions.
2. Determine which log issues those agents have been posting comments to by studying the transcript
   or asking the agents. If they have not posted to any log issue then open a new issue, and post a
   terse description of the topic in question to the body, and consider the set of issues to be this
   one issue.
3. Use gh-issue-to-md to dump to disk the full markdown content of each issue.
4. For each agent session, use /agent-sessions to ask that agent session to determine whether it has
   any valuable knowledge/understanding/wisdom/belief that is not already reflected in the log issue
   comments. If it does, then it should post a new comment to the appropriate issue(s) containing
   this knowledge/understanding/wisdom/belief. To do this step, provide the appropriate subset of
   the issue markdown files dumped at step 3 inline in the prompt you deliver to the agent session.
   I would like you to provide these inline in your prompt, not merely as file references, so that
   the agent is forced to read it in its entirety. However, avoid triggering compaction in the agent
   sessions.
5. Return to me the issue numbers.

If you created a new issue at step 2 then at the end, read all comments via gh-issue-to-md and
update the body to contain a terse executive summary.


#### Exfiltrate to a target issue number

In this case, your task is to extract all knowledge/understanding/beliefs/wisdom etc on the topic to
a _new_ issue.

Formally, the procedure is as above but you disregard any log issues they may have already posted
to. I.e. at step 2 you _assume_ that they have posted to no log issue and open a new one, and then
proceed, so that the end result is that each agent session is asked to post a comment to the new
issue.


### Gather-context

When I ask you to gather-context on a topic, do the following:

1. Exfiltrate the topic
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
5. Fetch to disk the full content of every log issue written to by the exfiltrate using gh-issue-to-md.
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

Build the page from `templates/map-sessions.html` in this skill's directory: copy it, set `<title>`
and `<h1>`, and replace the `META`, `PHASES`, `S` and `LINEAGES` data blocks (the comment above them
gives their shape). Do not change the styling or rendering code. Use `agent-sessions tree` for
genealogy, and parallel subagents to summarise lineages; for a forked child, summarise only what
happened after the fork. Write the html to the map-sessions/ dir in my log repo.

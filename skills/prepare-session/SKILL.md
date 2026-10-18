---
name: prepare-session
description: |
  Prepare a new agent session with chosen context: its purpose, what it should know, and
  what it must not see. Use when Dan asks to set up, start, build or rebuild a session for
  a purpose, or to make or change a context recipe.
  Triggers: "prepare a session", "set me up to", "start a session that", "context recipe"
---

# Prepare a session

The procedure is a script; do not do its steps yourself.

1. Run `agent prepare-session "<Dan's description of the session, in his words>"`. It takes
   minutes. Run it in the background if your harness allows.
2. It ends with a draft recipe and a report. Show Dan the report. Do not approve anything
   on his behalf.
3. Pass his reply on verbatim: `agent prepare-session <draft path> "<his reply>"`. Repeat
   until it prints a saved recipe path and a command.
4. Give Dan that command. Never run it, and never start the session any other way: Dan
   starts it himself.

To rebuild an existing session from its saved recipe, give Dan
`agent ctx ~/src/temporalio-etc/log/recipes/<name>.toml | agent with-input`.

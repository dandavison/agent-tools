"""Sessions forked from one another, as one tree, each with the context it was started from.

A fork is written as a copy of its parent's thread, uuids and all, so the
threads of a lineage merge wherever they share a turn: what they share is drawn
once, and each node of the tree is a run of turns that one set of sessions has
in common. Turns rather than records, because a copy does not always link its
silent records (tool calls, attachments) the way the original did. Each session
contributes its live thread only, so a branch rewound within a session is not
shown.
"""

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from agent_sessions import contexts
from agent_tools.overview import SLACK, issue_url, wormhole_url

# Messages the harness writes in the user's place.
HARNESS = re.compile(
    r"\s*<(task-notification|local-command-stdout|local-command-caveat|system-reminder"
    r"|bash-input|bash-stdout|ide_opened_file)>"
)
COMMAND = re.compile(r"\s*<command-")
COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
PASTE_MARK = re.compile(r"</?pasted_content[^>]*>")
# A turn is shown on one line, so more than a line's worth is never read.
LINE = 300


@dataclass(slots=True)
class Merged:
    """The turns of a lineage's live threads, one per uuid, and which sessions hold each."""

    sessions: dict[str, dict]
    forked_from: dict[str, str]
    selected: set[str]
    steps: dict[str, dict] = field(default_factory=dict)
    members: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    parent: dict[str, str] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


def of(conn: sqlite3.Connection, session_id: str) -> dict:
    """The whole lineage of one session."""
    forked_from = _lineage(conn, {session_id})
    ids = {session_id, *forked_from, *forked_from.values()}
    return {"focus": session_id, "nodes": _nodes(conn, ids, forked_from, ids)}


def forest(conn: sqlite3.Connection, selected: set[str]) -> dict:
    """The lineages of a set of sessions, with others only where they join two of the set."""
    forked_from = _lineage(conn, selected)
    ids = _joining(selected, forked_from)
    joined = {c: p for c, p in forked_from.items() if c in ids and p in ids}
    return {"focus": None, "nodes": _nodes(conn, ids, joined, selected)}


def said(uuid: str, ts: int | None, text: str) -> list[dict]:
    """A user turn: the context it pasted, if it pasted one, and what was typed."""
    if HARNESS.match(text):
        return []
    if COMMAND.match(text):
        text = _command(text)
    built = contexts.parse(text)
    turn = {
        "kind": "turn",
        "uuid": uuid,
        "ts": ts,
        "text": _line(built.typed if built else text),
    }
    return ([_context(built)] if built else []) + ([turn] if turn["text"] else [])


def _sessions(conn: sqlite3.Connection, ids: set[str]) -> dict[str, dict]:
    return {
        row["id"]: dict(row)
        for row in conn.execute(
            "SELECT id, title, started_at, leaf_uuid FROM session"
            f" WHERE id IN ({','.join('?' * len(ids))})",
            list(ids),
        )
    }


def lineages(conn: sqlite3.Connection, ids: set[str]) -> list[frozenset[str]]:
    """The lineages these sessions are in: each one and every session joined to it by forks."""
    forked_from = _lineage(conn, ids)
    group = {s: frozenset({s}) for s in ids | forked_from.keys() | set(forked_from.values())}
    for child, parent in forked_from.items():
        joined = group[child] | group[parent]
        for s in joined:
            group[s] = joined
    return list(set(group.values()))


def _nodes(
    conn: sqlite3.Connection, ids: set[str], forked_from: dict[str, str], selected: set[str]
) -> list[dict]:
    merged = _merge(conn, _sessions(conn, ids), forked_from, selected)
    roots = _order(merged, [u for u in merged.steps if u not in merged.parent])
    return [seg for root in roots for seg in _segments(merged, root, None, root)]


def _joining(selected: set[str], forked_from: dict[str, str]) -> set[str]:
    """The selected sessions, and those on the forks between two of them."""
    neighbours: dict[str, set[str]] = defaultdict(set)
    for child, parent in forked_from.items():
        neighbours[child].add(parent)
        neighbours[parent].add(child)
    ids = selected | neighbours.keys()
    while loose := {i for i in ids - selected if len(neighbours[i] & ids) <= 1}:
        ids -= loose
    return ids


def _merge(
    conn: sqlite3.Connection,
    sessions: dict[str, dict],
    forked_from: dict[str, str],
    selected: set[str],
) -> Merged:
    merged = Merged(sessions, forked_from, selected)
    for id, session in sessions.items():
        steps = _steps(_thread(conn, session))
        for before, step in zip([None, *steps], steps, strict=False):
            merged.members[step["uuid"]].add(id)
            merged.steps.setdefault(step["uuid"], step)
            if before:
                merged.parent[step["uuid"]] = before["uuid"]
    for child, parent in merged.parent.items():
        merged.children[parent].append(child)
    return merged


def _segments(merged: Merged, start: str, above: str | None, tree: str) -> list[dict]:
    """The run from `start` that one set of sessions shares, then what follows it."""
    run = [start]
    while (
        len(kids := merged.children[run[-1]]) == 1
        and merged.members[kids[0]] == merged.members[start]
    ):
        run.append(kids[0])
    steps = [merged.steps[u] for u in run]
    owner = merged.sessions[_owner(merged, start)]
    contexts = [s["context_tokens"] for s in steps if s["context_tokens"]]
    segment = {
        "id": start,
        "parent": above,
        "tree": tree,
        "inside": bool(merged.members[start] & merged.selected),
        "session": {"id": owner["id"], "title": owner["title"]},
        "members": sorted(merged.members[start]),
        "started_at": steps[0]["ts"],
        "context_tokens": contexts[-1] if contexts else 0,
        "items": [item for s in steps for item in s["items"]],
    }
    below = (s for kid in _order(merged, kids) for s in _segments(merged, kid, start, tree))
    return [segment, *below]


def _owner(merged: Merged, uuid: str) -> str:
    """The session that wrote it: every other one holding it forked from it, at some remove.

    Not the earliest started, because a fork's copy carries the original's timestamps.
    """
    held = merged.members[uuid]
    return min(id for id in held if merged.forked_from.get(id) not in held)


def _order(merged: Merged, uuids: list[str]) -> list[str]:
    return sorted(uuids, key=lambda u: (merged.steps[u]["ts"] or 0, _owner(merged, u)))


def _lineage(conn: sqlite3.Connection, ids: set[str]) -> dict[str, str]:
    """The forks joining these sessions to others, in either direction: child to parent."""
    forked_from: dict[str, str] = {}
    found, frontier = set(ids), list(ids)
    while frontier:
        at = frontier.pop()
        for row in conn.execute(
            "SELECT child, parent FROM session_edge"
            " WHERE kind = 'fork' AND (child = ? OR parent = ?)",
            (at, at),
        ):
            forked_from[row["child"]] = row["parent"]
            for other in {row["child"], row["parent"]} - found:
                found.add(other)
                frontier.append(other)
    return forked_from


def _thread(conn: sqlite3.Connection, session: dict) -> list[dict]:
    """The live thread, root first, continuing across compactions to what preceded them."""
    compactions = {
        row["uuid"]: dict(row)
        for row in conn.execute(
            "SELECT uuid, ts, trigger, pre_tokens, post_tokens, logical_parent_uuid"
            " FROM compaction WHERE session_id = ?",
            (session["id"],),
        )
    }
    nodes: list[dict[str, Any]] = [
        dict(row) | {"compaction": compactions.get(row["uuid"])}
        for row in conn.execute(
            "SELECT uuid, parent_uuid, role, text, ts, context_tokens FROM node"
            " WHERE session_id = ? ORDER BY seq",
            (session["id"],),
        )
    ]
    by_uuid = {n["uuid"]: n for n in nodes}
    node = by_uuid.get(session["leaf_uuid"] or "") or (nodes[-1] if nodes else None)
    thread: list[dict] = []
    seen: set[str] = set()
    while node and node["uuid"] not in seen:
        seen.add(node["uuid"])
        thread.append(node)
        compacted = node["compaction"] or {}
        node = by_uuid.get(node["parent_uuid"] or compacted.get("logical_parent_uuid") or "")
    return thread[::-1]


def _steps(thread: list[dict]) -> list[dict]:
    """The records worth showing, each with the context its replies grew to."""
    steps: list[dict] = []
    for node in thread:
        if items := _items(node):
            steps.append(
                {"uuid": node["uuid"], "ts": node["ts"], "items": items, "context_tokens": 0}
            )
        elif steps and node["context_tokens"]:
            steps[-1]["context_tokens"] = node["context_tokens"]
    return steps


def _items(node: dict) -> list[dict]:
    if c := node["compaction"]:
        return [
            {
                "kind": "compaction",
                "ts": c["ts"],
                "trigger": c["trigger"],
                "pre_tokens": c["pre_tokens"],
                "post_tokens": c["post_tokens"],
            }
        ]
    if node["role"] == "user" and node["text"]:
        return said(node["uuid"], node["ts"], node["text"])
    return []


def _context(built: contexts.Context) -> dict:
    return {
        "kind": "context",
        "recipe": built.recipe.stem if built.recipe else None,
        "recipe_url": wormhole_url(built.recipe) if built.recipe else None,
        "commit": built.commit,
        "sources": [_source(s) for s in built.sources],
    }


def _source(source: contexts.Source) -> dict:
    """Where it is, and the list of sessions built from it."""
    return {
        "uri": source.uri,
        "tokens": source.tokens,
        "url": _url(source.uri),
        "list": f"/?{urlencode({'source': contexts.identity(source.uri)})}",
    }


def _url(uri: str) -> str | None:
    if uri.startswith(("issue:", "https://github.com/")):
        return issue_url(uri.split()[0])
    if uri.startswith("slack:"):
        return uri.removeprefix("slack:")
    return uri if SLACK.match(uri) else None


def _command(text: str) -> str:
    """`/name args`, which is what was typed, from the record Claude makes of it."""
    name, args = COMMAND_NAME.search(text), COMMAND_ARGS.search(text)
    return f"{name[1] if name else ''} {args[1] if args else ''}"


def _line(text: str) -> str:
    return " ".join(PASTE_MARK.sub(" ", text).split())[:LINE]

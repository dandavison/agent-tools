"""Sessions that talk to each other, and what each was given to start with.

A network is declared in a TOML file under DIRECTORY: its sessions, where each
one's context came from (a recipe, or a note and sources), and the channels
between them. What actually crossed a channel is not declared but found: a
relay is a user turn in one session containing an assistant reply of the other,
which is what pasting one into the other leaves behind.
"""

import re
import sqlite3
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_sessions import query

DIRECTORY = Path.home() / ".config" / "agent-sessions" / "networks"

# Fewer words in common than this is coincidence, not pasting.
WINDOW = 12
PREVIEW = 600


@dataclass(frozen=True, slots=True)
class Relay:
    reply: str
    replied_at: int | None
    prompt: str
    prompted_at: int | None
    text: str


def load(conn: sqlite3.Connection, name: str, live: set[str]) -> dict | None:
    path = DIRECTORY / f"{name}.toml"
    if not path.is_file():
        return None
    spec = tomllib.loads(path.read_text())
    ids = {s["id"]: _resolve(conn, s["id"]) for s in spec["session"]}
    return {
        "title": spec.get("title", name),
        "sessions": [_session(conn, s, ids[s["id"]], live) for s in spec["session"]],
        "channels": [
            {
                "from": ids[c["from"]],
                "to": ids[c["to"]],
                "carries": c.get("carries", ""),
                "relays": [asdict(r) for r in relays(conn, ids[c["from"]], ids[c["to"]])],
            }
            for c in spec.get("channel", [])
        ],
    }


def relays(conn: sqlite3.Connection, source: str, target: str) -> list[Relay]:
    replies = [
        (r, _words(r["text"]))
        for r in _nodes(conn, source, "assistant")
        if len(r["text"].split()) >= WINDOW
    ]
    found = []
    # The first prompt is the session's context, which may quote the other
    # session by way of a log issue; that is not a relay.
    for prompt in _nodes(conn, target, "user")[1:]:
        said = _words(prompt["text"]).split()
        earlier = [(r, w) for r, w in replies if (r["ts"] or 0) <= (prompt["ts"] or 0)]
        if reply := _pasted(said, earlier):
            found.append(
                Relay(
                    reply["uuid"],
                    reply["ts"],
                    prompt["uuid"],
                    prompt["ts"],
                    reply["text"][:PREVIEW],
                )
            )
    return found


def _pasted(said: list[str], replies: list[tuple[dict, str]]) -> dict | None:
    for start in range(0, len(said) - WINDOW + 1, WINDOW):
        probe = " ".join(said[start : start + WINDOW])
        for reply, words in replies:
            if probe in words:
                return reply
    return None


def _words(text: str) -> str:
    return " ".join(re.sub(r"</?pasted_content[^>]*>", " ", text).split())


def _nodes(conn: sqlite3.Connection, session: str, role: str) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT uuid, ts, text FROM node WHERE session_id = ? AND role = ? AND text != ''"
            " ORDER BY seq",
            (session, role),
        )
    ]


def _resolve(conn: sqlite3.Connection, id: str) -> str:
    found = query.get(conn, id)
    if found is None:
        raise LookupError(f"No session matches {id}.")
    return found["id"]


def _session(conn: sqlite3.Connection, spec: dict, id: str, live: set[str]) -> dict:
    s = query.get(conn, id) or {}
    latest = conn.execute(
        "SELECT ts, text FROM node WHERE session_id = ? AND role = 'assistant' AND text != ''"
        " ORDER BY seq DESC LIMIT 1",
        (id,),
    ).fetchone()
    return {
        "id": id,
        "role": spec.get("role", ""),
        "title": s.get("title"),
        "model": s.get("model"),
        "project": s.get("project"),
        "branch": s.get("git_branch"),
        "started_at": s.get("started_at"),
        "ended_at": s.get("ended_at"),
        "turns": s.get("n_user_turns"),
        "context_tokens": s.get("context_tokens"),
        "live": id in live,
        "context": _context(spec),
        "latest": {"ts": latest["ts"], "text": latest["text"][:PREVIEW]} if latest else None,
    }


def _context(spec: dict) -> dict:
    if recipe := spec.get("recipe"):
        path = Path(recipe).expanduser()
        r = tomllib.loads(path.read_text())
        return {
            "recipe": str(path),
            "purpose": r.get("purpose", "").strip().split("\n\n")[0].replace("\n", " "),
            "budget": r.get("budget"),
            "exclusions": r.get("exclusions", []),
            "sources": [
                {"uri": s["uri"], "provenance": s.get("provenance", "")} for s in r["sources"]
            ],
        }
    given = spec.get("context", {})
    return {
        "recipe": None,
        "purpose": given.get("note", ""),
        "budget": None,
        "exclusions": [],
        "sources": [{"uri": uri, "provenance": ""} for uri in given.get("sources", [])],
    }

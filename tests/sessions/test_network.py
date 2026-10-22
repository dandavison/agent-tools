"""Sessions that talk to each other, through me pasting one's reply into the other."""

from pathlib import Path

import orjson
import pytest

from agent_sessions import db, index, network, web
from agent_sessions.models import Node, Session

IMPLEMENTER = "claude:00704f66-3612-400c-9125-a41502748732"
REVIEWER = "claude:45ec777b-c361-4731-9bc2-5f713641673d"
PROPOSAL = (
    "Proposal: the Notifier wakes every reader of a stream when a record is appended,"
    " and a reader that was not waiting reads from its offset on its next call."
)
REVIEW = (
    "The revision resolves most of the ten points, and I would accept all three departures."
    " But the new mode rule creates a serious problem."
)


@pytest.fixture
def indexed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "index.db"
    conn = db.connect(path)
    for id, title in ((IMPLEMENTER, "implementer"), (REVIEWER, "moe-expert")):
        db.write_session(
            conn,
            Session(
                id=id,
                agent="claude",
                native_id=id.split(":")[1],
                path=str(tmp_path / f"{title}.jsonl"),
                title=title,
                model="claude-opus-5-5",
                context_tokens=400_000,
            ),
        )
    db.write_nodes(
        conn,
        [
            Node(IMPLEMENTER, "i1", None, 0, "user", 10, "Write the Notifier proposal."),
            Node(IMPLEMENTER, "i2", "i1", 1, "assistant", 20, PROPOSAL, context_tokens=300_000),
            Node(REVIEWER, "r0", None, 0, "user", 25, f"# Context\n\n{PROPOSAL}"),
            Node(REVIEWER, "r1", "r0", 1, "user", 30, f"Please review this:\n\n{PROPOSAL}"),
            Node(REVIEWER, "r2", "r1", 2, "assistant", 40, REVIEW, context_tokens=350_000),
            Node(REVIEWER, "r3", "r2", 3, "user", 41, "Yes"),
            Node(IMPLEMENTER, "i3", "i2", 2, "user", 50, f"<pasted_content>\n{REVIEW}"),
            Node(IMPLEMENTER, "i4", "i3", 3, "assistant", 60, "Yes", context_tokens=310_000),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(index.SOURCES["claude"], "live", dict)
    return path


@pytest.fixture
def spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    recipe = tmp_path / "reviewer.toml"
    recipe.write_text(
        'purpose = """\nYou review the implementer.\n\nMore detail.\n"""\n'
        "budget = 250000\n"
        "exclusions = []\n"
        '[[sources]]\nuri = "issue:413"\nprovenance = "The handoff."\n'
    )
    directory = tmp_path / "networks"
    directory.mkdir()
    (directory / "streams.toml").write_text(
        'title = "Streams"\n'
        '[[session]]\nid = "00704f66"\nrole = "implementer"\n'
        'context = { note = "Issue #412, pasted in full.", sources = ["issue:412"] }\n'
        f'[[session]]\nid = "45ec777b"\nrole = "reviewer"\nrecipe = "{recipe}"\n'
        '[[channel]]\nfrom = "00704f66"\nto = "45ec777b"\ncarries = "proposals"\n'
        '[[channel]]\nfrom = "45ec777b"\nto = "00704f66"\ncarries = "reviews"\n'
    )
    monkeypatch.setattr(network, "DIRECTORY", directory)
    return directory


def test_a_reply_pasted_into_another_session_is_a_relay(indexed: Path) -> None:
    conn = db.connect()
    [relay] = network.relays(conn, IMPLEMENTER, REVIEWER)
    assert (relay.reply, relay.prompt) == ("i2", "r1")
    [relay] = network.relays(conn, REVIEWER, IMPLEMENTER)
    assert (relay.reply, relay.prompt) == ("r2", "i3")


def test_a_few_words_in_common_are_not_a_relay(indexed: Path) -> None:
    """Both sessions said "Yes"; neither was pasted."""
    conn = db.connect()
    assert all(r.reply != "i4" for r in network.relays(conn, IMPLEMENTER, REVIEWER))


def test_what_reached_a_session_in_its_context_was_not_relayed(indexed: Path) -> None:
    """The reviewer's context includes the implementer's proposal, by way of a log issue."""
    conn = db.connect()
    assert [r.prompt for r in network.relays(conn, IMPLEMENTER, REVIEWER)] == ["r1"]


def test_a_network_carries_each_sessions_context_and_each_channels_relays(
    indexed: Path, spec: Path
) -> None:
    response = web.handle("/network/streams.json")
    assert response.status == 200
    shown = orjson.loads(response.body)
    implementer, reviewer = shown["sessions"]
    assert implementer["id"] == IMPLEMENTER
    assert implementer["context"]["sources"] == [{"uri": "issue:412", "provenance": ""}]
    assert reviewer["context"]["purpose"] == "You review the implementer."
    assert reviewer["context"]["budget"] == 250000
    assert reviewer["context"]["sources"] == [{"uri": "issue:413", "provenance": "The handoff."}]
    assert reviewer["latest"]["text"] == REVIEW
    proposals, reviews = shown["channels"]
    assert (proposals["carries"], len(proposals["relays"])) == ("proposals", 1)
    assert (reviews["from"], reviews["to"], len(reviews["relays"])) == (REVIEWER, IMPLEMENTER, 1)


def test_a_network_is_drawn_on_a_page_of_its_own(indexed: Path, spec: Path) -> None:
    response = web.handle("/network/streams")
    assert response.status == 200
    assert "/network/streams.json" in response.body


def test_an_unknown_network_is_not_found(indexed: Path, spec: Path) -> None:
    assert web.handle("/network/nope").status == 404

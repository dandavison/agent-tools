"""Sessions that forked from one another, each with the context it was started from."""

from pathlib import Path

import orjson
import pytest

from agent_sessions import db, genealogy, index, web
from agent_sessions.models import Compaction, Edge, Node, Session

PARENT = "claude:11111111-0000-0000-0000-000000000000"
CHILD = "claude:22222222-0000-0000-0000-000000000000"
UNRELATED = "claude:33333333-0000-0000-0000-000000000000"
RECIPE = "/Users/dan/src/temporalio-etc/log/recipes/streams-implementer.toml"
SLACK = "https://temporaltechnologies.slack.com/archives/C08JS3TU4AW/p1792510188624239"
MANIFEST = (
    "| source | included | tokens |\n|-|-|-|\n"
    "| issue:412 exclude=issuecomment-6236552071 | raw | 21308 |\n"
    f"| {SLACK} | raw | 900 |\n"
    "| path:notes.md | raw | 40 |\n"
    "\nTotal: 22248 / 250000 tokens (estimated as characters / 4).\n"
)


def pasted(context: str, typed: str = "") -> str:
    """As `agent with-input` leaves it: the paste, then a `--` line, then what was typed."""
    paste = f'<pasted_content id="ab12">\n{context}\n\n</pasted_content id="ab12">'
    return f"{paste}\n\n--\n\n{typed}".strip()


def context(origin: str) -> str:
    return f"# Context\n\n{origin}Purpose: implement streams.\n\n{MANIFEST}\n## issue:412\n\nBody."


def session(conn, id: str, title: str, started_at: int, leaf: str) -> None:
    native = id.split(":")[1]
    db.write_session(
        conn,
        Session(
            id=id,
            agent="claude",
            native_id=native,
            path=f"/t/{native}.jsonl",
            title=title,
            started_at=started_at,
            leaf_uuid=leaf,
        ),
    )


def thread(id: str, *spec: tuple[str, str, str]) -> list[Node]:
    """Nodes in a line, each a child of the one before: (uuid, role, text)."""
    nodes, parent = [], None
    for seq, (uuid, role, text) in enumerate(spec):
        context_tokens = 1000 * (seq + 1) if role == "assistant" else 0
        nodes.append(Node(id, uuid, parent, seq, role, 100 + seq, text, None, context_tokens))
        parent = uuid
    return nodes


SHARED = (
    ("u1", "user", pasted(context(f"Recipe: {RECIPE} @ 05948a1\n\n"), "Start with the API.")),
    ("a1", "assistant", "Here is the API."),
    ("u2", "user", "Now the\nimplementation."),
    ("a2", "assistant", "Done."),
)


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "index.db"
    conn = db.connect(path)
    session(conn, PARENT, "streams-implementer", 100, "a3")
    # A fork's copy of its parent's records carries their timestamps.
    session(conn, CHILD, "streams-reviewer", 100, "a4")
    session(conn, UNRELATED, "something else", 300, "x1")
    db.write_nodes(conn, thread(PARENT, *SHARED, ("u3", "user", "three"), ("a3", "assistant", "")))
    db.write_nodes(conn, thread(CHILD, *SHARED, ("u4", "user", "four"), ("a4", "assistant", "")))
    db.write_nodes(conn, thread(UNRELATED, ("x1", "user", "elsewhere")))
    db.write_edges(conn, [Edge(child=CHILD, parent=PARENT, kind="fork", at_uuid="a2")])
    conn.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(index.SOURCES["claude"], "live", dict)
    return conn


def turns(node: dict) -> list[str]:
    return [i["text"] for i in node["items"] if i["kind"] == "turn"]


def test_a_fork_shares_the_turns_before_it_rather_than_repeating_them(conn) -> None:
    root, *children = genealogy.of(conn, PARENT)["nodes"]
    assert (root["session"]["id"], root["parent"]) == (PARENT, None)
    assert turns(root) == ["Start with the API.", "Now the implementation."]
    assert [(c["session"]["id"], c["parent"], turns(c)) for c in children] == [
        (PARENT, root["id"], ["three"]),
        (CHILD, root["id"], ["four"]),
    ]


def test_a_fork_whose_copy_threads_silent_records_differently_still_shares_its_turns(
    conn,
) -> None:
    conn.execute("DELETE FROM node WHERE session_id = ?", (CHILD,))
    silent = ("t1", "assistant", "")
    copy = (*SHARED[:2], silent, *SHARED[2:])
    db.write_nodes(conn, thread(CHILD, *copy, ("u4", "user", "four"), ("a4", "assistant", "")))
    conn.commit()
    root, *children = genealogy.of(conn, PARENT)["nodes"]
    assert (root["session"]["id"], turns(root)) == (
        PARENT,
        ["Start with the API.", "Now the implementation."],
    )
    assert [(c["session"]["id"], turns(c)) for c in children] == [
        (PARENT, ["three"]),
        (CHILD, ["four"]),
    ]


def test_the_whole_lineage_is_shown_from_any_session_in_it(conn) -> None:
    assert genealogy.of(conn, CHILD)["nodes"] == genealogy.of(conn, PARENT)["nodes"]


def test_a_session_outside_the_lineage_is_not_shown(conn) -> None:
    shown = {n["session"]["id"] for n in genealogy.of(conn, PARENT)["nodes"]}
    assert UNRELATED not in shown


def test_a_node_says_whose_it_is_when_it_started_and_how_large_its_context_had_grown(
    conn,
) -> None:
    root = genealogy.of(conn, PARENT)["nodes"][0]
    assert root["session"]["title"] == "streams-implementer"
    assert (root["started_at"], root["context_tokens"]) == (100, 4000)


def test_the_context_a_session_was_started_from_is_one_block_of_its_sources(conn) -> None:
    root = genealogy.of(conn, PARENT)["nodes"][0]
    built, typed = root["items"][:2]
    assert built == {
        "kind": "context",
        "recipe": "streams-implementer",
        "recipe_url": f"http://wormhole:7117/file/{RECIPE}:1?land-in=editor",
        "commit": "05948a1",
        "sources": [
            {
                "uri": "issue:412 exclude=issuecomment-6236552071",
                "tokens": 21308,
                "url": "https://github.com/temporalio/dandavison-log/issues/412",
            },
            {"uri": SLACK, "tokens": 900, "url": SLACK},
            {"uri": "path:notes.md", "tokens": 40, "url": None},
        ],
    }
    assert typed == {"kind": "turn", "uuid": "u1", "ts": 100, "text": "Start with the API."}


def test_a_context_from_an_uncommitted_recipe_says_so() -> None:
    text = pasted(context(f"Recipe: {RECIPE} (not committed)\n\n"))
    built = genealogy.said("u1", 100, text)
    assert built[0]["recipe"] == "streams-implementer"
    assert built[0]["commit"] is None


def test_a_context_from_before_recipes_were_recorded_has_sources_but_no_recipe() -> None:
    built = genealogy.said("u1", 100, pasted(context("")))
    assert (built[0]["recipe"], built[0]["recipe_url"], built[0]["commit"]) == (None, None, None)
    assert [s["tokens"] for s in built[0]["sources"]] == [21308, 900, 40]


def test_nothing_typed_after_a_context_is_not_a_turn() -> None:
    built = genealogy.said("u1", 100, pasted(context("")))
    assert [i["kind"] for i in built] == ["context"]


def test_a_turn_is_one_line_without_paste_markers() -> None:
    text = '<pasted_content id="cd34">\nline one\nline two\n</pasted_content id="cd34">\n\nok'
    [shown] = genealogy.said("u9", 100, text)
    assert shown["text"] == "line one line two ok"


def test_a_compaction_is_marked_where_it_happened_and_the_thread_continues_across_it(
    conn,
) -> None:
    db.write_nodes(
        conn,
        [
            Node(PARENT, "c1", None, 6, "system", 106, ""),
            Node(PARENT, "s1", "c1", 7, "summary", 107, "The summary."),
            Node(PARENT, "u5", "s1", 8, "user", 108, "five"),
        ],
    )
    db.write_compactions(
        conn, [Compaction(PARENT, "c1", 106, "auto", 900_000, 20_000, "a3", None, 0)]
    )
    conn.execute("UPDATE session SET leaf_uuid = 'u5' WHERE id = ?", (PARENT,))
    conn.commit()
    ours = genealogy.of(conn, PARENT)["nodes"][1]
    assert [i["kind"] for i in ours["items"]] == ["turn", "compaction", "turn"]
    assert ours["items"][1] == {
        "kind": "compaction",
        "ts": 106,
        "trigger": "auto",
        "pre_tokens": 900_000,
        "post_tokens": 20_000,
    }


def test_a_session_that_stopped_where_its_fork_began_ends_there(conn) -> None:
    conn.execute("DELETE FROM node WHERE session_id = ? AND seq > 3", (PARENT,))
    conn.execute("UPDATE session SET leaf_uuid = 'a2' WHERE id = ?", (PARENT,))
    conn.commit()
    root, child = genealogy.of(conn, PARENT)["nodes"]
    assert (root["session"]["id"], child["session"]["id"]) == (PARENT, CHILD)
    assert turns(child) == ["four"]


def test_the_genealogy_is_served_as_data_and_drawn_on_a_page(conn) -> None:
    response = web.handle("/genealogy/22222222.json")
    assert response.status == 200
    shown = orjson.loads(response.body)
    assert shown["focus"] == CHILD
    assert len(shown["nodes"]) == 3
    page = web.handle(f"/genealogy/{CHILD}")
    assert page.status == 200
    assert f"/genealogy/{CHILD}.json" in page.body


def test_an_unknown_session_has_no_genealogy(conn) -> None:
    assert web.handle("/genealogy/nope").status == 404
    assert web.handle("/genealogy/nope.json").status == 404


def test_a_session_page_links_to_its_genealogy(conn) -> None:
    assert f"/genealogy/{CHILD}" in web.handle(f"/session/{CHILD}").body

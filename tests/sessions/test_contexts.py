"""What a session was started from, read from the context `agent with-input` pasted into it."""

import time
from pathlib import Path

import pytest

from agent_sessions import contexts

RECIPE = "/Users/dan/src/temporalio-etc/log/recipes/moe-code-expert.toml"
SLACK = "https://temporaltechnologies.slack.com/archives/C08JS3TU4AW/p1792510188624239"
TEXT = (
    '<pasted_content id="ab12">\n# Context\n\n'
    f"Recipe: {RECIPE} @ 05948a1\n\nPurpose: review.\n\n"
    "| source | included | tokens |\n|-|-|-|\n"
    "| issue:413#issuecomment-6254016945 | raw | 2870 |\n"
    "| issue:413 exclude=issuecomment-6254016945 | raw | 56113 |\n"
    f"| slack:{SLACK}?thread_ts=1.2&cid=C1 | raw | 900 |\n"
    "\nTotal: 59883 / 250000 tokens (estimated as characters / 4).\n\n## issue:413\n\nBody.\n\n"
    '</pasted_content id="ab12">\n\n--\n\nStart.'
)


def test_a_context_says_its_recipe_and_sources() -> None:
    built = contexts.parse(TEXT)
    assert built is not None
    assert (built.recipe, built.commit, built.typed.strip()) == (Path(RECIPE), "05948a1", "Start.")
    assert [(s.uri, s.tokens) for s in built.sources] == [
        ("issue:413#issuecomment-6254016945", 2870),
        ("issue:413 exclude=issuecomment-6254016945", 56113),
        (f"slack:{SLACK}?thread_ts=1.2&cid=C1", 900),
    ]


def test_a_message_that_is_not_a_context_is_none() -> None:
    assert contexts.parse("# Context\n\nTyped, not pasted.") is None


@pytest.mark.parametrize(
    "uri",
    [
        "issue:413",
        "issue:413#issuecomment-6254016945",
        "issue:413 exclude=issuecomment-6254016945,issuecomment-1",
        "https://github.com/temporalio/dandavison-log/issues/413",
        "https://github.com/temporalio/dandavison-log/issues/413#issuecomment-1",
    ],
)
def test_every_part_of_a_log_issue_is_that_issue(uri: str) -> None:
    assert contexts.identity(uri) == contexts.identity("issue:413")


def test_an_issue_of_another_repo_is_another_issue() -> None:
    other = contexts.identity("https://github.com/temporalio/temporal/issues/413")
    assert other != contexts.identity("issue:413")


def test_a_slack_thread_is_the_same_however_it_is_linked() -> None:
    assert contexts.identity(f"slack:{SLACK}?thread_ts=1.2&cid=C1") == contexts.identity(SLACK)


def issue(number: int, url: str = "") -> str:
    """As `gh-issue-fetch` writes it; the url line is newer than the rest."""
    line = f"url: {url}\n" if url else ""
    return f'---\nnumber: {number}\n{line}date: 2026-09-30\ntitle: "History"\n---\n\n# History\n'


@pytest.mark.parametrize(
    ("pasted", "uri"),
    [
        (issue(395), "issue:395"),
        (issue(395, "https://github.com/temporalio/dandavison-log/issues/395"), "issue:395"),
        (
            issue(7, "https://github.com/temporalio/temporal/issues/7"),
            "https://github.com/temporalio/temporal/issues/7",
        ),
    ],
)
def test_a_pasted_issue_is_known_by_its_front_matter(pasted: str, uri: str) -> None:
    assert contexts.pasted_issues(f"Here it is:\n{pasted}") == [uri]


def test_every_issue_pasted_into_a_message_is_found() -> None:
    assert contexts.pasted_issues(issue(1) + issue(2)) == ["issue:1", "issue:2"]


def test_a_session_used_its_context_sources_and_the_issues_pasted_into_it() -> None:
    context = TEXT.replace("Start.", "Also this:\n" + issue(395))
    built = contexts.parse(TEXT)
    assert built is not None
    assert contexts.used("s", [("u1", context), ("u2", issue(396))]) == [
        contexts.ContextSource("s", "u1", "context", s.uri, "moe-code-expert")
        for s in built.sources
    ] + [
        contexts.ContextSource("s", "u1", "pasted", "issue:395", None),
        contexts.ContextSource("s", "u2", "pasted", "issue:396", None),
    ]


def test_the_issues_inside_a_context_were_not_pasted_on_their_own() -> None:
    inside = TEXT.replace("Body.", issue(413))
    assert [s.kind for s in contexts.used("s", [("u1", inside)])] == ["context"] * 3


THREAD = "https://temporaltechnologies.slack.com/archives/C08JS3TU4AW/p1791826899053549"
STARTED = time.strftime("%Y-%m-%d %H:%M", time.localtime(1791826899))


def test_a_slack_thread_is_in_a_channel_of_a_workspace() -> None:
    assert contexts.slack_channel(THREAD) == ("temporaltechnologies.slack.com", "C08JS3TU4AW")
    assert contexts.slack_channel("issue:413") is None


def test_a_slack_thread_is_labelled_by_its_channel_and_start() -> None:
    assert (
        contexts.label(THREAD, "crew-operator-commands") == f"#crew-operator-commands · {STARTED}"
    )


def test_a_slack_thread_in_a_channel_not_known_is_labelled_by_the_channel_id() -> None:
    assert contexts.label(THREAD, None) == f"#C08JS3TU4AW · {STARTED}"

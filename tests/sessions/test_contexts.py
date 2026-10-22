"""What a session was started from, read from the context `agent with-input` pasted into it."""

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

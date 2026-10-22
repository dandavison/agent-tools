"""Slack, through `agent-slack`, for what a transcript does not say: a channel's name."""

import json
import subprocess


def channels(workspace: str) -> dict[str, str]:
    """The names of the conversations I am in, by id."""
    listed = subprocess.run(
        ["agent-slack", "channel", "list", "--workspace", workspace, "--limit", "1000"],
        capture_output=True,
        check=True,
        text=True,
    )
    return {c["id"]: c["name"] for c in json.loads(listed.stdout)["channels"] if c.get("name")}

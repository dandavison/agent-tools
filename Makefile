.PHONY: install test skill

install:
	mkdir -p ~/.config
	ln -sf "$(CURDIR)/config/agent-models.toml" ~/.config/agent-models.toml
	uv tool install --editable --force .

test:
	uv run pytest -q
	tests/test-agent-text

skill:
	uv run python -m agent_tools.skill

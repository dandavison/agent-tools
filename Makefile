.PHONY: install test

install:
	mkdir -p ~/bin ~/.config
	for f in bin/* prompts/*; do ln -sf "$(CURDIR)/$$f" ~/bin/$$(basename $$f); done
	ln -sf "$(CURDIR)/config/agent-models.toml" ~/.config/agent-models.toml
	uv tool install --editable --force .
	uv tool install --editable --force ./sessions

test:
	uv run pytest -q
	cd sessions && uv run pytest -q tests/
	tests/test-agent-text

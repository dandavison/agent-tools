.PHONY: install test

install:
	mkdir -p ~/bin ~/.config
	for f in bin/* prompts/*; do ln -sf "$(CURDIR)/$$f" ~/bin/$$(basename $$f); done
	ln -sf "$(CURDIR)/config/agent-models.toml" ~/.config/agent-models.toml
	uv tool install --editable --force .

test:
	uv run pytest -q
	tests/test-agent-text

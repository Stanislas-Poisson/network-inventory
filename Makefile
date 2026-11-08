# Native targets: a virtual environment, no Docker needed.
VENV := .venv
PY := $(VENV)/bin/python

.DEFAULT_GOAL := help

.PHONY: help install test lint format serve

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "%-10s %s\n", $$1, $$2}'

$(VENV)/.installed: pyproject.toml
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet -e '.[dev]'
	touch $@

install: $(VENV)/.installed ## Create the virtual environment and install the project

test: install ## Run the tests
	$(PY) -m pytest

lint: install ## Check the code style
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format: install ## Fix the code style
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

serve: install ## Start the web interface
	$(PY) -m network_inventory serve

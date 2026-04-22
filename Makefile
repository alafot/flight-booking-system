.PHONY: build dev_install test lint format

PYTHON ?= python3.12
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python

$(VENV):
	$(PYTHON) -m venv $(VENV)

build: $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e '.[dev]'

dev_install: build
	$(VENV)/bin/pre-commit install

test:
	$(PY) -m pytest

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy src tests

format:
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

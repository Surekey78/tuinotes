.PHONY: install dev test tui lint types clean doctor screenshots

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -e .

dev:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

tui:
	$(PYTHON) -m tuinotes

lint:
	$(PYTHON) -m ruff check src tests

types:
	$(PYTHON) -m mypy

doctor:
	$(PYTHON) -m tuinotes doctor

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

PYTHON ?= python3
CARGO ?= cargo

.PHONY: fmt lint test test-python develop wheel

fmt:
	$(CARGO) fmt --all

lint:
	$(CARGO) fmt --all -- --check
	$(CARGO) clippy --all-targets -- -D warnings
	MYPYPATH=python $(PYTHON) -m mypy --python-version 3.10 python/gtlv tests

test: develop test-python

test-python:
	$(PYTHON) -m unittest discover -s tests -v

develop:
	$(PYTHON) -m maturin develop --release

wheel:
	$(PYTHON) -m maturin build --release

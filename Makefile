PYTHON ?= python3
CARGO ?= cargo

.PHONY: fmt lint test test-rust test-python develop wheel

fmt:
	$(CARGO) fmt --all

lint:
	$(CARGO) fmt --all -- --check
	$(CARGO) clippy --all-targets -- -D warnings
	MYPYPATH=python $(PYTHON) -m mypy --python-version 3.10 python/gtlv tests

test: test-rust develop test-python

test-rust:
	$(CARGO) test

test-python:
	$(PYTHON) -m unittest discover -s tests -v

develop:
	$(PYTHON) -m maturin develop --release

wheel:
	$(PYTHON) -m maturin build --release

# ds-runstore

Run storage of ds-init projects: the run folder format ([docs/format.md](docs/format.md)),
reading it, compacting it, the state of a run, and an example run for tests.

```python
from ds_runstore import read_table, list_runs, run_status, write_example_run

run = write_example_run("/tmp/example_run")           # a small valid run
read_table(run, "cells")                             # also channels, curves, predictions, plan
read_table(run, "predictions", with_cells=True)      # + axis and replicate columns
run_status(run)                                      # planned, done, ok, error, remaining, state
list_runs("runs/")                                   # every run folder with its essentials and state
```

Writing: `write_part`, `write_plan`, `compact` (the engine of a project builds the rows).
Only `pandas` and `pyarrow` (wide ranges, no pins). Python >= 3.11.

## Install

- **Project (uv):** `[tool.uv.sources] ds-runstore = { path = "../ds-runstore", editable = true }`
- **Tool / container:** `uv build` → `dist/ds_runstore-<version>-py3-none-any.whl`, `pip install` it.

## Name

`ds-runstore` (import `ds_runstore`) is free on PyPI; it was `ds-store` before, which clashes with an
unrelated macOS `.DS_Store` parser that imports as `ds_store`.

## Develop

```bash
uv sync && uv run pytest && uv run ruff check src tests
```

The tests run against an example run in both table states.

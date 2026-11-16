# ds-runstore

The run folder format of ds-init projects and the only code that reads and writes it
(contract: `docs/format.md`).

## Who changes this package

- **Only the agent maintaining the `ds-init` skill**, as part of a `ds-init` update that touches
  the run format. It commits and pushes here itself.
- **Every other agent (project, tool, analysis) never edits this package.** Report a wish or a
  bug as a comment on the Linear issue TIM-66 ("Skill Design - ds-init").

## Rules for a change

- Bump `version` in `pyproject.toml` with every pushed change to `src/`. Raise `store_version` only when a
  reader would otherwise misread a run (file or column renamed, removed or moved); additive,
  optional things keep it.
- Before pushing: `uv run pytest && uv run ruff check src tests`, and run the read test of every
  project that uses the package against the new state.
- Projects pin the commit through `uv.lock` and take a new state only on purpose, in an issue
  (`uv lock --upgrade-package ds-runstore`).

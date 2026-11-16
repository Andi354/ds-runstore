# Run folder format (store_version 1)

The contract between whatever **writes** runs (a ds-init project's engine) and whatever **reads**
them (the project's analysis code, tools, agents). Readers use `ds_runstore` and never open the
files themselves. The package is the only code that knows the layout below; a project's
`docs/run-format.md` links here and describes only what is specific to the project (which axes
and metrics exist, what the cells mean).

## Folder

```
runs/<YYYY-MM-DD_HHMM>_<name>/
  config.yaml          resolved config of the run, never edited
  config.base.yaml     merged base configs as they were at the start (optional)
  meta.json            provenance and state, see below
  code.diff            uncommitted code of the run (optional)
  plan.parquet         every planned cell (optional in old runs)
  cells.parquet        one row per planned cell
  channels.parquet     one row per cell and output channel (optional)
  curves.parquet       training curves, long form (optional)
  predictions.parquet  predictions with their truth (optional)
  description.yaml     why the run was made and what it should show (optional)
  summary.csv          derived readable view (never read by code)
  ckpt/, run.log, ...  whatever else the project keeps
```

While a run is going, a table is a folder of part files instead of one file:
`<table>/part-<shard>-<n>.parquet`, written atomically (`.tmp`, then rename) by one process
each. When the run ends, `compact` merges the parts into `<table>.parquet` and deletes them;
a table above 1 GB keeps its parts. Both states, and the moment between them, read the same.

## Tables

| table | one row per | primary key | columns |
|---|---|---|---|
| `plan` | planned cell | `row` | `row`, `cell_id`, `duplicate_of`, axes, replicates (+ project columns) |
| `cells` | planned cell | `row` | `row`, `cell_id`, axes, replicates, `is_duplicate`, `duplicate_of`, `status`, `error`, `duration_s`, `finished_at`, `shard`, metrics |
| `channels` | cell and channel | `row`, `channel` | the identity columns of `cells`, `channel`, metrics per channel, `finished_at` |
| `curves` | cell, epoch, metric | `cell_id`, `epoch`, `metric` | `cell_id`, `epoch`, `metric`, `value` |
| `predictions` | cell, date, channel | `cell_id`, `date`, `channel` | `cell_id`, `date`, `channel`, `y_pred`, `y_true` (+ optional `origin`) |

- `row`: position in the plan, dense. `cell_id`: identity of the cell's effective config and
  data; the same on duplicates. `status`: `ok` or `error` (`error` holds the message).
- **Axes and replicates** are named in `meta.json` (`axes`, `replicates`) and are columns of
  `plan` and `cells`; `curves` and `predictions` carry only `cell_id` (use `with_cells=True`).
- A **duplicate** (`is_duplicate`, `duplicate_of` = row of the original) copies the original's
  `cells` and `channels` rows; `curves` and `predictions` exist once per `cell_id`.
- Any column that is not listed is a metric or a project column; the package does not interpret
  them. Columns may be added without a new `store_version`.
- `curves` are long (`train_loss`, `val_loss`, ...), `predictions` hold `y_true` in every row.

## Reading rule

`read_table(run_dir, table, with_cells=False)` unites the compacted file and the parts it does
not contain yet (the file's metadata lists the parts it holds, so nothing counts twice), then
keeps per primary key the **newest** row:

- `cells`, `channels`: the row with the newest `finished_at` (a retried cell, `resume --retry-errors`).
- `curves`, `predictions`: the unit is the cell: all rows of a `cell_id` written last replace
  the earlier ones (part files carry a `written_at` column that is dropped on reading).

An empty DataFrame means the table has no rows. A missing `plan.parquet` reads as empty.

## State rule (`run_status`, `list_runs`)

`state` is `finished` if `meta.json` has `ended_at`; otherwise `running` if the newest written
file (tables, parts, logs; not checkpoints) is younger than `stale_after` (default 15 min), else
`stalled`. `planned` is `len(plan)`, else `meta.json` `plan.cells`, else unknown (None).
`done`, `ok`, `error` count the resolved `cells` rows, `remaining = planned - done`.

## meta.json

Read directly where convenient. Fields the package uses: `name`, `issue`, `store_version`,
`started_at`, `ended_at`, `epoch`, `axes`, `replicates`, `primary_metric`, `plan.cells`,
`migrated`. `counts` is the final tally written when a run ends; progress during a run comes
from `run_status`. Everything else (repos, data hashes, environment, `promoted_from`, ...) is the
project's provenance.

## Version rule

`store_version` is an integer in `meta.json` (this document: 1). A run without it is the
predecessor format and is read as is. The number only rises for changes a reader would
misread: a file or column renamed, removed or moved, a changed meaning of a key. A new optional
file or column does not raise it. A run with a higher number than the installed package knows is
an error (`UnsupportedStoreVersion`, "install a newer ds-runstore"), never silently wrong numbers;
`list_runs` shows such a run as `state: "unsupported"` instead of failing.

## Description (`description.yaml`, optional)

Written by a person (or an agent) per run; a run without one is valid. YAML, plain text without
Markdown, no results. Read with `read_description(run_dir)` (None without a file, else the fields and
a list `problems`; a broken file never raises), checked with `validate_description(fields)`, written
with `write_description(run_dir, fields)` (atomic, fixed field order, returns the problems).

| Field | Type | |
|---|---|---|
| `short` | text, one line, at most 100 characters | required |
| `purpose` | text, line breaks make paragraphs | required |
| `shows` | list of short texts | required |
| `notes` | list of texts | optional |
| `expectation` | text | optional |
| `compare_to` | list of run names | optional |

`list_runs` gives each run `short` (None without one) and `has["description"]`. The file does not
enter `cell_id`, may be edited after the run and is additive: `store_version` stays 1.

## Example run

`ds_runstore.write_example_run(path, finished=True, compacted=True)` writes a small valid run (8 cells,
one failed, one duplicate, 2 channels, curves, predictions, a description) in either state. Readers test
against it.

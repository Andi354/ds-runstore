"""
Run tables: read (whatever state the run is in), write parts atomically, compact.

While a run is going every process writes part files ``<table>/part-<shard>-<n>.parquet``
(``write_part``: ``.tmp``, then rename). ``compact`` merges the parts and an existing file into
one ``<table>.parquet`` and deletes the parts. ``read_table`` hides which state a table is in.
"""

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .format import COMPACT_LIMIT_BYTES, TABLES, check_version, read_json

_PARTS_KEY = b"ds_runstore.parts"
_PART_RE = re.compile(r"part-(\d+)-(\d+)\.parquet$")


def _uniform(df):
    """Parquet needs one type per column; mixed object columns become strings."""
    for col in df.columns:
        if df[col].dtype == object:
            types = {type(v) for v in df[col] if v is not None and v == v}
            if len(types) > 1:
                df[col] = df[col].map(lambda v: v if v is None or v != v else str(v))
    return df


def _table_file(run_dir, table):
    return Path(run_dir) / f"{table}.parquet"


def _parts(run_dir, table):
    return sorted(Path(run_dir, table).glob("part-*.parquet"))


def _consumed(path):
    """Part names a compacted file already contains (file metadata)."""
    meta = pq.read_schema(path).metadata or {}
    return set(json.loads(meta.get(_PARTS_KEY, b"[]")))


# ── writing ──────────────────────────────────────────────────────────────────

def write_part(run_dir, table, shard, frame):
    """Write ``frame`` as the next part file of ``shard`` (atomically); returns its path."""
    table_dir = Path(run_dir) / table
    table_dir.mkdir(parents=True, exist_ok=True)
    # Names the compacted file already lists count as taken: a part that reused one of them
    # would be skipped by read_table as "already contained" (the folder is gone after compact).
    file = _table_file(run_dir, table)
    names = [p.name for p in table_dir.glob("part-*.parquet")]
    names += sorted(_consumed(file)) if file.exists() else []
    seqs = [int(m.group(2)) for n in names if (m := _PART_RE.search(n)) and int(m.group(1)) == shard]
    final = table_dir / f"part-{shard}-{max(seqs, default=-1) + 1}.parquet"
    tmp = final.with_suffix(".tmp")
    _uniform(frame).to_parquet(tmp, index=False)
    tmp.replace(final)
    return final


def new_run_dir(runs_root, name, now=None):
    """Create ``<runs_root>/<YYYY-MM-DD_HHMM>_<name>`` (``_2``, ``_3`` ... if the minute is taken)."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M")
    d = Path(runs_root) / f"{stamp}_{name}"
    n = 2
    while d.exists():
        d = Path(runs_root) / f"{stamp}_{name}_{n}"
        n += 1
    d.mkdir(parents=True)
    return d


def write_plan(run_dir, frame):
    """Write ``plan.parquet`` (atomically): one row per planned cell."""
    final = Path(run_dir) / "plan.parquet"
    tmp = final.with_suffix(".tmp")
    _uniform(frame).to_parquet(tmp, index=False)
    tmp.replace(final)


# ── reading ──────────────────────────────────────────────────────────────────

def _load(run_dir, table, columns=None):
    """Compacted file plus the parts it does not contain yet, concatenated (not resolved)."""
    frames, file = [], _table_file(run_dir, table)
    skip = set()
    if file.exists():
        skip = _consumed(file)
        frames.append(pd.read_parquet(file, columns=columns))
    for p in _parts(run_dir, table):
        if p.name not in skip:
            frames.append(pd.read_parquet(p, columns=columns))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _resolve(df, table):
    """A cell written twice (``resume --retry-errors``) keeps its newest rows."""
    if df.empty:
        return df
    if table in ("cells", "channels") and "finished_at" in df.columns:
        keys = ["row"] + (["channel"] if table == "channels" else [])
        df = df.sort_values("finished_at", kind="stable").drop_duplicates(keys, keep="last").sort_values(keys)
    elif table in ("curves", "predictions"):
        # the unit of replacement is the cell: a rewritten cell replaces all its earlier rows.
        # Compacted rows carry no timestamp, parts are always newer than the file.
        stamp = df["written_at"] if "written_at" in df.columns else pd.Series("", index=df.index)
        stamp = stamp.fillna("")
        latest = stamp.groupby(df["cell_id"]).transform("max")
        df = df[stamp == latest]
    return df.drop(columns=[c for c in ("written_at",) if c in df.columns])


def read_table(run_dir, table, with_cells=False):
    """
    One table of a run as a DataFrame (empty if it has no rows): ``cells``, ``channels``,
    ``curves``, ``predictions`` or ``plan``. Works whatever state the run is in (parts only,
    file plus parts, file only); a cell written twice resolves to its newest rows.

    with_cells : add the axis and replicate columns of the cell (``curves``/``predictions`` carry
                 only ``cell_id``). A duplicate shares its original's ``cell_id``, so the
                 original's values are used.

    Raises UnsupportedStoreVersion if the run is newer than this package.
    """
    check_version(run_dir)
    if table == "plan":
        path = Path(run_dir) / "plan.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()
    if table not in TABLES:
        raise ValueError(f"unknown table {table!r}; one of {(*TABLES, 'plan')}")
    df = _resolve(_load(run_dir, table), table).reset_index(drop=True)
    if with_cells and not df.empty and table != "cells":
        df = _join_cells(run_dir, df)
    return df


def _join_cells(run_dir, df):
    cells = read_table(run_dir, "cells")
    if cells.empty:
        return df
    if "is_duplicate" in cells:
        cells = cells[~cells["is_duplicate"].astype(bool)]
    meta = read_json(run_dir, "meta.json")
    cols = [c for c in [*meta.get("axes", []), *meta.get("replicates", [])]
            if c in cells.columns and c not in df.columns]
    return df.merge(cells[["cell_id", *cols]].drop_duplicates("cell_id"), on="cell_id", how="left")


def table_version(run_dir, table):
    """Changes whenever the table's files change (cache key for readers)."""
    files = [_table_file(run_dir, table), *_parts(run_dir, table)]
    return tuple((f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in files if f.exists())


def has_table(run_dir, table):
    return bool(table_version(run_dir, table))


def tables_size(run_dir):
    """Bytes of all table files of a run (parts included)."""
    return sum(f.stat().st_size for t in TABLES for f in [_table_file(run_dir, t), *_parts(run_dir, t)]
               if f.exists())


# ── compacting ───────────────────────────────────────────────────────────────

def compact(run_dir, limit_bytes=COMPACT_LIMIT_BYTES):
    """
    Merge every table's parts (and an existing file) into one ``<table>.parquet``.

    The new file is written under a ``.tmp`` name, renamed, and only then are the parts deleted;
    its metadata lists the parts it contains, so a crash in between does not make ``read_table``
    count them twice. A table above ``limit_bytes`` keeps its parts.
    Returns {table: "compacted" | "kept parts"} for the tables that had parts.
    """
    check_version(run_dir)
    out = {}
    run_dir = Path(run_dir)
    for table in TABLES:
        parts = _parts(run_dir, table)
        if not parts:
            continue
        file = _table_file(run_dir, table)
        size = sum(p.stat().st_size for p in parts) + (file.stat().st_size if file.exists() else 0)
        if size > limit_bytes:
            out[table] = "kept parts"
            continue
        df = read_table(run_dir, table)
        names = sorted(p.name for p in parts)
        tmp = file.with_suffix(".tmp")
        tbl = pa.Table.from_pandas(_uniform(df), preserve_index=False)
        tbl = tbl.replace_schema_metadata({**(tbl.schema.metadata or {}),
                                           _PARTS_KEY: json.dumps(names).encode()})
        pq.write_table(tbl, tmp)
        tmp.replace(file)
        for p in parts:
            p.unlink()
        try:
            (run_dir / table).rmdir()
        except OSError:
            pass
        out[table] = "compacted"
    return out

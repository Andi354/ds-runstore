"""ds-runstore: the run folder format of ds-init projects and the only code that touches its files.

    from ds_runstore import read_table, list_runs, run_status
    cells = read_table(run_dir, "cells")

Contract: docs/format.md (in the package repository).
"""

from .description import read_description, validate_description, write_description
from .example import write_example_run
from .format import (
    COMPACT_LIMIT_BYTES,
    PRIMARY_KEYS,
    STALE_AFTER_S,
    STORE_VERSION,
    TABLES,
    UnsupportedStoreVersion,
    check_version,
    read_json,
)
from .runs import list_runs, run_status
from .tables import (
    compact,
    has_table,
    new_run_dir,
    read_table,
    table_version,
    tables_size,
    write_part,
    write_plan,
)

__all__ = [
    "COMPACT_LIMIT_BYTES", "PRIMARY_KEYS", "STALE_AFTER_S", "STORE_VERSION", "TABLES",
    "UnsupportedStoreVersion", "check_version", "compact", "has_table", "list_runs",
    "new_run_dir", "read_json", "read_table", "run_status", "table_version", "tables_size",
    "read_description", "validate_description", "write_description",
    "write_example_run", "write_part", "write_plan",
]

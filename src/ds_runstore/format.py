"""Constants of the run folder format (contract: docs/format.md) and the version check."""

import json
from pathlib import Path

# meta.json `store_version`. Raised only by changes a reader would otherwise misread (a file or
# column renamed, removed or moved); a new optional column or file does not need a new version.
STORE_VERSION = 1

TABLES = ("cells", "channels", "curves", "predictions")

# Primary key of every table. `plan` has one row per planned cell.
PRIMARY_KEYS = {
    "plan": ("row",),
    "cells": ("row",),
    "channels": ("row", "channel"),
    "curves": ("cell_id", "epoch", "metric"),
    "predictions": ("cell_id", "date", "channel"),
}

COMPACT_LIMIT_BYTES = 1 << 30     # a table above this keeps its part files
STALE_AFTER_S = 900               # no write for this long and no end: the run stands still


class UnsupportedStoreVersion(RuntimeError):
    """A run was written by a newer ds-runstore than the installed one."""


def read_json(run_dir, name):
    """``meta.json`` (or any JSON file of the run) as a dict, ``{}`` if the file is missing."""
    path = Path(run_dir) / name
    return json.loads(path.read_text()) if path.exists() else {}


def check_version(run_dir):
    """Raise UnsupportedStoreVersion if the run's ``store_version`` is newer than STORE_VERSION.
    Runs without the field are the predecessor format and are read as is."""
    version = read_json(run_dir, "meta.json").get("store_version")
    if version is not None and version > STORE_VERSION:
        raise UnsupportedStoreVersion(
            f"{Path(run_dir).name} has store_version {version}, this ds-runstore reads up to "
            f"{STORE_VERSION}: install a newer ds-runstore")

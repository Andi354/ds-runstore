"""The description of a run: why it was made and what it should show (``description.yaml``)."""

import os
from pathlib import Path

import yaml

FILE = "description.yaml"
SHORT_MAX = 100
REQUIRED = ("short", "purpose", "shows")
OPTIONAL = ("notes", "expectation", "compare_to")
FIELDS = REQUIRED + OPTIONAL                       # also the order in the file
_LISTS = ("shows", "notes", "compare_to")


def validate_description(fields):
    """Problems of a description as a list of short messages; empty if it is valid."""
    if not isinstance(fields, dict):
        return ["the file is not a mapping of fields"]
    problems = [f"missing field: {k}" for k in REQUIRED if fields.get(k) in (None, "", [])]
    for k in FIELDS:
        v = fields.get(k)
        if v is None:
            continue
        if k in _LISTS and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            problems.append(f"{k} must be a list of strings")
        elif k not in _LISTS and not isinstance(v, str):
            problems.append(f"{k} must be text")
    short = fields.get("short")
    if isinstance(short, str) and (len(short) > SHORT_MAX or "\n" in short.strip()):
        problems.append(f"short must be one line of at most {SHORT_MAX} characters")
    problems += [f"unknown field: {k}" for k in fields if k not in FIELDS]
    return problems


def read_description_file(path):
    """Description at ``path`` (any file): None if missing, else the known fields plus ``problems``.
    A broken file gives ``problems`` and no fields, never an exception."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        fields = yaml.safe_load(path.read_text())
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        return {"problems": [f"not readable YAML: {str(e).splitlines()[0]}"]}
    problems = validate_description(fields)
    known = {k: fields[k] for k in FIELDS if isinstance(fields, dict) and k in fields}
    return {**known, "problems": problems}


def read_description(run_dir):
    """``description.yaml`` of a run: None without one, else its fields and the list ``problems``."""
    return read_description_file(Path(run_dir) / FILE)


def write_description(run_dir, fields):
    """Write ``description.yaml`` atomically in the fixed field order (unknown fields are dropped).
    Returns the problems of ``fields``; a description with problems is written all the same."""
    run_dir = Path(run_dir)
    problems = validate_description(fields)
    data = {k: fields[k] for k in FIELDS if isinstance(fields, dict) and fields.get(k) is not None}
    tmp = run_dir / (FILE + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))
    os.replace(tmp, run_dir / FILE)
    return problems

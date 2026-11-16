"""The runs of a project: list them, and tell how far one has come."""

import time
from datetime import datetime
from pathlib import Path

from .description import FILE as DESCRIPTION
from .description import read_description
from .format import STALE_AFTER_S, STORE_VERSION, TABLES, UnsupportedStoreVersion, check_version, read_json
from .tables import _load, _parts, _resolve, has_table, read_table


def _last_change(run_dir):
    """Newest mtime among the run's tables, parts and logs (not checkpoints)."""
    run_dir = Path(run_dir)
    files = [f for f in run_dir.iterdir() if f.is_file()]
    for t in TABLES:
        files += _parts(run_dir, t)
    return max((f.stat().st_mtime for f in files), default=0.0)


def run_status(run_dir, stale_after=STALE_AFTER_S):
    """
    Progress and state of a run.

    state: ``finished`` (``ended_at`` in meta.json is set), ``running`` (no end, something was
    written within ``stale_after`` seconds) or ``stalled`` (no end, nothing written for longer: a
    crash, or one very long cell). ``planned`` is None for old runs without ``plan.parquet`` and
    ``meta.json`` ``plan.cells``; ``remaining`` counts planned cells without a result row.
    ``last_change`` is the time of the newest written file.
    """
    check_version(run_dir)
    run_dir = Path(run_dir)
    meta = read_json(run_dir, "meta.json")
    plan = read_table(run_dir, "plan")
    planned = len(plan) if not plan.empty else (meta.get("plan") or {}).get("cells")
    cells = _resolve(_load(run_dir, "cells", columns=["row", "status", "finished_at"]), "cells")
    ok = int((cells["status"] == "ok").sum()) if not cells.empty else 0
    err = int((cells["status"] == "error").sum()) if not cells.empty else 0
    last = _last_change(run_dir)
    if meta.get("ended_at"):
        state = "finished"
    else:
        state = "running" if time.time() - last <= stale_after else "stalled"
    return {"run": run_dir.name, "planned": planned, "done": ok + err, "ok": ok, "error": err,
            "remaining": None if planned is None else max(0, planned - ok - err),
            "state": state, "last_change": datetime.fromtimestamp(last).isoformat(timespec="seconds")}


def list_runs(runs_root, stale_after=STALE_AFTER_S):
    """
    Every run folder under ``runs_root`` that has a ``meta.json`` (newest first): its essentials
    plus ``run_status``. A run from a newer ds-runstore is listed with ``state: "unsupported"`` and
    ``error`` instead of raising, so one such run does not hide the others.
    """
    out = []
    root = Path(runs_root)
    for d in sorted(root.iterdir(), reverse=True) if root.exists() else []:
        if not (d / "meta.json").exists():
            continue
        m = read_json(d, "meta.json")
        entry = {"run": d.name, "name": m.get("name") or d.name, "issue": m.get("issue"),
                 "started_at": m.get("started_at"), "ended_at": m.get("ended_at"),
                 "epoch": m.get("epoch"), "axes": m.get("axes") or [],
                 "replicates": m.get("replicates") or [],
                 "primary_metric": m.get("primary_metric"),
                 "store_version": m.get("store_version"),     # None = predecessor format
                 "migrated": bool(m.get("migrated")), "short": None}
        desc = read_description(d)
        if desc:
            entry["short"] = desc.get("short")
        try:
            status = run_status(d, stale_after)
        except UnsupportedStoreVersion as e:
            out.append({**entry, "has": {"description": desc is not None}, "planned": None,
                        "done": None, "ok": None, "error": None, "remaining": None,
                        "state": "unsupported", "last_change": None, "message": str(e),
                        "supported_store_version": STORE_VERSION})
            continue
        has = {t: has_table(d, t) for t in ("channels", "curves", "predictions")}
        out.append({**entry, "has": {**has, "description": (d / DESCRIPTION).exists()},
                    **{k: status[k] for k in ("planned", "done", "ok", "error", "remaining",
                                              "state", "last_change")}})
    return out

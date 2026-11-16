"""A small example run, for tests of the readers (projects, tools) and for trying things out."""

import json
from pathlib import Path

import pandas as pd

from .description import write_description
from .format import STORE_VERSION
from .tables import compact, write_part, write_plan

AXES = ["model", "pred_len"]
REPLICATES = ["seed"]
NOW = "2026-01-01T10:00:00"
EXAMPLE_DESCRIPTION = {
    "short": "Model a against model b at two horizons",
    "purpose": "Check whether model a keeps its lead at the longer horizon.\n\nSecond paragraph.",
    "shows": ["MAE per model and horizon", "spread over the two seeds"],
    "notes": ["one cell diverged on purpose"],
    "expectation": "a is better at both horizons",
    "compare_to": [],
}


def write_example_run(run_dir, *, finished=True, compacted=True):
    """
    Write a small valid run into ``run_dir`` (created) and return it.

    Contents: 2 models x 2 horizons x 2 seeds = 8 planned cells, of which one failed
    (``status: error``) and one is a duplicate; 2 channels per cell; loss curves and predictions
    for the computed cells of model ``a``, and a valid ``description.yaml``.
    ``finished=False`` leaves out ``ended_at``; ``compacted=False`` leaves the tables as part
    files (a run that is going, or one before compacting).
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    plan, cells, channels, curves, preds = [], [], [], [], []
    row = 0
    for seed in (1, 2):
        for pred_len in (30, 90):
            for model in ("a", "b"):
                dup = None if not (model == "b" and seed == 2 and pred_len == 30) else 1   # copies row 1
                cid = f"{model}{pred_len}s{seed}" if dup is None else "b30s1"
                ident = {"row": row, "cell_id": cid, "model": model, "pred_len": pred_len, "seed": seed}
                plan.append({**{k: ident[k] for k in ("row", "cell_id")}, "duplicate_of": dup,
                             **{k: ident[k] for k in (*AXES, *REPLICATES)}})
                failed = (model == "b" and seed == 1 and pred_len == 90)
                base = 0.1 * pred_len / 30 + (0.05 if model == "b" else 0.0) + 0.01 * (1 if dup else seed)
                cells.append({**ident, "is_duplicate": dup is not None, "duplicate_of": dup,
                              "status": "error" if failed else "ok",
                              "error": "RuntimeError: diverged" if failed else None,
                              "duration_s": 1.5, "finished_at": NOW, "shard": 0,
                              "test_mae": None if failed else base,
                              "test_mse": None if failed else base * base})
                if not failed:
                    for ch, f in (("c1", 0.9), ("c2", 1.1)):
                        channels.append({**ident, "is_duplicate": dup is not None, "duplicate_of": dup,
                                         "channel": ch, "test_mae": base * f, "finished_at": NOW})
                    if model == "a":
                        curves += [{"cell_id": cid, "epoch": e, "metric": m, "value": 1.0 / (e + 1)}
                                   for e in range(3) for m in ("train_loss", "val_loss")]
                        preds += [{"cell_id": cid, "date": f"2025-12-{d:02d}", "channel": ch,
                                   "y_pred": 1.0 + d, "y_true": 1.1 + d} for d in range(1, 4)
                                  for ch in ("c1", "c2")]
                row += 1
    meta = {"name": "example", "store_version": STORE_VERSION, "issue": "TIM-0", "started_at": NOW,
            "ended_at": NOW if finished else None, "epoch": "initial", "axes": AXES,
            "replicates": REPLICATES, "primary_metric": "test_mae",
            "plan": {"cells": len(plan), "excluded": 0, "duplicates": 1}}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    (run_dir / "config.yaml").write_text(
        "sweep: {model: [a, b], pred_len: [30, 90]}\nreplicates: {seed: [1, 2]}\n")
    write_description(run_dir, EXAMPLE_DESCRIPTION)
    write_plan(run_dir, pd.DataFrame(plan))
    # two shards write their own parts; the cells of shard 1 are the second seed
    for table, rows in (("cells", cells), ("channels", channels), ("curves", curves), ("predictions", preds)):
        frame = pd.DataFrame(rows)
        if table in ("cells", "channels"):
            first = frame[frame["seed"] == 1]
            write_part(run_dir, table, 0, first)
            write_part(run_dir, table, 1, frame.drop(first.index))
        else:
            stamp = "2026-01-01T10:00:00"
            write_part(run_dir, table, 0, frame.assign(written_at=stamp))
    if compacted:
        compact(run_dir)
    return run_dir

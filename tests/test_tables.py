import time

import pandas as pd
import pytest

from ds_runstore import (
    PRIMARY_KEYS,
    STORE_VERSION,
    UnsupportedStoreVersion,
    compact,
    list_runs,
    read_table,
    run_status,
    write_example_run,
    write_part,
)


def test_example_run_in_both_states(tmp_path):
    parts = write_example_run(tmp_path / "parts", compacted=False)
    done = write_example_run(tmp_path / "done")
    assert (parts / "cells").is_dir() and not (parts / "cells.parquet").exists()
    assert (done / "cells.parquet").exists() and not (done / "cells").exists()
    for table in ("cells", "channels", "curves", "predictions", "plan"):
        pd.testing.assert_frame_equal(read_table(parts, table), read_table(done, table))
    cells = read_table(done, "cells")
    assert len(cells) == 8 and cells["status"].value_counts().to_dict() == {"ok": 7, "error": 1}
    assert cells["is_duplicate"].sum() == 1


def test_primary_keys_are_unique_after_reading(tmp_path):
    run = write_example_run(tmp_path / "r")
    for table, keys in PRIMARY_KEYS.items():
        df = read_table(run, table)
        assert not df.empty and not df.duplicated(list(keys)).any(), table


def test_compact_is_idempotent_and_keeps_parts_of_a_large_table(tmp_path):
    run = write_example_run(tmp_path / "r", compacted=False)
    assert compact(run, limit_bytes=1)["cells"] == "kept parts"
    assert (run / "cells").exists() and len(read_table(run, "cells")) == 8
    assert compact(run)["cells"] == "compacted"
    assert compact(run) == {}                                    # nothing left to do
    assert sorted(p.name for p in run.glob("*.parquet")) == [
        "cells.parquet", "channels.parquet", "curves.parquet", "plan.parquet", "predictions.parquet"]


def test_crash_between_rename_and_delete_does_not_double_count(tmp_path):
    run = write_example_run(tmp_path / "r", compacted=False)
    saved = {p: p.read_bytes() for p in (run / "cells").glob("part-*.parquet")}
    compact(run)
    for p, data in saved.items():                                 # the parts were not deleted yet
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(data)
    assert read_table(run, "cells")["row"].tolist() == list(range(8))


def test_file_plus_new_parts_newest_row_wins(tmp_path):
    run = write_example_run(tmp_path / "r")
    time.sleep(1.1)                                               # finished_at has second resolution
    old = read_table(run, "cells").set_index("row").loc[3]       # the failed cell, retried
    retry = pd.DataFrame([{**old.to_dict(), "row": 3, "status": "ok", "error": None, "test_mae": 9.0,
                           "finished_at": "2026-01-02T10:00:00"}])
    write_part(run, "cells", 0, retry)
    cells = read_table(run, "cells").set_index("row")
    assert len(cells) == 8 and cells.loc[3, "status"] == "ok" and cells.loc[3, "test_mae"] == 9.0
    # curves and predictions are replaced per cell_id
    curves = read_table(run, "curves")
    cid = curves["cell_id"].iloc[0]
    rewritten = {"cell_id": cid, "epoch": 0, "metric": "val_loss", "value": 7.0,
                 "written_at": "2026-01-03T00:00:00"}
    write_part(run, "curves", 0, pd.DataFrame([rewritten]))
    new = read_table(run, "curves")
    assert new[new["cell_id"] == cid]["value"].tolist() == [7.0]
    assert len(new[new["cell_id"] != cid]) == len(curves) - 6


def test_a_part_written_after_compacting_is_not_mistaken_for_a_consumed_one(tmp_path):
    run = write_example_run(tmp_path / "r")                       # parts part-0-0 and part-1-0 were consumed
    before = read_table(run, "cells")
    new = before.iloc[[0]].assign(row=99, cell_id="new", finished_at="2026-02-01T00:00:00")
    names = [write_part(run, "cells", shard, new.assign(row=99 + shard)).name for shard in (0, 1, 2)]
    assert names == ["part-0-1.parquet", "part-1-1.parquet", "part-2-0.parquet"]
    assert {99, 100, 101} <= set(read_table(run, "cells")["row"])
    compact(run)
    assert {99, 100, 101} <= set(read_table(run, "cells")["row"]) and len(read_table(run, "cells")) == 11


def test_with_cells_adds_axes_and_replicates(tmp_path):
    run = write_example_run(tmp_path / "r")
    preds = read_table(run, "predictions", with_cells=True)
    assert {"model", "pred_len", "seed"} <= set(preds.columns) and set(preds["model"]) == {"a"}
    assert "model" not in read_table(run, "predictions").columns


def test_status_and_state(tmp_path):
    done = write_example_run(tmp_path / "done")
    st = run_status(done)
    assert [st[k] for k in ("planned", "done", "ok", "error", "remaining", "state")] == [
        8, 8, 7, 1, 0, "finished"]
    going = write_example_run(tmp_path / "going", finished=False, compacted=False)
    assert run_status(going)["state"] == "running"
    assert run_status(going, stale_after=-1)["state"] == "stalled"


def test_old_runs_without_plan_or_version(tmp_path):
    run = write_example_run(tmp_path / "r", compacted=False)
    (run / "plan.parquet").unlink()
    import json
    meta = json.loads((run / "meta.json").read_text())
    meta.pop("store_version")
    meta["plan"] = {}
    (run / "meta.json").write_text(json.dumps(meta))
    st = run_status(run)
    assert st["planned"] is None and st["remaining"] is None and st["done"] == 8
    assert read_table(run, "plan").empty and len(read_table(run, "cells")) == 8


def test_newer_store_version_is_an_error_not_wrong_numbers(tmp_path):
    import json
    run = write_example_run(tmp_path / "r")
    meta = json.loads((run / "meta.json").read_text())
    meta["store_version"] = STORE_VERSION + 1
    (run / "meta.json").write_text(json.dumps(meta))
    for call in (lambda: read_table(run, "cells"), lambda: run_status(run), lambda: compact(run)):
        with pytest.raises(UnsupportedStoreVersion, match="install a newer ds-runstore"):
            call()
    (listed,) = list_runs(tmp_path)                               # listing does not raise
    assert listed["state"] == "unsupported" and "newer ds-runstore" in listed["message"]
    # and one such run does not hide the others
    write_example_run(tmp_path / "2026-02-02_0000_ok")
    assert sorted(r["state"] for r in list_runs(tmp_path)) == ["finished", "unsupported"]


def test_list_runs(tmp_path):
    assert list_runs(tmp_path / "missing") == []
    write_example_run(tmp_path / "2026-01-01_1000_example")
    write_example_run(tmp_path / "2026-01-02_1000_example", finished=False, compacted=False)
    (tmp_path / "no_meta").mkdir()
    runs = list_runs(tmp_path)
    assert [r["run"] for r in runs] == ["2026-01-02_1000_example", "2026-01-01_1000_example"]
    assert runs[1]["state"] == "finished" and runs[1]["axes"] == ["model", "pred_len"]
    assert runs[1]["has"] == {"channels": True, "curves": True, "predictions": True, "description": True}
    assert runs[1]["store_version"] == STORE_VERSION and runs[1]["migrated"] is False


def test_unknown_table(tmp_path):
    with pytest.raises(ValueError, match="unknown table"):
        read_table(write_example_run(tmp_path / "r"), "nope")


def test_new_run_dir_never_reuses_a_folder(tmp_path):
    from datetime import datetime

    from ds_runstore import new_run_dir
    now = datetime(2026, 10, 6, 14, 30)
    a, b = new_run_dir(tmp_path, "TIM-70_x", now), new_run_dir(tmp_path, "TIM-70_x", now)
    assert (a.name, b.name) == ("2026-10-06_1430_TIM-70_x", "2026-10-06_1430_TIM-70_x_2")


def test_example_run_has_a_valid_description(tmp_path):
    from ds_runstore import read_description
    desc = read_description(write_example_run(tmp_path / "r"))
    assert desc["problems"] == [] and desc["short"] and desc["shows"]
    assert list(desc)[:3] == ["short", "purpose", "shows"]


def test_description_missing_and_broken(tmp_path):
    from ds_runstore import read_description, validate_description, write_description
    run = write_example_run(tmp_path / "r")
    (run / "description.yaml").unlink()
    assert read_description(run) is None
    (run / "description.yaml").write_text("short: [unclosed\n")
    assert "not readable" in read_description(run)["problems"][0]    # no exception
    bad = {"short": "x" * 101, "purpose": 3, "shows": "a", "extra": 1}
    problems = validate_description(bad)
    assert len(problems) == 4
    assert "missing field: shows" in validate_description({"short": "a", "purpose": "b"})
    assert write_description(run, bad) == problems                    # written all the same
    assert "extra" not in read_description(run) and not (run / "description.yaml.tmp").exists()


def test_list_runs_shows_short_and_description_flag(tmp_path):
    from ds_runstore import write_description
    write_example_run(tmp_path / "runs" / "a")
    plain = write_example_run(tmp_path / "runs" / "b")
    (plain / "description.yaml").unlink()
    got = {r["run"]: r for r in list_runs(tmp_path / "runs")}
    assert got["a"]["short"] == "Model a against model b at two horizons" and got["a"]["has"]["description"]
    assert got["b"]["short"] is None and not got["b"]["has"]["description"]
    meta = tmp_path / "runs" / "a" / "meta.json"
    assert "short" not in meta.read_text()
    write_description(plain, {"short": "s", "purpose": "p", "shows": ["x"]})
    assert {r["run"]: r for r in list_runs(tmp_path / "runs")}["b"]["short"] == "s"

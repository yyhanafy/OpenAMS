#!/usr/bin/env python3
"""
Generic parallel ngspice validation of an already-selected witness CSV.

This script performs NO candidate selection.

The validation plan supplies input_csv. Every eligible row in that CSV is
simulated.

Pipeline:
  1. load validation plan;
  2. read plan input_csv;
  3. optionally apply the plan's explicit status filter;
  4. assign a stable simulation_row_id;
  5. deterministically shard all rows across N workers;
  6. create one ngspice validation plan per worker;
  7. run openams.validation.ngspice_witness in parallel;
  8. merge worker validation CSVs;
  9. join validation results back to the original witness rows;
 10. write an MLP-oriented dataset.

Selection belongs upstream, e.g.:
    hierarchical witnesses
        -> structured/farthest-point selector
        -> selected witness CSV
        -> THIS SCRIPT
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run ngspice validation in parallel for every row in the "
            "validation plan input_csv."
        )
    )
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def resolve(root: Path, value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p


def run_worker(
    worker_id: int,
    root: Path,
    plan_path: Path,
    output_csv: Path,
    log_path: Path,
) -> dict[str, Any]:

    cmd = [
        sys.executable,
        "-m",
        "openams.validation.ngspice_witness",
        "--plan",
        str(plan_path),
        "--root",
        str(root),
        "--output-csv",
        str(output_csv),
    ]

    env = os.environ.copy()

    src = str(root / "src")
    env["PYTHONPATH"] = (
        src
        + (
            ":" + env["PYTHONPATH"]
            if env.get("PYTHONPATH")
            else ""
        )
    )

    # Prevent one worker from internally consuming all CPU cores.
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["NUMEXPR_NUM_THREADS"] = "1"
    env["VECLIB_MAXIMUM_THREADS"] = "1"
    env["BLIS_NUM_THREADS"] = "1"

    t0 = time.perf_counter()

    with log_path.open("w", encoding="utf-8") as log:
        cp = subprocess.run(
            cmd,
            cwd=str(root),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    return {
        "worker_id": worker_id,
        "returncode": int(cp.returncode),
        "elapsed_s": float(time.perf_counter() - t0),
        "plan": str(plan_path),
        "output_csv": str(output_csv),
        "log": str(log_path),
        "command": " ".join(cmd),
    }


def main() -> int:
    a = parse_args()

    root = a.root.resolve()
    plan_path = resolve(root, a.plan)
    out = resolve(root, a.output_dir)

    if not plan_path.is_file():
        raise SystemExit(f"missing plan: {plan_path}")

    if a.workers <= 0:
        raise SystemExit("--workers must be > 0")

    plan = yaml.safe_load(
        plan_path.read_text(encoding="utf-8")
    )

    if not isinstance(plan, dict):
        raise SystemExit("validation plan must be a YAML mapping")

    if "input_csv" not in plan:
        raise SystemExit("validation plan is missing input_csv")

    source_csv = resolve(root, plan["input_csv"])

    if not source_csv.is_file():
        raise SystemExit(
            f"missing plan input_csv: {source_csv}"
        )

    if out.exists():
        if not a.overwrite:
            raise SystemExit(
                f"output exists: {out}; use --overwrite"
            )
        shutil.rmtree(out)

    out.mkdir(parents=True)

    # --------------------------------------------------------------
    # Read every input witness.
    # --------------------------------------------------------------

    df = pd.read_csv(source_csv)

    if df.empty:
        raise SystemExit(
            f"input witness CSV is empty: {source_csv}"
        )

    # Optional explicit status filtering from the validation plan.
    #
    # If the configured status column does not exist, all rows are used.
    # This permits already-selected hierarchical witness CSVs to be used
    # directly.
    status_col = plan.get("status_column")
    status_val = plan.get("status_value")

    if (
        status_col
        and status_val is not None
        and status_col in df.columns
    ):
        before = len(df)
        df = df[
            df[status_col].astype(str)
            == str(status_val)
        ].copy()

        print(
            f"status filter: "
            f"{status_col} == {status_val} "
            f"({before} -> {len(df)})"
        )

    if df.empty:
        raise SystemExit(
            "no witness rows remain after status filtering"
        )

    # Stable one-to-one identifier.
    #
    # Do not assume point_index is unique: hierarchical synthesis may
    # produce many witnesses for the same independent point.
    if "simulation_row_id" in df.columns:
        df = df.drop(columns=["simulation_row_id"])

    df.insert(
        0,
        "simulation_row_id",
        np.arange(len(df), dtype=int),
    )

    # Validation currently expects point_index/witness_rank.
    # Preserve user data exactly, but require these traceability fields.
    required = ["point_index", "witness_rank"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        raise SystemExit(
            "input witness CSV lacks required validation columns: "
            + ", ".join(missing)
        )

    input_copy = out / "input_witnesses.csv"
    df.to_csv(input_copy, index=False)

    print("===== OPENAMS PARALLEL NGSPICE VALIDATION =====")
    print(f"source witness CSV:      {source_csv}")
    print(f"input witness rows:      {len(df)}")
    print(f"parallel workers:        {a.workers}")
    print(f"output:                  {out}")
    print()

    # --------------------------------------------------------------
    # Deterministic round-robin sharding.
    # --------------------------------------------------------------

    nworkers = min(a.workers, len(df))

    shards = [
        df.iloc[i::nworkers].copy()
        for i in range(nworkers)
    ]

    shard_dir = out / "shards"
    plan_dir = out / "plans"
    worker_dir = out / "workers"
    log_dir = out / "logs"

    for d in (
        shard_dir,
        plan_dir,
        worker_dir,
        log_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    jobs = []
    worker_outputs: list[Path] = []

    for wid, sdf in enumerate(shards):
        if sdf.empty:
            continue

        shard_csv = (
            shard_dir
            / f"witnesses_worker_{wid:02d}.csv"
        )

        sdf.to_csv(shard_csv, index=False)

        worker_plan = dict(plan)

        worker_plan["input_csv"] = str(shard_csv)

        # Every row in this shard must be simulated.
        worker_plan["top_n"] = len(sdf)

        # Selection/ranking belongs upstream.  This runner executes every
        # supplied row exactly once, so the inner validator must not require
        # legacy ranking fields such as max_abs_residual/rms_residual.
        worker_plan["rank_by"] = []

        # Do not permit the inner validator's configured ranking to reorder
        # different witnesses in a way that affects inclusion. Since top_n
        # equals shard size, every row is still evaluated.
        worker_plan_path = (
            plan_dir
            / f"ngspice_worker_{wid:02d}.yaml"
        )

        worker_plan_path.write_text(
            yaml.safe_dump(
                worker_plan,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        worker_output = (
            worker_dir
            / f"validation_worker_{wid:02d}.csv"
        )

        worker_outputs.append(worker_output)

        jobs.append(
            (
                wid,
                root,
                worker_plan_path,
                worker_output,
                log_dir / f"worker_{wid:02d}.log",
            )
        )

    print("worker shard sizes:")
    for wid, sdf in enumerate(shards):
        if not sdf.empty:
            print(
                f"  worker {wid:02d}: "
                f"{len(sdf)} witnesses"
            )

    print()
    print("starting workers...", flush=True)

    # --------------------------------------------------------------
    # Parallel validation.
    # --------------------------------------------------------------

    results = []

    with cf.ThreadPoolExecutor(
        max_workers=len(jobs)
    ) as pool:

        futures = {
            pool.submit(run_worker, *job): job[0]
            for job in jobs
        }

        for future in cf.as_completed(futures):
            result = future.result()
            results.append(result)

            state = (
                "PASS"
                if result["returncode"] == 0
                else "FAIL"
            )

            print(
                f"[worker {result['worker_id']:02d}] "
                f"{state} "
                f"time={result['elapsed_s']:.1f}s "
                f"log={result['log']}",
                flush=True,
            )

    manifest = (
        pd.DataFrame(results)
        .sort_values("worker_id")
    )

    manifest.to_csv(
        out / "worker_manifest.csv",
        index=False,
    )

    failed = [
        r for r in results
        if r["returncode"] != 0
    ]

    if failed:
        print()
        print(
            f"ERROR: {len(failed)} worker(s) failed; "
            "merge skipped."
        )

        for r in failed:
            print(
                f"  worker {r['worker_id']:02d}: "
                f"{r['log']}"
            )

        return 1

    # --------------------------------------------------------------
    # Merge worker validator outputs.
    # --------------------------------------------------------------

    frames = []

    for p in worker_outputs:
        if not p.is_file():
            raise RuntimeError(
                f"missing worker validation output: {p}"
            )

        frames.append(pd.read_csv(p))

    merged = pd.concat(
        frames,
        ignore_index=True,
    )

    # --------------------------------------------------------------
    # Recover simulation_row_id.
    #
    # The inner validator may or may not preserve arbitrary source fields.
    # The safest stable key currently shared by the generated witness table
    # and validator result is (point_index, witness_rank).
    #
    # Validate uniqueness before using it.
    # --------------------------------------------------------------

    key = ["point_index", "witness_rank"]

    input_key_dups = df.duplicated(key).sum()

    if input_key_dups:
        raise RuntimeError(
            f"input contains {input_key_dups} duplicate "
            "(point_index, witness_rank) keys; "
            "cannot safely merge validation results"
        )

    if merged.duplicated(key).any():
        raise RuntimeError(
            "ngspice validation output contains duplicate "
            "(point_index, witness_rank) keys"
        )

    id_map = df[
        key + ["simulation_row_id"]
    ].copy()

    for c in key:
        id_map[c] = pd.to_numeric(
            id_map[c],
            errors="coerce",
        )

        merged[c] = pd.to_numeric(
            merged[c],
            errors="coerce",
        )

    merged = merged.merge(
        id_map,
        on=key,
        how="left",
        validate="one_to_one",
    )

    if merged["simulation_row_id"].isna().any():
        raise RuntimeError(
            "some validation rows could not be mapped "
            "back to source witnesses"
        )

    merged["simulation_row_id"] = (
        merged["simulation_row_id"].astype(int)
    )

    merged = merged.sort_values(
        "simulation_row_id"
    ).reset_index(drop=True)

    validation_csv = (
        out / "ngspice_validation.csv"
    )

    merged.to_csv(
        validation_csv,
        index=False,
    )

    # --------------------------------------------------------------
    # Build training-oriented dataset.
    # --------------------------------------------------------------

    validation_payload = merged.drop(
        columns=["selection_rank"],
        errors="ignore",
    )

    dataset = df.merge(
        validation_payload,
        on=[
            "simulation_row_id",
            "point_index",
            "witness_rank",
        ],
        how="left",
        suffixes=("", "_ng"),
        validate="one_to_one",
    )

    dataset = dataset.sort_values(
        "simulation_row_id"
    ).reset_index(drop=True)

    dataset_csv = out / "mlp_dataset.csv"

    dataset.to_csv(
        dataset_csv,
        index=False,
    )

    # --------------------------------------------------------------
    # Summary.
    # --------------------------------------------------------------

    dc_pass = (
        int(
            (
                merged["dc_validation_status"]
                == "PASS"
            ).sum()
        )
        if "dc_validation_status" in merged.columns
        else None
    )

    total_pass = (
        int(
            (
                merged["validation_status"]
                == "PASS"
            ).sum()
        )
        if "validation_status" in merged.columns
        else None
    )

    print()
    print("===== FINAL =====")
    print(f"input witnesses:          {len(df)}")
    print(f"merged validation rows:   {len(merged)}")
    print(
        f"DC PASS:                  "
        f"{dc_pass if dc_pass is not None else 'N/A'}"
    )
    print(
        f"total PASS:               "
        f"{total_pass if total_pass is not None else 'N/A'}"
    )
    print(f"validation CSV:           {validation_csv}")
    print(f"MLP dataset:              {dataset_csv}")

    run_manifest = {
        "artifact":
            "openams.parallel_ngspice_validation",
        "source_plan": str(plan_path),
        "source_witness_csv": str(source_csv),
        "input_witness_count": int(len(df)),
        "workers": int(nworkers),
        "selection_performed": False,
        "input_copy": str(input_copy),
        "validation_csv": str(validation_csv),
        "mlp_dataset_csv": str(dataset_csv),
        "dc_pass_count": dc_pass,
        "validation_pass_count": total_pass,
    }

    (
        out / "run_manifest.json"
    ).write_text(
        json.dumps(
            run_manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

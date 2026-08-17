#!/usr/bin/env python3
"""
Generic parallel ngspice validation for an already-selected candidate CSV.

This runner performs NO candidate selection.

Canonical pipeline
------------------
selected_candidates.csv
        |
        v
generic schema preparation
  - optional status filter
  - declarative witness aliases
  - required-column preflight
  - stable simulation_row_id
  - validator-local point_index
        |
        v
deterministic sharding
        |
        v
openams.validation.ngspice_witness  (parallel)
        |
        v
merge by validator-local point_index
        |
        +--> ngspice_validation.csv
        +--> validated_candidates.csv
        +--> run_manifest.json

Topology-specific information stays in the validation YAML:
  * template/netlist
  * parameter mappings
  * operating-point checks
  * AC/DC analyses
  * optional witness aliases

Optional validation-plan metadata
---------------------------------
witness_aliases:
  vx_v: n1_v
  vy_v: n2_v

The mapping is:
    TARGET_COLUMN: SOURCE_COLUMN

Aliases are created only when TARGET_COLUMN is absent.

This script contains no topology names, transistor names, node names,
fixed device count, or metric-extraction equations.
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
            "Generic parallel ngspice validation of every row in an "
            "already-selected candidate CSV."
        )
    )
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument(
        "--candidates",
        type=Path,
        default=None,
        help=(
            "Selected candidate CSV. Overrides plan input_csv. "
            "If omitted, plan input_csv is used."
        ),
    )
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--no-status-filter",
        action="store_true",
        help="Ignore plan status_column/status_value and simulate all rows.",
    )
    return p.parse_args()


def resolve(root: Path, value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p).resolve()


def walk_witness_columns(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        wc = obj.get("witness_column")
        if isinstance(wc, str):
            out.add(wc)
        for v in obj.values():
            walk_witness_columns(v, out)
    elif isinstance(obj, list):
        for v in obj:
            walk_witness_columns(v, out)


def prepare_candidates(
    df: pd.DataFrame,
    plan: dict[str, Any],
    *,
    apply_status_filter: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Normalize an arbitrary selected-candidate table for ngspice_witness.

    The original source identity is preserved in source_* columns.
    The validator gets a unique synthetic point_index equal to simulation_row_id.
    """
    if df.empty:
        raise SystemExit("selected candidate CSV is empty")

    df = df.copy()
    prep: dict[str, Any] = {
        "input_rows": int(len(df)),
        "status_filter_applied": False,
        "aliases_created": {},
    }

    # Optional explicit status filtering from validation plan.
    if apply_status_filter:
        status_col = plan.get("status_column")
        status_val = plan.get("status_value")
        if (
            status_col
            and status_val is not None
            and status_col in df.columns
        ):
            before = len(df)
            df = df[
                df[status_col].astype(str) == str(status_val)
            ].copy()
            prep["status_filter_applied"] = True
            prep["status_column"] = status_col
            prep["status_value"] = status_val
            prep["status_rows_before"] = int(before)
            prep["status_rows_after"] = int(len(df))

    if df.empty:
        raise SystemExit("no candidate rows remain after status filtering")

    # Declarative schema aliases, e.g. legacy validator name <- canonical name.
    aliases = plan.get("witness_aliases", {}) or {}
    if not isinstance(aliases, dict):
        raise SystemExit("plan witness_aliases must be a YAML mapping")

    for target, source in aliases.items():
        target = str(target)
        source = str(source)
        if target in df.columns:
            continue
        if source not in df.columns:
            raise SystemExit(
                f"cannot create witness alias {target!r}: "
                f"source column {source!r} is missing"
            )
        df[target] = df[source]
        prep["aliases_created"][target] = source

    # Preflight every witness_column referenced anywhere in the plan.
    needed: set[str] = set()
    walk_witness_columns(plan, needed)
    missing = sorted(c for c in needed if c not in df.columns)
    prep["required_witness_columns"] = sorted(needed)
    prep["missing_witness_columns"] = missing

    if missing:
        raise SystemExit(
            "candidate CSV is incompatible with validation plan; "
            "missing witness columns: " + ", ".join(missing)
        )

    # Preserve original identities, if present.
    if "point_index" in df.columns:
        name = "source_point_index"
        if name not in df.columns:
            df[name] = df["point_index"]

    if "witness_rank" in df.columns:
        name = "source_witness_rank"
        if name not in df.columns:
            df[name] = df["witness_rank"]

    # Stable one-to-one simulation identity.
    if "simulation_row_id" in df.columns:
        df = df.drop(columns=["simulation_row_id"])

    df.insert(
        0,
        "simulation_row_id",
        np.arange(len(df), dtype=int),
    )

    # The current inner validator expects point_index and witness_rank.
    # Use a validator-local unique point_index so merge safety does not depend
    # on topology-specific synthesis keys.
    df["point_index"] = df["simulation_row_id"].astype(int)

    if "witness_rank" not in df.columns:
        df["witness_rank"] = 0

    # Internal eligibility marker for the inner validator.  The current
    # ngspice_witness implementation always applies a status filter and
    # defaults to generation_status == WITNESS when none is declared.
    # Use a private runner-owned column so every already-selected row is
    # simulated exactly once without depending on topology/source schema.
    df["_openams_validate_status"] = "WITNESS"

    # De-fragment after schema preparation.
    df = df.copy()

    prep["prepared_rows"] = int(len(df))
    prep["synthetic_point_index"] = True
    prep["point_index_unique"] = bool(df["point_index"].is_unique)

    if not df["point_index"].is_unique:
        raise RuntimeError("internal error: synthetic point_index is not unique")

    return df, prep


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
        src + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    )

    # One external simulation worker should not expand into a nested BLAS pool.
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        env[key] = "1"

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
        "worker_id": int(worker_id),
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
        raise SystemExit(f"missing validation plan: {plan_path}")
    if a.workers <= 0:
        raise SystemExit("--workers must be > 0")

    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise SystemExit("validation plan must be a YAML mapping")

    if a.candidates is not None:
        source_csv = resolve(root, a.candidates)
    else:
        if "input_csv" not in plan:
            raise SystemExit(
                "supply --candidates or define input_csv in validation plan"
            )
        source_csv = resolve(root, plan["input_csv"])

    if not source_csv.is_file():
        raise SystemExit(f"missing selected candidate CSV: {source_csv}")

    if out.exists():
        if not a.overwrite:
            raise SystemExit(f"output exists: {out}; use --overwrite")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    raw = pd.read_csv(source_csv)
    df, prep = prepare_candidates(
        raw,
        plan,
        apply_status_filter=not a.no_status_filter,
    )

    prepared_csv = out / "prepared_candidates.csv"
    df.to_csv(prepared_csv, index=False)

    print("===== OPENAMS GENERIC PARALLEL NGSPICE VALIDATION =====")
    print(f"validation plan:         {plan_path}")
    print(f"selected candidate CSV:  {source_csv}")
    print(f"input candidate rows:    {len(raw)}")
    print(f"prepared rows:           {len(df)}")
    print(f"parallel workers:        {a.workers}")
    print(f"output:                  {out}")

    if prep["aliases_created"]:
        print("witness aliases:")
        for target, source in prep["aliases_created"].items():
            print(f"  {target} <- {source}")

    if prep["status_filter_applied"]:
        print(
            "status filter:           "
            f"{prep['status_column']} == {prep['status_value']} "
            f"({prep['status_rows_before']} -> "
            f"{prep['status_rows_after']})"
        )

    print(
        f"required witness columns: {len(prep['required_witness_columns'])}"
    )
    print()

    nworkers = min(a.workers, len(df))
    shards = [df.iloc[i::nworkers].copy() for i in range(nworkers)]

    shard_dir = out / "shards"
    plan_dir = out / "plans"
    worker_dir = out / "workers"
    log_dir = out / "logs"
    for d in (shard_dir, plan_dir, worker_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)

    jobs = []
    worker_outputs: list[Path] = []

    for wid, sdf in enumerate(shards):
        if sdf.empty:
            continue

        shard_csv = shard_dir / f"candidates_worker_{wid:02d}.csv"
        sdf.to_csv(shard_csv, index=False)

        worker_plan = dict(plan)
        worker_plan["input_csv"] = str(shard_csv)
        worker_plan["top_n"] = len(sdf)

        # Selection/ranking and any status filtering have already happened
        # upstream.  Every prepared row in this shard must be simulated.
        worker_plan["rank_by"] = []

        # The current inner validator always applies a status filter and
        # defaults to generation_status == WITNESS if these keys are absent.
        # Point it explicitly at the private runner-owned marker so every
        # prepared candidate in this shard is simulated.
        worker_plan["status_column"] = "_openams_validate_status"
        worker_plan["status_value"] = "WITNESS"

        # Alias preparation has already happened; keep metadata harmlessly in
        # the worker plan for provenance.
        worker_plan_path = plan_dir / f"ngspice_worker_{wid:02d}.yaml"
        worker_plan_path.write_text(
            yaml.safe_dump(worker_plan, sort_keys=False),
            encoding="utf-8",
        )

        worker_output = worker_dir / f"validation_worker_{wid:02d}.csv"
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
            print(f"  worker {wid:02d}: {len(sdf)} candidates")

    print("\nstarting workers...", flush=True)

    results = []
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {
            pool.submit(run_worker, *job): job[0]
            for job in jobs
        }

        for future in cf.as_completed(futures):
            result = future.result()
            results.append(result)
            state = "PASS" if result["returncode"] == 0 else "FAIL"
            print(
                f"[worker {result['worker_id']:02d}] "
                f"{state} "
                f"time={result['elapsed_s']:.1f}s "
                f"log={result['log']}",
                flush=True,
            )

    manifest = pd.DataFrame(results).sort_values("worker_id")
    manifest.to_csv(out / "worker_manifest.csv", index=False)

    failed = [r for r in results if r["returncode"] != 0]
    if failed:
        print()
        print(
            f"ERROR: {len(failed)} worker(s) failed; merge skipped."
        )
        for r in failed:
            print(f"  worker {r['worker_id']:02d}: {r['log']}")
        return 1

    frames = []
    for p in worker_outputs:
        if not p.is_file():
            raise RuntimeError(f"missing worker output: {p}")
        frames.append(pd.read_csv(p))

    merged = pd.concat(frames, ignore_index=True)

    if "point_index" not in merged.columns:
        raise RuntimeError(
            "inner ngspice validator did not preserve point_index"
        )

    merged["point_index"] = pd.to_numeric(
        merged["point_index"], errors="coerce"
    )

    if merged["point_index"].isna().any():
        raise RuntimeError(
            "ngspice output contains invalid point_index values"
        )

    if merged["point_index"].duplicated().any():
        raise RuntimeError(
            "ngspice output contains duplicate validator-local point_index"
        )

    # Recover stable simulation_row_id from the validator-local point_index.
    merged["simulation_row_id"] = merged["point_index"].astype(int)

    expected_ids = set(df["simulation_row_id"].astype(int))
    actual_ids = set(merged["simulation_row_id"].astype(int))
    if expected_ids != actual_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise RuntimeError(
            "validation/source identity mismatch: "
            f"missing={missing[:10]} extra={extra[:10]}"
        )

    merged = merged.sort_values("simulation_row_id").reset_index(drop=True)

    validation_csv = out / "ngspice_validation.csv"
    merged.to_csv(validation_csv, index=False)

    # Join simulation results back to all original selected-candidate columns.
    payload = merged.drop(
        columns=[
            c for c in ("point_index", "witness_rank")
            if c in merged.columns
        ],
        errors="ignore",
    )

    validated = df.merge(
        payload,
        on="simulation_row_id",
        how="left",
        suffixes=("", "_ng"),
        validate="one_to_one",
    ).sort_values("simulation_row_id").reset_index(drop=True)

    validated_csv = out / "validated_candidates.csv"
    validated.to_csv(validated_csv, index=False)

    dc_pass = (
        int((merged["dc_validation_status"] == "PASS").sum())
        if "dc_validation_status" in merged.columns else None
    )
    total_pass = (
        int((merged["validation_status"] == "PASS").sum())
        if "validation_status" in merged.columns else None
    )

    print("\n===== FINAL =====")
    print(f"selected candidates:      {len(df)}")
    print(f"validation rows:          {len(merged)}")
    print(
        f"DC PASS:                  "
        f"{dc_pass if dc_pass is not None else 'N/A'}"
    )
    print(
        f"total PASS:               "
        f"{total_pass if total_pass is not None else 'N/A'}"
    )
    print(f"validation CSV:           {validation_csv}")
    print(f"validated candidates:     {validated_csv}")

    run_manifest = {
        "artifact": "openams.generic_parallel_ngspice_validation",
        "source_plan": str(plan_path),
        "source_candidate_csv": str(source_csv),
        "input_candidate_count": int(len(raw)),
        "prepared_candidate_count": int(len(df)),
        "workers": int(nworkers),
        "selection_performed": False,
        "schema_preparation": prep,
        "prepared_candidates_csv": str(prepared_csv),
        "validation_csv": str(validation_csv),
        "validated_candidates_csv": str(validated_csv),
        "dc_pass_count": dc_pass,
        "validation_pass_count": total_pass,
    }

    (out / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

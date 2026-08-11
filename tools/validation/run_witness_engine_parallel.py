#!/usr/bin/env python3
"""
run_witness_engine_parallel.py

Topology-generic parallel wrapper for OpenAMS witness_engine.py.

This script does not contain topology-specific circuit logic.

It:
  1. loads the supplied witness-plan YAML;
  2. resolves the plan's coverage_csv;
  3. splits coverage rows deterministically across N workers;
  4. writes N temporary coverage CSV shards;
  5. writes N temporary plan YAMLs, changing ONLY:
       coverage_csv
       output_csv
  6. launches witness_engine.py independently for every shard;
  7. merges worker witness CSVs by (point_index, witness_rank).

The topology, device equations, constraints, MLP checkpoints, staged search,
residual ranking, saturation rules, aliases, and witness count remain defined
by the original plan and witness_engine.py.

Default parallelism: 12 workers.

Example:
    python tools/validation/run_witness_engine_parallel.py \
      --plan examples/two_stage_opamp/.../witness_plan.yaml \
      --workers 12 \
      --witnesses-per-point 5 \
      --output-csv examples/two_stage_opamp/generated/assignment_synthesis/two_stage_all_2025_mlp_witnesses_full.csv \
      --overwrite
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


def resolve(root: Path, value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p


def parse_args() -> argparse.Namespace:
    root = Path.cwd()
    p = argparse.ArgumentParser(description=__doc__)

    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--root", type=Path, default=root)

    p.add_argument(
        "--engine",
        type=Path,
        default=root / "tools/validation/witness_engine.py",
    )

    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--witnesses-per-point", type=int)

    p.add_argument(
        "--output-csv",
        type=Path,
        help=(
            "Final merged output. If omitted, uses output_csv from the "
            "original plan."
        ),
    )

    p.add_argument(
        "--work-dir",
        type=Path,
        help=(
            "Temporary shard/worker directory. Defaults beside the final "
            "output under a '.parallel_work' directory."
        ),
    )

    p.add_argument("--overwrite", action="store_true")

    return p.parse_args()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        fields = list(r.fieldnames or [])
        rows = list(r)

    if not fields:
        raise ValueError(f"CSV has no header: {path}")
    if "point_index" not in fields:
        raise ValueError(f"coverage CSV lacks point_index: {path}")

    return fields, rows


def write_csv(
    path: Path,
    fields: list[str],
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def status_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        s = str(row.get("status", "")).strip() or "<blank>"
        counts[s] = counts.get(s, 0) + 1
    return counts


def run_worker(
    worker_id: int,
    python_exe: str,
    engine: str,
    plan: str,
    root: str,
    log_file: str,
    witnesses_per_point: int | None,
) -> dict[str, Any]:

    cmd = [
        python_exe,
        engine,
        "--plan", plan,
        "--root", root,
    ]

    if witnesses_per_point is not None:
        cmd += [
            "--witnesses-per-point",
            str(witnesses_per_point),
        ]

    # One OpenAMS generator process = one parallel worker.
    # Prevent BLAS/OpenMP internals from oversubscribing all cores.
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["NUMEXPR_NUM_THREADS"] = "1"
    env["VECLIB_MAXIMUM_THREADS"] = "1"

    t0 = time.perf_counter()

    with open(log_file, "w", encoding="utf-8") as log:
        cp = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    elapsed = time.perf_counter() - t0

    return {
        "worker_id": worker_id,
        "returncode": int(cp.returncode),
        "elapsed_s": float(elapsed),
        "plan": plan,
        "log": log_file,
        "command": " ".join(cmd),
    }


def merge_worker_csvs(
    worker_csvs: list[Path],
    final_output: Path,
) -> tuple[int, int, dict[str, int]]:
    fields: list[str] | None = None
    rows: list[dict[str, str]] = []

    for f in worker_csvs:
        if not f.is_file():
            raise RuntimeError(f"missing worker output: {f}")

        flds, part = read_csv(f)

        if fields is None:
            fields = flds
        elif flds != fields:
            raise RuntimeError(
                f"worker schema mismatch: {f}"
            )

        rows.extend(part)

    if fields is None:
        raise RuntimeError("no worker outputs found")

    def sort_key(row: dict[str, str]):
        try:
            point = int(float(row.get("point_index", "0")))
        except Exception:
            point = 0
        try:
            rank = int(float(row.get("witness_rank", "0") or 0))
        except Exception:
            rank = 0
        return point, rank

    rows.sort(key=sort_key)

    final_output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(final_output, fields, rows)

    point_ids = {
        int(float(row["point_index"]))
        for row in rows
    }

    generation_counts: dict[str, int] = {}
    for row in rows:
        s = str(row.get("generation_status", "")).strip() or "<blank>"
        generation_counts[s] = generation_counts.get(s, 0) + 1

    return len(rows), len(point_ids), generation_counts


def main() -> int:
    cfg = parse_args()

    root = cfg.root.resolve()
    plan_path = resolve(root, cfg.plan)
    engine_path = resolve(root, cfg.engine)

    if not plan_path.is_file():
        raise SystemExit(f"missing plan: {plan_path}")
    if not engine_path.is_file():
        raise SystemExit(f"missing witness engine: {engine_path}")
    if cfg.workers <= 0:
        raise SystemExit("--workers must be > 0")

    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

    if "coverage_csv" not in plan:
        raise SystemExit("plan is missing coverage_csv")
    if "output_csv" not in plan and cfg.output_csv is None:
        raise SystemExit(
            "plan is missing output_csv and --output-csv was not supplied"
        )

    coverage_path = resolve(root, plan["coverage_csv"])
    if not coverage_path.is_file():
        raise SystemExit(
            f"plan coverage_csv does not exist: {coverage_path}"
        )

    final_output = (
        resolve(root, cfg.output_csv)
        if cfg.output_csv is not None
        else resolve(root, plan["output_csv"])
    )

    if cfg.work_dir is not None:
        work_dir = resolve(root, cfg.work_dir)
    else:
        work_dir = (
            final_output.parent
            / (final_output.stem + ".parallel_work")
        )

    if cfg.overwrite:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        if final_output.exists():
            final_output.unlink()
    else:
        if work_dir.exists() or final_output.exists():
            raise SystemExit(
                "output/work directory already exists; use --overwrite "
                "or choose different paths"
            )

    fields, rows = read_csv(coverage_path)

    point_ids = [int(float(r["point_index"])) for r in rows]
    if len(set(point_ids)) != len(point_ids):
        raise SystemExit(
            "coverage CSV contains duplicate point_index values; "
            "refusing unsafe parallelization"
        )

    counts = status_counts(rows)

    work_dir.mkdir(parents=True, exist_ok=True)
    shards_dir = work_dir / "coverage_shards"
    plans_dir = work_dir / "plans"
    outputs_dir = work_dir / "worker_outputs"
    logs_dir = work_dir / "logs"

    for d in (shards_dir, plans_dir, outputs_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Deterministic round-robin sharding by coverage CSV order.
    shards: list[list[dict[str, str]]] = [
        [] for _ in range(cfg.workers)
    ]

    for i, row in enumerate(rows):
        shards[i % cfg.workers].append(row)

    jobs = []
    worker_csvs: list[Path] = []

    for worker_id, shard_rows in enumerate(shards):
        if not shard_rows:
            continue

        shard_csv = shards_dir / f"coverage_worker_{worker_id:02d}.csv"
        worker_csv = outputs_dir / f"witnesses_worker_{worker_id:02d}.csv"
        worker_plan = plans_dir / f"plan_worker_{worker_id:02d}.yaml"
        log_file = logs_dir / f"worker_{worker_id:02d}.log"

        write_csv(shard_csv, fields, shard_rows)

        # Clone the original topology plan.  Only replace the input coverage
        # and output artifact for this worker.  Everything circuit-specific
        # remains untouched.
        worker_plan_obj = dict(plan)
        worker_plan_obj["coverage_csv"] = str(shard_csv)
        worker_plan_obj["output_csv"] = str(worker_csv)

        worker_plan.write_text(
            yaml.safe_dump(
                worker_plan_obj,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        worker_csvs.append(worker_csv)

        jobs.append(
            (
                worker_id,
                sys.executable,
                str(engine_path),
                str(worker_plan),
                str(root),
                str(log_file),
                cfg.witnesses_per_point,
            )
        )

    print("===== OPENAMS GENERIC PARALLEL WITNESS ENGINE =====")
    print(f"plan:                    {plan_path}")
    print(f"engine:                  {engine_path}")
    print(f"coverage CSV:            {coverage_path}")
    print(f"coverage rows:           {len(rows)}")
    print(f"unique point_index:      {len(set(point_ids))}")
    print(f"coverage status counts:  {counts}")
    print(f"workers:                 {len(jobs)}")
    print(
        "witnesses per point:     "
        + (
            str(cfg.witnesses_per_point)
            if cfg.witnesses_per_point is not None
            else f"plan default ({plan.get('witnesses_per_point', 5)})"
        )
    )
    print(f"final output:            {final_output}")
    print(f"work dir:                {work_dir}")
    print()
    print("worker shard sizes:")
    for worker_id, shard_rows in enumerate(shards):
        if shard_rows:
            print(
                f"  worker {worker_id:02d}: "
                f"{len(shard_rows)} points"
            )
    print()
    print("starting workers...", flush=True)

    results: list[dict[str, Any]] = []

    # Threads only supervise subprocesses; actual work is in separate Python
    # processes, one per worker.
    with cf.ThreadPoolExecutor(
        max_workers=cfg.workers
    ) as pool:

        future_map = {
            pool.submit(run_worker, *job): job[0]
            for job in jobs
        }

        for future in cf.as_completed(future_map):
            worker_id = future_map[future]

            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "worker_id": worker_id,
                    "returncode": -999,
                    "elapsed_s": 0.0,
                    "plan": "",
                    "log": str(
                        logs_dir / f"worker_{worker_id:02d}.log"
                    ),
                    "command": "",
                    "exception": f"{type(exc).__name__}: {exc}",
                }

            results.append(result)

            status = (
                "PASS"
                if result["returncode"] == 0
                else "FAIL"
            )

            print(
                f"[worker {worker_id:02d}] {status} "
                f"time={result['elapsed_s']:.1f}s "
                f"log={result['log']}",
                flush=True,
            )

    results.sort(key=lambda r: r["worker_id"])

    manifest_fields: list[str] = []
    for result in results:
        for key in result:
            if key not in manifest_fields:
                manifest_fields.append(key)

    write_csv(
        work_dir / "worker_manifest.csv",
        manifest_fields,
        results,
    )

    failures = [
        r for r in results
        if r["returncode"] != 0
    ]

    if failures:
        print()
        print(
            f"ERROR: {len(failures)} worker(s) failed. "
            "Final CSV was not merged."
        )
        for r in failures:
            print(
                f"  worker {r['worker_id']:02d}: "
                f"{r['log']}"
            )
        return 1

    merged_rows, unique_points, generation_counts = (
        merge_worker_csvs(
            worker_csvs,
            final_output,
        )
    )

    expected_points = len(rows)

    run_manifest = {
        "artifact": "openams.generic_parallel_witness_generation",
        "source_plan": str(plan_path),
        "witness_engine": str(engine_path),
        "coverage_csv": str(coverage_path),
        "coverage_rows": len(rows),
        "coverage_status_counts": counts,
        "workers": cfg.workers,
        "witnesses_per_point": (
            cfg.witnesses_per_point
            if cfg.witnesses_per_point is not None
            else plan.get("witnesses_per_point", 5)
        ),
        "final_output_csv": str(final_output),
        "merged_output_rows": merged_rows,
        "merged_unique_points": unique_points,
        "expected_unique_points": expected_points,
        "generation_status_counts": generation_counts,
        "worker_failures": 0,
        "blas_threads_per_worker": 1,
        "parallelization": (
            "coverage CSV sharded across independent witness_engine processes"
        ),
    }

    (work_dir / "run_manifest.json").write_text(
        json.dumps(
            run_manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("===== FINAL =====")
    print(f"merged output rows:       {merged_rows}")
    print(f"unique processed points: {unique_points}")
    print(f"expected points:         {expected_points}")
    print(f"generation status:       {generation_counts}")
    print(f"output:                  {final_output}")
    print(
        f"manifest:                "
        f"{work_dir / 'run_manifest.json'}"
    )

    if unique_points != expected_points:
        print(
            "WARNING: not every input point appears in the merged output. "
            "Inspect worker logs before using the dataset."
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

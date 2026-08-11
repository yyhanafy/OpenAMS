#!/usr/bin/env python3
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

import numpy as np
import pandas as pd
import yaml


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generic parallel ngspice validation of a selected witness CSV."
    )
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--count", type=int, default=1500)
    p.add_argument(
        "--coverage-columns",
        nargs="+",
        required=True,
        help="Exact witness CSV columns used for space-filling selection.",
    )
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def resolve(root: Path, p: str | Path) -> Path:
    x = Path(p)
    return x if x.is_absolute() else root / x


def normalize(x: np.ndarray) -> np.ndarray:
    lo = np.nanmin(x, axis=0)
    hi = np.nanmax(x, axis=0)
    span = hi - lo
    span[span == 0] = 1.0
    return (x - lo) / span


def farthest_point_sample(z: np.ndarray, count: int) -> list[int]:
    n = len(z)
    if count >= n:
        return list(range(n))

    d = z.shape[1]
    seeds: list[int] = []

    # Extremes per dimension.
    for j in range(d):
        seeds.append(int(np.argmin(z[:, j])))
        seeds.append(int(np.argmax(z[:, j])))

    # Center.
    center = np.full(d, 0.5)
    seeds.append(int(np.argmin(np.sum((z - center) ** 2, axis=1))))

    # Corners.
    for mask in range(1 << d):
        corner = np.array([(mask >> j) & 1 for j in range(d)], dtype=float)
        seeds.append(int(np.argmin(np.sum((z - corner) ** 2, axis=1))))

    selected: list[int] = []
    seen: set[int] = set()
    for i in seeds:
        if i not in seen:
            seen.add(i)
            selected.append(i)
        if len(selected) >= count:
            return selected[:count]

    nearest = np.full(n, np.inf)
    for i in selected:
        nearest = np.minimum(nearest, np.sum((z - z[i]) ** 2, axis=1))
    nearest[selected] = -np.inf

    while len(selected) < count:
        i = int(np.argmax(nearest))
        selected.append(i)
        nearest = np.minimum(nearest, np.sum((z - z[i]) ** 2, axis=1))
        nearest[i] = -np.inf

    return selected


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
    env["PYTHONPATH"] = src + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["NUMEXPR_NUM_THREADS"] = "1"

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
        "returncode": cp.returncode,
        "elapsed_s": time.perf_counter() - t0,
        "plan": str(plan_path),
        "output_csv": str(output_csv),
        "log": str(log_path),
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

    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    source_csv = resolve(root, plan["input_csv"])
    if not source_csv.is_file():
        raise SystemExit(f"missing plan input_csv: {source_csv}")

    if out.exists():
        if not a.overwrite:
            raise SystemExit(f"output exists: {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    df = pd.read_csv(source_csv)
    status_col = plan.get("status_column", "generation_status")
    status_val = plan.get("status_value", "WITNESS")
    if status_col in df.columns:
        df = df[df[status_col].astype(str) == str(status_val)].copy()

    missing = [c for c in a.coverage_columns if c not in df.columns]
    if missing:
        raise SystemExit(f"missing coverage columns: {missing}")

    # One best witness per point first, so the 1500 cases cover independent
    # design points rather than repeatedly sampling the same point_index.
    rank_by = plan.get("rank_by", ["max_abs_residual", "rms_residual"])
    sort_cols = ["point_index"] + [c for c in rank_by if c in df.columns]
    df = df.sort_values(sort_cols).drop_duplicates("point_index").reset_index(drop=True)

    x = df[a.coverage_columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    good = np.isfinite(x).all(axis=1)
    df = df.loc[good].reset_index(drop=True)
    x = x[good]

    if len(df) < a.count:
        raise SystemExit(f"only {len(df)} eligible unique design points; requested {a.count}")

    z = normalize(x)
    idx = farthest_point_sample(z, a.count)
    selected = df.iloc[idx].copy().reset_index(drop=True)

    # The input may itself be a previously selected witness CSV and already
    # contain this bookkeeping column. Recreate it deterministically.
    if "selection_rank_global" in selected.columns:
        selected = selected.drop(columns=["selection_rank_global"])

    selected.insert(
        0,
        "selection_rank_global",
        np.arange(1, len(selected) + 1),
    )
    selected_csv = out / "selected_witnesses_1500.csv"
    selected.to_csv(selected_csv, index=False)

    # Coverage report.
    print("===== OPENAMS GENERIC 1500 NGSPICE VALIDATION =====")
    print(f"source witness CSV:      {source_csv}")
    print(f"eligible unique points:  {len(df)}")
    print(f"selected points:         {len(selected)}")
    print(f"coverage dimensions:     {', '.join(a.coverage_columns)}")
    print(f"parallel workers:        {a.workers}")
    print(f"output:                  {out}")
    print()
    print("selected ranges:")
    for c in a.coverage_columns:
        print(f"  {c}: {selected[c].min():.12g} .. {selected[c].max():.12g}")
    print()

    # Round-robin shard selected rows.
    shards = [selected.iloc[i::a.workers].copy() for i in range(a.workers)]

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

        shard_csv = shard_dir / f"selected_worker_{wid:02d}.csv"
        sdf.to_csv(shard_csv, index=False)

        worker_plan = dict(plan)
        worker_plan["input_csv"] = str(shard_csv)
        worker_plan["top_n"] = len(sdf)
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
            print(f"  worker {wid:02d}: {len(sdf)} points")
    print()
    print("starting workers...", flush=True)

    results = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_worker, *job): job[0] for job in jobs}
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            state = "PASS" if r["returncode"] == 0 else "FAIL"
            print(
                f"[worker {r['worker_id']:02d}] {state} "
                f"time={r['elapsed_s']:.1f}s log={r['log']}",
                flush=True,
            )

    pd.DataFrame(results).sort_values("worker_id").to_csv(
        out / "worker_manifest.csv", index=False
    )

    failed = [r for r in results if r["returncode"] != 0]
    if failed:
        print(f"ERROR: {len(failed)} worker(s) failed; merge skipped.")
        return 1

    frames = [pd.read_csv(p) for p in worker_outputs]
    merged = pd.concat(frames, ignore_index=True)

    # Restore global selection rank.
    rank_map = selected[["point_index", "selection_rank_global"]].copy()
    merged["point_index"] = pd.to_numeric(merged["point_index"], errors="coerce").astype("Int64")
    rank_map["point_index"] = pd.to_numeric(rank_map["point_index"], errors="coerce").astype("Int64")
    merged = merged.merge(rank_map, on="point_index", how="left")
    merged = merged.sort_values(["selection_rank_global", "point_index"]).reset_index(drop=True)

    merged_csv = out / "ngspice_validation_1500.csv"
    merged.to_csv(merged_csv, index=False)

    # Training-oriented merged table.
    dataset = selected.merge(
        merged.drop(columns=["selection_rank"], errors="ignore"),
        on=["point_index", "witness_rank"],
        how="left",
        suffixes=("", "_ng"),
    )
    dataset_csv = out / "mlp_dataset_1500.csv"
    dataset.to_csv(dataset_csv, index=False)

    print()
    print("===== FINAL =====")
    print(f"selected:                {len(selected)}")
    print(f"merged validation rows:  {len(merged)}")
    print(f"DC PASS:                 {(merged['dc_validation_status'] == 'PASS').sum() if 'dc_validation_status' in merged else 'N/A'}")
    print(f"total PASS:              {(merged['validation_status'] == 'PASS').sum() if 'validation_status' in merged else 'N/A'}")
    print(f"validation CSV:          {merged_csv}")
    print(f"MLP dataset:             {dataset_csv}")

    manifest = {
        "source_plan": str(plan_path),
        "source_witness_csv": str(source_csv),
        "selected_count": len(selected),
        "workers": a.workers,
        "coverage_columns": a.coverage_columns,
        "validation_csv": str(merged_csv),
        "mlp_dataset_csv": str(dataset_csv),
    }
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

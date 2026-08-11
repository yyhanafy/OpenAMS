#!/usr/bin/env python3
"""
Coverage-oriented selection + multicore simulation orchestration for OpenAMS.

Current two-stage coverage space:
    coverage__w_m1_um
    coverage__w_m3_um__center
    coverage__w_m3_um__halfspan
    coverage__w_m6_um__center
    coverage__w_m6_um__halfspan

Default selected points: 1500

The expensive simulation phase runs independent point jobs concurrently.
Each selected point_index is passed to an existing one-point OpenAMS/ngspice
runner through --runner-template.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_COVERAGE_COLUMNS = [
    "coverage__w_m1_um",
    "coverage__w_m3_um__center",
    "coverage__w_m3_um__halfspan",
    "coverage__w_m6_um__center",
    "coverage__w_m6_um__halfspan",
]

PASS_VALUES = {"PASS", "PASSED", "VALID", "FEASIBLE", "TRUE", "1", "OK"}


def norm_name(name: str) -> str:
    return "".join(ch.lower() for ch in str(name) if ch.isalnum())


def find_status_column(df: pd.DataFrame) -> str | None:
    wanted = [
        "status",
        "result",
        "classification",
        "feasibility_status",
        "design_status",
        "pass_fail",
    ]
    by_norm = {norm_name(c): c for c in df.columns}
    for w in wanted:
        if norm_name(w) in by_norm:
            return by_norm[norm_name(w)]
    return None


def filter_eligible(df: pd.DataFrame, include_all: bool):
    if include_all:
        return df.copy(), None
    status_col = find_status_column(df)
    if status_col is None:
        return df.copy(), None
    s = df[status_col].astype(str).str.strip().str.upper()
    mask = s.isin(PASS_VALUES)
    if mask.any():
        return df.loc[mask].copy(), status_col
    return df.copy(), None


def normalize(x: np.ndarray):
    lo = np.min(x, axis=0)
    hi = np.max(x, axis=0)
    span = hi - lo
    span[span == 0.0] = 1.0
    return (x - lo) / span, lo, hi


def unique_ordered(values):
    seen = set()
    out = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def initial_seeds(z: np.ndarray):
    n, d = z.shape
    seeds = []

    # Per-dimension extrema.
    for j in range(d):
        seeds.append(int(np.argmin(z[:, j])))
        seeds.append(int(np.argmax(z[:, j])))

    # Point nearest the middle of the normalized space.
    center = np.full(d, 0.5)
    seeds.append(int(np.argmin(np.sum((z - center) ** 2, axis=1))))

    # Nearest realizable point to each hypercube corner.
    if d <= 6:
        for corner_id in range(1 << d):
            corner = np.array([(corner_id >> j) & 1 for j in range(d)], dtype=float)
            seeds.append(int(np.argmin(np.sum((z - corner) ** 2, axis=1))))

    return unique_ordered(seeds)


def farthest_point_sample(z: np.ndarray, count: int):
    n = len(z)
    if count >= n:
        return list(range(n)), [math.nan] * n

    selected = initial_seeds(z)[:count]
    nearest_d2 = np.full(n, np.inf)
    score = {idx: math.nan for idx in selected}

    for idx in selected:
        d2 = np.sum((z - z[idx]) ** 2, axis=1)
        nearest_d2 = np.minimum(nearest_d2, d2)

    nearest_d2[selected] = -np.inf

    while len(selected) < count:
        idx = int(np.argmax(nearest_d2))
        score[idx] = float(math.sqrt(max(0.0, nearest_d2[idx])))
        selected.append(idx)

        d2 = np.sum((z - z[idx]) ** 2, axis=1)
        nearest_d2 = np.minimum(nearest_d2, d2)
        nearest_d2[idx] = -np.inf

    return selected, [score[i] for i in selected]


def coverage_metrics(z: np.ndarray, chosen: list[int]):
    nearest = np.full(len(z), np.inf)
    for idx in chosen:
        d = np.sqrt(np.sum((z - z[idx]) ** 2, axis=1))
        nearest = np.minimum(nearest, d)
    return {
        "mean_nearest_selected_distance": float(np.mean(nearest)),
        "p50_nearest_selected_distance": float(np.percentile(nearest, 50)),
        "p90_nearest_selected_distance": float(np.percentile(nearest, 90)),
        "p95_nearest_selected_distance": float(np.percentile(nearest, 95)),
        "p99_nearest_selected_distance": float(np.percentile(nearest, 99)),
        "worst_nearest_selected_distance": float(np.max(nearest)),
    }


def format_template(template: str, point_index: int) -> str:
    return template.format(point_index=point_index)


def run_one_point(point_index: int, runner_template: str, runs_dir: str, cwd: str):
    runs = Path(runs_dir)
    stdout_path = runs / f"point_{point_index:06d}.stdout.txt"
    stderr_path = runs / f"point_{point_index:06d}.stderr.txt"
    command = format_template(runner_template, point_index)

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        rc = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exception = ""
    except Exception as exc:
        rc = -999
        stdout = ""
        stderr = ""
        exception = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - t0
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)

    return {
        "point_index": int(point_index),
        "returncode": rc,
        "status": "PASS" if rc == 0 else "FAIL",
        "elapsed_s": float(elapsed),
        "command": command,
        "stdout_file": str(stdout_path),
        "stderr_file": str(stderr_path),
        "exception": exception,
    }


def merge_json_results(selected: pd.DataFrame, template: str, output_dir: Path):
    records = []
    missing = 0
    selected_by_point = selected.set_index("point_index", drop=False)

    for point_index in selected["point_index"].astype(int):
        result_path = Path(format_template(template, point_index))
        if not result_path.exists():
            missing += 1
            continue

        try:
            result = json.loads(result_path.read_text())
        except Exception as exc:
            result = {
                "_result_parse_error": f"{type(exc).__name__}: {exc}",
            }

        base = selected_by_point.loc[point_index].to_dict()
        base.update(result)
        base["_result_file"] = str(result_path)
        records.append(base)

    if records:
        jsonl_path = output_dir / "verified_dataset.jsonl"
        with jsonl_path.open("w") as f:
            for rec in records:
                f.write(json.dumps(rec, default=str) + "\n")

        pd.json_normalize(records).to_csv(
            output_dir / "verified_dataset.csv", index=False
        )

    return len(records), missing


def parse_args():
    p = argparse.ArgumentParser(
        description="Select coverage points and run OpenAMS/ngspice jobs in parallel."
    )
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--count", type=int, default=1500)
    p.add_argument(
        "--coverage-columns",
        nargs="+",
        default=DEFAULT_COVERAGE_COLUMNS,
    )
    p.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 2),
        help="Parallel point simulations; default is CPU count minus 2.",
    )
    p.add_argument("--include-all", action="store_true")
    p.add_argument("--select-only", action="store_true")
    p.add_argument(
        "--runner-template",
        help="Per-point command. Use {point_index} or {point_index:06d}.",
    )
    p.add_argument(
        "--result-json-template",
        help="Optional per-point JSON result path for dataset merging.",
    )
    p.add_argument("--cwd", type=Path, default=Path.cwd())
    return p.parse_args()


def main():
    args = parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input does not exist: {args.input}")
    if args.count <= 0:
        raise SystemExit("--count must be > 0")
    if args.workers <= 0:
        raise SystemExit("--workers must be > 0")
    if not args.select_only and not args.runner_template:
        raise SystemExit("Provide --runner-template, or use --select-only")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = args.output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.input)
    if "point_index" not in df.columns:
        raise SystemExit("Input CSV must contain point_index")

    missing = [c for c in args.coverage_columns if c not in df.columns]
    if missing:
        raise SystemExit("Missing coverage columns: " + ", ".join(missing))

    eligible, status_col = filter_eligible(df, args.include_all)
    numeric = eligible[args.coverage_columns].apply(pd.to_numeric, errors="coerce")
    x_all = numeric.to_numpy(dtype=float)
    finite_mask = np.isfinite(x_all).all(axis=1)
    eligible = eligible.loc[finite_mask].copy()
    x = x_all[finite_mask]

    if len(eligible) == 0:
        raise SystemExit("No finite eligible coverage rows")

    z, lo, hi = normalize(x)
    count = min(args.count, len(eligible))
    chosen_local, spacing = farthest_point_sample(z, count)
    selected = eligible.iloc[chosen_local].copy()

    selected.insert(0, "selection_rank", np.arange(1, len(selected) + 1))
    selected.insert(1, "selection_spacing_score", spacing)

    for j, col in enumerate(args.coverage_columns):
        selected[f"_selection_norm__{col}"] = z[chosen_local, j]

    selected_path = args.output_dir / "selected_candidates.csv"
    selected.to_csv(selected_path, index=False)

    index_path = args.output_dir / "selected_point_indices.txt"
    with index_path.open("w") as f:
        for idx in selected["point_index"].astype(int):
            f.write(f"{idx}\n")

    metrics = coverage_metrics(z, chosen_local)
    summary = {
        "input": str(args.input),
        "input_rows": int(len(df)),
        "status_filter_column": status_col,
        "eligible_finite_rows": int(len(eligible)),
        "requested_count": int(args.count),
        "selected_count": int(len(selected)),
        "coverage_columns": list(args.coverage_columns),
        "dimension_min": {c: float(v) for c, v in zip(args.coverage_columns, lo)},
        "dimension_max": {c: float(v) for c, v in zip(args.coverage_columns, hi)},
        "coverage": metrics,
        "workers": int(args.workers),
    }
    (args.output_dir / "coverage_summary.json").write_text(json.dumps(summary, indent=2))

    print("===== OPENAMS MLP DATASET COVERAGE SELECTION =====")
    print(f"input:                    {args.input}")
    print(f"input rows:               {len(df)}")
    print(f"eligible finite rows:     {len(eligible)}")
    print(f"selected points:          {len(selected)}")
    print(f"workers:                  {args.workers}")
    print(f"selected CSV:             {selected_path}")
    print(f"point-index list:         {index_path}")
    print("coverage columns:")
    for c in args.coverage_columns:
        print(f"  {c}")
    print("coverage:")
    for k, v in metrics.items():
        print(f"  {k:<38} {v:.6f}")

    if args.select_only:
        print("selection-only mode: no simulations launched")
        return

    point_indices = selected["point_index"].astype(int).tolist()
    print("\n===== PARALLEL SIMULATION =====")
    print(f"jobs:                     {len(point_indices)}")
    print(f"parallel workers:         {args.workers}")
    print(f"runner template:          {args.runner_template}")

    results = []
    completed = passed = failed = 0
    total = len(point_indices)
    t_all = time.perf_counter()

    with cf.ProcessPoolExecutor(max_workers=args.workers) as pool:
        future_map = {
            pool.submit(
                run_one_point,
                idx,
                args.runner_template,
                str(runs_dir),
                str(args.cwd),
            ): idx
            for idx in point_indices
        }

        for future in cf.as_completed(future_map):
            idx = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "point_index": idx,
                    "returncode": -998,
                    "status": "FAIL",
                    "elapsed_s": math.nan,
                    "command": "",
                    "stdout_file": "",
                    "stderr_file": "",
                    "exception": f"{type(exc).__name__}: {exc}",
                }

            results.append(result)
            completed += 1
            if result["status"] == "PASS":
                passed += 1
            else:
                failed += 1

            print(
                f"[{completed:4d}/{total}] point={idx:6d} "
                f"{result['status']:<4} time={result['elapsed_s']:.3f}s "
                f"pass={passed} fail={failed}",
                flush=True,
            )

    elapsed_all = time.perf_counter() - t_all
    manifest = pd.DataFrame(results).sort_values("point_index")
    manifest_path = args.output_dir / "simulation_manifest.csv"
    manifest.to_csv(manifest_path, index=False)

    with (args.output_dir / "simulation_manifest.jsonl").open("w") as f:
        for rec in results:
            f.write(json.dumps(rec, default=str) + "\n")

    print("\n===== SIMULATION SUMMARY =====")
    print(f"total:                    {total}")
    print(f"pass:                     {passed}")
    print(f"fail:                     {failed}")
    print(f"wall time:                {elapsed_all:.3f}s")
    print(f"manifest:                 {manifest_path}")

    if args.result_json_template:
        merged, missing_results = merge_json_results(
            selected, args.result_json_template, args.output_dir
        )
        print("\n===== DATASET MERGE =====")
        print(f"JSON results merged:      {merged}")
        print(f"JSON results missing:     {missing_results}")
        if merged:
            print(f"verified CSV:             {args.output_dir / 'verified_dataset.csv'}")
            print(f"verified JSONL:           {args.output_dir / 'verified_dataset.jsonl'}")


if __name__ == "__main__":
    main()

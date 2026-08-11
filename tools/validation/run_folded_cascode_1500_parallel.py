#!/usr/bin/env python3
"""
Run 1,500 folded-cascode native witnesses through ngspice in parallel.

Selection:
  - PASS native correlated witnesses only
  - coverage dimensions: W1, W4, W6
  - normalized greedy farthest-point sampling

Execution:
  - selected witnesses are split across N workers (default 12)
  - each worker invokes the already-validated
    run_folded_cascode_native_witness_ngspice.py
  - each worker gets exactly its own JSONL shard and output directory
  - the existing PM-fixed AC extraction remains untouched

Outputs:
  <output>/
    selected_witnesses_1500.jsonl
    selected_witnesses_1500.csv
    shards/
    worker_00/ ... worker_11/
    validation_summary_merged.csv
    ngspice_ac_metrics_merged.csv
    dc_node_comparison_merged.csv
    dc_device_comparison_merged.csv
    mlp_dataset_1500.csv
    run_manifest.json
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    root = Path.cwd()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--witnesses",
        type=Path,
        default=root / (
            "examples/folded_cascode/generated/assignment_synthesis/"
            "folded_cascode_design_space_witnesses.jsonl"
        ),
    )
    p.add_argument(
        "--runner",
        type=Path,
        default=root / "tools/validation/run_folded_cascode_native_witness_ngspice.py",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=root / "validation/ngspice/folded_cascode_native_1500_parallel",
    )
    p.add_argument("--count", type=int, default=1500)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{lineno}: expected JSON object")
            if str(obj.get("status", "")).upper() == "PASS":
                out.append(obj)
    return out


def recursive_numeric(obj: Any, aliases: set[str]) -> float | None:
    """Find a finite numeric value whose normalized key matches an alias."""
    def norm(s: str) -> str:
        return "".join(ch.lower() for ch in str(s) if ch.isalnum())

    alias_norm = {norm(a) for a in aliases}

    if isinstance(obj, dict):
        # Prefer direct matches at the current level.
        for k, v in obj.items():
            if norm(k) in alias_norm:
                try:
                    x = float(v)
                    if math.isfinite(x):
                        return x
                except Exception:
                    pass
        # Then recurse.
        for v in obj.values():
            x = recursive_numeric(v, aliases)
            if x is not None:
                return x

    elif isinstance(obj, list):
        for v in obj:
            x = recursive_numeric(v, aliases)
            if x is not None:
                return x

    return None


def width_value(w: dict[str, Any], device: int) -> float:
    # Concrete transistor width in micrometers.
    # IMPORTANT: coverage widths come only from widths_um; never
    # recursively search the full witness because currents_a.M4/M6
    # can otherwise be mistaken for widths.
    key = f"M{device}"

    widths = w.get("widths_um")
    if isinstance(widths, dict) and key in widths:
        x = float(widths[key])
        if math.isfinite(x):
            return x

    groups = {
        1: "M1_M2", 2: "M1_M2", 3: "M3",
        4: "M4_M5", 5: "M4_M5",
        6: "M6_M7", 7: "M6_M7",
        8: "M8_M9", 9: "M8_M9",
        10: "M10_M11", 11: "M10_M11",
    }
    realizations = w.get("device_realizations", {})
    group = groups.get(device)
    if isinstance(realizations, dict) and group in realizations:
        rec = realizations[group]
        if isinstance(rec, dict) and "width_um" in rec:
            x = float(rec["width_um"])
            if math.isfinite(x):
                return x

    raise KeyError(
        f"Could not resolve concrete width_um for {key} "
        f"from witness point_index={w.get('point_index')}"
    )


def feature_matrix(witnesses: list[dict[str, Any]]) -> np.ndarray:
    rows = []
    for w in witnesses:
        rows.append([
            width_value(w, 1),
            width_value(w, 4),
            width_value(w, 6),
        ])
    return np.asarray(rows, dtype=float)


def normalize(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lo = np.min(x, axis=0)
    hi = np.max(x, axis=0)
    span = hi - lo
    span[span == 0.0] = 1.0
    return (x - lo) / span, lo, hi


def seed_indices(z: np.ndarray) -> list[int]:
    n, d = z.shape
    seeds = []

    for j in range(d):
        seeds += [int(np.argmin(z[:, j])), int(np.argmax(z[:, j]))]

    center = np.full(d, 0.5)
    seeds.append(int(np.argmin(np.sum((z - center) ** 2, axis=1))))

    for corner_id in range(1 << d):
        corner = np.array([(corner_id >> j) & 1 for j in range(d)], dtype=float)
        seeds.append(int(np.argmin(np.sum((z - corner) ** 2, axis=1))))

    seen = set()
    unique = []
    for idx in seeds:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)
    return unique


def farthest_point_sample(z: np.ndarray, count: int) -> tuple[list[int], list[float]]:
    n = len(z)
    if count >= n:
        return list(range(n)), [math.nan] * n

    selected = seed_indices(z)[:count]
    nearest_d2 = np.full(n, np.inf, dtype=float)
    scores = {idx: math.nan for idx in selected}

    for idx in selected:
        nearest_d2 = np.minimum(nearest_d2, np.sum((z - z[idx]) ** 2, axis=1))

    nearest_d2[selected] = -np.inf

    while len(selected) < count:
        idx = int(np.argmax(nearest_d2))
        scores[idx] = float(math.sqrt(max(0.0, nearest_d2[idx])))
        selected.append(idx)
        nearest_d2 = np.minimum(
            nearest_d2,
            np.sum((z - z[idx]) ** 2, axis=1),
        )
        nearest_d2[idx] = -np.inf

    return selected, [scores[i] for i in selected]


def coverage_metrics(z: np.ndarray, selected: list[int]) -> dict[str, float]:
    nearest = np.full(len(z), np.inf)
    for idx in selected:
        nearest = np.minimum(
            nearest,
            np.sqrt(np.sum((z - z[idx]) ** 2, axis=1)),
        )
    return {
        "mean_nearest_selected_distance": float(np.mean(nearest)),
        "p95_nearest_selected_distance": float(np.percentile(nearest, 95)),
        "worst_nearest_selected_distance": float(np.max(nearest)),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def run_worker(
    worker_id: int,
    python_exe: str,
    runner: str,
    shard: str,
    output: str,
    count: int,
    seed: int,
) -> dict[str, Any]:
    cmd = [
        python_exe,
        runner,
        "--witnesses", shard,
        "--count", str(count),
        "--seed", str(seed),
        "--output", output,
        "--overwrite",
    ]

    log_path = Path(output).parent / f"worker_{worker_id:02d}.launcher.log"
    t0 = time.perf_counter()

    cp = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    elapsed = time.perf_counter() - t0
    log_path.write_text(cp.stdout or "", encoding="utf-8")

    return {
        "worker": worker_id,
        "returncode": int(cp.returncode),
        "elapsed_s": float(elapsed),
        "count": int(count),
        "output": output,
        "log": str(log_path),
        "command": " ".join(cmd),
    }


def merge_csvs(worker_dirs: list[Path], filename: str, output: Path) -> pd.DataFrame:
    frames = []
    for d in worker_dirs:
        p = d / filename
        if p.is_file():
            df = pd.read_csv(p)
            df.insert(0, "worker_id", int(d.name.split("_")[-1]))
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    if "point_index" in merged.columns:
        merged = merged.sort_values(["point_index", "worker_id"]).reset_index(drop=True)
    merged.to_csv(output, index=False)
    return merged


def main() -> int:
    cfg = parse_args()

    witnesses_path = cfg.witnesses.resolve()
    runner_path = cfg.runner.resolve()
    output = cfg.output.resolve()

    if not witnesses_path.is_file():
        raise SystemExit(f"Missing witnesses: {witnesses_path}")
    if not runner_path.is_file():
        raise SystemExit(f"Missing runner: {runner_path}")
    if cfg.count <= 0:
        raise SystemExit("--count must be > 0")
    if cfg.workers <= 0:
        raise SystemExit("--workers must be > 0")

    if output.exists():
        if not cfg.overwrite:
            raise SystemExit(f"Output exists; use --overwrite: {output}")
        shutil.rmtree(output)

    output.mkdir(parents=True)
    shards_dir = output / "shards"
    shards_dir.mkdir()

    witnesses = read_jsonl(witnesses_path)
    if not witnesses:
        raise SystemExit("No PASS witnesses found")

    x = feature_matrix(witnesses)
    z, lo, hi = normalize(x)

    count = min(cfg.count, len(witnesses))
    selected_idx, spacing = farthest_point_sample(z, count)
    selected = [witnesses[i] for i in selected_idx]

    metrics = coverage_metrics(z, selected_idx)

    selected_jsonl = output / f"selected_witnesses_{count}.jsonl"
    write_jsonl(selected_jsonl, selected)

    selection_rows = []
    for rank, (idx, witness, score) in enumerate(
        zip(selected_idx, selected, spacing), 1
    ):
        selection_rows.append({
            "selection_rank": rank,
            "selection_spacing_score": score,
            "point_index": int(witness["point_index"]),
            "w_m1_um": float(x[idx, 0]),
            "w_m4_um": float(x[idx, 1]),
            "w_m6_um": float(x[idx, 2]),
            "norm_w_m1": float(z[idx, 0]),
            "norm_w_m4": float(z[idx, 1]),
            "norm_w_m6": float(z[idx, 2]),
        })

    selection_df = pd.DataFrame(selection_rows)
    selection_csv = output / f"selected_witnesses_{count}.csv"
    selection_df.to_csv(selection_csv, index=False)

    # Round-robin sharding keeps shard sizes balanced.
    shards: list[list[dict[str, Any]]] = [[] for _ in range(cfg.workers)]
    for i, witness in enumerate(selected):
        shards[i % cfg.workers].append(witness)

    worker_dirs = []
    jobs = []

    for worker_id, shard_rows in enumerate(shards):
        if not shard_rows:
            continue

        shard_path = shards_dir / f"worker_{worker_id:02d}.jsonl"
        write_jsonl(shard_path, shard_rows)

        worker_out = output / f"worker_{worker_id:02d}"
        worker_dirs.append(worker_out)

        jobs.append((
            worker_id,
            str(cfg.python),
            str(runner_path),
            str(shard_path),
            str(worker_out),
            len(shard_rows),
            cfg.seed + worker_id,
        ))

    print("===== OPENAMS FOLDED CASCODE 1500 PARALLEL =====")
    print(f"PASS native witnesses:     {len(witnesses)}")
    print(f"selected witnesses:        {count}")
    print("coverage dimensions:       W1, W4, W6 (from widths_um)")
    print(f"parallel workers:          {len(jobs)}")
    print(f"runner:                    {runner_path}")
    print(f"output:                    {output}")
    print()
    print("width ranges:")
    print(f"  W1: {lo[0]:.12g} .. {hi[0]:.12g} um")
    print(f"  W4: {lo[1]:.12g} .. {hi[1]:.12g} um")
    print(f"  W6: {lo[2]:.12g} .. {hi[2]:.12g} um")
    print()
    print("coverage after selection:")
    for k, v in metrics.items():
        print(f"  {k:<38} {v:.6f}")
    print()
    print("starting workers...")

    worker_results = []

    with cf.ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        future_map = {
            pool.submit(run_worker, *job): job[0]
            for job in jobs
        }

        for future in cf.as_completed(future_map):
            worker_id = future_map[future]
            result = future.result()
            worker_results.append(result)
            status = "PASS" if result["returncode"] == 0 else "FAIL"
            print(
                f"[worker {worker_id:02d}] {status} "
                f"points={result['count']} "
                f"time={result['elapsed_s']:.1f}s "
                f"log={result['log']}",
                flush=True,
            )

    worker_results = sorted(worker_results, key=lambda x: x["worker"])
    pd.DataFrame(worker_results).to_csv(
        output / "worker_manifest.csv",
        index=False,
    )

    failures = [r for r in worker_results if r["returncode"] != 0]
    if failures:
        print()
        print(f"WARNING: {len(failures)} worker(s) failed.")
        print("Inspect worker_XX.launcher.log before using the merged dataset.")

    print()
    print("merging outputs...")

    summary = merge_csvs(
        worker_dirs,
        "validation_summary.csv",
        output / "validation_summary_merged.csv",
    )
    ac = merge_csvs(
        worker_dirs,
        "ngspice_ac_metrics.csv",
        output / "ngspice_ac_metrics_merged.csv",
    )
    nodes = merge_csvs(
        worker_dirs,
        "dc_node_comparison.csv",
        output / "dc_node_comparison_merged.csv",
    )
    devices = merge_csvs(
        worker_dirs,
        "dc_device_comparison.csv",
        output / "dc_device_comparison_merged.csv",
    )

    # One convenient MLP-oriented table: selection coordinates + DC summary + AC metrics.
    dataset = selection_df.copy()

    if not summary.empty:
        summary_keep = summary.drop(
            columns=[c for c in ("worker_id", "w_m1_um") if c in summary.columns],
            errors="ignore",
        )
        # Keep one row per point_index.
        summary_keep = summary_keep.drop_duplicates("point_index")
        dataset = dataset.merge(
            summary_keep,
            on="point_index",
            how="left",
            suffixes=("", "_summary"),
        )

    if not ac.empty:
        ac_keep = ac.drop(columns=["worker_id"], errors="ignore")
        ac_keep = ac_keep.drop_duplicates("point_index")
        dataset = dataset.merge(
            ac_keep,
            on="point_index",
            how="left",
            suffixes=("", "_ac"),
        )

    dataset_path = output / "mlp_dataset_1500.csv"
    dataset.to_csv(dataset_path, index=False)

    manifest = {
        "artifact": "openams.folded_cascode.native_1500_parallel",
        "witnesses": str(witnesses_path),
        "runner": str(runner_path),
        "available_pass_witnesses": len(witnesses),
        "selected_witnesses": count,
        "selection_dimensions": ["w_m1_um", "w_m4_um", "w_m6_um"],
        "workers": cfg.workers,
        "coverage": metrics,
        "width_min_um": {"w_m1_um": lo[0], "w_m4_um": lo[1], "w_m6_um": lo[2]},
        "width_max_um": {"w_m1_um": hi[0], "w_m4_um": hi[1], "w_m6_um": hi[2]},
        "worker_failures": len(failures),
        "merged_summary_rows": int(len(summary)),
        "merged_ac_rows": int(len(ac)),
        "mlp_dataset_rows": int(len(dataset)),
        "pm_definition": "180 deg + absolute continuous unwrapped phase of Vout/(Vip-Vin) at first descending 0 dB crossing",
    }

    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=float) + "\n",
        encoding="utf-8",
    )

    print()
    print("===== FINAL =====")
    print(f"selected:                  {count}")
    print(f"workers failed:            {len(failures)}")
    print(f"merged validation rows:    {len(summary)}")
    print(f"merged AC rows:            {len(ac)}")
    print(f"MLP dataset rows:          {len(dataset)}")
    print(f"dataset:                   {dataset_path}")
    print(f"manifest:                  {output / 'run_manifest.json'}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

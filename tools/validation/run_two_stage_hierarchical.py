#!/usr/bin/env python3
"""
Prototype hierarchical DC witness search for the OpenAMS two-stage op-amp.

This intentionally leaves src/openams/synthesis/witness_engine.py unchanged.

Hierarchy:
    Component A = M1..M5  (first four stages of the existing witness plan)
    Component B = M6..M7  (output_m6_m7 stage)

The script:
  1. derives an A-only witness plan from the existing two-stage plan;
  2. runs the existing generic witness engine for A;
  3. converts every surviving A witness into an interface row for B;
  4. derives and runs a B-only witness plan;
  5. joins A+B results into complete hierarchical candidates.

The first goal is architectural validation, not component-MLP training yet.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml


DEFAULT_PLAN = Path(
    "examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml"
)
DEFAULT_ENGINE = Path("tools/validation/witness_engine.py")
DEFAULT_WORK = Path(
    "runtime/two_stage_hierarchical"
)


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a YAML mapping")
    return data


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    raise KeyError(
        f"none of {names!r} were present/nonempty; columns={sorted(row)}"
    )


def stage_by_id(plan: dict, stage_id: str) -> dict:
    for stage in plan.get("stages", []):
        if stage.get("id") == stage_id:
            return stage
    raise KeyError(f"stage {stage_id!r} not found in base plan")


def device_by_name(plan: dict, name: str) -> dict:
    for device in plan["final"]["devices"]:
        if device.get("name") == name:
            return device
    raise KeyError(f"final device {name!r} not found")


def build_component_a_plan(
    base: dict,
    coverage_csv: Path,
    output_csv: Path,
    witnesses_per_point: int,
) -> dict:
    a_stage_ids = [
        "m1_input",
        "m5_bias",
        "m3_load",
        "balanced_m2_m4",
    ]
    stages = [stage_by_id(base, sid) for sid in a_stage_ids]

    plan = {
        "schema_version": base.get("schema_version", 1),
        "name": "two_stage_component_A_m1_m5",
        "coverage_csv": str(coverage_csv),
        "output_csv": str(output_csv),
        "witnesses_per_point": int(witnesses_per_point),
        "sat_margin_v": base.get("sat_margin_v", 0.05),
        "mlp": base["mlp"],
        "constants": base["constants"],
        "point_bindings": base["point_bindings"],
        "derived_bindings": base.get("derived_bindings", {}),
        "stages": stages,
        "final": {
            "devices": [
                device_by_name(base, "M1"),
                device_by_name(base, "M2"),
                device_by_name(base, "M3"),
                device_by_name(base, "M4"),
                device_by_name(base, "M5"),
            ],
            "residuals": {
                k: base["final"]["residuals"][k]
                for k in (
                    "tail_kcl",
                    "x_kcl",
                    "y_kcl",
                    "mirror_balance",
                    "i5_target",
                )
            },
            "saturation_headroom": {
                k: base["final"]["saturation_headroom"][k]
                for k in ("M1", "M2", "M3", "M4", "M5")
            },
            "constraints": [
                "M1_domain & M2_domain & M3_domain & M4_domain & M5_domain",
                "((vx-vtail)-M1_vdsat)>=sat_margin_v",
                "((vy-vtail)-M2_vdsat)>=sat_margin_v",
                "((vdd-vx)-M3_vdsat)>=sat_margin_v",
                "((vdd-vy)-M4_vdsat)>=sat_margin_v",
                "((vtail-vss)-M5_vdsat)>=sat_margin_v",
            ],
        },
        "csv_aliases": {
            "w_m1_um": "w1",
            "i_m5_target_a": "i5_target",
            "i_half_target_a": "ib",
            "vbias_v": "vbias",
            "vtail_v": "vtail",
            "vx_v": "vx",
            "vy_v": "vy",
            "w_m3_um": "w3",
            "w_m5_um": "w5",
        },
    }
    return plan


def make_b_coverage(a_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    hidx = 0
    for row in a_rows:
        # The witness engine also emits summary rows for points with
        # zero witnesses.  Those rows have empty realization fields and
        # must not be passed to Component B.
        if not row.get("w_m1_um") or not row.get("witness_rank"):
            continue

        out.append(
            {
                # B gets a unique point index for every A interface witness.
                "point_index": hidx,
                "parent_point_index": pick(row, "point_index"),
                "parent_witness_rank": row.get("witness_rank", "0"),
                "w_m1_um": pick(row, "w_m1_um", "w1"),
                "i_m5_target_a": pick(
                    row, "i_m5_target_a", "i5_target", "i_m5_a"
                ),
                "vbias_v": pick(row, "vbias_v", "vbias"),
                "vtail_v": pick(row, "vtail_v", "vtail"),
                "vx_v": pick(row, "vx_v", "vx"),
                "vy_v": pick(row, "vy_v", "vy"),
                "w_m3_um": pick(row, "w_m3_um", "w3"),
                "w_m5_um": pick(row, "w_m5_um", "w5"),
            }
        )
        hidx += 1
    return out


def build_component_b_plan(
    base: dict,
    coverage_csv: Path,
    output_csv: Path,
    witnesses_per_point: int,
) -> dict:
    output_stage = stage_by_id(base, "output_m6_m7")

    # B receives the interface state from A instead of recomputing it.
    point_bindings = {
        "w1": {"column": "w_m1_um"},
        "i5_target": {"column": "i_m5_target_a"},
        "vbias": {"column": "vbias_v"},
        "vtail": {"column": "vtail_v"},
        "vx": {"column": "vx_v"},
        "vy": {"column": "vy_v"},
        "w3": {"column": "w_m3_um"},
        "w5": {"column": "w_m5_um"},
        "parent_point_index": {"column": "parent_point_index"},
        "parent_witness_rank": {"column": "parent_witness_rank"},
    }

    # Preserve the original M6 width limits.
    for key in ("w6_allowed_lo", "w6_allowed_hi"):
        if key in base.get("point_bindings", {}):
            point_bindings[key] = base["point_bindings"][key]

    plan = {
        "schema_version": base.get("schema_version", 1),
        "name": "two_stage_component_B_m6_m7",
        "coverage_csv": str(coverage_csv),
        "output_csv": str(output_csv),
        "witnesses_per_point": int(witnesses_per_point),
        "sat_margin_v": base.get("sat_margin_v", 0.05),
        "mlp": base["mlp"],
        "constants": base["constants"],
        "point_bindings": point_bindings,
        "derived_bindings": base.get("derived_bindings", {}),
        "stages": [output_stage],
        "final": {
            "devices": [
                device_by_name(base, "M6"),
                device_by_name(base, "M7"),
            ],
            "residuals": {
                "output_kcl": base["final"]["residuals"]["output_kcl"],
            },
            "saturation_headroom": {
                "M6": base["final"]["saturation_headroom"]["M6"],
                "M7": base["final"]["saturation_headroom"]["M7"],
            },
            "constraints": [
                "M6_domain & M7_domain",
                "((vdd-vout)-M6_vdsat)>=sat_margin_v",
                "((vout-vss)-M7_vdsat)>=sat_margin_v",
            ],
        },
        "csv_aliases": {
            "parent_point_index": "parent_point_index",
            "parent_witness_rank": "parent_witness_rank",
            "w_m1_um": "w1",
            "i_m5_target_a": "i5_target",
            "vbias_v": "vbias",
            "vtail_v": "vtail",
            "vx_v": "vx",
            "vy_v": "vy",
            "w_m3_um": "w3",
            "w_m5_um": "w5",
            "vout_v": "vout",
            "w_m6_um": "w6",
            "w_m7_um": "w7",
        },
    }
    return plan


def run_engine(
    root: Path,
    engine: Path,
    plan: Path,
    max_points: int | None,
    witnesses_per_point: int,
) -> None:
    cmd = [
        sys.executable,
        str(engine),
        "--plan",
        str(plan),
        "--root",
        str(root),
        "--witnesses-per-point",
        str(witnesses_per_point),
    ]
    if max_points is not None:
        cmd += ["--max-points", str(max_points)]
    print("\nRUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=root, check=True)


def merge_results(
    a_rows: list[dict[str, str]],
    b_coverage_rows: list[dict[str, object]],
    b_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    # Remove zero-witness summary rows before reconstructing
    # the Component-A -> Component-B interface mapping.
    a_witness_rows = [
        row for row in a_rows
        if row.get("w_m1_um") and row.get("witness_rank")
    ]

    assert len(a_witness_rows) == len(b_coverage_rows), (
        f"A/B interface mismatch: "
        f"{len(a_witness_rows)} A witnesses vs "
        f"{len(b_coverage_rows)} B inputs"
    )

    a_by_hidx = {
        int(row["point_index"]): a_witness_rows[i]
        for i, row in enumerate(b_coverage_rows)
    }

    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)

    for b in b_rows:
        hidx = int(float(pick(b, "point_index")))
        a = a_by_hidx[hidx]

        original_point = int(float(pick(a, "point_index")))
        merged: dict[str, object] = {
            "point_index": original_point,
            "component_a_witness_rank": a.get("witness_rank", ""),
            "component_b_witness_rank": b.get("witness_rank", ""),
            "w_m1_um": pick(a, "w_m1_um", "w1"),
            "i_m5_target_a": pick(
                a, "i_m5_target_a", "i5_target", "i_m5_a"
            ),
            "vbias_v": pick(a, "vbias_v", "vbias"),
            "vtail_v": pick(a, "vtail_v", "vtail"),
            "vx_v": pick(a, "vx_v", "vx"),
            "vy_v": pick(a, "vy_v", "vy"),
            "w_m3_um": pick(a, "w_m3_um", "w3"),
            "w_m5_um": pick(a, "w_m5_um", "w5"),
            "w_m6_um": pick(b, "w_m6_um", "w6"),
            "w_m7_um": pick(b, "w_m7_um", "w7"),
            "vout_v": pick(b, "vout_v", "vout"),
            "hierarchical_interface_id": hidx,
        }

        # Preserve component scores/residual diagnostics where available.
        for prefix, src in (("a_", a), ("b_", b)):
            for key, value in src.items():
                if (
                    "score" in key.lower()
                    or "residual" in key.lower()
                    or "headroom" in key.lower()
                ):
                    merged[prefix + key] = value

        grouped[original_point].append(merged)

    final: list[dict[str, object]] = []
    for point_index in sorted(grouped):
        rows = grouped[point_index]
        for rank, row in enumerate(rows):
            row["witness_rank"] = rank
            final.append(row)
    return final


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prototype hierarchical two-stage DC witness search."
    )
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--base-plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    ap.add_argument(
        "--max-points",
        type=int,
        default=None,
        help="Limit original independent points for a smoke test.",
    )
    ap.add_argument(
        "--a-witnesses",
        type=int,
        default=8,
        help="Feasible A interface states retained per independent point.",
    )
    ap.add_argument(
        "--b-witnesses",
        type=int,
        default=5,
        help="B witnesses retained per A interface state.",
    )
    args = ap.parse_args()

    root = args.root.resolve()

    def abs_from_root(p: Path) -> Path:
        return p if p.is_absolute() else (root / p).resolve()

    base_plan_path = abs_from_root(args.base_plan)
    engine_path = abs_from_root(args.engine)
    work = abs_from_root(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    base = read_yaml(base_plan_path)

    original_coverage = Path(base["coverage_csv"])
    if not original_coverage.is_absolute():
        original_coverage = (root / original_coverage).resolve()

    a_plan_path = work / "two_stage_component_a_plan.yaml"
    a_output = work / "component_a_witnesses.csv"
    b_coverage = work / "component_b_coverage.csv"
    b_plan_path = work / "two_stage_component_b_plan.yaml"
    b_output = work / "component_b_witnesses.csv"
    merged_output = work / "hierarchical_witnesses.csv"

    a_plan = build_component_a_plan(
        base,
        original_coverage,
        a_output,
        args.a_witnesses,
    )
    write_yaml(a_plan_path, a_plan)

    run_engine(
        root,
        engine_path,
        a_plan_path,
        args.max_points,
        args.a_witnesses,
    )

    a_rows = read_csv(a_output)

    # Keep only real Component-A witnesses.  The witness engine also
    # writes empty summary rows for independent points with no witness.
    a_witness_rows = [
        row for row in a_rows
        if row.get("w_m1_um") and row.get("witness_rank")
    ]

    if not a_witness_rows:
        print("Component A produced zero feasible interface states.")
        return 2

    b_cov_rows = make_b_coverage(a_rows)
    write_csv(b_coverage, b_cov_rows)

    b_plan = build_component_b_plan(
        base,
        b_coverage,
        b_output,
        args.b_witnesses,
    )
    write_yaml(b_plan_path, b_plan)

    # B coverage already contains only A survivors, so do not apply the
    # original --max-points again.
    run_engine(
        root,
        engine_path,
        b_plan_path,
        None,
        args.b_witnesses,
    )

    b_rows = read_csv(b_output)
    merged = merge_results(a_rows, b_cov_rows, b_rows)
    write_csv(merged_output, merged)

    original_points = {
        int(float(pick(r, "point_index")))
        for r in a_witness_rows
    }
    surviving_points = {
        int(row["point_index"])
        for row in merged
    }

    print("\n===== TWO-STAGE HIERARCHICAL SEARCH =====")
    print(f"Component A interface states : {len(a_witness_rows)}")
    print(f"Component B input states     : {len(b_cov_rows)}")
    print(f"Component B witnesses        : {len(b_rows)}")
    print(f"Joined A+B witnesses         : {len(merged)}")
    print(f"A-covered original points    : {len(original_points)}")
    print(f"A+B-covered original points  : {len(surviving_points)}")
    if original_points:
        print(
            "Join survival of A-covered points: "
            f"{100.0 * len(surviving_points) / len(original_points):.2f}%"
        )
    print(f"\nA plan   : {a_plan_path}")
    print(f"A states : {a_output}")
    print(f"B plan   : {b_plan_path}")
    print(f"B input  : {b_coverage}")
    print(f"B states : {b_output}")
    print(f"JOINED   : {merged_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

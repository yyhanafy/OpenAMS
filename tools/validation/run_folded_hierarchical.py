#!/usr/bin/env python3
"""
Prototype hierarchical folded-cascode DC witness search for OpenAMS.

Keeps the existing generic witness engine unchanged.

Nominal component partition from design_intent.yaml:
    FC-A = M1,M2,M3
    FC-B = M4,M5,M6,M7
    FC-C = M8,M9,M10,M11

Important electrical detail:
    The folded PMOS M6/M7 requires the internal node x, while x is
    established by the lower sink network M10/M11.  Therefore x is treated
    as an explicit B<->C interface variable:
        A -> B(x candidate) -> C(enforce same x)

The existing transistor MLP remains the oracle.  This script only changes
the search decomposition.
"""
from __future__ import annotations

import argparse
import copy
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml


DEFAULT_PLAN = Path(
    "examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml"
)
DEFAULT_ENGINE = Path("tools/validation/witness_engine.py")
DEFAULT_WORK = Path("runtime/folded_cascode_hierarchical")


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
        w.writerows(rows)


def pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    raise KeyError(
        f"none of {names!r} were present/nonempty; columns={sorted(row)}"
    )


def actual_witness_rows(rows: list[dict[str, str]], key: str = "w_m1_um"):
    return [
        r for r in rows
        if r.get(key) not in (None, "") and r.get("witness_rank") not in (None, "")
    ]


def stage_by_id(plan: dict, stage_id: str) -> dict:
    for stage in plan.get("stages", []):
        if stage.get("id") == stage_id:
            return copy.deepcopy(stage)
    raise KeyError(f"stage {stage_id!r} not found")


def device_by_name(plan: dict, name: str) -> dict:
    for device in plan["final"]["devices"]:
        if device.get("name") == name:
            return copy.deepcopy(device)
    raise KeyError(f"final device {name!r} not found")


def make_5x5_coverage(path: Path) -> None:
    # Representative architectural smoke grid.  The production experiment
    # should later use the characterized I3 grid from Step 3.
    w1s = [1.0, 25.75, 50.5, 75.25, 100.0]
    i3s = [10e-6, 32.5e-6, 55e-6, 77.5e-6, 100e-6]
    rows = []
    idx = 0
    for i3 in i3s:
        for w1 in w1s:
            rows.append({
                "point_index": idx,
                "w_m1_um": w1,
                "i_m3_a": i3,
            })
            idx += 1
    write_csv(path, rows)


def base_shell(
    base: dict,
    *,
    name: str,
    coverage_csv: Path,
    output_csv: Path,
    witnesses_per_point: int,
    point_bindings: dict,
    stages: list[dict],
    final: dict,
    csv_aliases: dict,
) -> dict:
    return {
        "schema_version": base.get("schema_version", 1),
        "name": name,
        "coverage_csv": str(coverage_csv),
        "output_csv": str(output_csv),
        "witnesses_per_point": int(witnesses_per_point),
        "sat_margin_v": base.get("sat_margin_v", 0.05),
        "mlp": copy.deepcopy(base["mlp"]),
        "constants": copy.deepcopy(base["constants"]),
        "point_bindings": point_bindings,
        "derived_bindings": copy.deepcopy(base.get("derived_bindings", {})),
        "stages": stages,
        "final": final,
        "csv_aliases": csv_aliases,
    }


def build_a_plan(base, coverage_csv, output_csv, keep):
    stages = [
        stage_by_id(base, "input_pair"),
        stage_by_id(base, "tail_source"),
    ]
    final = {
        "devices": [device_by_name(base, n) for n in ("M1", "M2", "M3")],
        "residuals": {
            "tail_kcl": base["final"]["residuals"]["tail_kcl"],
            "m3_target": base["final"]["residuals"]["m3_target"],
        },
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n]
            for n in ("M1", "M2", "M3")
        },
        "constraints": [
            "M1_domain & M2_domain & M3_domain",
            "((psrc_left-tail)-M1_vdsat) >= sat_margin_v",
            "((psrc_right-tail)-M2_vdsat) >= sat_margin_v",
            "((tail-vss)-M3_vdsat) >= sat_margin_v",
        ],
    }
    return base_shell(
        base,
        name="folded_component_A_m1_m3",
        coverage_csv=coverage_csv,
        output_csv=output_csv,
        witnesses_per_point=keep,
        point_bindings=copy.deepcopy(base["point_bindings"]),
        stages=stages,
        final=final,
        csv_aliases={
            "w_m1_um": "w1",
            "i_m3_a": "i3_target",
            "tail_v": "tail",
            "psrc_left_v": "psrc_left",
            "psrc_right_v": "psrc_right",
            "vnb1_v": "vnb1",
            "w_m3_um": "w3",
        },
    )


def make_b_coverage(a_rows):
    out = []
    hidx = 0
    for a in actual_witness_rows(a_rows):
        out.append({
            "point_index": hidx,
            "parent_point_index": pick(a, "point_index"),
            "parent_a_rank": a.get("witness_rank", "0"),
            "w_m1_um": pick(a, "w_m1_um", "w1"),
            "i_m3_a": pick(a, "i_m3_a", "i3_target"),
            "tail_v": pick(a, "tail_v", "tail"),
            "psrc_left_v": pick(a, "psrc_left_v", "psrc_left"),
            "psrc_right_v": pick(a, "psrc_right_v", "psrc_right"),
            "vnb1_v": pick(a, "vnb1_v", "vnb1"),
            "w_m3_um": pick(a, "w_m3_um", "w3"),
        })
        hidx += 1
    return out


def build_b_plan(base, coverage_csv, output_csv, keep):
    upper = stage_by_id(base, "upper_sources")
    folded = stage_by_id(base, "folded_pmos_left")

    # x is the electrical cut between folded PMOS and lower sink/cascode.
    # In the monolithic plan x was created earlier by lower_sink.  Here B
    # explicitly searches x and C later proves that the lower network can
    # realize the same value.
    folded["sweeps"] = {
        "x": {
            "source": "row_interval",
            "prefix": "x",
            "unit": "v",
            "default_lo": 0.05,
            "default_hi": 1.75,
            "count": 31,
            "spacing": "linear",
        },
        **folded.get("sweeps", {}),
    }
    folded.setdefault("outputs", {})["x"] = "x"
    coords = list(folded.get("selection_coordinates", []))
    if "x" not in coords:
        coords.insert(0, "x")
    folded["selection_coordinates"] = coords

    pb = {
        "w1": {"column": "w_m1_um"},
        "i3_target": {"column": "i_m3_a"},
        "tail": {"column": "tail_v"},
        "psrc_left": {"column": "psrc_left_v"},
        "psrc_right": {"column": "psrc_right_v"},
        "vnb1": {"column": "vnb1_v"},
        "w3": {"column": "w_m3_um"},
        "parent_point_index": {"column": "parent_point_index"},
        "parent_a_rank": {"column": "parent_a_rank"},
    }

    # B can fully verify M4/M5 and the left representative M6.  M7 shares
    # width/gate bias with M6 but its drain is vout, so M7 saturation/current
    # is deliberately deferred to C's output_branch.
    final = {
        "devices": [device_by_name(base, n) for n in ("M4", "M5", "M6")],
        "residuals": {
            "psrc_left_kcl": base["final"]["residuals"]["psrc_left_kcl"],
        },
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n]
            for n in ("M4", "M5", "M6")
        },
        "constraints": [
            "M4_domain & M5_domain & M6_domain",
            "((vdd-psrc_left)-M4_vdsat) >= sat_margin_v",
            "((vdd-psrc_right)-M5_vdsat) >= sat_margin_v",
            "((psrc_left-x)-M6_vdsat) >= sat_margin_v",
        ],
    }
    return base_shell(
        base,
        name="folded_component_B_m4_m7",
        coverage_csv=coverage_csv,
        output_csv=output_csv,
        witnesses_per_point=keep,
        point_bindings=pb,
        stages=[upper, folded],
        final=final,
        csv_aliases={
            "parent_point_index": "parent_point_index",
            "parent_a_rank": "parent_a_rank",
            "w_m1_um": "w1",
            "i_m3_a": "i3_target",
            "tail_v": "tail",
            "psrc_left_v": "psrc_left",
            "psrc_right_v": "psrc_right",
            "vnb1_v": "vnb1",
            "w_m3_um": "w3",
            "vpb1_v": "vpb1",
            "w_m4_um": "w4",
            "x_v": "x",
            "vpb2_v": "vpb2",
            "w_m6_um": "w6",
        },
    )


def make_c_coverage(a_rows, b_cov_rows, b_rows):
    a_real = actual_witness_rows(a_rows)
    if len(a_real) != len(b_cov_rows):
        raise RuntimeError(
            f"A/B interface mismatch: {len(a_real)} vs {len(b_cov_rows)}"
        )
    a_by_bpoint = {
        int(float(r["point_index"])): a_real[i]
        for i, r in enumerate(b_cov_rows)
    }

    out = []
    cidx = 0
    for b in actual_witness_rows(b_rows):
        bpoint = int(float(pick(b, "point_index")))
        a = a_by_bpoint[bpoint]
        out.append({
            "point_index": cidx,
            "parent_point_index": pick(a, "point_index"),
            "parent_a_rank": a.get("witness_rank", "0"),
            "parent_b_point": bpoint,
            "parent_b_rank": b.get("witness_rank", "0"),
            "w_m1_um": pick(a, "w_m1_um", "w1"),
            "i_m3_a": pick(a, "i_m3_a", "i3_target"),
            "tail_v": pick(a, "tail_v", "tail"),
            "psrc_left_v": pick(a, "psrc_left_v", "psrc_left"),
            "psrc_right_v": pick(a, "psrc_right_v", "psrc_right"),
            "vnb1_v": pick(a, "vnb1_v", "vnb1"),
            "w_m3_um": pick(a, "w_m3_um", "w3"),
            "vpb1_v": pick(b, "vpb1_v", "vpb1"),
            "w_m4_um": pick(b, "w_m4_um", "w4"),
            "x_v": pick(b, "x_v", "x"),
            "vpb2_v": pick(b, "vpb2_v", "vpb2"),
            "w_m6_um": pick(b, "w_m6_um", "w6"),
        })
        cidx += 1
    return out


def build_c_plan(base, coverage_csv, output_csv, keep):
    sink = stage_by_id(base, "lower_sink")
    cascode = stage_by_id(base, "lower_cascode_left")
    output = stage_by_id(base, "output_branch")

    # x is fixed by the B candidate and must be realized by M10/M11 here.
    sink.get("sweeps", {}).pop("x", None)
    sink.setdefault("outputs", {})["x"] = "x"
    sink["selection_coordinates"] = [
        q for q in sink.get("selection_coordinates", []) if q != "x"
    ]

    pb = {
        "w1": {"column": "w_m1_um"},
        "i3_target": {"column": "i_m3_a"},
        "tail": {"column": "tail_v"},
        "psrc_left": {"column": "psrc_left_v"},
        "psrc_right": {"column": "psrc_right_v"},
        "vnb1": {"column": "vnb1_v"},
        "w3": {"column": "w_m3_um"},
        "vpb1": {"column": "vpb1_v"},
        "w4": {"column": "w_m4_um"},
        "x": {"column": "x_v"},
        "vpb2": {"column": "vpb2_v"},
        "w6": {"column": "w_m6_um"},
        "parent_point_index": {"column": "parent_point_index"},
        "parent_a_rank": {"column": "parent_a_rank"},
        "parent_b_point": {"column": "parent_b_point"},
        "parent_b_rank": {"column": "parent_b_rank"},
    }

    # C verifies the lower network plus the deferred right folded device M7.
    # M5H/M11H aliases in output_branch are used only for headroom expressions.
    final = {
        "devices": [
            device_by_name(base, n) for n in ("M7", "M8", "M9", "M10", "M11")
        ],
        "residuals": {
            k: base["final"]["residuals"][k]
            for k in (
                "x_kcl",
                "nsink_left_kcl",
                "output_kcl",
                "nsink_right_kcl",
            )
        },
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n]
            for n in ("M7", "M8", "M9", "M10", "M11")
        },
        "constraints": [
            "M7_domain & M8_domain & M9_domain & M10_domain & M11_domain",
            "((psrc_right-vout)-M7_vdsat) >= sat_margin_v",
            "((x-nsink_left)-M8_vdsat) >= sat_margin_v",
            "((vout-nsink_right)-M9_vdsat) >= sat_margin_v",
            "((nsink_left-vss)-M10_vdsat) >= sat_margin_v",
            "((nsink_right-vss)-M11_vdsat) >= sat_margin_v",
            "vout > vss + M9_vdsat + M11_vdsat",
        ],
    }

    return base_shell(
        base,
        name="folded_component_C_m8_m11",
        coverage_csv=coverage_csv,
        output_csv=output_csv,
        witnesses_per_point=keep,
        point_bindings=pb,
        stages=[sink, cascode, output],
        final=final,
        csv_aliases={
            "parent_point_index": "parent_point_index",
            "parent_a_rank": "parent_a_rank",
            "parent_b_point": "parent_b_point",
            "parent_b_rank": "parent_b_rank",
            "w_m1_um": "w1",
            "i_m3_a": "i3_target",
            "tail_v": "tail",
            "psrc_left_v": "psrc_left",
            "psrc_right_v": "psrc_right",
            "vnb1_v": "vnb1",
            "w_m3_um": "w3",
            "vpb1_v": "vpb1",
            "w_m4_um": "w4",
            "x_v": "x",
            "vpb2_v": "vpb2",
            "w_m6_um": "w6",
            "nsink_left_v": "nsink_left",
            "nsink_right_v": "nsink_right",
            "w_m8_um": "w8",
            "vnb2_v": "vnb2",
            "vout_v": "vout",
        },
    )


def run_engine(root, engine, plan, keep, max_points=None):
    cmd = [
        sys.executable,
        str(engine),
        "--plan", str(plan),
        "--root", str(root),
        "--witnesses-per-point", str(keep),
    ]
    if max_points is not None:
        cmd += ["--max-points", str(max_points)]
    print("\nRUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=root, check=True)


def join_final(a_rows, b_cov, b_rows, c_cov, c_rows):
    # c_coverage already contains the complete A+B interface.  Join C rows
    # directly back to those interface rows.
    c_by_point = {
        int(float(r["point_index"])): r
        for r in c_cov
    }

    grouped = defaultdict(list)
    for c in actual_witness_rows(c_rows):
        cpoint = int(float(pick(c, "point_index")))
        interface = c_by_point[cpoint]
        original = int(float(interface["parent_point_index"]))

        row = dict(interface)
        row.update({
            "point_index": original,
            "component_c_witness_rank": c.get("witness_rank", ""),
            "nsink_left_v": pick(c, "nsink_left_v", "nsink_left"),
            "nsink_right_v": pick(c, "nsink_right_v", "nsink_right"),
            "w_m8_um": pick(c, "w_m8_um", "w8"),
            "vnb2_v": pick(c, "vnb2_v", "vnb2"),
            "vout_v": pick(c, "vout_v", "vout"),
        })
        grouped[original].append(row)

    out = []
    for point in sorted(grouped):
        for rank, row in enumerate(grouped[point]):
            row["witness_rank"] = rank
            out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--base-plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--coverage-csv", type=Path, default=None)
    ap.add_argument("--max-points", type=int, default=None)
    ap.add_argument("--a-witnesses", type=int, default=16)
    ap.add_argument("--b-witnesses", type=int, default=16)
    ap.add_argument("--c-witnesses", type=int, default=5)
    args = ap.parse_args()

    root = args.root.resolve()

    def absroot(p: Path) -> Path:
        return p if p.is_absolute() else (root / p).resolve()

    base_path = absroot(args.base_plan)
    engine = absroot(args.engine)
    work = absroot(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    base = read_yaml(base_path)

    coverage = (
        absroot(args.coverage_csv)
        if args.coverage_csv is not None
        else work / "folded_coverage_5x5.csv"
    )
    if args.coverage_csv is None:
        make_5x5_coverage(coverage)

    a_plan_p = work / "component_a_plan.yaml"
    a_out = work / "component_a_witnesses.csv"
    b_cov_p = work / "component_b_coverage.csv"
    b_plan_p = work / "component_b_plan.yaml"
    b_out = work / "component_b_witnesses.csv"
    c_cov_p = work / "component_c_coverage.csv"
    c_plan_p = work / "component_c_plan.yaml"
    c_out = work / "component_c_witnesses.csv"
    joined_p = work / "hierarchical_witnesses.csv"

    write_yaml(
        a_plan_p,
        build_a_plan(base, coverage, a_out, args.a_witnesses),
    )
    run_engine(
        root, engine, a_plan_p, args.a_witnesses, args.max_points
    )
    a_rows = read_csv(a_out)
    a_real = actual_witness_rows(a_rows)
    if not a_real:
        print("Component A produced zero witnesses.")
        return 2

    b_cov = make_b_coverage(a_rows)
    write_csv(b_cov_p, b_cov)
    write_yaml(
        b_plan_p,
        build_b_plan(base, b_cov_p, b_out, args.b_witnesses),
    )
    run_engine(root, engine, b_plan_p, args.b_witnesses)
    b_rows = read_csv(b_out)
    b_real = actual_witness_rows(b_rows)
    if not b_real:
        print("Component B produced zero witnesses.")
        return 3

    c_cov = make_c_coverage(a_rows, b_cov, b_rows)
    write_csv(c_cov_p, c_cov)
    write_yaml(
        c_plan_p,
        build_c_plan(base, c_cov_p, c_out, args.c_witnesses),
    )
    run_engine(root, engine, c_plan_p, args.c_witnesses)
    c_rows = read_csv(c_out)
    c_real = actual_witness_rows(c_rows)

    joined = join_final(a_rows, b_cov, b_rows, c_cov, c_rows)
    write_csv(joined_p, joined)

    a_points = {int(float(r["point_index"])) for r in a_real}
    b_points = {int(float(r["parent_point_index"])) for r in c_cov}
    final_points = {int(r["point_index"]) for r in joined}

    print("\n===== FOLDED-CASCODE HIERARCHICAL SEARCH =====")
    print(f"Component A interface states : {len(a_real)}")
    print(f"Component B input states     : {len(b_cov)}")
    print(f"Component B interface states : {len(b_real)}")
    print(f"Component C input states     : {len(c_cov)}")
    print(f"Component C witnesses        : {len(c_real)}")
    print(f"Joined A+B+C witnesses       : {len(joined)}")
    print(f"A-covered original points    : {len(a_points)}")
    print(f"A+B-covered original points  : {len(b_points)}")
    print(f"A+B+C-covered points         : {len(final_points)}")
    if a_points:
        print(
            "A->B point survival          : "
            f"{100.0*len(b_points)/len(a_points):.2f}%"
        )
    if b_points:
        print(
            "B->C point survival          : "
            f"{100.0*len(final_points)/len(b_points):.2f}%"
        )

    print(f"\ncoverage : {coverage}")
    print(f"A states : {a_out}")
    print(f"B states : {b_out}")
    print(f"C states : {c_out}")
    print(f"JOINED   : {joined_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

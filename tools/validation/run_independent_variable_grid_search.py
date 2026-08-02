#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json
from pathlib import Path
from openams.synthesis.independent_grid_search import search_grid

def main() -> int:
    p = argparse.ArgumentParser()
    base = Path("examples/two_stage_opamp/generated")
    p.add_argument("--compiled-model", type=Path, default=base/"compiled_circuit_model.json")
    p.add_argument("--independent-regions", type=Path, default=base/"assignment_synthesis/independent_regions.json")
    p.add_argument("--contract", type=Path, default=base/"generic_assignment_contract.json")
    p.add_argument("--output-dir", type=Path, default=base/"assignment_synthesis/independent_grid_search")
    p.add_argument("--w1-step-um", type=float, default=1.0)
    p.add_argument("--vout-step-v", type=float, default=0.1)
    p.add_argument("--i5-stride", type=int, default=1)
    p.add_argument("--start-index", type=int, default=0)
    p.add_argument("--max-grid-points", type=int, default=1000)
    p.add_argument("--max-partials-per-point", type=int, default=5000)
    p.add_argument("--progress-every", type=int, default=100)
    a = p.parse_args()

    artifact = search_grid(
        a.compiled_model, a.independent_regions, a.contract,
        w1_step_um=a.w1_step_um,
        vout_step_v=a.vout_step_v,
        i5_stride=a.i5_stride,
        start_index=a.start_index,
        max_grid_points=a.max_grid_points,
        max_partials_per_point=a.max_partials_per_point,
        progress_every=a.progress_every,
    )
    a.output_dir.mkdir(parents=True, exist_ok=True)
    jp = a.output_dir/"independent_grid_assignments.json"
    cp = a.output_dir/"independent_grid_assignments.csv"
    rp = a.output_dir/"INDEPENDENT_GRID_SEARCH_REPORT.md"
    jp.write_text(json.dumps(artifact, indent=2))
    rows = artifact["assignments"]
    if rows:
        fields = sorted({k for row in rows for k in row})
        with cp.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader(); w.writerows(rows)
    rp.write_text(
        "# Independent Grid Search\n\n"
        f"- Full grid: {artifact['grid']['full_point_count']}\n"
        f"- Tested: {artifact['grid']['points_tested']}\n"
        f"- Feasible: {artifact['results']['feasible_point_count']}\n"
        f"- Rejected: {artifact['results']['rejected_point_count']}\n"
        f"- Truncated: {artifact['results']['truncated_point_count']}\n"
    )
    print("===== OPENAMS INDEPENDENT-VARIABLE GRID SEARCH =====")
    print("full grid points:", artifact["grid"]["full_point_count"])
    print("points tested:", artifact["grid"]["points_tested"])
    print("feasible points:", artifact["results"]["feasible_point_count"])
    print("rejected points:", artifact["results"]["rejected_point_count"])
    print("truncated points:", artifact["results"]["truncated_point_count"])
    print("partials visited:", artifact["results"]["partials_visited_total"])
    print("json:", jp); print("csv:", cp); print("report:", rp)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

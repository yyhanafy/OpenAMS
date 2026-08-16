from __future__ import annotations
import json, math, tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from openams.synthesis.generic_topology_solver import solve_generic_assignments

@dataclass(frozen=True)
class GridPoint:
    index: int
    i_m5_a: float
    w_m1_um: float
    vout_v: float

def inclusive_grid(minimum: float, maximum: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    count = int(math.floor((maximum - minimum) / step + 1e-12))
    values = [minimum + i * step for i in range(count + 1)]
    if not math.isclose(values[-1], maximum, abs_tol=1e-12):
        values.append(maximum)
    return values

def one_point_independent_regions(base: Mapping[str, Any], point: GridPoint) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for name, value in (
        ("i_m5_a", point.i_m5_a),
        ("w_m1_um", point.w_m1_um),
        ("vout_v", point.vout_v),
    ):
        domain = result["domains"][name]
        domain["candidate_values"] = [value]
        domain["candidate_count"] = 1
        domain["effective_minimum"] = value
        domain["effective_maximum"] = value
        domain["technology_minimum"] = value
        domain["technology_maximum"] = value
        domain["domain_type"] = "fixed_independent_grid_coordinate"
    return result

def build_points(base: Mapping[str, Any], w1_step_um: float, vout_step_v: float, i5_stride: int) -> list[GridPoint]:
    i5_values = [float(v) for v in base["domains"]["i_m5_a"]["candidate_values"]][::i5_stride]
    w1 = base["domains"]["w_m1_um"]
    vout = base["domains"]["vout_v"]
    w1_values = inclusive_grid(float(w1["technology_minimum"]), float(w1["technology_maximum"]), w1_step_um)
    vout_values = inclusive_grid(float(vout["technology_minimum"]), float(vout["technology_maximum"]), vout_step_v)
    points = []
    idx = 0
    for i5 in i5_values:
        for width in w1_values:
            for output in vout_values:
                points.append(GridPoint(idx, i5, width, output))
                idx += 1
    return points

def search_grid(
    compiled_model_path: Path,
    independent_regions_path: Path,
    contract_path: Path,
    *,
    w1_step_um: float,
    vout_step_v: float,
    i5_stride: int,
    start_index: int,
    max_grid_points: int,
    max_partials_per_point: int,
    progress_every: int,
) -> dict[str, Any]:
    base = json.loads(independent_regions_path.read_text())
    all_points = build_points(base, w1_step_um, vout_step_v, i5_stride)
    points = all_points[start_index:start_index + max_grid_points]
    feasible, rejected, truncated, partials = [], 0, 0, 0

    with tempfile.TemporaryDirectory(prefix="openams-grid-") as td:
        point_path = Path(td) / "point.json"
        for count, point in enumerate(points, start=1):
            point_path.write_text(json.dumps(one_point_independent_regions(base, point)))
            result = solve_generic_assignments(
                compiled_model_path,
                point_path,
                contract_path,
                max_solutions=1,
                max_partials=max_partials_per_point,
                progress_every=0,
            )
            partials += int(result["statistics"]["partials"])
            if result["assignment_count"]:
                row = dict(result["assignments"][0])
                row.update({
                    "independent_grid_point_index": point.index,
                    "grid_i_m5_a": point.i_m5_a,
                    "grid_w_m1_um": point.w_m1_um,
                    "grid_vout_v": point.vout_v,
                })
                feasible.append(row)
            elif result.get("stop_reason") == "max_partials_reached":
                truncated += 1
            else:
                rejected += 1
            if progress_every and count % progress_every == 0:
                print(f"[GRID] tested={count}/{len(points)} feasible={len(feasible)} rejected={rejected} truncated={truncated}", flush=True)

    return {
        "artifact": "openams.independent_variable_grid_search",
        "status": "PASS",
        "search_semantics": "one representative per feasible (I5,W1,Vout) grid point",
        "grid": {
            "full_point_count": len(all_points),
            "points_tested": len(points),
            "start_index": start_index,
            "w1_step_um": w1_step_um,
            "vout_step_v": vout_step_v,
            "i5_stride": i5_stride,
        },
        "results": {
            "feasible_point_count": len(feasible),
            "rejected_point_count": rejected,
            "truncated_point_count": truncated,
            "partials_visited_total": partials,
        },
        "assignments": feasible,
    }

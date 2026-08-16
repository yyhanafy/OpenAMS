from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from openams.technology.mlp_oracle import MlpOracle

SAFE_FUNCTIONS = {
    "abs": np.abs,
    "min": np.minimum,
    "max": np.maximum,
    "sqrt": np.sqrt,
    "clip": np.clip,
    "where": np.where,
}


def relative_error(value, target):
    value = np.asarray(value, dtype=float)
    target = np.asarray(target, dtype=float)
    denominator = np.maximum(np.maximum(np.abs(value), np.abs(target)), 1e-30)
    return np.abs(value - target) / denominator


def evaluate(expression: Any, environment: dict[str, Any]):
    return eval(
        str(expression),
        {"__builtins__": {}},
        {**SAFE_FUNCTIONS, "np": np, "relerr": relative_error, **environment},
    )


def row_float(row: dict[str, str], key: str, default=None) -> float:
    value = row.get(key, "")
    if value not in ("", None):
        return float(value)
    if default is not None:
        return float(default)
    raise KeyError(f"missing required design-space column: {key}")


def interval(row: dict[str, str], specification: dict[str, Any]) -> tuple[float, float]:
    if "lo_column" in specification:
        lo = row_float(row, specification["lo_column"], specification.get("default_lo"))
        hi = row_float(row, specification["hi_column"], specification.get("default_hi"))
    else:
        prefix = specification["prefix"]
        unit = specification["unit"]
        lo = row_float(row, f"{prefix}_min_{unit}", specification.get("default_lo"))
        hi = row_float(row, f"{prefix}_max_{unit}", specification.get("default_hi"))
    return (lo, hi) if lo <= hi else (hi, lo)


def sweep_values(
    specification: dict[str, Any],
    row: dict[str, str],
    environment: dict[str, Any],
    oracle: MlpOracle,
) -> np.ndarray:
    source = specification.get("source", "range")
    if source == "row_interval":
        lo, hi = interval(row, specification)
    elif source == "model_width_interval":
        lo, hi = interval(row, specification["row_interval"])
        domain_lo, domain_hi = oracle.width_domain(specification["polarity"])
        lo, hi = max(lo, domain_lo), min(hi, domain_hi)
    else:
        lo = float(evaluate(specification["lo"], environment))
        hi = float(evaluate(specification["hi"], environment))

    if hi < lo:
        return np.array([], dtype=float)

    count = int(specification.get("count", 1))
    if count <= 1:
        return np.array([(lo + hi) / 2.0], dtype=float)
    if specification.get("spacing", "linear") == "geom":
        return np.geomspace(lo, hi, count)
    return np.linspace(lo, hi, count)


def _cap_diverse(records: list[dict[str, float]], cap: int, keys: list[str]):
    if cap <= 0 or len(records) <= cap:
        return records
    output: list[dict[str, float]] = []
    seen: set[int] = set()

    def add(index: int):
        if index not in seen:
            output.append(records[index])
            seen.add(index)

    for key in keys:
        values = np.array([float(record[key]) for record in records])
        add(int(np.argmin(values)))
        add(int(np.argmax(values)))
        add(int(np.argmin(np.abs(values - np.median(values)))))

    if len(output) < cap:
        order = sorted(
            range(len(records)),
            key=lambda index: tuple(
                float(records[index][key]) for key in keys
            ),
        )
        for position in np.linspace(
            0, len(order) - 1, cap
        ).round().astype(int):
            add(order[int(position)])
            if len(output) >= cap:
                break

    return output[:cap]


def _representatives(mask, score, coordinates, count: int):
    indices = [tuple(map(int, item)) for item in np.argwhere(mask)]
    if not indices:
        return []
    candidates = [min(indices, key=lambda q: float(score[q]))]
    for coordinate in coordinates:
        candidates.extend(
            [
                min(indices, key=lambda q: float(coordinate[q])),
                max(indices, key=lambda q: float(coordinate[q])),
            ]
        )
    output = []
    for candidate in candidates:
        if candidate not in output:
            output.append(candidate)
        if len(output) >= count:
            break
    return output


def _base_environment(plan: dict[str, Any], row: dict[str, str]) -> dict[str, float]:
    environment = {key: float(value) for key, value in (plan.get("constants") or {}).items()}
    for key, binding in (plan.get("point_bindings") or {}).items():
        environment[key] = row_float(row, binding["column"], binding.get("default"))
    for key, expression in (plan.get("derived_bindings") or {}).items():
        environment[key] = float(evaluate(expression, environment))
    return environment


def _evaluate_devices(block, environment, oracle: MlpOracle):
    for device in block.get("devices", []):
        name = device["name"]
        polarity = device["polarity"]
        width = np.asarray(evaluate(device["width"], environment), float)
        vgs = np.asarray(evaluate(device["vgs"], environment), float)
        vds = np.asarray(evaluate(device["vds"], environment), float)
        vbs = np.asarray(evaluate(device["vbs"], environment), float)
        width, vgs, vds, vbs = np.broadcast_arrays(width, vgs, vds, vbs)
        environment[name + "_domain"] = oracle.inside_domain(
            polarity, width, vgs, vds, vbs
        )
        prediction = oracle.predict(polarity, width, vgs, vds, vbs)
        environment[name + "_id"] = prediction["id_abs_a"]
        environment[name + "_vdsat"] = prediction["vdsat_abs_v"]


def _run_stage(stage, parents, row, base, oracle: MlpOracle):
    output = []
    feasible_count = 0
    for parent in parents:
        seed = {**base, **parent}
        names = list((stage.get("sweeps") or {}).keys())
        vectors = [
            sweep_values(stage["sweeps"][name], row, seed, oracle) for name in names
        ]
        if any(len(vector) == 0 for vector in vectors):
            continue

        environment = dict(seed)
        if names:
            mesh = np.meshgrid(*vectors, indexing="ij")
            shape = mesh[0].shape
            for name, values in zip(names, mesh):
                environment[name] = values
        else:
            shape = (1,)
            for key, value in list(environment.items()):
                if isinstance(value, (int, float, np.number)):
                    environment[key] = np.array([value], dtype=float)

        for key, expression in (stage.get("derived") or {}).items():
            environment[key] = np.broadcast_to(
                np.asarray(evaluate(expression, environment), float), shape
            )

        _evaluate_devices(stage, environment, oracle)
        mask = np.ones(shape, dtype=bool)
        for expression in stage.get("constraints", []):
            mask &= np.broadcast_to(
                np.asarray(evaluate(expression, environment), bool), shape
            )
        feasible_count += int(mask.sum())
        if not mask.any():
            continue

        score = np.broadcast_to(
            np.asarray(evaluate(stage.get("score", "0"), environment), float), shape
        )
        selection_names = stage.get("selection_coordinates", names)
        coordinates = [
            np.broadcast_to(np.asarray(environment[name], float), shape)
            for name in selection_names
        ]
        selection_mode = stage.get("selection_mode", "representative")
        keep = int(stage.get("per_parent_keep", 3))

        if selection_mode == "all_feasible":
            selected_indices = [
                tuple(map(int, item))
                for item in np.argwhere(mask)
            ]
        elif selection_mode == "representative":
            selected_indices = _representatives(
                mask, score, coordinates, keep
            )
        else:
            raise ValueError(
                f"unsupported selection_mode: {selection_mode!r}"
            )

        for index in selected_indices:
            record = dict(parent)
            for key, expression in (stage.get("outputs") or {}).items():
                value = np.broadcast_to(
                    np.asarray(evaluate(expression, environment), float), shape
                )[index]
                record[key] = float(value)
            output.append(record)

    output = _cap_diverse(
        output,
        int(stage.get("global_cap", 64)),
        stage.get("diversity_keys") or list((stage.get("outputs") or {}).keys()),
    )
    return output, feasible_count


def _final_rank(final, candidates, base, oracle: MlpOracle):
    if not candidates:
        return []
    count = len(candidates)
    environment = dict(base)
    keys = set().union(*(candidate.keys() for candidate in candidates))
    for key in keys:
        environment[key] = np.array([float(candidate[key]) for candidate in candidates])
    for key, value in list(environment.items()):
        if isinstance(value, (int, float, np.number)):
            environment[key] = np.full(count, float(value))

    for key, expression in (final.get("derived") or {}).items():
        environment[key] = np.broadcast_to(
            np.asarray(evaluate(expression, environment), float), (count,)
        )

    _evaluate_devices(final, environment, oracle)
    residuals = {
        key: np.broadcast_to(np.asarray(evaluate(expr, environment), float), (count,))
        for key, expr in (final.get("residuals") or {}).items()
    }
    saturation = {
        key: np.broadcast_to(np.asarray(evaluate(expr, environment), float), (count,))
        for key, expr in (final.get("saturation_headroom") or {}).items()
    }

    if residuals:
        residual_matrix = np.column_stack(list(residuals.values()))
    else:
        residual_matrix = np.zeros((len(next(iter(environment.values()))), 1), dtype=float)
    max_abs = np.max(np.abs(residual_matrix), axis=1)
    rms = np.sqrt(np.mean(residual_matrix * residual_matrix, axis=1))
    valid = np.ones(count, dtype=bool)
    for expression in final.get("constraints", []):
        valid &= np.broadcast_to(
            np.asarray(evaluate(expression, environment), bool), (count,)
        )

    ranked = []
    for index, candidate in enumerate(candidates):
        if not valid[index]:
            continue
        diagnostics = {
            "residuals": {key: float(values[index]) for key, values in residuals.items()},
            "saturation": {key: float(values[index]) for key, values in saturation.items()},
            "ids": {
                device["name"]: float(np.asarray(environment[device["name"] + "_id"])[index])
                for device in final.get("devices", [])
            },
        }
        ranked.append((float(max_abs[index]), float(rms[index]), candidate, diagnostics))
    return sorted(ranked, key=lambda item: (item[0], item[1]))


def output_fields(plan: dict[str, Any]) -> list[str]:
    fields = [
        "point_index",
        "point_status",
        "generation_status",
        "witness_rank",
        "max_abs_residual",
        "rms_residual",
        "all_saturated",
        "complete_candidates",
        "point_elapsed_s",
    ]
    fields += list((plan.get("csv_aliases") or {}).keys())
    fields += ["residual_" + key for key in plan["final"].get("residuals", {})]
    fields += [
        "sat_" + key + "_headroom_v"
        for key in plan["final"].get("saturation_headroom", {})
    ]
    fields += [
        "id_" + device["name"].lower() + "_a"
        for device in plan["final"].get("devices", [])
    ]
    fields += [stage["id"] + "_feasible" for stage in plan.get("stages", [])]
    return list(dict.fromkeys(fields))


def resolve(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def generate_witnesses(
    *,
    plan_path: Path,
    root: Path,
    max_points: int = 0,
    output_csv: Path | None = None,
    witnesses_per_point: int | None = None,
) -> Path:
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    mlp = plan["mlp"]
    oracle = MlpOracle.load(
        {
            "nmos": resolve(root, mlp["nmos_checkpoint"]),
            "pmos": resolve(root, mlp["pmos_checkpoint"]),
        },
        length_um=float(mlp.get("length_um", 0.5)),
    )

    coverage_path = resolve(root, plan["coverage_csv"])
    with coverage_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if max_points:
        rows = rows[:max_points]

    output_path = output_csv or resolve(root, plan["output_csv"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = output_fields(plan)
    keep = witnesses_per_point or int(plan.get("witnesses_per_point", 5))
    started = time.perf_counter()

    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()

        for ordinal, row in enumerate(rows, 1):
            point_started = time.perf_counter()
            base = _base_environment(plan, row)
            parents = [{}]
            stage_stats: dict[str, int] = {}

            for stage in plan.get("stages", []):
                parents, feasible = _run_stage(stage, parents, row, base, oracle)
                stage_stats[stage["id"]] = feasible

            ranked = _final_rank(plan["final"], parents, base, oracle) if parents else []
            elapsed = time.perf_counter() - point_started
            point_index = int(float(row["point_index"]))

            if ranked:
                for rank, (max_abs, rms, candidate, diagnostics) in enumerate(
                    ranked[:keep], 1
                ):
                    environment = {**base, **candidate}
                    record = {
                        "point_index": point_index,
                        "point_status": row.get("status", ""),
                        "generation_status": "WITNESS",
                        "witness_rank": rank,
                        "max_abs_residual": max_abs,
                        "rms_residual": rms,
                        "all_saturated": all(
                            value >= float(plan.get("sat_margin_v", 0.05))
                            for value in diagnostics["saturation"].values()
                        ),
                        "complete_candidates": len(ranked),
                        "point_elapsed_s": elapsed,
                    }
                    for key, expression in (plan.get("csv_aliases") or {}).items():
                        record[key] = float(evaluate(expression, environment))
                    for key, value in diagnostics["residuals"].items():
                        record["residual_" + key] = value
                    for key, value in diagnostics["saturation"].items():
                        record["sat_" + key + "_headroom_v"] = value
                    for key, value in diagnostics["ids"].items():
                        record["id_" + key.lower() + "_a"] = value
                    for key, value in stage_stats.items():
                        record[key + "_feasible"] = value
                    writer.writerow(record)
            else:
                record = {key: "" for key in fieldnames}
                record.update(
                    point_index=point_index,
                    point_status=row.get("status", ""),
                    generation_status="NO_WITNESS",
                    witness_rank=0,
                    complete_candidates=0,
                    point_elapsed_s=elapsed,
                )
                record.update({key + "_feasible": value for key, value in stage_stats.items()})
                writer.writerow(record)

            stream.flush()
            print(
                f"[{ordinal:4d}/{len(rows):4d}] point={point_index:6d} "
                f"witnesses={min(len(ranked), keep)} complete={len(ranked):4d} "
                f"time={elapsed:6.3f}s"
            )

    print(
        f"DONE rows={len(rows)} wall={time.perf_counter()-started:.3f}s "
        f"MLP_calls={oracle.calls:,} MLP_points={oracle.points:,} output={output_path}"
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate topology-generic correlated MLP witnesses.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--max-points", type=int, default=0)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--witnesses-per-point", type=int)
    args = parser.parse_args()
    generate_witnesses(
        plan_path=args.plan,
        root=args.root,
        max_points=args.max_points,
        output_csv=args.output_csv,
        witnesses_per_point=args.witnesses_per_point,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

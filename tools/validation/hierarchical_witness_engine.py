#!/usr/bin/env python3
"""
Generic hierarchical Step-5 witness engine.

The engine is topology-agnostic. It consumes a compiled hierarchical contract
that declares:

  * independent design-point source
  * component DAG
  * component MLP checkpoints and feature names
  * interface coordinates
  * optional propagated variables
  * exact-realizer builders
  * final canonical witness fields

Supported component behavior:
  1. binary_feasibility_classifier
  2. feasibility_range_emitter

Supported execution:
  * arbitrary acyclic component chains / DAGs
  * shared discrete interface coordinates
  * upstream propagated exact values after realization
  * local search coordinates
  * parallel exact realization
  * complete canonical witness assembly

There is intentionally no circuit-name, transistor-number, "two stage",
"folded", A/B/C, VP/VX/VY, or other topology-specific branching here.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import itertools
import json
import os
import subprocess
import sys
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import torch
from torch import nn


# ---------------------------------------------------------------------------
# Generic neural models
# ---------------------------------------------------------------------------

class BinaryMLP(nn.Module):
    def __init__(self, nin: int, hidden):
        super().__init__()
        layers = []
        d = nin
        for h in hidden:
            layers += [nn.Linear(d, h), nn.ReLU()]
            d = h
        layers.append(nn.Linear(d, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x).squeeze(-1)


class RangeEmitterMLP(nn.Module):
    def __init__(self, nin: int, hidden):
        super().__init__()
        layers = []
        d = nin
        for h in hidden:
            layers += [nn.Linear(d, h), nn.ReLU()]
            d = h
        self.backbone = nn.Sequential(*layers)
        self.valid_head = nn.Linear(d, 1)
        self.range_head = nn.Linear(d, 2)

    def forward(self, x):
        z = self.backbone(x)
        return self.valid_head(z).squeeze(-1), self.range_head(z)


# ---------------------------------------------------------------------------
# Basic IO/helpers
# ---------------------------------------------------------------------------

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                fields.append(k)

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(
        f"_openams_realizer_{path.stem}", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import realizer module {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def q(value, digits=9):
    return round(float(value), digits)


def safe_eval(expr, env):
    return eval(
        expr,
        {"__builtins__": {}, "min": min, "max": max, "abs": abs},
        env,
    )


def grid_values(spec):
    g = spec["grid"]
    lo = float(g["minimum"])
    hi = float(g["maximum"])
    n = int(g["count"])
    spacing = g.get("spacing", "linear")

    if spacing in ("geom", "log", "geometric"):
        return [float(x) for x in np.geomspace(lo, hi, n)]

    return [float(x) for x in np.linspace(lo, hi, n)]


def nested_domains(data):
    if isinstance(data, dict):
        if isinstance(data.get("domains"), dict):
            return data["domains"]
        for v in data.values():
            found = nested_domains(v)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# Contract / DAG
# ---------------------------------------------------------------------------

def component_map(contract):
    return {c["id"]: c for c in contract["components"]}


def interface_map(contract):
    return {i["id"]: i for i in contract["interfaces"]}


def topological_order(contract):
    comps = component_map(contract)
    indegree = {cid: 0 for cid in comps}
    children = defaultdict(list)

    # Explicit dependencies.
    for c in contract["components"]:
        for dep in c.get("depends_on", []):
            if dep not in comps:
                raise ValueError(
                    f"component {c['id']}: unknown dependency {dep}"
                )
            indegree[c["id"]] += 1
            children[dep].append(c["id"])

    # Interface direction also implies upstream -> downstream whenever one side
    # declares the interface as output and the other as input.
    for interface in contract["interfaces"]:
        iid = interface["id"]
        left, right = interface["between"]
        lc = comps[left]
        rc = comps[right]

        if iid in lc.get("interface_outputs", []) and \
           iid in rc.get("interface_inputs", []):
            upstream, downstream = left, right
        elif iid in rc.get("interface_outputs", []) and \
             iid in lc.get("interface_inputs", []):
            upstream, downstream = right, left
        else:
            # Pure symmetric shared-coordinate interface. It adds no ordering.
            continue

        if downstream not in children[upstream]:
            indegree[downstream] += 1
            children[upstream].append(downstream)

    queue = deque(sorted([k for k, v in indegree.items() if v == 0]))
    order = []

    while queue:
        u = queue.popleft()
        order.append(u)
        for v in children[u]:
            indegree[v] -= 1
            if indegree[v] == 0:
                queue.append(v)

    if len(order) != len(comps):
        raise ValueError("component dependency graph contains a cycle")

    return order


def component_interface_coordinates(contract, cid):
    interfaces = interface_map(contract)
    comp = component_map(contract)[cid]

    coords = {}
    for iid in comp.get("interface_inputs", []) + \
               comp.get("interface_outputs", []):
        interface = interfaces[iid]
        for x in interface.get("coordinates", []):
            coords[x["name"]] = x

    return coords


def component_propagated_inputs(contract, cid):
    result = []
    for interface in contract["interfaces"]:
        for p in interface.get("propagated_variables", []):
            if p.get("destination_component") == cid:
                result.append(p)
    return result


def component_propagated_outputs(contract, cid):
    result = []
    for interface in contract["interfaces"]:
        for p in interface.get("propagated_variables", []):
            if p.get("source_component") == cid:
                result.append(p)
    return result


# ---------------------------------------------------------------------------
# Independent-point generation
# ---------------------------------------------------------------------------

def independent_points(contract, root, max_points=None):
    cfg = contract["independent_point_source"]
    kind = cfg["kind"]

    names = []
    vectors = []

    if kind == "explicit_grid":
        for name, spec in cfg["variables"].items():
            names.append(name)
            vectors.append(grid_values(spec))

    elif kind == "independent_regions_json":
        data = load_json(root / cfg["path"])
        domains = nested_domains(data)
        if not isinstance(domains, dict):
            raise RuntimeError(
                "could not locate domains in independent_regions.json"
            )

        for name, spec in cfg["variables"].items():
            d = domains[spec["domain"]]
            mode = spec["sampling"]

            if mode == "candidate_values":
                vals = [float(x) for x in d.get("candidate_values", [])]
                if not vals:
                    raise RuntimeError(
                        f"{spec['domain']}: candidate_values is empty"
                    )

            elif mode == "linear_from_domain":
                lo = float(
                    d.get(
                        "declared_effective_minimum",
                        d.get("technology_minimum"),
                    )
                )
                hi = float(
                    d.get(
                        "declared_effective_maximum",
                        d.get("technology_maximum"),
                    )
                )
                vals = [
                    float(x)
                    for x in np.linspace(lo, hi, int(spec["count"]))
                ]

            elif mode == "log_from_domain":
                lo = float(d["declared_effective_minimum"])
                hi = float(d["declared_effective_maximum"])
                vals = [
                    float(x)
                    for x in np.geomspace(lo, hi, int(spec["count"]))
                ]

            else:
                raise ValueError(
                    f"unsupported independent sampling mode: {mode}"
                )

            names.append(name)
            vectors.append(vals)

    else:
        raise ValueError(
            f"unsupported independent point source kind: {kind}"
        )

    rows = []
    for idx, values in enumerate(itertools.product(*vectors)):
        r = {"independent_point_index": idx}
        r.update(dict(zip(names, values)))
        rows.append(r)

        if max_points is not None and len(rows) >= max_points:
            break

    return rows


# ---------------------------------------------------------------------------
# Model inference
# ---------------------------------------------------------------------------

def load_component_model(root, comp):
    ck = torch.load(
        root / comp["model"]["checkpoint"],
        map_location="cpu",
        weights_only=False,
    )

    features = list(
        ck.get("feature_names", comp["model"].get("features", []))
    )
    hidden = tuple(ck.get("hidden", [64, 64]))
    kind = comp["model"]["kind"]

    if kind == "binary_feasibility_classifier":
        model = BinaryMLP(len(features), hidden)
    elif kind == "feasibility_range_emitter":
        model = RangeEmitterMLP(len(features), hidden)
    else:
        raise ValueError(
            f"component {comp['id']}: unsupported model kind {kind}"
        )

    model.load_state_dict(ck["state_dict"])
    model.eval()

    return {
        "kind": kind,
        "model": model,
        "features": features,
        "mean": torch.tensor(
            np.asarray(ck["mean"], dtype=np.float32)
        ),
        "std": torch.tensor(
            np.asarray(ck["std"], dtype=np.float32)
        ),
        "threshold": float(ck["threshold"]),
        "checkpoint": str(root / comp["model"]["checkpoint"]),
    }


def predict_component(model_info, rows):
    if not rows:
        return np.zeros(0, dtype=bool), np.zeros(0), None

    X = torch.tensor(
        [
            [float(r[f]) for f in model_info["features"]]
            for r in rows
        ],
        dtype=torch.float32,
    )

    with torch.inference_mode():
        xn = (X - model_info["mean"]) / model_info["std"]

        if model_info["kind"] == "binary_feasibility_classifier":
            p = torch.sigmoid(
                model_info["model"](xn)
            ).cpu().numpy()
            return p >= model_info["threshold"], p, None

        logits, ranges = model_info["model"](xn)
        p = torch.sigmoid(logits).cpu().numpy()
        return (
            p >= model_info["threshold"],
            p,
            ranges.cpu().numpy(),
        )


# ---------------------------------------------------------------------------
# Candidate-space construction
# ---------------------------------------------------------------------------

def static_component_rows(contract, cid, seeds):
    """
    Build rows for a component whose MLP inputs are fully defined by:
      * independent design variables
      * discrete interface coordinates
      * local search coordinates

    Propagated exact values from an upstream realization are intentionally not
    included here; those components are evaluated dynamically after upstream
    exact realization.
    """
    comp = component_map(contract)[cid]

    if component_propagated_inputs(contract, cid):
        return None

    coords = component_interface_coordinates(contract, cid)
    coord_names = list(coords.keys())
    coord_vectors = [grid_values(coords[k]) for k in coord_names]

    local = comp.get("local_search_coordinates", [])
    local_names = [x["name"] for x in local]
    local_vectors = [grid_values(x) for x in local]

    vectors = coord_vectors + local_vectors
    names = coord_names + local_names

    product = list(itertools.product(*vectors)) if vectors else [()]

    rows = []
    for seed in seeds:
        for vals in product:
            r = dict(seed)
            r.update(dict(zip(names, vals)))
            rows.append(r)

    return rows


def row_interface_signature(contract, cid, row):
    coords = component_interface_coordinates(contract, cid)
    return tuple(
        (name, q(row[name]))
        for name in sorted(coords)
        if name in row
    )


def row_seed(row):
    return int(float(row["independent_point_index"]))


def compatible_static_rows(contract, static_positive_by_component):
    """
    Compute discrete compatibility among static components.

    A candidate row survives if, for every interface it participates in,
    there exists at least one positive row on the neighboring component with
    identical values for all shared discrete interface coordinates.

    This works for A--B--C chains and general acyclic shared-coordinate graphs.
    """
    comps = component_map(contract)

    survivors = {
        cid: list(rows)
        for cid, rows in static_positive_by_component.items()
    }

    changed = True
    while changed:
        changed = False

        for interface in contract["interfaces"]:
            left, right = interface["between"]
            if left not in survivors or right not in survivors:
                continue

            coord_names = [
                x["name"] for x in interface.get("coordinates", [])
            ]
            if not coord_names:
                continue

            left_keys = defaultdict(set)
            right_keys = defaultdict(set)

            for r in survivors[left]:
                key = (
                    row_seed(r),
                    tuple(q(r[n]) for n in coord_names),
                )
                left_keys[row_seed(r)].add(key[1])

            for r in survivors[right]:
                key = (
                    row_seed(r),
                    tuple(q(r[n]) for n in coord_names),
                )
                right_keys[row_seed(r)].add(key[1])

            new_left = []
            for r in survivors[left]:
                sig = tuple(q(r[n]) for n in coord_names)
                if sig in right_keys[row_seed(r)]:
                    new_left.append(r)

            new_right = []
            for r in survivors[right]:
                sig = tuple(q(r[n]) for n in coord_names)
                if sig in left_keys[row_seed(r)]:
                    new_right.append(r)

            if len(new_left) != len(survivors[left]):
                changed = True
                survivors[left] = new_left

            if len(new_right) != len(survivors[right]):
                changed = True
                survivors[right] = new_right

    return survivors


# ---------------------------------------------------------------------------
# Parallel exact realization
# ---------------------------------------------------------------------------

def split_rows(rows, workers):
    if not rows:
        return []
    n = max(1, min(int(workers), len(rows)))
    buckets = [[] for _ in range(n)]
    for i, r in enumerate(rows):
        buckets[i % n].append(r)
    return [x for x in buckets if x]


def prepare_realizer_job(root, comp, rows, shard_dir, sid):
    rr = comp["exact_realizer"]
    module = load_module(root / rr["module"])
    builder = getattr(module, rr["builder_function"])
    base_plan = module.read_yaml(root / rr["base_plan"])

    local_rows = []
    for i, r in enumerate(rows):
        x = dict(r)
        x["global_point_index"] = r["point_index"]
        x["point_index"] = i
        local_rows.append(x)

    cov = shard_dir / "coverage.csv"
    out = shard_dir / "exact.csv"
    plan = shard_dir / "plan.yaml"

    write_csv(cov, local_rows)

    plan_data = builder(
        base_plan,
        cov,
        out,
        int(rr["witnesses_per_state"]),
    )
    module.write_yaml(plan, plan_data)

    cmd = [
        sys.executable,
        str(root / "tools/validation/witness_engine.py"),
        "--plan",
        str(plan),
        "--root",
        str(root),
        "--witnesses-per-point",
        str(rr["witnesses_per_state"]),
    ]

    return sid, cmd, out, local_rows, shard_dir


def execute_realizer_job(root, job):
    sid, cmd, out, local_rows, shard_dir = job

    env = os.environ.copy()
    env.update({
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "BLIS_NUM_THREADS": "1",
    })

    with (shard_dir / "engine.log").open("w") as stream:
        subprocess.run(
            cmd,
            cwd=root,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
            env=env,
        )

    exact = [
        r for r in read_csv(out)
        if r.get("generation_status") == "WITNESS"
        and r.get("witness_rank") not in (None, "")
    ]

    by_local = {
        int(float(r["point_index"])): r for r in local_rows
    }

    merged = []
    for r in exact:
        local_pi = int(float(r["point_index"]))
        src = by_local[local_pi]
        x = dict(r)
        x["point_index"] = int(float(src["global_point_index"]))
        merged.append(x)

    return sid, merged


def exact_realize(root, comp, coverage_rows, work_dir, workers):
    if not coverage_rows:
        return []

    chunks = split_rows(coverage_rows, workers)
    base = work_dir / f"{comp['id']}_parallel"
    base.mkdir(parents=True, exist_ok=True)

    print(
        f"RUN exact realizer {comp['id']}: "
        f"coverage_rows={len(coverage_rows)} "
        f"workers={len(chunks)}",
        flush=True,
    )

    jobs = []
    for sid, rows in enumerate(chunks):
        shard_dir = base / f"shard_{sid:02d}"
        shard_dir.mkdir(parents=True, exist_ok=True)
        jobs.append(
            prepare_realizer_job(
                root, comp, rows, shard_dir, sid
            )
        )

    got = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [
            pool.submit(execute_realizer_job, root, job)
            for job in jobs
        ]

        done = 0
        for future in as_completed(futures):
            sid, rows = future.result()
            done += 1
            print(
                f"  {comp['id']} shard {sid:02d} done "
                f"witnesses={len(rows)} "
                f"[{done}/{len(jobs)}]",
                flush=True,
            )
            got.append((sid, rows))

    got.sort(key=lambda x: x[0])
    return [r for _, rows in got for r in rows]


def enrich_exact_rows(exact_rows, coverage_rows, comp):
    by_point = {
        int(float(r["point_index"])): r
        for r in coverage_rows
    }

    out = []
    for r in exact_rows:
        pi = int(float(r["point_index"]))
        x = dict(by_point[pi])
        x.update(r)

        env = {}
        for k, v in x.items():
            try:
                env[k] = float(v)
            except (TypeError, ValueError):
                env[k] = v

        for d in comp.get("derived_after_realization", []):
            value = float(safe_eval(d["expression"], env))
            x[d["name"]] = value
            env[d["name"]] = value

        out.append(x)

    return out


# ---------------------------------------------------------------------------
# Dynamic downstream components (propagated exact inputs)
# ---------------------------------------------------------------------------

def build_dynamic_component_rows(
    contract,
    cid,
    upstream_exact,
):
    comp = component_map(contract)[cid]
    propagated = component_propagated_inputs(contract, cid)

    if not propagated:
        raise ValueError(
            f"component {cid} has no propagated inputs"
        )

    # One or more local search coordinates can still be declared.
    local = comp.get("local_search_coordinates", [])
    local_names = [x["name"] for x in local]
    local_vectors = [grid_values(x) for x in local]
    local_product = (
        list(itertools.product(*local_vectors))
        if local_vectors else [()]
    )

    rows = []

    for upstream_cid, exact_rows in upstream_exact.items():
        relevant = [
            p for p in propagated
            if p["source_component"] == upstream_cid
        ]
        if not relevant:
            continue

        for src in exact_rows:
            base = {
                "independent_point_index":
                    int(float(src["independent_point_index"])),
                "source_component": upstream_cid,
                "source_point_index":
                    int(float(src["point_index"])),
                "source_witness_rank":
                    int(float(src["witness_rank"])),
            }

            # Preserve every upstream field because exact realizer adapters may
            # need lineage/auxiliary quantities beyond the MLP features.
            for k, v in src.items():
                if k not in base:
                    base[k] = v

            for p in relevant:
                name = p["name"]
                base[name] = float(src[name])

            for vals in local_product:
                r = dict(base)
                r.update(dict(zip(local_names, vals)))

                # Contract-declared aliases required by an exact-realizer
                # builder.  This stays generic: the engine does not know
                # what the aliases mean.
                bindings = comp.get(
                    "exact_realizer", {}
                ).get("coverage_bindings", {})
                if bindings:
                    env = {}
                    for k, v in r.items():
                        try:
                            env[k] = float(v)
                        except (TypeError, ValueError):
                            env[k] = v
                    for out_name, expr in bindings.items():
                        r[out_name] = safe_eval(expr, env)
                        env[out_name] = r[out_name]

                rows.append(r)

    return rows


# ---------------------------------------------------------------------------
# Exact-state compatibility / joining
# ---------------------------------------------------------------------------

def component_exact_key(contract, cid, row):
    """
    Key a realized component state by independent point and all shared discrete
    interface coordinates it participates in.
    """
    coords = component_interface_coordinates(contract, cid)
    return (
        int(float(row["independent_point_index"])),
        tuple(
            (name, q(row[name]))
            for name in sorted(coords)
            if name in row
        ),
    )


def interface_match(interface, left_row, right_row):
    for x in interface.get("coordinates", []):
        name = x["name"]
        if name in left_row and name in right_row:
            if q(left_row[name]) != q(right_row[name]):
                return False

    for p in interface.get("propagated_variables", []):
        name = p["name"]
        # Exact propagated values must match when both sides carry them.
        if name in left_row and name in right_row:
            if q(left_row[name]) != q(right_row[name]):
                return False

    return True


def combine_component_realizations(contract, exact_by_component):
    """
    Generic incremental join over exact component realizations.
    """
    order = topological_order(contract)
    interfaces = contract["interfaces"]

    partials = [
        {order[0]: r}
        for r in exact_by_component.get(order[0], [])
    ]

    for cid in order[1:]:
        candidates = exact_by_component.get(cid, [])
        new_partials = []

        # Generic scalability optimization:
        # candidates from different independent design points can never join.
        # Index once by independent_point_index instead of repeatedly scanning
        # the entire downstream witness population.
        candidates_by_seed = defaultdict(list)

        for row in candidates:
            seed = int(float(row["independent_point_index"]))
            candidates_by_seed[seed].append(row)

        for partial in partials:
            existing_seed = next(
                int(float(r["independent_point_index"]))
                for r in partial.values()
            )

            for row in candidates_by_seed.get(existing_seed, []):
                ok = True

                for interface in interfaces:
                    left, right = interface["between"]

                    if cid == left and right in partial:
                        if not interface_match(
                            interface, row, partial[right]
                        ):
                            ok = False
                            break

                    elif cid == right and left in partial:
                        if not interface_match(
                            interface, partial[left], row
                        ):
                            ok = False
                            break

                if ok:
                    x = dict(partial)
                    x[cid] = row
                    new_partials.append(x)

        partials = new_partials

        if not partials:
            break

    return partials


# ---------------------------------------------------------------------------
# Final witness canonicalization
# ---------------------------------------------------------------------------

def canonicalize(contract, component_rows):
    env = {}
    raw = {}

    # Stable prefixes use C0_, C1_, ... so final_witness expressions are
    # generic and independent of component names. For backward compatibility,
    # also expose A_, B_, C_ for the first three components.
    order = topological_order(contract)
    legacy_prefixes = ["A", "B", "C"]

    for idx, cid in enumerate(order):
        row = component_rows[cid]
        prefixes = [f"C{idx}"]
        if idx < len(legacy_prefixes):
            prefixes.append(legacy_prefixes[idx])

        for prefix in prefixes:
            for k, v in row.items():
                key = f"{prefix}_{k}"
                raw[key] = v
                try:
                    env[key] = float(v)
                except (TypeError, ValueError):
                    env[key] = v

    first = component_rows[order[0]]
    out = {
        "independent_point_index":
            int(float(first["independent_point_index"]))
    }

    for name, expr in \
            contract["final_witness"]["canonical_fields"].items():
        out[name] = safe_eval(expr, env)

    out["all_saturated"] = int(
        all(
            str(r.get("all_saturated", "0"))
            in ("1", "1.0", "True", "true")
            for r in component_rows.values()
        )
    )
    out["exact_device_pass"] = 1
    out["witness_status"] = "VALID_EXACT_COMPONENT_JOIN"

    out.update(raw)
    return out


def deduplicate(contract, rows):
    keys = contract["final_witness"].get("deduplicate_on", [])
    if not keys:
        return rows

    seen = set()
    out = []

    for r in rows:
        sig = tuple(q(r[k]) for k in keys)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)

    return out


# ---------------------------------------------------------------------------
# Main generic execution
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--work-dir",
        type=Path,
        default=Path("runtime/hierarchical_step5_generic"),
    )
    ap.add_argument("--max-points", type=int)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    if args.workers < 1:
        raise ValueError("--workers must be >=1")

    torch.set_num_threads(1)

    root = args.root.resolve()
    contract_path = (
        args.contract
        if args.contract.is_absolute()
        else root / args.contract
    )
    contract = load_json(contract_path)

    output = (
        args.output
        if args.output.is_absolute()
        else root / args.output
    )
    work = (
        args.work_dir
        if args.work_dir.is_absolute()
        else root / args.work_dir
    )
    work.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()

    comps = component_map(contract)
    order = topological_order(contract)
    seeds = independent_points(
        contract, root, args.max_points
    )

    print("===== GENERIC HIERARCHICAL STEP 5 =====")
    print("components          :", len(order))
    print("component order     :", " -> ".join(order))
    print("independent points  :", len(seeds))
    print("parallel workers    :", args.workers)

    # ------------------------------------------------------------------
    # Phase 1: evaluate all static components.
    # ------------------------------------------------------------------
    static_positive = {}
    models = {}

    for cid in order:
        comp = comps[cid]
        models[cid] = load_component_model(root, comp)

        rows = static_component_rows(contract, cid, seeds)
        if rows is None:
            continue

        mask, probs, ranges = predict_component(
            models[cid], rows
        )

        positive = []
        for idx, (r, keep) in enumerate(zip(rows, mask)):
            if not keep:
                continue

            x = dict(r)
            x["mlp_probability"] = float(probs[idx])

            if ranges is not None:
                emitted = comp["model"].get(
                    "emitted_ranges", []
                )
                for j, spec in enumerate(emitted):
                    lo = float(ranges[idx, 2*j])
                    hi = float(ranges[idx, 2*j+1])

                    if spec.get("transform") == "exp":
                        lo = float(np.exp(lo))
                        hi = float(np.exp(hi))

                    x[spec["name"] + "_pred_min"] = min(lo, hi)
                    x[spec["name"] + "_pred_max"] = max(lo, hi)

            positive.append(x)

        static_positive[cid] = positive

        print(
            f"{cid}: MLP evaluations={len(rows)} "
            f"positive={len(positive)} "
            f"({100*len(positive)/max(len(rows),1):.3f}%)"
        )

    # Prune mutually incompatible shared-coordinate static states.
    static_positive = compatible_static_rows(
        contract, static_positive
    )

    print("\nstatic compatibility after interface intersection:")
    for cid in order:
        if cid in static_positive:
            print(
                f"  {cid}: {len(static_positive[cid])}"
            )

    # ------------------------------------------------------------------
    # Phase 2: exact-realize static components.
    # ------------------------------------------------------------------
    exact_by_component = {}

    for cid in order:
        if cid not in static_positive:
            continue

        rows = static_positive[cid]

        # Deduplicate identical exact-realizer inputs.
        unique = []
        seen = set()
        comp = comps[cid]
        relevant_names = (
            ["independent_point_index"]
            + list(component_interface_coordinates(
                contract, cid
            ).keys())
            + [
                x["name"]
                for x in comp.get(
                    "local_search_coordinates", []
                )
            ]
        )

        # Preserve all MLP feature inputs as well.
        relevant_names += models[cid]["features"]

        for r in rows:
            sig = tuple(
                (name, q(r[name]))
                for name in sorted(set(relevant_names))
                if name in r
            )
            if sig in seen:
                continue
            seen.add(sig)

            x = dict(r)
            x["point_index"] = len(unique)
            unique.append(x)

        exact_raw = exact_realize(
            root, comp, unique, work, args.workers
        )
        exact = enrich_exact_rows(
            exact_raw, unique, comp
        )
        exact_by_component[cid] = exact

        print(
            f"{cid}: exact witnesses={len(exact)}"
        )

    # ------------------------------------------------------------------
    # Phase 3: dynamically evaluate components needing propagated exact
    # upstream values.
    # ------------------------------------------------------------------
    for cid in order:
        if cid in exact_by_component:
            continue

        comp = comps[cid]
        rows = build_dynamic_component_rows(
            contract, cid, exact_by_component
        )

        mask, probs, _ = predict_component(
            models[cid], rows
        )

        positive = [
            dict(r, mlp_probability=float(p))
            for r, p, keep in zip(rows, probs, mask)
            if keep
        ]

        for i, r in enumerate(positive):
            r["point_index"] = i

        print(
            f"{cid}: dynamic MLP evaluations={len(rows)} "
            f"positive={len(positive)} "
            f"({100*len(positive)/max(len(rows),1):.3f}%)"
        )

        exact_raw = exact_realize(
            root, comp, positive, work, args.workers
        )
        exact = enrich_exact_rows(
            exact_raw, positive, comp
        )
        exact_by_component[cid] = exact

        print(
            f"{cid}: exact witnesses={len(exact)}"
        )

    # ------------------------------------------------------------------
    # Phase 4: generic exact join.
    # ------------------------------------------------------------------
    partials = combine_component_realizations(
        contract, exact_by_component
    )

    print("exact joined component tuples:", len(partials))

    final_rows = [
        canonicalize(contract, p)
        for p in partials
    ]
    final_rows = deduplicate(
        contract, final_rows
    )

    by_seed = defaultdict(list)
    for r in final_rows:
        by_seed[int(r["independent_point_index"])].append(r)

    ranked = []
    for seed_idx in sorted(by_seed):
        for rank, r in enumerate(by_seed[seed_idx], 1):
            r["witness_rank"] = rank
            ranked.append(r)

    write_csv(output, ranked)

    wall = time.perf_counter() - t0

    print("\n===== GENERIC STEP-5 RESULT =====")
    print("components                :", len(order))
    print("independent points        :", len(seeds))
    print("points with >=1 witness   :", len(by_seed))
    print(
        "coverage                  :",
        f"{100*len(by_seed)/max(len(seeds),1):.2f}%"
    )
    print("final exact witnesses     :", len(ranked))
    print("wall seconds              :", f"{wall:.3f}")
    print("output                    :", output)


if __name__ == "__main__":
    raise SystemExit(main())

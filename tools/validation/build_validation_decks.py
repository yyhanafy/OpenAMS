#!/usr/bin/env python3
"""Build traceable ngspice validation decks from a frozen OpenAMS benchmark.

This stage does not run ngspice. It:
- reads selected_points.csv,
- resolves matching records from constructed_assignments.jsonl,
- renders the canonical two-stage-opamp deck template,
- injects a deterministic .op/.ac control block,
- writes one self-contained directory per selected grid point,
- records source hashes and rendering conventions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openams.validation.generic_ngspice_ac import (
    ValidationError,
    metadata_template_values,
    render_template,
)

SCHEMA_VERSION = "1.0"


def inject_validation_control_block(
    deck: str,
    *,
    ac_start_hz: float,
    ac_stop_hz: float,
    points_per_decade: int,
    hierarchy_prefix: str,
) -> str:
    """Append the verified SKY130/ngspice hierarchy-aware control block."""
    # Remove a terminal .end so the control block can be inserted before it.
    lines = deck.rstrip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip().lower() == ".end":
        lines.pop()

    hp = hierarchy_prefix.lower()
    models = {
        1: "nfet",
        2: "nfet",
        3: "pfet",
        4: "pfet",
        5: "nfet",
        6: "pfet",
        7: "nfet",
    }

    control = [
        "",
        "* OPENAMS_GENERIC_VALIDATION_CONTROL",
        ".control",
        "set noaskquit",
        "set filetype=ascii",
        "op",
        "echo OPENAMS_OP_BEGIN",
        f"print v({hp}.ntail) v({hp}.n1) v({hp}.n2) v(vbias) v(out)",
        "print vdd_src#branch vss_src#branch vbias_src#branch",
        "echo OPENAMS_OP_END",
        "echo OPENAMS_DEVICE_BEGIN",
    ]

    for index, polarity in models.items():
        model = f"sky130_fd_pr__{polarity}_01v8"
        base = f"@m.{hp}.xm{index}.m{model}"
        control.append(
            "print "
            + " ".join(
                f"{base}[{field}]"
                for field in ("id", "gm", "gds", "vds", "vdsat")
            )
        )

    control.extend(
        [
            "echo OPENAMS_DEVICE_END",
            f"ac dec {points_per_decade} {ac_start_hz:.17g} {ac_stop_hz:.17g}",
            "wrdata openams_ac.dat frequency vdb(out) vp(out)",
            "quit",
            ".endc",
            ".end",
            "",
        ]
    )
    return "\n".join(lines + control)
DEVICES = tuple(f"M{i}" for i in range(1, 8))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build ngspice validation decks for selected frozen benchmark points."
    )
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--deck-template",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs/deck_template.spice"),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs"),
    )
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=Path("examples/two_stage_opamp/generated/compiled_circuit_model.json"),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ac-start-hz", type=float, default=1.0)
    parser.add_argument("--ac-stop-hz", type=float, default=1.0e10)
    parser.add_argument("--points-per-decade", type=int, default=100)
    parser.add_argument(
        "--hierarchy-prefix",
        default="xu1",
        help="Hierarchy prefix used by ngspice device show commands (default: xu1).",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_selected(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValidationError(f"selection contains no rows: {path}")
    required = {"grid_index", "status"}
    missing = required - set(rows[0])
    if missing:
        raise ValidationError(f"selection missing columns: {sorted(missing)}")
    if any(row["status"] != "PASS" for row in rows):
        raise ValidationError("selection contains non-PASS benchmark rows")
    return rows


def load_assignment_records(path: Path, wanted: set[int]) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            grid_index = int(payload["grid_index"])
            if grid_index not in wanted:
                continue
            if grid_index in records:
                raise ValidationError(
                    f"duplicate grid_index {grid_index} in {path} at line {line_number}"
                )
            records[grid_index] = payload
    missing = sorted(wanted - set(records))
    if missing:
        raise ValidationError(
            "constructed assignment records missing selected grid indices: "
            + ", ".join(map(str, missing[:20]))
        )
    return records


def finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise ValidationError(f"{name} must be finite: {value!r}")
    return result


def assignment_values(
    record: Mapping[str, Any],
    selected_row: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assignment = dict(record["assignment"])
    values: dict[str, Any] = {**selected_row, **assignment}
    conventions: dict[str, Any] = {
        "width_semantics": "total_device_width_um",
        "finger_count_policy": "use explicit nf_mN if present; otherwise nf=1",
        "length_policy": "use device-point length_um",
    }

    aliases = {
        "vdd": "vdd_v",
        "vss": "vss_v",
        "vin_cm": "vin_cm_v",
        "vbias": "vbias_v",
        "vout": "vout_v",
        "vtail": "vtail_v",
        "n1": "n1_v",
        "n2": "n2_v",
    }
    for alias, source in aliases.items():
        values[alias] = assignment[source]

    points = assignment.get("device_points", {})
    for index, device in enumerate(DEVICES, start=1):
        point = points.get(device)
        if not isinstance(point, Mapping):
            raise ValidationError(f"assignment missing device point {device}")

        width_um = finite(point["width_um"], f"{device}.width_um")
        length_um = finite(point["length_um"], f"{device}.length_um")
        nf_key = f"nf_m{index}"
        nf = int(round(finite(selected_row.get(nf_key, 1), nf_key)))
        if nf <= 0:
            raise ValidationError(f"{nf_key} must be positive")

        # Cover all placeholder conventions currently used in OpenAMS templates.
        values.update(
            {
                f"w_m{index}": width_um,
                f"w_m{index}_um": width_um,
                f"m{index}_w_um": width_um,
                f"l_m{index}": length_um,
                f"l_m{index}_um": length_um,
                f"m{index}_l_um": length_um,
                nf_key: nf,
                f"m{index}_nf": nf,
            }
        )

    # Legacy template aliases.
    values.update(
        {
            "w_input": values["w_m1_um"],
            "w_load": values["w_m3_um"],
            "w_tail": values["w_m5_um"],
            "w_stage2": values["w_m6_um"],
            "w_sink": values["w_m7_um"],
            "l_default": finite(points["M1"]["length_um"], "M1.length_um") * 1e-6,
            "l_default_um": finite(points["M1"]["length_um"], "M1.length_um"),
        }
    )
    return values, conventions


def main() -> int:
    args = parse_args()
    repo_root = Path.cwd().resolve()
    benchmark = args.benchmark.resolve()
    selection = args.selection.resolve()
    output = args.output.resolve()
    deck_template = args.deck_template.resolve()
    input_dir = args.input_dir.resolve()
    compiled_model = args.compiled_model.resolve()
    assignments_path = benchmark / "constructed_assignments.jsonl"

    for path, label in (
        (benchmark, "benchmark directory"),
        (selection, "selection CSV"),
        (deck_template, "deck template"),
        (input_dir, "input directory"),
        (compiled_model, "compiled circuit model"),
        (assignments_path, "constructed assignments"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"missing {label}: {path}")

    if args.limit is not None and args.limit <= 0:
        raise ValidationError("--limit must be positive")
    if args.ac_start_hz <= 0 or args.ac_stop_hz <= args.ac_start_hz:
        raise ValidationError("invalid AC frequency range")
    if args.points_per_decade <= 0:
        raise ValidationError("--points-per-decade must be positive")

    selected = load_selected(selection)
    selected.sort(key=lambda row: int(row.get("selection_order", row["grid_index"])))
    if args.limit is not None:
        selected = selected[: args.limit]

    wanted = {int(row["grid_index"]) for row in selected}
    records = load_assignment_records(assignments_path, wanted)

    if output.exists():
        if not args.overwrite:
            raise FileExistsError(
                f"output already exists: {output}; use a new directory or --overwrite"
            )
        shutil.rmtree(output)
    output.mkdir(parents=True)

    model = json.loads(compiled_model.read_text(encoding="utf-8"))
    static_values = metadata_template_values(
        repo_root=repo_root,
        input_dir=input_dir,
        model=model,
    )
    template_text = deck_template.read_text(encoding="utf-8")

    manifest_points: list[dict[str, Any]] = []
    for order, selected_row in enumerate(selected):
        grid_index = int(selected_row["grid_index"])
        record = records[grid_index]
        assignment_id = str(record["assignment_id"])
        case_name = f"point_{grid_index:06d}"
        case_dir = output / case_name
        case_dir.mkdir()

        dynamic_values, conventions = assignment_values(record, selected_row)
        values = {**static_values, **dynamic_values}
        deck = render_template(template_text, values)
        deck = inject_validation_control_block(
            deck,
            ac_start_hz=args.ac_start_hz,
            ac_stop_hz=args.ac_stop_hz,
            points_per_decade=args.points_per_decade,
            hierarchy_prefix=args.hierarchy_prefix,
        )

        deck_path = case_dir / "deck.spice"
        assignment_path = case_dir / "assignment.json"
        provenance_path = case_dir / "provenance.json"
        deck_path.write_text(deck, encoding="utf-8")
        assignment_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        provenance = {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "selection_order": order,
            "selection_reasons": selected_row.get("selection_reasons", ""),
            "grid_index": grid_index,
            "assignment_id": assignment_id,
            "benchmark_directory": str(benchmark),
            "benchmark_assignments_sha256": sha256_file(assignments_path),
            "selection_csv": str(selection),
            "selection_csv_sha256": sha256_file(selection),
            "deck_template": str(deck_template),
            "deck_template_sha256": sha256_file(deck_template),
            "compiled_model": str(compiled_model),
            "compiled_model_sha256": sha256_file(compiled_model),
            "rendering_conventions": conventions,
            "ac_analysis": {
                "start_hz": args.ac_start_hz,
                "stop_hz": args.ac_stop_hz,
                "points_per_decade": args.points_per_decade,
                "hierarchy_prefix": args.hierarchy_prefix,
            },
            "artifacts": {
                "deck": "deck.spice",
                "assignment": "assignment.json",
                "deck_sha256": sha256_file(deck_path),
                "assignment_sha256": sha256_file(assignment_path),
            },
        }
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_points.append(
            {
                "selection_order": order,
                "grid_index": grid_index,
                "assignment_id": assignment_id,
                "case_directory": case_name,
                "selection_reasons": selected_row.get("selection_reasons", ""),
                "deck_sha256": provenance["artifacts"]["deck_sha256"],
            }
        )

    manifest = {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark": str(benchmark),
        "selection": str(selection),
        "deck_template": str(deck_template),
        "point_count": len(manifest_points),
        "points": manifest_points,
    }
    manifest_path = output / "deck_build_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("===== OPENAMS NGSPICE VALIDATION DECK BUILD =====")
    print(f"selected points: {len(selected)}")
    print(f"decks built:     {len(manifest_points)}")
    print(f"output:          {output}")
    print(f"manifest:        {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
OpenAMS folded-cascode native-witness ngspice validation.

Input:
  folded_cascode_design_space_witnesses.jsonl

The witnesses are emitted natively by ordered_dc_propagation from the same
correlated states that caused each independent point to PASS.

Flow:
  witness JSONL
    -> select representative witnesses over (W1, I3)
    -> render one folded-cascode deck per witness
    -> ngspice .op + .ac
    -> DC: scalar witness vs ngspice
    -> AC: ngspice-only characterization

No midpointing, no Step-5 recovery, and no second technology search.

The source folded_cascode.spice is not modified.  The validation copy uses
the SKY130 wrapper geometry convention established by the project:
  W and L are numeric micrometer values (for example w=1, l=0.5).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

# Scalar witness nodes we can print directly from ngspice.
NODE_EXPR = {
    "vdd_v": "v(vdd)",
    "vss_v": "v(vss)",
    "vip_v": "v(vip)",
    "vin_v": "v(vin)",
    "tail_v": "v(xota.tail)",
    "psrc_left_v": "v(xota.psrc_left)",
    "psrc_right_v": "v(xota.psrc_right)",
    "x_v": "v(xota.x)",
    "nsink_left_v": "v(xota.nsink_left)",
    "nsink_right_v": "v(xota.nsink_right)",
    "vnb1_node_v": "v(xota.vnb1_node)",
    "vpb1_node_v": "v(xota.vpb1_node)",
    "vnb2_node_v": "v(xota.vnb2_node)",
    "vpb2_node_v": "v(xota.vpb2_node)",
    "vout_v": "v(vout)",
}

# Exact terminal mapping of the flat folded-cascode topology.
DEVICE_TERMINALS = {
    "M1": ("psrc_left_v", "vip_v", "tail_v", "vss_v", "nmos"),
    "M2": ("psrc_right_v", "vin_v", "tail_v", "vss_v", "nmos"),
    "M3": ("tail_v", "vnb1_node_v", "vss_v", "vss_v", "nmos"),
    "M4": ("psrc_left_v", "vpb1_node_v", "vdd_v", "vdd_v", "pmos"),
    "M5": ("psrc_right_v", "vpb1_node_v", "vdd_v", "vdd_v", "pmos"),
    "M6": ("x_v", "vpb2_node_v", "psrc_left_v", "vdd_v", "pmos"),
    "M7": ("vout_v", "vpb2_node_v", "psrc_right_v", "vdd_v", "pmos"),
    "M8": ("x_v", "vnb2_node_v", "nsink_left_v", "vss_v", "nmos"),
    "M9": ("vout_v", "vnb2_node_v", "nsink_right_v", "vss_v", "nmos"),
    "M10": ("nsink_left_v", "x_v", "vss_v", "vss_v", "nmos"),
    "M11": ("nsink_right_v", "x_v", "vss_v", "vss_v", "nmos"),
}

GROUP_FOR_DEVICE = {
    "M1": "M1_M2", "M2": "M1_M2",
    "M3": "M3",
    "M4": "M4_M5", "M5": "M4_M5",
    "M6": "M6_M7", "M7": "M6_M7",
    "M8": "M8_M9", "M9": "M8_M9",
    "M10": "M10_M11", "M11": "M10_M11",
}


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
        "--source-spice",
        type=Path,
        default=root / "examples/folded_cascode/inputs/folded_cascode.spice",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=root / "validation/ngspice/folded_cascode_native_100",
    )
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--ngspice", default="ngspice")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ac-start-hz", type=float, default=1.0)
    p.add_argument("--ac-stop-hz", type=float, default=1e10)
    p.add_argument("--ac-points-per-decade", type=int, default=100)
    p.add_argument("--node-tolerance-v", type=float, default=0.025)
    p.add_argument("--device-voltage-tolerance-v", type=float, default=0.025)
    p.add_argument("--current-relative-tolerance", type=float, default=0.10)
    p.add_argument("--current-absolute-tolerance-a", type=float, default=1e-6)
    p.add_argument("--vdsat-tolerance-v", type=float, default=0.05)
    return p.parse_args()


def fnum(v: Any, name: str = "value") -> float:
    try:
        x = float(v)
    except Exception as exc:
        raise ValueError(f"{name}: non-numeric {v!r}") from exc
    if not math.isfinite(x):
        raise ValueError(f"{name}: non-finite {v!r}")
    return x


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{lineno}: expected JSON object")
        if str(obj.get("status", "")).upper() != "PASS":
            continue
        rows.append(obj)
    if not rows:
        raise SystemExit(f"No PASS witnesses found in {path}")
    return rows


def select_space_filling(
    witnesses: list[dict[str, Any]],
    count: int,
    seed: int,
) -> list[dict[str, Any]]:
    if count >= len(witnesses):
        return list(witnesses)

    X = np.asarray(
        [
            [fnum(w["w_m1_um"]), fnum(w["i_m3_a"])]
            for w in witnesses
        ],
        dtype=float,
    )
    mins = X.min(axis=0)
    spans = X.max(axis=0) - mins
    spans[spans == 0.0] = 1.0
    Z = (X - mins) / spans

    chosen: set[int] = set()
    for j in range(Z.shape[1]):
        chosen.add(int(np.argmin(Z[:, j])))
        chosen.add(int(np.argmax(Z[:, j])))

    for corner in (
        np.array([0.0, 0.0]),
        np.array([0.0, 1.0]),
        np.array([1.0, 0.0]),
        np.array([1.0, 1.0]),
    ):
        chosen.add(int(np.argmin(np.linalg.norm(Z - corner, axis=1))))

    selected = sorted(chosen)
    min_dist = np.full(len(witnesses), np.inf)
    for idx in selected:
        min_dist = np.minimum(min_dist, np.linalg.norm(Z - Z[idx], axis=1))
    min_dist[selected] = -1.0

    rng = np.random.default_rng(seed)
    jitter = rng.random(len(witnesses)) * 1e-12

    while len(selected) < count:
        nxt = int(np.argmax(min_dist + jitter))
        selected.append(nxt)
        min_dist = np.minimum(min_dist, np.linalg.norm(Z - Z[nxt], axis=1))
        min_dist[selected] = -1.0

    selected = sorted(selected[:count])
    return [witnesses[i] for i in selected]


def find_sky130_lib() -> Path:
    candidates: list[Path] = []
    env = os.environ.get("SKY130_LIB")
    if env:
        candidates.append(Path(os.path.expanduser(os.path.expandvars(env))))

    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        root = Path(os.path.expanduser(os.path.expandvars(pdk_root)))
        candidates += [
            root / "sky130/sky130A/libs.tech/ngspice/sky130.lib.spice",
            root / "sky130A/libs.tech/ngspice/sky130.lib.spice",
        ]

    candidates.append(
        Path.home()
        / "pdks/open_pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice"
    )

    for p in candidates:
        if p.is_file():
            return p.resolve()

    raise SystemExit(
        "Could not locate sky130.lib.spice. Set SKY130_LIB, for example:\n"
        'export SKY130_LIB="$HOME/pdks/open_pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice"'
    )


def render_source_spice(source: str, witness: dict[str, Any]) -> str:
    widths = witness["widths_um"]
    nf = witness["nf"]
    biases = witness["biases_v"]

    external = {
        "w_m1_um": widths["M1"],
        "i_m3_a": witness["i_m3_a"],
        "vnb1_v": biases["vnb1_v"],
        "vpb1_v": biases["vpb1_v"],
        "vpb2_v": biases["vpb2_v"],
        "vnb2_v": biases["vnb2_v"],
        "w_m3_um": widths["M3"],
        "w_m4_um": widths["M4"],
        "w_m6_um": widths["M6"],
        "w_m8_um": widths["M8"],
        "nf_m1": nf["M1"],
        "nf_m3": nf["M3"],
        "nf_m4": nf["M4"],
        "nf_m6": nf["M6"],
        "nf_m8": nf["M8"],
        "nf_m10": nf["M10"],
    }

    # Replace only compiler/template placeholders.  Internal SPICE parameter
    # references such as {w_m1} and {l_default} remain untouched.
    rendered = source
    for key, value in external.items():
        rendered = rendered.replace("{" + key + "}", str(value))

    unresolved_external = [
        k for k in external if ("{" + k + "}") in rendered
    ]
    if unresolved_external:
        raise RuntimeError(
            "unresolved validation placeholders: "
            + ", ".join(unresolved_external)
        )

    # The project's SKY130 wrapper expects geometry in numeric micrometers:
    #   w=1    means 1 um
    #   l=0.5  means 0.5 um
    #
    # Do not leave a SPICE `u` suffix on these wrapper parameters.  Rewrite
    # the internal geometry definitions explicitly from the native witness.
    rendered = re.sub(
        r"(?m)^\.param\s+l_default=.*$",
        ".param l_default=0.5",
        rendered,
    )

    for idx in range(1, 12):
        width_um = float(widths[f"M{idx}"])
        rendered = re.sub(
            rf"(?m)^\.param\s+w_m{idx}=.*$",
            f".param w_m{idx}={width_um:.12g}",
            rendered,
        )

    return rendered


def build_deck(
    point_dir: Path,
    witness: dict[str, Any],
    source_spice: str,
    lib: Path,
    cfg: argparse.Namespace,
) -> None:
    rendered = render_source_spice(source_spice, witness)
    (point_dir / "folded_cascode.spice").write_text(rendered, encoding="utf-8")

    node_prints = " ".join(NODE_EXPR.values())

    control = [
        ".control",
        "set noaskquit",
        "set filetype=ascii",
        "op",
        "echo OPENAMS_OP_BEGIN",
        f"print {node_prints}",
        "echo OPENAMS_OP_END",
        "echo OPENAMS_DEVICE_BEGIN",
    ]

    # Same ngspice hierarchy convention already used by OpenAMS validation:
    # @m.xota.xmN[metric]
    for idx in range(1, 12):
        inst = f"@m.xota.xm{idx}"
        control.append(
            f"show {inst}[id] {inst}[gm] {inst}[gds] "
            f"{inst}[vgs] {inst}[vds] {inst}[vbs] {inst}[vdsat]"
        )

    control += [
        "echo OPENAMS_DEVICE_END",
        f"ac dec {cfg.ac_points_per_decade} {cfg.ac_start_hz:g} {cfg.ac_stop_hz:g}",
        "wrdata openams_ac.dat frequency vdb(vout) vp(vout)",
        "quit",
        ".endc",
    ]

    deck = f"""* OpenAMS folded-cascode native-witness validation
* point_index={witness['point_index']}
* source={witness.get('source')}
.option savecurrents
.temp 27
.lib "{lib}" tt

VDD_SUPPLY vdd 0 1.8
VSS_SUPPLY vss 0 0

* 1-V differential AC excitation, 0.9-V DC common mode.
VIP_SOURCE vip 0 DC 0.9 AC 0.5 0
VIN_SOURCE vin 0 DC 0.9 AC 0.5 180

.include "folded_cascode.spice"
XOTA vip vin vout vdd vss folded_cascode_ota

{chr(10).join(control)}
.end
"""
    (point_dir / "deck.spice").write_text(deck, encoding="utf-8")
    (point_dir / "witness.json").write_text(
        json.dumps(witness, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_nodes(log_text: str) -> dict[str, float]:
    try:
        block = log_text.split("OPENAMS_OP_BEGIN", 1)[1].split(
            "OPENAMS_OP_END", 1
        )[0]
    except IndexError:
        block = log_text

    out: dict[str, float] = {}
    for key, expr in NODE_EXPR.items():
        simple = expr[2:-1] if expr.startswith("v(") else expr
        patterns = [
            rf"{re.escape(expr)}\s*=\s*({FLOAT_RE})",
            rf"\b{re.escape(simple)}\s*=\s*({FLOAT_RE})",
        ]
        for pat in patterns:
            hits = re.findall(pat, block, flags=re.I)
            if hits:
                out[key] = float(hits[-1])
                break
    return out


DEVICE_VALUE_RE = re.compile(
    r"@m\.[^\[]*xm(?P<device>1[01]|[1-9])"
    r"\[(?P<metric>id|gm|gds|vgs|vds|vbs|vdsat)\]"
    r"\s*=\s*(?P<value>[+\-0-9.eE]+)",
    re.IGNORECASE,
)


def parse_device_show(log_text: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for m in DEVICE_VALUE_RE.finditer(log_text):
        dev = "M" + m.group("device")
        metric = m.group("metric").lower()
        out.setdefault(dev, {})[metric] = float(m.group("value"))
    return out


def _legacy_derive_device_voltages(
    nodes: dict[str, float]
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for dev, (d, g, s, b, polarity) in DEVICE_TERMINALS.items():
        if not all(k in nodes for k in (d, g, s, b)):
            continue
        vd, vg, vs, vb = nodes[d], nodes[g], nodes[s], nodes[b]
        if polarity == "nmos":
            vals = {
                "vgs": vg - vs,
                "vds": vd - vs,
                "vbs": vb - vs,
            }
        else:
            # Witness technology payload stores absolute PMOS magnitudes.
            vals = {
                "vgs": vs - vg,
                "vds": vs - vd,
                "vbs": vs - vb,
            }
        out[dev] = vals
    return out


def compare_scalar(
    model: float,
    spice: float,
    tolerance: float,
) -> tuple[float, bool]:
    error = spice - model
    return error, abs(error) <= tolerance



def witness_scalar_nodes(witness: dict[str, Any]) -> dict[str, float]:
    """
    Return scalar circuit-node values explicitly represented by the native
    witness.  Vout is excluded from scalar equality because it is a free
    equilibrium/output-window variable in this topology.
    """
    src = witness.get("nodes", {})
    aliases = {
        "vdd_v": ("vdd_v",),
        "vss_v": ("vss_v",),
        "vip_v": ("vip_v",),
        "vin_v": ("vin_v",),
        "tail_v": ("tail_v",),
        "psrc_left_v": ("psrc_left_v",),
        "psrc_right_v": ("psrc_right_v",),
        "x_v": ("x_v",),
        "nsink_left_v": ("nsink_left_v",),
        "nsink_right_v": ("nsink_right_v",),
        "vnb1_node_v": ("vnb1_node_v", "vnb1_v"),
        "vpb1_node_v": ("vpb1_node_v", "vpb1_v"),
        "vnb2_node_v": ("vnb2_node_v", "vnb2_v"),
        "vpb2_node_v": ("vpb2_node_v", "vpb2_v"),
    }
    out: dict[str, float] = {}
    for dst, names in aliases.items():
        for name in names:
            if name in src:
                out[dst] = fnum(src[name], name)
                break
        if dst not in out:
            # Biases are also stored in witness["biases_v"] in the native
            # witness schema.
            biases = witness.get("biases_v", {})
            bias_map = {
                "vnb1_node_v": "vnb1_v",
                "vpb1_node_v": "vpb1_v",
                "vnb2_node_v": "vnb2_v",
                "vpb2_node_v": "vpb2_v",
            }
            if dst in bias_map and bias_map[dst] in biases:
                out[dst] = fnum(biases[bias_map[dst]], bias_map[dst])
    return out


def witness_vout_range(witness: dict[str, Any]) -> tuple[float, float] | None:
    nodes = witness.get("nodes", {})
    candidates = (
        ("vout_min_v", "vout_max_v"),
        ("vout_lower_v", "vout_upper_v"),
    )
    for lo_key, hi_key in candidates:
        if lo_key in nodes and hi_key in nodes:
            return fnum(nodes[lo_key]), fnum(nodes[hi_key])

    # Some witness schemas retain output-window values at top level.
    for lo_key, hi_key in candidates:
        if lo_key in witness and hi_key in witness:
            return fnum(witness[lo_key]), fnum(witness[hi_key])
    return None


def derive_device_voltages_from_nodes(
    nodes: dict[str, float]
) -> dict[str, dict[str, float]]:
    """
    Derive circuit terminal voltages from a scalar node assignment.

    For PMOS, return magnitudes |VSG|, |VSD| and |VSB| using the same positive
    magnitude convention as the technology realization.
    """
    out: dict[str, dict[str, float]] = {}
    for dev, (d, g, s, b, polarity) in DEVICE_TERMINALS.items():
        if not all(k in nodes for k in (d, g, s, b)):
            continue
        vd, vg, vs, vb = nodes[d], nodes[g], nodes[s], nodes[b]
        if polarity == "nmos":
            out[dev] = {
                "vgs": vg - vs,
                "vds": vd - vs,
                "vbs": vb - vs,
            }
        else:
            out[dev] = {
                "vgs": vs - vg,
                "vds": vs - vd,
                "vbs": vs - vb,
            }
    return out


def compare_dc(
    witness: dict[str, Any],
    nodes: dict[str, float],
    shown: dict[str, dict[str, float]],
    cfg: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Correct native-witness DC comparison.

    * Bias/internal nodes are scalar witness-to-ngspice comparisons.
    * Vout is a free operating-point variable and is checked against the
      witness/model feasible output window.
    * Device VGS/VDS/VBS are derived from witness nodes and ngspice nodes.
      Technology-table VDS is NOT treated as the circuit VDS.
    * Device current and VDSAT may still be compared to the native technology
      realization when ngspice exposes those quantities.
    """
    node_result: dict[str, Any] = {}
    node_checks: list[bool] = []

    model_scalar = witness_scalar_nodes(witness)

    for key, mv in model_scalar.items():
        if key not in nodes:
            continue
        sv = fnum(nodes[key])
        error, ok = compare_scalar(mv, sv, cfg.node_tolerance_v)
        node_result[f"{key}_model"] = mv
        node_result[f"{key}_ngspice"] = sv
        node_result[f"{key}_error_v"] = error
        node_result[f"{key}_match"] = ok
        node_checks.append(ok)

    # Vout is not forced by a source.  Validate it against the feasible output
    # window retained by the native witness instead of against a chosen scalar.
    vout_range = witness_vout_range(witness)
    if vout_range is not None and "vout_v" in nodes:
        lo, hi = vout_range
        sv = fnum(nodes["vout_v"])
        ok = (lo - cfg.node_tolerance_v) <= sv <= (hi + cfg.node_tolerance_v)
        node_result["vout_v_model_min"] = lo
        node_result["vout_v_model_max"] = hi
        node_result["vout_v_ngspice"] = sv
        node_result["vout_v_inside_model_range"] = ok
        if sv < lo:
            node_result["vout_v_distance_to_range_v"] = sv - lo
        elif sv > hi:
            node_result["vout_v_distance_to_range_v"] = sv - hi
        else:
            node_result["vout_v_distance_to_range_v"] = 0.0
        node_checks.append(ok)

    node_result["node_comparisons"] = len(node_checks)
    node_result["node_matches"] = sum(node_checks)
    node_result["all_nodes_match"] = all(node_checks) if node_checks else False

    # Build witness-side node map using the same canonical node names that the
    # terminal mapper uses.
    witness_nodes = dict(model_scalar)

    # A scalar Vout may exist in the witness and is useful only to derive a
    # complete witness-side device terminal tuple.  It is not separately
    # validated as a scalar node.
    wn = witness.get("nodes", {})
    if "vout_v" in wn:
        witness_nodes["vout_v"] = fnum(wn["vout_v"])
    elif "vout_v" in witness:
        witness_nodes["vout_v"] = fnum(witness["vout_v"])
    elif vout_range is not None:
        witness_nodes["vout_v"] = 0.5 * (vout_range[0] + vout_range[1])

    model_device_v = derive_device_voltages_from_nodes(witness_nodes)
    spice_device_v = derive_device_voltages_from_nodes(nodes)

    device_rows: list[dict[str, Any]] = []

    for idx in range(1, 12):
        dev = f"M{idx}"
        group = GROUP_FOR_DEVICE[dev]
        tech = witness["device_realizations"][group]

        row: dict[str, Any] = {
            "point_index": witness["point_index"],
            "device": dev,
            "group": group,
            "width_um": witness["widths_um"][dev],
            "nf": witness["nf"][dev],
            "model_current_a": witness["currents_a"][dev],
            "technology_vgs_v": tech.get("vgs_v"),
            "technology_vds_v": tech.get("vds_v"),
            "technology_vbs_v": tech.get("vbs_v"),
            "model_vdsat_v": tech.get("vdsat_v"),
        }

        checks: list[bool] = []

        # Device terminal voltages: compare circuit-derived witness values
        # against circuit-derived ngspice values.
        if dev in model_device_v and dev in spice_device_v:
            for metric in ("vgs", "vds", "vbs"):
                # M7 and M9 drain directly into Vout.  Vout is a free
                # equilibrium variable constrained by a feasible window, not
                # a forced scalar witness node.  Therefore their circuit VDS
                # is not a scalar witness quantity and must not be used as a
                # model-vs-ngspice equality check.
                if metric == "vds" and dev in {"M7", "M9"}:
                    row["vds_check"] = "SKIPPED_FREE_VOUT"
                    row["model_vds_v"] = abs(fnum(model_device_v[dev][metric]))
                    row["ngspice_vds_v"] = abs(fnum(spice_device_v[dev][metric]))
                    continue

                mv = abs(fnum(model_device_v[dev][metric]))
                sv = abs(fnum(spice_device_v[dev][metric]))
                err, ok = compare_scalar(
                    mv, sv, cfg.device_voltage_tolerance_v
                )
                row[f"model_{metric}_v"] = mv
                row[f"ngspice_{metric}_v"] = sv
                row[f"{metric}_error_v"] = err
                row[f"{metric}_match"] = ok
                checks.append(ok)

        # Device current and VDSAT remain valid technology/witness comparisons
        # if ngspice exposed them successfully.
        s = shown.get(dev, {})
        if "id" in s:
            mv = abs(fnum(witness["currents_a"][dev]))
            sv = abs(fnum(s["id"]))
            err = sv - mv
            allowed = max(
                cfg.current_absolute_tolerance_a,
                cfg.current_relative_tolerance * max(mv, 1e-30),
            )
            ok = abs(err) <= allowed
            row["ngspice_id_a"] = sv
            row["id_error_a"] = err
            row["id_error_pct"] = (
                100.0 * err / mv if abs(mv) > 1e-30 else None
            )
            row["id_match"] = ok
            checks.append(ok)

        if "vdsat" in s and tech.get("vdsat_v") is not None:
            mv = abs(fnum(tech["vdsat_v"]))
            sv = abs(fnum(s["vdsat"]))
            err, ok = compare_scalar(mv, sv, cfg.vdsat_tolerance_v)
            row["ngspice_vdsat_v"] = sv
            row["vdsat_error_v"] = err
            row["vdsat_match"] = ok
            checks.append(ok)

        for metric in ("gm", "gds"):
            if metric in s:
                row[f"ngspice_{metric}_s"] = s[metric]

        row["comparisons"] = len(checks)
        row["matches"] = sum(checks)
        row["all_available_match"] = all(checks) if checks else False
        device_rows.append(row)

    return node_result, device_rows


def parse_ac(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows: list[tuple[float, float, float]] = []
    for raw in path.read_text(errors="replace").splitlines():
        vals: list[float] = []
        for tok in raw.replace(",", " ").split():
            try:
                vals.append(float(tok))
            except ValueError:
                pass

        if len(vals) >= 7:
            f, gain_db, phase_deg = vals[0], vals[4], math.degrees(vals[6])
        elif len(vals) >= 4:
            f, gain_db, phase_deg = vals[0], vals[1], math.degrees(vals[3])
        elif len(vals) >= 3:
            f, gain_db, phase_deg = vals[0], vals[1], vals[2]
        else:
            continue

        if f > 0 and all(math.isfinite(x) for x in (f, gain_db, phase_deg)):
            rows.append((f, gain_db, phase_deg))

    if len(rows) < 2:
        raise ValueError(f"Could not parse AC sweep: {path}")

    a = np.asarray(rows, dtype=float)
    a = a[np.argsort(a[:, 0])]
    keep = np.concatenate(([True], np.diff(a[:, 0]) > 0.0))
    a = a[keep]
    return a[:, 0], a[:, 1], a[:, 2]


def crossing(
    f: np.ndarray,
    y: np.ndarray,
    target: float,
    *,
    falling: bool = False,
) -> tuple[int, float] | None:
    for i in range(len(y) - 1):
        y1, y2 = float(y[i]), float(y[i + 1])
        if falling and not (y1 >= target and y2 <= target):
            continue
        if not ((y1 <= target <= y2) or (y2 <= target <= y1)):
            continue
        if y1 == y2:
            continue
        t = (target - y1) / (y2 - y1)
        lf = math.log10(float(f[i])) + t * (
            math.log10(float(f[i + 1])) - math.log10(float(f[i]))
        )
        return i, 10.0 ** lf
    return None


def interp_log_f(
    f: float,
    f1: float,
    f2: float,
    y1: float,
    y2: float,
) -> float:
    t = (math.log10(f) - math.log10(f1)) / (
        math.log10(f2) - math.log10(f1)
    )
    return y1 + t * (y2 - y1)


def ac_metrics(path: Path) -> dict[str, Any]:
    f, gain, phase_raw = parse_ac(path)

    # Absolute continuous phase of A(jw).
    #
    # Testbench:
    #   VIP = +0.5∠0 deg
    #   VIN = +0.5∠180 deg = -0.5
    # Therefore Vip - Vin = 1∠0 V and v(vout) is directly A(jw).
    #
    # Do NOT subtract phase_raw[0]; that would make the phase relative and
    # could hide a 180-degree polarity error.
    phase_unwrapped = np.rad2deg(
        np.unwrap(np.deg2rad(phase_raw))
    )

    gain0 = float(gain[0])
    peak_i = int(np.argmax(gain))

    out: dict[str, Any] = {
        "gain_db": gain0,
        "gain_v_v": float(10.0 ** (gain0 / 20.0)),
        "peak_gain_db": float(gain[peak_i]),
        "peak_gain_frequency_hz": float(f[peak_i]),
        "frequency_start_hz": float(f[0]),
        "frequency_stop_hz": float(f[-1]),
        "ac_rows": int(len(f)),
        "phase_low_frequency_raw_deg": float(phase_raw[0]),
        "phase_low_frequency_unwrapped_deg": float(phase_unwrapped[0]),
    }

    bw = crossing(f, gain, gain0 - 3.0, falling=True)
    out["bandwidth_3db_hz"] = None if bw is None else float(bw[1])

    ug = crossing(f, gain, 0.0, falling=True)
    if ug is None:
        out["ugb_hz"] = None
        out["phase_at_ugb_raw_deg"] = None
        out["phase_at_ugb_unwrapped_deg"] = None
        out["phase_at_ugb_deg"] = None
        out["phase_margin_deg"] = None
    else:
        i, ugb = ug

        ph_raw = interp_log_f(
            ugb,
            float(f[i]), float(f[i + 1]),
            float(phase_raw[i]), float(phase_raw[i + 1]),
        )

        ph_unwrapped = interp_log_f(
            ugb,
            float(f[i]), float(f[i + 1]),
            float(phase_unwrapped[i]), float(phase_unwrapped[i + 1]),
        )

        out["ugb_hz"] = float(ugb)
        out["phase_at_ugb_raw_deg"] = float(ph_raw)
        out["phase_at_ugb_unwrapped_deg"] = float(ph_unwrapped)
        out["phase_at_ugb_deg"] = float(ph_unwrapped)

        # Classical phase margin from the absolute continuous phase.
        # Do not wrap the phase into [-180, 180); e.g. -190 deg must
        # produce PM = -10 deg, not 350 deg.
        out["phase_margin_deg"] = float(180.0 + ph_unwrapped)

    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)

    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    cfg = parse_args()

    witnesses_path = cfg.witnesses.resolve()
    source_path = cfg.source_spice.resolve()
    output = cfg.output.resolve()

    if not witnesses_path.is_file():
        raise SystemExit(f"Missing witness JSONL: {witnesses_path}")
    if not source_path.is_file():
        raise SystemExit(f"Missing source SPICE: {source_path}")
    if not cfg.dry_run and shutil.which(cfg.ngspice) is None:
        raise SystemExit(f"ngspice not found: {cfg.ngspice}")

    lib = find_sky130_lib()
    all_witnesses = read_jsonl(witnesses_path)
    selected = select_space_filling(all_witnesses, cfg.count, cfg.seed)
    source_spice = source_path.read_text(encoding="utf-8")

    if output.exists():
        if not cfg.overwrite:
            raise SystemExit(f"Output exists; use --overwrite: {output}")
        shutil.rmtree(output)
    points_root = output / "points"
    points_root.mkdir(parents=True)

    print("===== OPENAMS FOLDED CASCODE NATIVE-WITNESS VALIDATION =====")
    print(f"witnesses:          {witnesses_path}")
    print(f"PASS witnesses:     {len(all_witnesses)}")
    print(f"selected:           {len(selected)}")
    print("selection axes:     w_m1_um, i_m3_a")
    print("DC reference:       exact native correlated witness")
    print("AC reference:       ngspice only")
    print(f"output:             {output}")
    print()

    selected_rows: list[dict[str, Any]] = []
    node_rows: list[dict[str, Any]] = []
    device_rows_all: list[dict[str, Any]] = []
    ac_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for ordinal, witness in enumerate(selected, 1):
        point_index = int(witness["point_index"])
        name = f"point_{point_index:06d}"
        point_dir = points_root / name
        point_dir.mkdir()

        selected_rows.append({
            "validation_ordinal": ordinal - 1,
            "point": name,
            "point_index": point_index,
            "w_m1_um": witness["w_m1_um"],
            "i_m3_a": witness["i_m3_a"],
            "minimum_saturation_margin_v": witness.get(
                "minimum_saturation_margin_v"
            ),
        })

        try:
            build_deck(point_dir, witness, source_spice, lib, cfg)
        except Exception as exc:
            print(f"[{ordinal:3d}/{len(selected)}] {name} DECK_FAIL {exc}")
            summary_rows.append({
                "point": name,
                "point_index": point_index,
                "status": "DECK_FAIL",
                "error": str(exc),
            })
            continue

        if cfg.dry_run:
            print(f"[{ordinal:3d}/{len(selected)}] {name} DECK_BUILT")
            summary_rows.append({
                "point": name,
                "point_index": point_index,
                "status": "DECK_BUILT",
            })
            continue

        cp = subprocess.run(
            [cfg.ngspice, "-b", "-o", "ngspice.log", "deck.spice"],
            cwd=point_dir,
            text=True,
            capture_output=True,
        )

        log_path = point_dir / "ngspice.log"
        log = log_path.read_text(errors="replace") if log_path.is_file() else ""

        nodes = parse_nodes(log)
        shown = parse_device_show(log)
        node_cmp, dev_cmp = compare_dc(witness, nodes, shown, cfg)

        node_row = {
            "point": name,
            "point_index": point_index,
            "ngspice_returncode": cp.returncode,
            **node_cmp,
        }
        node_rows.append(node_row)

        for r in dev_cmp:
            r["point"] = name
            device_rows_all.append(r)

        ac_path = point_dir / "openams_ac.dat"
        if cp.returncode == 0 and ac_path.is_file():
            try:
                ac = ac_metrics(ac_path)
                ac_status = "PASS"
            except Exception as exc:
                ac = {"error": f"{type(exc).__name__}: {exc}"}
                ac_status = "PARSE_FAIL"
        else:
            ac = {}
            ac_status = "NO_AC_DATA"

        ac_row = {
            "point": name,
            "point_index": point_index,
            "status": ac_status,
            **ac,
        }
        ac_rows.append(ac_row)

        device_checks = sum(int(r["comparisons"]) for r in dev_cmp)
        device_matches = sum(int(r["matches"]) for r in dev_cmp)

        if cp.returncode != 0:
            status = "NGSPICE_FAIL"
        elif not node_cmp.get("all_nodes_match", False):
            status = "DC_NODE_MISMATCH"
        elif device_checks and device_matches != device_checks:
            status = "DC_DEVICE_MISMATCH"
        else:
            status = "DC_PASS"

        summary_rows.append({
            "point": name,
            "point_index": point_index,
            "w_m1_um": witness["w_m1_um"],
            "i_m3_a": witness["i_m3_a"],
            "status": status,
            "ngspice_returncode": cp.returncode,
            "node_matches": node_cmp.get("node_matches"),
            "node_comparisons": node_cmp.get("node_comparisons"),
            "device_matches": device_matches,
            "device_comparisons": device_checks,
            "ac_status": ac_status,
            "gain_db_ngspice": ac.get("gain_db"),
            "ugb_hz_ngspice": ac.get("ugb_hz"),
            "phase_margin_deg_ngspice": ac.get("phase_margin_deg"),
            "bandwidth_3db_hz_ngspice": ac.get("bandwidth_3db_hz"),
        })

        (point_dir / "dc_comparison.json").write_text(
            json.dumps({
                "nodes": node_cmp,
                "devices": dev_cmp,
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (point_dir / "ac_metrics.json").write_text(
            json.dumps({
                "source": "ngspice_only",
                "model_ac_comparison_performed": False,
                "status": ac_status,
                "metrics": ac,
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"[{ordinal:3d}/{len(selected)}] {name} "
            f"rc={cp.returncode} "
            f"nodes={node_cmp.get('node_matches',0)}/{node_cmp.get('node_comparisons',0)} "
            f"devices={device_matches}/{device_checks} "
            f"gain={ac.get('gain_db')} dB "
            f"ugb={ac.get('ugb_hz')} Hz "
            f"pm={ac.get('phase_margin_deg')} deg"
        )

    write_csv(output / "selected_witnesses.csv", selected_rows)
    write_csv(output / "validation_summary.csv", summary_rows)

    if not cfg.dry_run:
        write_csv(output / "dc_node_comparison.csv", node_rows)
        write_csv(output / "dc_device_comparison.csv", device_rows_all)
        write_csv(output / "ngspice_ac_metrics.csv", ac_rows)

    pass_count = sum(r.get("status") == "DC_PASS" for r in summary_rows)
    manifest = {
        "artifact": "openams.folded_cascode.native_witness_ngspice_validation",
        "witness_jsonl": str(witnesses_path),
        "available_pass_witnesses": len(all_witnesses),
        "selected_witnesses": len(selected),
        "selection_axes": ["w_m1_um", "i_m3_a"],
        "dc_reference": "native witness scalar nodes + output feasibility window + circuit-derived device terminal voltages; M7/M9 VDS excluded because Vout is free",
        "ac_model_comparison": False,
        "dc_pass_count": pass_count,
        "node_tolerance_v": cfg.node_tolerance_v,
        "device_voltage_tolerance_v": cfg.device_voltage_tolerance_v,
        "current_relative_tolerance": cfg.current_relative_tolerance,
        "current_absolute_tolerance_a": cfg.current_absolute_tolerance_a,
        "vdsat_tolerance_v": cfg.vdsat_tolerance_v,
        "sky130_library": str(lib),
        "dry_run": cfg.dry_run,
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print("===== SUMMARY =====")
    print(f"selected:            {len(selected)}")
    if not cfg.dry_run:
        print(f"DC PASS:             {pass_count}")
        print(f"node comparison:     {output/'dc_node_comparison.csv'}")
        print(f"device comparison:   {output/'dc_device_comparison.csv'}")
        print(f"ngspice AC metrics:  {output/'ngspice_ac_metrics.csv'}")
    print(f"summary:             {output/'validation_summary.csv'}")
    print(f"raw points:          {points_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

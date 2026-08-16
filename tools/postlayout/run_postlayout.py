#!/usr/bin/env python3
"""
OpenAMS one-command post-layout reference driver.

Version 1 purpose
-----------------
Qualify and orchestrate the CURRENT proven two-stage LayGO2 -> Magic -> PEX flow
without silently pretending that arbitrary pre-layout widths are already supported.

The existing physical regression:
    tools/layout/run_laygo2_magic_two_stage_opamp_demo.sh
currently generates seven W=10um, L=0.5um MOS devices with geometry/pin coordinates
calibrated for that physical cell.

Therefore this driver:
  1. validates the environment,
  2. parses the supplied pre-layout two-stage netlist,
  3. checks M1..M7 and their W/L values,
  4. refuses arbitrary widths unless --allow-reference-geometry is used,
  5. runs the proven LayGO2/Magic/PEX regression,
  6. verifies that the extracted SPICE exists and contains M1..M7,
  7. optionally runs a supplied post-layout ngspice deck,
  8. writes a machine-readable summary.json.

This gives OpenAMS one command TODAY without hiding the remaining physical
quantization/generic-device-generation work.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple


EXPECTED_DEVICES = tuple(f"M{i}" for i in range(1, 8))
REFERENCE_W_UM = 10.0
REFERENCE_L_UM = 0.5


def die(msg: str, code: int = 2) -> "NoReturn":
    print(f"\nFAIL: {msg}", file=sys.stderr)
    raise SystemExit(code)


def banner(i: int, n: int, name: str) -> None:
    print(f"\n[{i}/{n}] {name}")


def which_or_fail(name: str) -> str:
    p = shutil.which(name)
    if not p:
        die(f"required executable not found in PATH: {name}")
    return p


def parse_spice_number(text: str) -> float:
    """
    Parse a small useful subset of SPICE numeric suffixes.
    Returns SI units.
    """
    s = text.strip().lower()
    table = {
        "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3,
        "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
    }
    m = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)(meg|[tgkmunpf])?", s)
    if not m:
        raise ValueError(text)
    v = float(m.group(1))
    suf = m.group(2)
    return v * table.get(suf, 1.0)


def joined_lines(text: str):
    logical = []
    cur = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            cur += " " + line[1:].strip()
        else:
            if cur:
                logical.append(cur)
            cur = line
    if cur:
        logical.append(cur)
    return logical


def parse_mos_wl(netlist: Path) -> Dict[str, Tuple[float, float]]:
    """
    Return M-device W/L in micrometers.
    Handles lines beginning M1...M7 and w=/l= tokens.
    """
    text = netlist.read_text(encoding="utf-8", errors="replace")
    found: Dict[str, Tuple[float, float]] = {}
    for line in joined_lines(text):
        toks = line.split()
        if not toks:
            continue
        name = toks[0].upper()
        if name not in EXPECTED_DEVICES:
            continue

        params = {}
        for tok in toks[1:]:
            if "=" in tok:
                k, v = tok.split("=", 1)
                params[k.lower()] = v

        if "w" not in params or "l" not in params:
            die(f"{name} is missing explicit W= or L= in {netlist}")

        try:
            w_si = parse_spice_number(params["w"])
            l_si = parse_spice_number(params["l"])
        except ValueError as exc:
            die(f"cannot parse {name} geometry token: {exc}")

        # SPICE W=10u -> 10 um; if bare values are used by an OpenAMS
        # SCALE=1e-6 deck, this parser cannot safely infer that convention.
        # Fail rather than silently scaling incorrectly.
        if abs(w_si) > 1e-3 or abs(l_si) > 1e-3:
            die(
                f"{name} geometry appears to use bare/non-SI values "
                f"(W={params['w']}, L={params['l']}). "
                "Use explicit unit suffixes such as W=10u L=0.5u for this driver."
            )

        found[name] = (w_si * 1e6, l_si * 1e6)

    missing = [m for m in EXPECTED_DEVICES if m not in found]
    if missing:
        die(f"pre-layout netlist does not contain explicit {', '.join(missing)}")
    return found


def run_logged(cmd, cwd: Path, env: dict, log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    print("RUN:", " ".join(map(str, cmd)))
    with log.open("w", encoding="utf-8") as f:
        p = subprocess.run(
            list(map(str, cmd)),
            cwd=str(cwd),
            env=env,
            stdout=f,
            stderr=subprocess.STDOUT,
        )
    if p.returncode != 0:
        tail = ""
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-40:])
        except Exception:
            pass
        die(f"command failed (rc={p.returncode}). Log: {log}\n\n{tail}")


def check_reference_geometry(wl: Dict[str, Tuple[float, float]]) -> list[str]:
    mismatches = []
    for name in EXPECTED_DEVICES:
        w, l = wl[name]
        if abs(w - REFERENCE_W_UM) > 1e-9 or abs(l - REFERENCE_L_UM) > 1e-9:
            mismatches.append(f"{name}: W={w:g}um L={l:g}um")
    return mismatches


def main() -> int:
    ap = argparse.ArgumentParser(
        description="OpenAMS one-command qualified post-layout reference flow"
    )
    ap.add_argument("--netlist", type=Path, required=True,
                    help="pre-layout sized SPICE netlist")
    ap.add_argument("--output", type=Path,
                    default=Path("runtime/postlayout/two_stage_reference"))
    ap.add_argument("--root", type=Path, default=Path("."),
                    help="OpenAMS repository root")
    ap.add_argument("--laygo2-workspace", type=Path,
                    default=Path("~/AMS-Tutorial/laygo2_workspace_sky130").expanduser())
    ap.add_argument("--magic-tech", type=Path,
                    default=Path("/usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech"))
    ap.add_argument("--layout-script", type=Path,
                    default=Path("tools/layout/run_laygo2_magic_two_stage_opamp_demo.sh"))
    ap.add_argument("--postlayout-deck", type=Path, default=None,
                    help="optional ngspice deck that already includes/instantiates the extracted circuit")
    ap.add_argument("--allow-reference-geometry", action="store_true",
                    help="run the W=10um/L=0.5um reference layout even when the supplied netlist has other sizes")
    ap.add_argument("--keep-layout-work", action="store_true",
                    help="do not delete the backend work directory before execution")
    args = ap.parse_args()

    root = args.root.resolve()
    netlist = args.netlist if args.netlist.is_absolute() else (root / args.netlist)
    netlist = netlist.resolve()
    out = args.output if args.output.is_absolute() else (root / args.output)
    out = out.resolve()
    layout_script = args.layout_script if args.layout_script.is_absolute() else (root / args.layout_script)
    layout_script = layout_script.resolve()
    laygo2_ws = args.laygo2_workspace.expanduser().resolve()
    magic_tech = args.magic_tech.expanduser().resolve()

    out.mkdir(parents=True, exist_ok=True)
    layout_work = out / "layout_backend"

    summary = {
        "schema_version": 1,
        "status": "RUNNING",
        "mode": "qualified_two_stage_reference",
        "input_netlist": str(netlist),
        "output_dir": str(out),
        "reference_geometry": {"w_um": REFERENCE_W_UM, "l_um": REFERENCE_L_UM},
        "stages": {},
    }

    def save_summary():
        (out / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    try:
        banner(1, 6, "Environment qualification")
        if not netlist.is_file():
            die(f"netlist not found: {netlist}")
        if not layout_script.is_file():
            die(f"layout script not found: {layout_script}")
        if not laygo2_ws.is_dir():
            die(f"LayGO2 workspace not found: {laygo2_ws}")
        if not magic_tech.is_file():
            die(f"Magic technology file not found: {magic_tech}")
        tools = {
            "python": sys.executable,
            "bash": which_or_fail("bash"),
            "magic": which_or_fail("magic"),
            "ngspice": which_or_fail("ngspice"),
        }
        summary["tools"] = tools
        summary["stages"]["environment"] = "PASS"
        print("PASS")
        save_summary()

        banner(2, 6, "Canonical pre-layout netlist")
        wl = parse_mos_wl(netlist)
        summary["electrical_geometry_um"] = {
            k: {"w_um": v[0], "l_um": v[1]} for k, v in wl.items()
        }
        print("M1..M7 found with explicit W/L")
        for name in EXPECTED_DEVICES:
            w, l = wl[name]
            print(f"  {name}: W={w:g} um  L={l:g} um")
        summary["stages"]["netlist"] = "PASS"
        save_summary()

        banner(3, 6, "Physical realization guard")
        mismatches = check_reference_geometry(wl)
        if mismatches and not args.allow_reference_geometry:
            summary["stages"]["physical_mapping"] = "BLOCKED"
            summary["physical_mapping_reason"] = (
                "current proven backend is calibrated only for W=10um L=0.5um"
            )
            save_summary()
            die(
                "the supplied sized netlist is NOT the W=10um/L=0.5um reference geometry.\n"
                "Current backend would otherwise silently ignore the requested sizes.\n"
                "Mismatches:\n  " + "\n  ".join(mismatches) + "\n\n"
                "This is the correct stopping point. The next implementation step is "
                "the generic physical-realization mapper."
            )
        if mismatches:
            print("WARNING: running reference geometry by explicit request; input widths are NOT realized.")
            summary["physical_mapping"] = "REFERENCE_OVERRIDE"
        else:
            print("PASS: supplied geometry matches qualified reference cell")
            summary["physical_mapping"] = "REFERENCE_MATCH"
        summary["stages"]["physical_mapping"] = "PASS"
        save_summary()

        banner(4, 6, "LayGO2 + Magic + PEX")
        if layout_work.exists() and args.keep_layout_work:
            print(f"Keeping existing backend work directory: {layout_work}")
        env = os.environ.copy()
        env.update({
            "OPENAMS_ROOT": str(root),
            "LAYGO2_WS": str(laygo2_ws),
            "MAGIC_TECH": str(magic_tech),
            "WORK": str(layout_work),
        })
        run_logged(
            ["bash", layout_script],
            cwd=root,
            env=env,
            log=out / "layout_pex.log",
        )
        extracted = layout_work / "two_stage_opamp_extracted.spice"
        if not extracted.is_file():
            die(f"layout/PEX command completed but extracted SPICE is missing: {extracted}")
        summary["extracted_spice"] = str(extracted)
        summary["stages"]["layout_pex"] = "PASS"
        print(f"PASS: {extracted}")
        save_summary()

        banner(5, 6, "Extracted-netlist topology smoke check")
        extext = extracted.read_text(encoding="utf-8", errors="replace")
        missing = [
            m for m in EXPECTED_DEVICES
            if not re.search(rf"(?mi)^X{re.escape(m)}\s+", extext)
        ]
        if missing:
            die(f"extracted SPICE missing hierarchical instances: {', '.join(missing)}")
        print("PASS: extracted SPICE contains XM1..XM7")
        summary["stages"]["extracted_topology"] = "PASS"
        save_summary()

        banner(6, 6, "Post-layout ngspice")
        if args.postlayout_deck is None:
            print(
                "SKIP: no --postlayout-deck supplied.\n"
                "Layout and PEX are qualified; electrical post-layout convergence "
                "is not yet claimed by this run."
            )
            summary["stages"]["postlayout_ngspice"] = "SKIP"
            summary["status"] = "PEX_PASS_POSTLAYOUT_SIM_NOT_RUN"
            save_summary()
        else:
            deck = args.postlayout_deck
            if not deck.is_absolute():
                deck = (root / deck).resolve()
            if not deck.is_file():
                die(f"post-layout ngspice deck not found: {deck}")
            log = out / "postlayout_ngspice.log"
            run_logged(
                ["ngspice", "-b", "-o", str(log), str(deck)],
                cwd=deck.parent,
                env=os.environ.copy(),
                log=out / "postlayout_driver.log",
            )
            text = log.read_text(encoding="utf-8", errors="replace")
            bad_patterns = [
                "singular matrix",
                "timestep too small",
                "doAnalyses: operating point failed",
                "no convergence in dc operating point",
            ]
            hits = [p for p in bad_patterns if p.lower() in text.lower()]
            if hits:
                summary["stages"]["postlayout_ngspice"] = "FAIL"
                summary["ngspice_failure_markers"] = hits
                summary["status"] = "FAIL"
                save_summary()
                die("ngspice completed with failure marker(s): " + ", ".join(hits))
            print("PASS: ngspice completed without known convergence-failure markers")
            summary["stages"]["postlayout_ngspice"] = "PASS"
            summary["postlayout_deck"] = str(deck)
            summary["status"] = "PASS"
            save_summary()

        print("\n===== OPENAMS POST-LAYOUT RESULT =====")
        print(f"status          : {summary['status']}")
        print(f"input netlist   : {netlist}")
        print(f"extracted SPICE : {summary.get('extracted_spice', '-')}")
        print(f"summary         : {out / 'summary.json'}")
        return 0

    except SystemExit:
        if summary.get("status") == "RUNNING":
            summary["status"] = "FAIL"
            save_summary()
        raise


if __name__ == "__main__":
    raise SystemExit(main())

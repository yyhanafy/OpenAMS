#!/usr/bin/env python3
"""
Inspect the installed Laygo2 SKY130 technology implementation to determine
how composite MOS devices are built from nf1/nf2 primitives and where
placement/routing grids are defined.

Read-only diagnostic tool.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import os
import re
import sys
from pathlib import Path


TARGET_NAMES = [
    "mos_generate_func",
    "nmos_generate_func",
    "pmos_generate_func",
    "mos_bbox_func",
    "mos_pins_func",
    "load_templates",
    "load_grids",
]


def print_source(fn, max_lines=220):
    try:
        src = inspect.getsource(fn)
    except Exception as e:
        print(f"  SOURCE UNAVAILABLE: {e}")
        return
    lines = src.splitlines()
    for line in lines[:max_lines]:
        print(line)
    if len(lines) > max_lines:
        print(f"... ({len(lines)-max_lines} more lines)")


def find_candidate_files(root: Path):
    pats = [
        "*grid*.py",
        "*template*.py",
        "*tech*.py",
        "*.yaml",
    ]
    out = set()
    for pat in pats:
        out.update(root.rglob(pat))
    return sorted(p for p in out if p.is_file())


def scan_file(path: Path):
    try:
        txt = path.read_text(errors="replace")
    except Exception:
        return []

    hits = []
    patterns = [
        r"\bPlacementGrid\b",
        r"\bRoutingGrid\b",
        r"\bload_grids\b",
        r"\bnmos_generate_func\b",
        r"\bpmos_generate_func\b",
        r"\bmos_generate_func\b",
        r"\bparams\b",
        r"\bnf\b",
        r"\btrackswap\b",
    ]
    for pat in patterns:
        if re.search(pat, txt):
            hits.append(pat)
    return hits


def import_module_from_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--workspace",
        default="~/AMS-Tutorial/laygo2_workspace_sky130",
    )
    args = ap.parse_args()

    ws = Path(args.workspace).expanduser().resolve()
    tech = ws / "skywater130" / "laygo2_tech"
    if not tech.is_dir():
        raise SystemExit(f"Technology directory not found: {tech}")

    # Make the local Laygo2 package and workspace importable.
    sys.path.insert(0, str(ws / "laygo2"))
    sys.path.insert(0, str(ws))
    sys.path.insert(0, str(ws / "skywater130"))

    print("===== TECHNOLOGY DIRECTORY =====")
    print(tech)

    print("\n===== RELEVANT FILES =====")
    candidates = find_candidate_files(tech)
    for f in candidates:
        hits = scan_file(f)
        if hits:
            print(f"{f.relative_to(ws)}")
            print("  hits:", ", ".join(hits))

    template_py = tech / "laygo2_tech_templates.py"
    if not template_py.is_file():
        raise SystemExit(f"Missing expected file: {template_py}")

    print("\n===== IMPORT TECHNOLOGY TEMPLATE MODULE =====")
    try:
        mod = import_module_from_file(template_py, "openams_laygo2_sky130_templates")
        print("PASS:", template_py)
    except Exception as e:
        print("IMPORT FAILED:", repr(e))
        print("\nFalling back to static source inspection.")
        mod = None

    if mod is not None:
        for name in TARGET_NAMES:
            obj = getattr(mod, name, None)
            if obj is None:
                continue
            print(f"\n===== {name} SIGNATURE =====")
            try:
                print(inspect.signature(obj))
            except Exception as e:
                print("signature unavailable:", e)

            print(f"\n===== {name} SOURCE =====")
            print_source(obj)

        print("\n===== LOAD_TEMPLATES CONTENT =====")
        try:
            tlib = mod.load_templates()
            keys = list(tlib.keys()) if hasattr(tlib, "keys") else []
            print("template count:", len(keys))
            for k in keys:
                if any(s in str(k).lower() for s in ["nmos", "pmos"]):
                    print(" ", k, type(tlib[k]).__name__)
        except Exception as e:
            print("load_templates failed:", repr(e))

    print("\n===== STATIC GENERATOR LINES =====")
    txt = template_py.read_text(errors="replace").splitlines()
    keywords = [
        "def mos_generate_func",
        "def nmos_generate_func",
        "def pmos_generate_func",
        "params.get",
        "params[",
        "'nf'",
        '"nf"',
        "shape=",
        "center_nf2",
        "center_nf1",
    ]
    for i, line in enumerate(txt, 1):
        if any(k in line for k in keywords):
            lo = max(1, i - 2)
            hi = min(len(txt), i + 5)
            print(f"\n--- {template_py.name}:{lo}-{hi} ---")
            for j in range(lo, hi + 1):
                print(f"{j:4d}: {txt[j-1]}")

    print("\n===== GRID DEFINITIONS SEARCH =====")
    for f in candidates:
        try:
            lines = f.read_text(errors="replace").splitlines()
        except Exception:
            continue
        matched = []
        for i, line in enumerate(lines, 1):
            if any(k in line for k in [
                "PlacementGrid", "RoutingGrid", "load_grids",
                "placement_grid", "routing_grid",
                "routing_12", "routing_23", "placement_basic",
            ]):
                matched.append((i, line))
        if matched:
            print(f"\nFILE: {f.relative_to(ws)}")
            for i, line in matched[:120]:
                print(f"{i:4d}: {line}")

    print("\n===== INTERPRETATION GUARD =====")
    print("Do NOT infer the legal OpenAMS quantization space from YAML nf=[1,2] alone.")
    print("Those may be primitive tiles used by a composite UserDefinedTemplate generator.")
    print("The legal sizing rule must come from the generator parameters + grid/template composition.")


if __name__ == "__main__":
    main()

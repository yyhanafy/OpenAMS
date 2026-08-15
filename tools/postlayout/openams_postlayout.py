#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


class PipelineError(RuntimeError):
    pass


def fail(msg: str):
    raise PipelineError(msg)


def spice_si(x: str) -> float:
    x = x.strip().lower()
    mult = {"t":1e12,"g":1e9,"meg":1e6,"k":1e3,"m":1e-3,
            "u":1e-6,"n":1e-9,"p":1e-12,"f":1e-15}
    m = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)(meg|[tgkmunpf])?", x)
    if not m:
        fail(f"cannot parse SPICE value: {x}")
    return float(m.group(1)) * mult.get(m.group(2), 1.0)


def logical_lines(text: str):
    out, cur = [], ""
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("*"):
            continue
        if s.startswith("+"):
            cur += " " + s[1:].strip()
        else:
            if cur:
                out.append(cur)
            cur = s
    if cur:
        out.append(cur)
    return out


def parse_netlist(path: Path):
    text = path.read_text(errors="replace")
    ph = sorted(set(re.findall(r"\{[^{}]+\}", text)))
    if ph:
        fail("input netlist still has unresolved placeholders: " + ", ".join(ph[:10]))

    subckt = None
    pins = []
    geom = {}
    for line in logical_lines(text):
        t = line.split()
        if not t:
            continue
        if t[0].lower() == ".subckt" and subckt is None:
            subckt, pins = t[1], t[2:]
        m = re.fullmatch(r"X?M(\d+)", t[0].upper())
        if not m:
            continue
        params = {}
        for tok in t:
            if "=" in tok:
                k,v = tok.split("=",1)
                params[k.lower()] = v
        if "w" in params and "l" in params:
            geom[f"M{int(m.group(1))}"] = {
                "w_um": spice_si(params["w"]) * 1e6,
                "l_um": spice_si(params["l"]) * 1e6,
            }
    if subckt is None:
        fail("no .subckt found")
    if len(geom) != 7:
        fail(f"expected M1..M7 with numeric W/L; found {sorted(geom)}")
    return {"subckt": subckt, "pins": pins, "geom": geom}


def load_physical_witness(info, pool: Path, tol_um=0.11):
    rows = list(csv.DictReader(pool.open(newline="")))
    candidates = []
    for row in rows:
        if str(row.get("physical_legal","")).lower() not in ("true","1","yes"):
            continue
        err = 0.0
        ok = True
        for i in range(1,8):
            key = f"realized_w_m{i}_um"
            if not row.get(key):
                ok = False
                break
            e = abs(info["geom"][f"M{i}"]["w_um"] - float(row[key]))
            if e > tol_um:
                ok = False
                break
            err += e
        if ok:
            candidates.append((err,row))
    if not candidates:
        fail(f"no physical witness matches the sized netlist within {tol_um}um")
    candidates.sort(key=lambda x:x[0])
    row = candidates[0][1]
    devices = {}
    for i in range(1,8):
        devices[f"M{i}"] = {
            "requested_w_um": info["geom"][f"M{i}"]["w_um"],
            "requested_l_um": info["geom"][f"M{i}"]["l_um"],
            "nf": int(float(row[f"nf_m{i}"])),
            "realized_w_um": float(row[f"realized_w_m{i}_um"]),
            "width_error_um": float(row.get(f"width_error_m{i}_um") or 0),
            "width_rel_error": float(row.get(f"width_rel_error_m{i}") or 0),
        }
    return {
        "physical_candidate_id": row.get("physical_candidate_id"),
        "source_candidate_id": row.get("source_candidate_id"),
        "physical_legal": True,
        "vbias_v": float(row["vbias_v"]) if row.get("vbias_v") else None,
        "vout_v": float(row["vout_v"]) if row.get("vout_v") else None,
        "devices": devices,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist", type=Path)
    ap.add_argument("--output-netlist", type=Path, default=Path("netlist_post_layout.spice"))
    ap.add_argument("--run-dir", type=Path, default=Path("runtime/postlayout/latest"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument(
        "--physical-witness-pool", type=Path,
        default=Path("examples/two_stage_opamp/generated/assignment_synthesis/physical_witness_pool.csv")
    )
    ap.add_argument(
        "--backend-script", type=Path,
        default=Path("tools/postlayout/run_align_magic_two_stage_dynamic.sh")
    )
    ap.add_argument("--align-length-um", type=float, default=0.15)
    args = ap.parse_args()

    root = args.root.resolve()
    netlist = args.netlist if args.netlist.is_absolute() else root / args.netlist
    pool = args.physical_witness_pool if args.physical_witness_pool.is_absolute() else root / args.physical_witness_pool
    backend = args.backend_script if args.backend_script.is_absolute() else root / args.backend_script
    run_dir = args.run_dir if args.run_dir.is_absolute() else root / args.run_dir
    output = args.output_netlist if args.output_netlist.is_absolute() else root / args.output_netlist
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {"status":"RUNNING","input":str(netlist),"output":str(output),"stages":{}}
    def save():
        (run_dir/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")

    try:
        print("[1/6] Environment")
        for cmd in ("magic","netgen","ngspice"):
            if shutil.which(cmd) is None:
                fail(f"required command not found: {cmd}")
        for p,label in ((netlist,"input netlist"),(pool,"physical witness pool"),(backend,"ALIGN backend")):
            if not p.is_file():
                fail(f"{label} not found: {p}")
        align_py = Path.home()/"AMS-Tutorial/ALIGN-public/.venv-align/bin/python"
        align_cli = Path.home()/"AMS-Tutorial/ALIGN-public/.venv-align/bin/schematic2layout.py"
        if not align_py.is_file() or not align_cli.is_file():
            fail("ALIGN virtual environment/CLI not found")
        summary["stages"]["environment"]="PASS"
        save(); print("PASS")

        print("\n[2/6] Canonical sized netlist")
        info = parse_netlist(netlist)
        lengths = {round(d["l_um"],9) for d in info["geom"].values()}
        if lengths != {round(args.align_length_um,9)}:
            fail(
                "input netlist length is incompatible with the qualified ALIGN technology flow: "
                f"found {sorted(lengths)} um, expected {args.align_length_um:g} um"
            )
        summary["canonical"]=info
        summary["stages"]["canonical"]="PASS"
        save(); print(f"PASS: {info['subckt']} M1..M7 L={args.align_length_um:g}um")

        print("\n[3/6] Physical witness")
        mapping = load_physical_witness(info,pool)
        mdir = run_dir/"02_physical_mapping"
        mdir.mkdir(parents=True,exist_ok=True)
        mapping_json = mdir/"mapping.json"
        mapping_json.write_text(json.dumps(mapping,indent=2,sort_keys=True)+"\n")
        summary["physical_mapping"]=mapping
        summary["stages"]["physical_witness"]="PASS"
        save()
        print("PASS:",mapping["physical_candidate_id"])
        for n,d in mapping["devices"].items():
            print(f"  {n}: nf={d['nf']} Wreal={d['realized_w_um']:g}um")

        print("\n[4/6] ALIGN -> Magic -> LVS -> RCX")
        env = dict(**__import__("os").environ)
        env.update({
            "OPENAMS_ROOT":str(root),
            "OPENAMS_PHYSICAL_MAPPING":str(mapping_json),
            "OPENAMS_OUTPUT_NETLIST":str(output),
            "ALIGN_WORK":str(run_dir/"03_layout/align"),
            "MAGIC_WORK":str(run_dir/"04_pex/magic"),
            "ALIGN_INPUT_WORK":str(run_dir/"03_layout/align_input"),
            "ALIGN_PYTHON":str(align_py),
            "ALIGN_CLI":str(align_cli),
        })
        log = run_dir/"physical_backend.log"
        with log.open("w") as f:
            p = subprocess.run(["bash",str(backend)],cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT)
        if p.returncode:
            tail = "\n".join(log.read_text(errors="replace").splitlines()[-80:])
            fail(f"physical backend failed (rc={p.returncode})\n{tail}")
        if not output.is_file():
            fail("backend completed without post-layout netlist")
        summary["stages"]["physical_backend"]="PASS"
        summary["backend_log"]=str(log)
        save(); print("PASS")

        print("\n[5/6] Post-layout artifact validation")
        text = output.read_text(errors="replace")
        counts = {
            "R":sum(1 for l in text.splitlines() if l.startswith("R")),
            "C":sum(1 for l in text.splitlines() if l.startswith("C")),
            "X":sum(1 for l in text.splitlines() if l.startswith("X")),
        }
        lvs = run_dir/"04_pex/magic/lvs_report.out"
        if not lvs.is_file() or "Circuits match uniquely" not in lvs.read_text(errors="replace"):
            fail("LVS PASS evidence missing")
        if min(counts["R"],counts["C"],counts["X"]) <= 0:
            fail(f"incomplete RCX counts: {counts}")
        summary["rcx_counts"]=counts
        summary["stages"]["artifact_validation"]="PASS"
        save()
        print("PASS:",counts)

        print("\n[6/6] Result")
        summary["status"]="PASS_POST_LAYOUT_NETLIST_CREATED"
        save()
        print("PASS:",output)
        print("summary:",run_dir/"summary.json")
        print("NOTE: ngspice .op/AC validation is the next stage; this command certifies ALIGN/LVS/RCX output.")

        return 0

    except PipelineError as e:
        summary["status"]="FAIL"
        summary["error"]=str(e)
        save()
        print("\nRESULT: FAIL",file=sys.stderr)
        print(e,file=sys.stderr)
        print("summary:",run_dir/"summary.json",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

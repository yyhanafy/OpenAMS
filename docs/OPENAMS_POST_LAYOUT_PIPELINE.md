# OpenAMS Pre-Layout to Post-Layout Pipeline

## Purpose

This document freezes the qualified OpenAMS two-stage post-layout flow developed during the ALIGN/Magic expedition.

The user-facing contract is:

```text
sized pre-layout netlist.spice
        ↓
physical witness selection
        ↓
ALIGN-compatible realization
        ↓
ALIGN placement + routing
        ↓
GDS
        ↓
Magic extraction
        ↓
Netgen LVS
        ↓
Magic full flat RCX
        ↓
netlist_post_layout.spice
```

The goal is that the user remains in the OpenAMS virtual environment and runs one OpenAMS command. The wrapper explicitly invokes ALIGN from ALIGN's own virtual environment internally.

## Current qualified scope

The frozen implementation is currently qualified for the OpenAMS two-stage op-amp topology:

```text
M1 n1    inp   ntail vss
M2 n2    inn   ntail vss
M3 n1    n1    vdd   vdd
M4 n2    n1    vdd   vdd
M5 ntail vbias vss   vss
M6 out   n2    vdd   vdd
M7 out   vbias vss   vss
```

The physical-flow technology point is SKY130 with the ALIGN-compatible device representation:

```text
ALIGN unit transistor width = 0.42 um
ALIGN transistor length     = 0.15 um
large effective width       = 0.42 um × even NF
```

This is not yet a topology-generic backend. The orchestration structure is intended to become generic later.

## Required installations

The qualified workstation configuration uses:

```text
OpenAMS:
~/AMS-Tutorial/openams
virtual environment:
~/AMS-Tutorial/openams/.venv-openams

ALIGN:
~/AMS-Tutorial/ALIGN-public
ALIGN virtual environment:
~/AMS-Tutorial/ALIGN-public/.venv-align

ALIGN SKY130 PDK:
~/AMS-Tutorial/ALIGN-pdk-sky130/SKY130_PDK

Magic SKY130 technology:
 /usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech

Netgen SKY130 setup:
 /usr/local/share/pdk/sky130A/libs.tech/netgen/sky130A_setup.tcl
```

Required commands:

```bash
magic
netgen
ngspice
```

The user does **not** need to activate `.venv-align`. `openams_postlayout.py` invokes:

```text
~/AMS-Tutorial/ALIGN-public/.venv-align/bin/python
~/AMS-Tutorial/ALIGN-public/.venv-align/bin/schematic2layout.py
```

directly.

## Input contract

The input must be a numerically sized SPICE netlist, not a parameterized template.

Example:

```spice
.subckt two_stage_opamp inp inn out vdd vss vbias
XM1 n1 inp ntail vss sky130_fd_pr__nfet_01v8_lvt L=0.15u W=1.0u nf=1 mult=1
XM2 n2 inn ntail vss sky130_fd_pr__nfet_01v8_lvt L=0.15u W=1.0u nf=1 mult=1
XM3 n1 n1 vdd vdd sky130_fd_pr__pfet_01v8 L=0.15u W=5.0u nf=1 mult=1
XM4 n2 n1 vdd vdd sky130_fd_pr__pfet_01v8 L=0.15u W=5.0u nf=1 mult=1
XM5 ntail vbias vss vss sky130_fd_pr__nfet_01v8_lvt L=0.15u W=5.0u nf=1 mult=1
XM6 out n2 vdd vdd sky130_fd_pr__pfet_01v8 L=0.15u W=98.0u nf=1 mult=1
XM7 out vbias vss vss sky130_fd_pr__nfet_01v8_lvt L=0.15u W=50.0u nf=1 mult=1
Cc n2 out 2p
.ends two_stage_opamp
```

The wrapper rejects unresolved placeholders such as `{w_m1_um}`.

## Physical witness source of truth

The physical witness file is:

```text
examples/two_stage_opamp/generated/assignment_synthesis/physical_witness_pool.csv
```

The generic columns include:

```text
physical_candidate_id
candidate_id
nf_m1 ... nf_m7
realized_w_m1_um ... realized_w_m7_um
physical_legal
width_error_m*_um
width_rel_error_m*
```

The wrapper finds a `physical_legal=True` row whose **realized widths** match the sized netlist.

For the first current candidate:

```text
physical_candidate_id = physical_00000000

M1: nf=2    realized W=1.0 um
M2: nf=2    realized W=1.0 um
M3: nf=5    realized W=5.0 um
M4: nf=5    realized W=5.0 um
M5: nf=10   realized W=5.0 um
M6: nf=98   realized W=98.0 um
M7: nf=100  realized W=50.0 um
```

## ALIGN-specific realization

The physical witness is backend-neutral. ALIGN then maps the target physical widths onto its legal SKY130 representation using:

```text
unit W = 0.42 um
L      = 0.15 um
NF     = nearest legal even finger count
```

The successful current realization is recorded in:

```text
netlist_post_layout.align_realization.json
```

Current example:

```text
M1 target 1.00 um  → W=0.42 um, NF=2   → 0.84 um   error 16.0%
M2 target 1.00 um  → W=0.42 um, NF=2   → 0.84 um   error 16.0%
M3 target 5.00 um  → W=0.42 um, NF=12  → 5.04 um   error 0.8%
M4 target 5.00 um  → W=0.42 um, NF=12  → 5.04 um   error 0.8%
M5 target 5.00 um  → W=0.42 um, NF=12  → 5.04 um   error 0.8%
M6 target 98.0 um  → W=0.42 um, NF=234 → 98.28 um  error 0.286%
M7 target 50.0 um  → W=0.42 um, NF=120 → 50.40 um  error 0.8%
```

The 16% minimum-device error on M1/M2 is currently accepted for the physical-flow proof and must be carried into post-layout performance evaluation.

## Exact one-command execution

From OpenAMS:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate

rm -rf runtime/postlayout/two_stage

python tools/postlayout/openams_postlayout.py \
  examples/two_stage_opamp/generated/sized_netlist.spice \
  --output-netlist netlist_post_layout.spice \
  --run-dir runtime/postlayout/two_stage
```

The expected qualified result is:

```text
[1/6] Environment
PASS

[2/6] Canonical sized netlist
PASS

[3/6] Physical witness
PASS

[4/6] ALIGN -> Magic -> LVS -> RCX
PASS

[5/6] Post-layout artifact validation
PASS

[6/6] Result
PASS: .../netlist_post_layout.spice
```

A representative successful run produced:

```text
R = 2730
C = 2264
X = 394
```

The counts can change with the selected physical witness and ALIGN realization.

## Pipeline stages

### Stage 1 - Environment qualification

`openams_postlayout.py` checks:

```text
input netlist exists
physical_witness_pool.csv exists
dynamic ALIGN backend exists
magic exists
netgen exists
ngspice exists
ALIGN Python exists
ALIGN schematic2layout.py exists
```

The OpenAMS environment stays active. ALIGN is invoked explicitly through its own interpreter.

### Stage 2 - Canonical sized-netlist validation

The wrapper verifies:

```text
.subckt exists
M1 ... M7 exist
numeric W and L exist
no unresolved {...} placeholders remain
qualified ALIGN length is L=0.15 um
```

A mismatched length is a hard failure. The script must never silently convert an electrical design from one channel length to another.

### Stage 3 - Physical witness selection

The wrapper matches the sized netlist against:

```text
physical_witness_pool.csv
```

and writes:

```text
runtime/postlayout/two_stage/02_physical_mapping/mapping.json
```

This is the formal handoff from OpenAMS electrical/physical witness generation into physical design.

### Stage 4A - Generate ALIGN-compatible netlist

The dynamic backend reads `mapping.json`.

It generates an ALIGN input netlist using:

```text
W=0.42 um
L=0.15 um
even NF
M=1
STACK=1
```

The ALIGN realization is saved separately so that backend quantization is never hidden.

### Stage 4B - ALIGN placement and routing

ALIGN is invoked from the OpenAMS shell using ALIGN's own interpreter:

```text
$HOME/AMS-Tutorial/ALIGN-public/.venv-align/bin/python
$HOME/AMS-Tutorial/ALIGN-public/.venv-align/bin/schematic2layout.py
```

Conceptually:

```bash
<ALIGN_PYTHON> <ALIGN_CLI> \
  <generated_align_input_dir> \
  -p SKY130_PDK \
  -w <align_work_dir>
```

The backend requires:

```text
OPENAMS_TWO_STAGE_0.gds
```

and rejects a non-empty:

```text
3_pnr/OPENAMS_TWO_STAGE_0.errors
```

### Stage 4C - Magic import and port restoration

ALIGN's GDS does not automatically provide the required Magic SPICE port ordering.

A reference file is created:

```spice
.subckt OPENAMS_TWO_STAGE_0 INP INN OUT VDD VSS VBIAS
.ends OPENAMS_TWO_STAGE_0
```

Magic then uses:

```tcl
gds read <ALIGN_GDS>
load OPENAMS_TWO_STAGE_0
readspice <reference_ports.spice>
extract all
ext2spice lvs
ext2spice subcircuit on
```

The extracted netlist must contain:

```spice
.subckt OPENAMS_TWO_STAGE_0 INP INN OUT VDD VSS VBIAS
```

### Stage 4D - Netgen LVS

ALIGN represents each large transistor as many `W=0.42 um, L=0.15 um` physical fingers.

The backend creates a finger-expanded reference schematic with the same ALIGN finger counts.

Because physical extraction can reverse MOS source/drain orientation, the Netgen setup is extended with:

```tcl
permute pins sky130_fd_pr__nfet_01v8_lvt D S
permute pins sky130_fd_pr__pfet_01v8 D S
```

The acceptance criterion is exact:

```text
Final result:
Circuits match uniquely.
```

If that string is absent, the physical flow fails.

### Stage 4E - Full flat RC extraction

The proven RCX sequence is:

```tcl
gds read <ALIGN_GDS>
load OPENAMS_TWO_STAGE_0
readspice <reference_ports.spice>

flatten OPENAMS_TWO_STAGE_FLAT
load OPENAMS_TWO_STAGE_FLAT

extract do unique
extract do resistance

extresist all
extresist extout on

extract all

ext2spice lvs
ext2spice subcircuit on
ext2spice cthresh 0
ext2spice extresist on

ext2spice -o <rcx_output.spice>
```

`extresist all` is important for analog characterization because it forces detailed resistance extraction for all logical nets, including internal N1, N2, and NTAIL.

During the expedition, the qualified reference run demonstrated:

```text
Total Nets: 9
Nets extracted: 9
Nets output: 9
```

### Stage 5 - Artifact validation

The wrapper requires:

```text
LVS PASS evidence exists
R count > 0
C count > 0
X count > 0
```

It then installs the RCX netlist as:

```text
netlist_post_layout.spice
```

and saves the ALIGN realization as:

```text
netlist_post_layout.align_realization.json
```

### Stage 6 - Current completion boundary

At present the one-command implementation certifies:

```text
sized input netlist
physical witness
ALIGN-compatible realization
ALIGN P&R
GDS
Magic extraction
Netgen LVS
full flat RCX
post-layout SPICE creation
```

It does **not yet certify post-layout `.op` and AC performance**.

The next extension is:

```text
netlist_post_layout.spice
        ↓
same testbench as pre-layout
        ↓
ngspice .op
        ↓
ngspice AC
        ↓
gain / UGB / phase margin / VOUT / power
        ↓
pre-layout versus post-layout delta
```

## Generated artifacts

With:

```text
--run-dir runtime/postlayout/two_stage
```

important artifacts include:

```text
runtime/postlayout/two_stage/
├── summary.json
├── physical_backend.log
├── 02_physical_mapping/
│   └── mapping.json
├── 03_layout/
│   ├── align/
│   └── align_input/
└── 04_pex/
    └── magic/
        ├── align_realization.json
        ├── lvs_report.out
        ├── openams_two_stage_with_ports.spice
        ├── openams_two_stage_xref.spice
        └── openams_two_stage_rcx_force_all.spice

repository root:
├── netlist_post_layout.spice
└── netlist_post_layout.align_realization.json
```

## Known warnings that are currently non-blocking

Magic reports several ALIGN GDS layer/datatype warnings such as:

```text
Unknown layer/datatype in boundary, layer=100 type=5
Unknown layer/datatype in boundary, layer=235 type=5
Unknown layer/datatype in boundary, layer=104 type=0
```

In the qualified run these warnings did not prevent:

```text
SKY130 MOS recognition
top-level extraction
LVS match
full 9-net RCX
```

They should remain documented and monitored. If a future run fails extraction or LVS, they must be reconsidered.

Netgen also prints property warnings for the model stubs. The acceptance criterion is the final unique circuit match, not warning-free output.

## Files installed in OpenAMS

The current implementation uses:

```text
tools/postlayout/openams_postlayout.py
tools/postlayout/run_align_magic_two_stage_dynamic.sh
```

The older fixed reference script:

```text
tools/postlayout/run_align_magic_two_stage.sh
```

was useful to freeze the expedition recipe but should not be the dynamic production backend.

## Installation commands

```bash
cd ~/AMS-Tutorial/openams

cp ~/Downloads/openams_postlayout_v5.py \
  tools/postlayout/openams_postlayout.py

cp ~/Downloads/run_align_magic_two_stage_dynamic.sh \
  tools/postlayout/run_align_magic_two_stage_dynamic.sh

chmod +x \
  tools/postlayout/openams_postlayout.py \
  tools/postlayout/run_align_magic_two_stage_dynamic.sh
```

## Recommended repository documentation location

Install this document as:

```text
docs/POST_LAYOUT_PIPELINE.md
```

The previously developed expedition document remains useful as historical/diagnostic background. This document should be the operational reproducibility guide.

## Final operational command

The command to remember is:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate

python tools/postlayout/openams_postlayout.py \
  examples/two_stage_opamp/generated/sized_netlist.spice \
  --output-netlist netlist_post_layout.spice \
  --run-dir runtime/postlayout/two_stage
```

Successful completion means the repository contains:

```text
netlist_post_layout.spice
```

whose physical implementation has passed ALIGN P&R, Magic extraction, Netgen LVS, and full flat RC extraction.

Post-layout ngspice `.op` and AC verification is the next required qualification stage.

---

# Appendix A - `tools/postlayout/openams_postlayout.py`

```python
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

```

# Appendix B - `tools/postlayout/run_align_magic_two_stage_dynamic.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

# Dynamic OpenAMS two-stage ALIGN -> Magic -> LVS -> full RCX backend.
#
# Required from openams_postlayout.py:
#   OPENAMS_ROOT
#   OPENAMS_PHYSICAL_MAPPING
#   OPENAMS_OUTPUT_NETLIST
#
# Optional:
#   ALIGN_PDK_ROOT
#   ALIGN_PYTHON
#   ALIGN_CLI
#   ALIGN_WORK
#   MAGIC_WORK
#   MAGIC_TECH
#   NETGEN_SETUP
#   ALIGN_UNIT_W_UM
#   ALIGN_L_UM
#   ALIGN_MAX_WIDTH_REL_ERROR

OPENAMS_ROOT="${OPENAMS_ROOT:-$HOME/AMS-Tutorial/openams}"
MAPPING="${OPENAMS_PHYSICAL_MAPPING:?OPENAMS_PHYSICAL_MAPPING is required}"
OUTPUT="${OPENAMS_OUTPUT_NETLIST:-$OPENAMS_ROOT/netlist_post_layout.spice}"

ALIGN_PDK_ROOT="${ALIGN_PDK_ROOT:-$HOME/AMS-Tutorial/ALIGN-pdk-sky130}"
ALIGN_PYTHON="${ALIGN_PYTHON:-$HOME/AMS-Tutorial/ALIGN-public/.venv-align/bin/python}"
ALIGN_CLI="${ALIGN_CLI:-$HOME/AMS-Tutorial/ALIGN-public/.venv-align/bin/schematic2layout.py}"

ALIGN_WORK="${ALIGN_WORK:-/tmp/openams_two_stage_align}"
MAGIC_WORK="${MAGIC_WORK:-/tmp/openams_two_stage_magic}"
ALIGN_INPUT_WORK="${ALIGN_INPUT_WORK:-$MAGIC_WORK/align_input}"

MAGIC_TECH="${MAGIC_TECH:-/usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech}"
NETGEN_SETUP="${NETGEN_SETUP:-/usr/local/share/pdk/sky130A/libs.tech/netgen/sky130A_setup.tcl}"

ALIGN_UNIT_W_UM="${ALIGN_UNIT_W_UM:-0.42}"
ALIGN_L_UM="${ALIGN_L_UM:-0.15}"
ALIGN_MAX_WIDTH_REL_ERROR="${ALIGN_MAX_WIDTH_REL_ERROR:-0.20}"

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: required command not found: $1" >&2
        exit 1
    }
}

need magic
need netgen
need python

[[ -x "$ALIGN_PYTHON" ]] || { echo "ERROR: ALIGN Python not found: $ALIGN_PYTHON" >&2; exit 1; }
[[ -f "$ALIGN_CLI" ]] || { echo "ERROR: ALIGN CLI not found: $ALIGN_CLI" >&2; exit 1; }
[[ -f "$MAPPING" ]] || { echo "ERROR: physical mapping not found: $MAPPING" >&2; exit 1; }
[[ -f "$MAGIC_TECH" ]] || { echo "ERROR: Magic tech not found: $MAGIC_TECH" >&2; exit 1; }
[[ -f "$NETGEN_SETUP" ]] || { echo "ERROR: Netgen setup not found: $NETGEN_SETUP" >&2; exit 1; }

CONST_SRC="$ALIGN_PDK_ROOT/examples/openams_two_stage/openams_two_stage.const.json"
[[ -f "$CONST_SRC" ]] || { echo "ERROR: ALIGN constraint file not found: $CONST_SRC" >&2; exit 1; }

rm -rf "$ALIGN_WORK" "$MAGIC_WORK"
mkdir -p "$ALIGN_WORK" "$MAGIC_WORK" "$ALIGN_INPUT_WORK" "$(dirname "$OUTPUT")"

echo "============================================================"
echo " OPENAMS DYNAMIC ALIGN -> MAGIC -> LVS -> RCX"
echo "============================================================"

echo
echo "[A1] Build ALIGN-compatible circuit from physical witness"

python - "$MAPPING" "$ALIGN_INPUT_WORK/openams_two_stage.sp" \
         "$MAGIC_WORK/align_realization.json" \
         "$MAGIC_WORK/openams_two_stage_xref.spice" \
         "$ALIGN_UNIT_W_UM" "$ALIGN_L_UM" "$ALIGN_MAX_WIDTH_REL_ERROR" <<'PY'
import json, math, sys
from pathlib import Path

mapping_path, spice_out, manifest_out, xref_out = map(Path, sys.argv[1:5])
unit_w = float(sys.argv[5])
align_l = float(sys.argv[6])
max_rel = float(sys.argv[7])

m = json.loads(mapping_path.read_text())
devs = m["devices"]

def even_nf_for(target_w):
    raw = target_w / unit_w
    nf = max(2, int(round(raw / 2.0)) * 2)
    return nf

align = {}
for name, d in devs.items():
    target = float(d["realized_w_um"])
    nf = even_nf_for(target)
    realized = unit_w * nf
    rel = abs(realized - target) / max(abs(target), 1e-30)
    if rel > max_rel:
        raise SystemExit(
            f"ERROR: {name}: ALIGN mapping error {100*rel:.2f}% exceeds "
            f"{100*max_rel:.2f}% (target={target}um, Wunit={unit_w}um, NF={nf})"
        )
    align[name] = {
        "target_w_um": target,
        "align_unit_w_um": unit_w,
        "align_l_um": align_l,
        "align_nf": nf,
        "align_realized_w_um": realized,
        "align_width_rel_error": rel,
    }

# Fixed two-stage topology; sizes come entirely from the selected physical witness.
sp = [
    ".subckt openams_two_stage inp inn out vdd vss vbias",
    "",
]
topo = {
    "M1": ("n1", "inp", "ntail", "vss", "sky130_fd_pr__nfet_01v8_lvt"),
    "M2": ("n2", "inn", "ntail", "vss", "sky130_fd_pr__nfet_01v8_lvt"),
    "M3": ("n1", "n1", "vdd", "vdd", "sky130_fd_pr__pfet_01v8"),
    "M4": ("n2", "n1", "vdd", "vdd", "sky130_fd_pr__pfet_01v8"),
    "M5": ("ntail", "vbias", "vss", "vss", "sky130_fd_pr__nfet_01v8_lvt"),
    "M6": ("out", "n2", "vdd", "vdd", "sky130_fd_pr__pfet_01v8"),
    "M7": ("out", "vbias", "vss", "vss", "sky130_fd_pr__nfet_01v8_lvt"),
}
for name in [f"M{i}" for i in range(1,8)]:
    d,g,s,b,model = topo[name]
    a = align[name]
    sp.append(
        f"{name} {d} {g} {s} {b} {model} "
        f"L={align_l*1e-6:.12g} W={unit_w*1e-6:.12g} "
        f"NF={a['align_nf']} M=1 STACK=1"
    )
sp += ["", ".ends openams_two_stage", ""]
spice_out.write_text("\n".join(sp))

manifest = {
    "physical_candidate_id": m.get("physical_candidate_id"),
    "source_physical_mapping": str(mapping_path),
    "align_unit_w_um": unit_w,
    "align_l_um": align_l,
    "devices": align,
}
manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

# Exact finger-expanded LVS reference corresponding to the ALIGN input.
lines = [
    ".subckt sky130_fd_pr__nfet_01v8_lvt D G S B",
    ".ends sky130_fd_pr__nfet_01v8_lvt",
    "",
    ".subckt sky130_fd_pr__pfet_01v8 D G S B",
    ".ends sky130_fd_pr__pfet_01v8",
    "",
    ".subckt OPENAMS_TWO_STAGE_0 INP INN OUT VDD VSS VBIAS",
]
def add(name, count, d, g, s, b, model):
    for i in range(count):
        lines.append(
            f"X{name}_{i} {d} {g} {s} {b} {model} "
            f"w={unit_w:g} l={align_l:g}"
        )
for name in [f"M{i}" for i in range(1,8)]:
    d,g,s,b,model = topo[name]
    add(name, align[name]["align_nf"], d.upper(), g.upper(), s.upper(), b.upper(), model)
lines.append(".ends OPENAMS_TWO_STAGE_0")
xref_out.write_text("\n".join(lines) + "\n")

print(f"physical_candidate_id: {m.get('physical_candidate_id')}")
for name in [f"M{i}" for i in range(1,8)]:
    a = align[name]
    print(
        f"  {name}: target={a['target_w_um']:g}um -> "
        f"ALIGN W={unit_w:g}um NF={a['align_nf']} -> "
        f"{a['align_realized_w_um']:g}um "
        f"(err={100*a['align_width_rel_error']:.2f}%)"
    )
print("total ALIGN fingers:", sum(a["align_nf"] for a in align.values()))
PY

cp "$CONST_SRC" "$ALIGN_INPUT_WORK/openams_two_stage.const.json"

echo
echo "[A2] ALIGN placement and routing"
(
    cd "$ALIGN_PDK_ROOT"
    "$ALIGN_PYTHON" "$ALIGN_CLI" \
        "$ALIGN_INPUT_WORK" \
        -p SKY130_PDK \
        -w "$ALIGN_WORK"
)

ALIGN_GDS="$ALIGN_WORK/OPENAMS_TWO_STAGE_0.gds"
ALIGN_ERRORS="$ALIGN_WORK/3_pnr/OPENAMS_TWO_STAGE_0.errors"
[[ -s "$ALIGN_GDS" ]] || { echo "ERROR: ALIGN GDS missing: $ALIGN_GDS" >&2; exit 1; }
if [[ -f "$ALIGN_ERRORS" && -s "$ALIGN_ERRORS" ]]; then
    echo "ERROR: ALIGN reported errors:" >&2
    cat "$ALIGN_ERRORS" >&2
    exit 1
fi
echo "PASS: ALIGN GDS $ALIGN_GDS"

echo
echo "[A3] Magic extraction + top-level ports"
cat > "$MAGIC_WORK/reference_ports.spice" <<'EOF'
.subckt OPENAMS_TWO_STAGE_0 INP INN OUT VDD VSS VBIAS
.ends OPENAMS_TWO_STAGE_0
EOF

cat > "$MAGIC_WORK/extract_lvs.tcl" <<EOF
gds read $ALIGN_GDS
load OPENAMS_TWO_STAGE_0
readspice $MAGIC_WORK/reference_ports.spice
extract all
ext2spice lvs
ext2spice subcircuit on
ext2spice -o $MAGIC_WORK/openams_two_stage_with_ports.spice
quit -noprompt
EOF

(
    cd "$MAGIC_WORK"
    magic -dnull -noconsole -T "$MAGIC_TECH" extract_lvs.tcl
)

grep -q '^\.subckt OPENAMS_TWO_STAGE_0 INP INN OUT VDD VSS VBIAS' \
    "$MAGIC_WORK/openams_two_stage_with_ports.spice" || {
    echo "ERROR: Magic top-level ports are incorrect" >&2
    exit 1
}

echo
echo "[A4] Netgen LVS"
cat > "$MAGIC_WORK/model_stubs.spice" <<'EOF'
.subckt sky130_fd_pr__nfet_01v8_lvt D G S B
.ends sky130_fd_pr__nfet_01v8_lvt
.subckt sky130_fd_pr__pfet_01v8 D G S B
.ends sky130_fd_pr__pfet_01v8
EOF

cat "$MAGIC_WORK/model_stubs.spice" \
    "$MAGIC_WORK/openams_two_stage_with_ports.spice" \
    > "$MAGIC_WORK/openams_two_stage_layout_lvs.spice"

cp "$NETGEN_SETUP" "$MAGIC_WORK/sky130A_openams_setup.tcl"
cat >> "$MAGIC_WORK/sky130A_openams_setup.tcl" <<'EOF'
permute pins sky130_fd_pr__nfet_01v8_lvt D S
permute pins sky130_fd_pr__pfet_01v8 D S
EOF

(
    cd "$MAGIC_WORK"
    netgen -batch lvs \
        "openams_two_stage_layout_lvs.spice OPENAMS_TWO_STAGE_0" \
        "openams_two_stage_xref.spice OPENAMS_TWO_STAGE_0" \
        sky130A_openams_setup.tcl \
        lvs_report.out
)
grep -q 'Circuits match uniquely' "$MAGIC_WORK/lvs_report.out" || {
    echo "ERROR: LVS did not match uniquely" >&2
    tail -100 "$MAGIC_WORK/lvs_report.out" >&2
    exit 1
}
echo "PASS: LVS circuits match uniquely"

echo
echo "[A5] Full flat Magic RCX"
cat > "$MAGIC_WORK/extract_rcx_force_all.tcl" <<EOF
gds read $ALIGN_GDS
load OPENAMS_TWO_STAGE_0
readspice $MAGIC_WORK/reference_ports.spice
flatten OPENAMS_TWO_STAGE_FLAT
load OPENAMS_TWO_STAGE_FLAT
extract do unique
extract do resistance
extresist all
extresist extout on
extract all
ext2spice lvs
ext2spice subcircuit on
ext2spice cthresh 0
ext2spice extresist on
ext2spice -o $MAGIC_WORK/openams_two_stage_rcx_force_all.spice
quit -noprompt
EOF

(
    cd "$MAGIC_WORK"
    rm -f OPENAMS_TWO_STAGE_FLAT.ext OPENAMS_TWO_STAGE_FLAT.res.ext
    magic -dnull -noconsole -T "$MAGIC_TECH" extract_rcx_force_all.tcl
)

RCX="$MAGIC_WORK/openams_two_stage_rcx_force_all.spice"
[[ -s "$RCX" ]] || { echo "ERROR: RCX netlist missing" >&2; exit 1; }

R_COUNT="$(grep -c '^R' "$RCX" || true)"
C_COUNT="$(grep -c '^C' "$RCX" || true)"
X_COUNT="$(grep -c '^X' "$RCX" || true)"
echo "PASS: RCX R=$R_COUNT C=$C_COUNT X=$X_COUNT"

cp "$RCX" "$OUTPUT"
cp "$MAGIC_WORK/align_realization.json" "${OUTPUT%.spice}.align_realization.json"

echo
echo "============================================================"
echo " DYNAMIC ALIGN PHYSICAL FLOW PASS"
echo "============================================================"
echo "Output: $OUTPUT"
echo "ALIGN realization: ${OUTPUT%.spice}.align_realization.json"

```

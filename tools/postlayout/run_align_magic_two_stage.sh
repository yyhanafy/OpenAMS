#!/usr/bin/env bash
set -euo pipefail

# OpenAMS two-stage ALIGN -> Magic -> LVS -> RCX post-layout flow.
#
# Usage:
#   bash tools/postlayout/run_align_magic_two_stage.sh
#
# Optional environment overrides:
#   OPENAMS_ROOT
#   ALIGN_PDK_ROOT
#   ALIGN_WORK
#   MAGIC_WORK
#   MAGIC_TECH
#   NETGEN_SETUP
#
# Assumptions:
#   - schematic2layout.py, magic, and netgen are on PATH.
#   - ALIGN example input exists at:
#       $ALIGN_PDK_ROOT/examples/openams_two_stage/openams_two_stage.sp
#   - The ALIGN-compatible netlist uses legal W/L and even NF.

OPENAMS_ROOT="${OPENAMS_ROOT:-$HOME/AMS-Tutorial/openams}"
ALIGN_PDK_ROOT="${ALIGN_PDK_ROOT:-$HOME/AMS-Tutorial/ALIGN-pdk-sky130}"
ALIGN_WORK="${ALIGN_WORK:-/tmp/openams_two_stage_align}"
MAGIC_WORK="${MAGIC_WORK:-/tmp/openams_two_stage_magic}"
MAGIC_TECH="${MAGIC_TECH:-/usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech}"
NETGEN_SETUP="${NETGEN_SETUP:-/usr/local/share/pdk/sky130A/libs.tech/netgen/sky130A_setup.tcl}"

ALIGN_INPUT="$ALIGN_PDK_ROOT/examples/openams_two_stage"
ALIGN_GDS="$ALIGN_WORK/OPENAMS_TWO_STAGE_0.gds"
ALIGN_ERRORS="$ALIGN_WORK/3_pnr/OPENAMS_TWO_STAGE_0.errors"

mkdir -p "$ALIGN_WORK" "$MAGIC_WORK"

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: required command not found: $1" >&2
        exit 1
    }
}

need magic
need netgen
need python

ALIGN_CLI="${ALIGN_CLI:-$HOME/AMS-Tutorial/ALIGN-public/.venv-align/bin/schematic2layout.py}"
ALIGN_PYTHON="${ALIGN_PYTHON:-$HOME/AMS-Tutorial/ALIGN-public/.venv-align/bin/python}"

[[ -x "$ALIGN_CLI" ]] || {
    echo "ERROR: ALIGN CLI not found: $ALIGN_CLI" >&2
    exit 1
}

[[ -x "$ALIGN_PYTHON" ]] || {
    echo "ERROR: ALIGN Python not found: $ALIGN_PYTHON" >&2
    exit 1
}

[[ -f "$ALIGN_INPUT/openams_two_stage.sp" ]] || {
    echo "ERROR: missing ALIGN input: $ALIGN_INPUT/openams_two_stage.sp" >&2
    exit 1
}
[[ -f "$MAGIC_TECH" ]] || {
    echo "ERROR: missing Magic technology file: $MAGIC_TECH" >&2
    exit 1
}
[[ -f "$NETGEN_SETUP" ]] || {
    echo "ERROR: missing Netgen setup: $NETGEN_SETUP" >&2
    exit 1
}

echo "============================================================"
echo " OPENAMS TWO-STAGE POST-LAYOUT FLOW: ALIGN -> LVS -> RCX"
echo "============================================================"

echo
echo "[1/6] ALIGN placement and routing"
rm -rf "$ALIGN_WORK"
mkdir -p "$ALIGN_WORK"

(
    cd "$ALIGN_PDK_ROOT"
    "$ALIGN_PYTHON" "$ALIGN_CLI" \
        examples/openams_two_stage \
        -p SKY130_PDK \
        -w "$ALIGN_WORK"
)

[[ -s "$ALIGN_GDS" ]] || {
    echo "ERROR: ALIGN did not produce $ALIGN_GDS" >&2
    exit 1
}

if [[ -f "$ALIGN_ERRORS" && -s "$ALIGN_ERRORS" ]]; then
    echo "ERROR: ALIGN reported physical-design errors:" >&2
    cat "$ALIGN_ERRORS" >&2
    exit 1
fi

echo "PASS: ALIGN GDS produced: $ALIGN_GDS"

echo
echo "[2/6] Prepare Magic port reference"

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
    echo "ERROR: extracted top-level ports are incorrect." >&2
    exit 1
}

echo "PASS: Magic extraction with correct top-level ports"

echo
echo "[3/6] Build exact 400-finger LVS reference"

cat > "$MAGIC_WORK/model_stubs.spice" <<'EOF'
.subckt sky130_fd_pr__nfet_01v8_lvt D G S B
.ends sky130_fd_pr__nfet_01v8_lvt

.subckt sky130_fd_pr__pfet_01v8 D G S B
.ends sky130_fd_pr__pfet_01v8
EOF

cat "$MAGIC_WORK/model_stubs.spice" \
    "$MAGIC_WORK/openams_two_stage_with_ports.spice" \
    > "$MAGIC_WORK/openams_two_stage_layout_lvs.spice"

python - "$MAGIC_WORK/openams_two_stage_xref.spice" <<'PY'
from pathlib import Path
import sys

out = Path(sys.argv[1])

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
            f"X{name}_{i} {d} {g} {s} {b} {model} w=0.42 l=0.15"
        )

add("M1",   2, "N1",    "INP",   "NTAIL", "VSS",
    "sky130_fd_pr__nfet_01v8_lvt")
add("M2",   2, "N2",    "INN",   "NTAIL", "VSS",
    "sky130_fd_pr__nfet_01v8_lvt")
add("M3", 120, "N1",    "N1",    "VDD",   "VDD",
    "sky130_fd_pr__pfet_01v8")
add("M4", 120, "N2",    "N1",    "VDD",   "VDD",
    "sky130_fd_pr__pfet_01v8")
add("M5",  30, "NTAIL", "VBIAS", "VSS",   "VSS",
    "sky130_fd_pr__nfet_01v8_lvt")
add("M6", 112, "OUT",   "N2",    "VDD",   "VDD",
    "sky130_fd_pr__pfet_01v8")
add("M7",  14, "OUT",   "VBIAS", "VSS",   "VSS",
    "sky130_fd_pr__nfet_01v8_lvt")

lines.append(".ends OPENAMS_TWO_STAGE_0")
out.write_text("\n".join(lines) + "\n")

print("physical MOS fingers:", 2 + 2 + 120 + 120 + 30 + 112 + 14)
PY

echo
echo "[4/6] Netgen LVS"

cp "$NETGEN_SETUP" "$MAGIC_WORK/sky130A_openams_setup.tcl"
cat >> "$MAGIC_WORK/sky130A_openams_setup.tcl" <<'EOF'

# OpenAMS/ALIGN extracted primitive stubs use named D/G/S/B pins.
# Allow MOS source/drain interchange during LVS normalization.
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

if ! grep -q 'Circuits match uniquely' "$MAGIC_WORK/lvs_report.out"; then
    echo "ERROR: LVS did not match uniquely." >&2
    tail -100 "$MAGIC_WORK/lvs_report.out" >&2
    exit 1
fi

echo "PASS: LVS circuits match uniquely"

echo
echo "[5/6] Full flat Magic RCX"

cat > "$MAGIC_WORK/extract_rcx_force_all.tcl" <<EOF
gds read $ALIGN_GDS
load OPENAMS_TWO_STAGE_0

readspice $MAGIC_WORK/reference_ports.spice

flatten OPENAMS_TWO_STAGE_FLAT
load OPENAMS_TWO_STAGE_FLAT

extract do unique
extract do resistance

# Analog characterization: force detailed R extraction on every net.
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
[[ -s "$RCX" ]] || {
    echo "ERROR: RCX netlist was not generated." >&2
    exit 1
}

R_COUNT="$(grep -c '^R' "$RCX" || true)"
C_COUNT="$(grep -c '^C' "$RCX" || true)"
X_COUNT="$(grep -c '^X' "$RCX" || true)"

echo "PASS: RCX generated"
echo "  R = $R_COUNT"
echo "  C = $C_COUNT"
echo "  X = $X_COUNT"

echo
echo "[6/6] Install post-layout netlist"

OUTPUT="$OPENAMS_ROOT/netlist_post_layout.spice"
cp "$RCX" "$OUTPUT"

echo "PASS: $OUTPUT"

echo
echo "===== PER-NET RESISTOR DIAGNOSTIC ====="

python - "$RCX" <<'PY'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text().splitlines()

nets = {
    "N1":    "a_200_561",
    "NTAIL": "a_316_4389",
    "N2":    "a_230_2079",
    "OUT":   "OUT",
    "VDD":   "VDD",
    "VSS":   "VSS",
    "VBIAS": "VBIAS",
    "INP":   "INP",
    "INN":   "INN",
}

print(f"{'NET':8s} {'R segments':>10s} {'sum R (ohm)':>15s}")

for logical, root in nets.items():
    count = 0
    total = 0.0

    for line in lines:
        if not line.startswith("R"):
            continue
        f = line.split()
        if len(f) < 4:
            continue

        n1, n2 = f[1], f[2]

        def belongs(n):
            return (
                n == root
                or n.startswith(root + ".n")
                or n.startswith(root + ".t")
            )

        if belongs(n1) or belongs(n2):
            count += 1
            try:
                total += float(f[3])
            except ValueError:
                pass

    print(f"{logical:8s} {count:10d} {total:15.6f}")
PY

echo
echo "============================================================"
echo " POST-LAYOUT PHYSICAL FLOW PASS"
echo "============================================================"
echo "ALIGN GDS : $ALIGN_GDS"
echo "LVS report: $MAGIC_WORK/lvs_report.out"
echo "RCX       : $RCX"
echo "Output    : $OUTPUT"
echo
echo "Next: run the same ngspice testbench used for the pre-layout"
echo "candidate, replacing only the DUT with the extracted subckt."

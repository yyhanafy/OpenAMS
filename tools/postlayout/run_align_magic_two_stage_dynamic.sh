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

#!/usr/bin/env bash
set -euo pipefail

# OpenAMS / Laygo2 / Magic bridge regression demo
# Proven flow:
#   Magic SKY130 PCell (W=10um, L=0.5um)
#      -> Laygo2 NativeInstanceTemplate
#      -> two placed instances
#      -> Laygo2 Magic export
#      -> Magic extraction
#      -> verify hierarchy + W/L preservation
#
# This is intentionally a reproducible regression of the proven experiment.
# The D/G/S/B abstract pin rectangles below are specific to this W=10um,
# L=0.5um, nf=1 generated cell. Generic pin abstraction is future work.

LAYGO2_WS="${LAYGO2_WS:-$HOME/AMS-Tutorial/laygo2_workspace_sky130}"
OPENAMS_ROOT="${OPENAMS_ROOT:-$HOME/AMS-Tutorial/openams}"
MAGIC_TECH="${MAGIC_TECH:-/usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech}"
OUT="${OUT:-/tmp/openams_laygo2_magic_bridge_demo}"
W_UM="${W_UM:-10.0}"
L_UM="${L_UM:-0.5}"
NF="${NF:-1}"

if [[ "$W_UM" != "10.0" || "$L_UM" != "0.5" || "$NF" != "1" ]]; then
  echo "ERROR: This regression script currently supports only W_UM=10.0, L_UM=0.5, NF=1"
  echo "       because the Laygo2 abstract pin rectangles are hard-coded from the proven cell."
  exit 2
fi

source "$OPENAMS_ROOT/.venv-openams/bin/activate"
cd "$LAYGO2_WS"
export PYTHONPATH="$PWD/laygo2:$PWD${PYTHONPATH:+:$PYTHONPATH}"

rm -rf "$OUT"
mkdir -p "$OUT/device" "$OUT/layout/openams_magic" "$OUT/layout/openams_test"

echo "===== 1. GENERATE MAGIC SKY130 NFET ====="
cat > "$OUT/generate_nfet.tcl" <<EOF_TCL
source /usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tcl
load NFET_TOP
box values 0 0 1 1
magic::gencell \\
    sky130::sky130_fd_pr__nfet_01v8 \\
    MTEST \\
    w $W_UM \\
    l $L_UM \\
    nf $NF \\
    m 1
set child ""
foreach c [cellname list allcells] {
    if {[string match "sky130_fd_pr__nfet_01v8_*" \$c]} {
        set child \$c
    }
}
puts "CHILD=\$child"
load \$child
save \${child}.mag
extract all
ext2spice lvs
ext2spice -o $OUT/device/NFET.spice
quit -noprompt
EOF_TCL

cd "$OUT/device"
magic -dnull -noconsole -T "$MAGIC_TECH" "$OUT/generate_nfet.tcl" | tee "$OUT/generate_nfet.log"

CHILD_MAG=$(find "$OUT/device" -maxdepth 1 -name 'sky130_fd_pr__nfet_01v8_*.mag' | head -1)
if [[ -z "${CHILD_MAG:-}" ]]; then
  echo "ERROR: Magic child .mag file was not generated"
  exit 3
fi
CHILD=$(basename "$CHILD_MAG" .mag)
echo "CHILD=$CHILD"

if ! grep -qE 'w=10([ .]|$).*l=0\.5([ .]|$)' "$OUT/device/NFET.spice"; then
  echo "ERROR: Magic extraction did not preserve w=10 l=0.5"
  cat "$OUT/device/NFET.spice"
  exit 4
fi

echo "PASS: Magic extracted w=10 l=0.5"

# Laygo2 Magic interface expects <libname>_<cellname>.mag
cp "$CHILD_MAG" "$OUT/layout/openams_magic/openams_magic_${CHILD}.mag"
# Keeping a same-directory copy avoids Magic search-path ambiguity during export.
cp "$CHILD_MAG" "$OUT/layout/openams_test/openams_magic_${CHILD}.mag"

export OPENAMS_MAGIC_CHILD="$CHILD"
export OPENAMS_BRIDGE_OUT="$OUT"

echo
echo "===== 2. BUILD LAYGO2 EXTERNAL TEMPLATE + PLACE TWO DEVICES ====="
cat > "$OUT/export_two_nfets.py" <<'PY'
import os
import numpy as np
import laygo2
import laygo2.object
import laygo2.interface.magic

child = os.environ["OPENAMS_MAGIC_CHILD"]
out = os.environ["OPENAMS_BRIDGE_OUT"]

# Abstract pin rectangles derived from the proven Magic W=10um/L=0.5um/nf=1 cell.
# Magic physical bbox: [-125,-607] -> [125,607]
# Normalized Laygo2 bbox: [0,0] -> [250,1214]
pins = {
    "D": laygo2.object.Pin(
        xy=np.array([[156,105],[174,1109]]),
        layer=["locali","pin"], netname="D"),
    "G": laygo2.object.Pin(
        xy=np.array([[100,70],[150,88]]),
        layer=["locali","pin"], netname="G"),
    "S": laygo2.object.Pin(
        xy=np.array([[76,105],[94,1109]]),
        layer=["locali","pin"], netname="S"),
    "B": laygo2.object.Pin(
        xy=np.array([[18,19],[67,36]]),
        layer=["locali","pin"], netname="B"),
}

tnfet = laygo2.object.template.NativeInstanceTemplate(
    libname="openams_magic",
    cellname=child,
    bbox=np.array([[0,0],[250,1214]]),
    pins=pins,
)

m0 = tnfet.generate(name="M0")
m1 = tnfet.generate(name="M1")
m0.xy = np.array([0,0])
m1.xy = np.array([400,0])

dsn = laygo2.object.database.Design(name="two_nfet", libname="openams_test")
dsn.append(m0)
dsn.append(m1)
lib = laygo2.object.database.Library(name="openams_test")
lib.append(dsn)

laygo2.interface.magic.export(
    lib,
    filename=f"{out}/export_two_nfets.tcl",
    cellname="two_nfet",
    libpath=f"{out}/layout",
    scale=1,
    tech_library="sky130A",
    gds_filename=f"{out}/two_nfets.gds",
)
with open(f"{out}/export_two_nfets.tcl", "a") as f:
    f.write("\nquit -noprompt\n")

print("M0", m0.xy.tolist(), {k:v.xy.tolist() for k,v in m0.pins.items()})
print("M1", m1.xy.tolist(), {k:v.xy.tolist() for k,v in m1.pins.items()})
print("LAYGO2 TEMPLATE/PLACEMENT PASS")
PY

cd "$LAYGO2_WS"
python3 "$OUT/export_two_nfets.py" | tee "$OUT/laygo2.log"

if [[ $(grep -c '_laygo2_generate_instance M[01] ' "$OUT/export_two_nfets.tcl") -ne 2 ]]; then
  echo "ERROR: Laygo2 did not emit two external Magic instance commands"
  exit 5
fi

echo "PASS: Laygo2 emitted M0 and M1"

echo
echo "===== 3. EXECUTE LAYGO2-GENERATED MAGIC EXPORT ====="
cd "$OUT/layout/openams_test"
magic -dnull -noconsole -T "$MAGIC_TECH" "$OUT/export_two_nfets.tcl" | tee "$OUT/magic_export.log"

TOP_MAG="$OUT/layout/openams_test/openams_test_two_nfet.mag"
if [[ ! -f "$TOP_MAG" ]]; then
  echo "ERROR: top-level .mag was not generated"
  exit 6
fi
if [[ $(grep -c '^use openams_magic_.*  M[01]$' "$TOP_MAG") -ne 2 ]]; then
  echo "ERROR: top-level Magic cell does not contain both M0 and M1"
  cat "$TOP_MAG"
  exit 7
fi

echo "PASS: top-level Magic layout contains M0 and M1"

echo
echo "===== 4. MAGIC EXTRACTION OF COMBINED LAYOUT ====="
cat > "$OUT/extract_two_nfets.tcl" <<EOF_TCL
load openams_test_two_nfet
extract all
ext2spice lvs
ext2spice -o $OUT/two_nfets_extracted.spice
quit -noprompt
EOF_TCL

magic -dnull -noconsole -T "$MAGIC_TECH" "$OUT/extract_two_nfets.tcl" | tee "$OUT/extract.log"

if [[ ! -f "$OUT/two_nfets_extracted.spice" ]]; then
  echo "ERROR: extracted SPICE was not generated"
  exit 8
fi

if [[ $(grep -c '^XM[01] SUB openams_magic_' "$OUT/two_nfets_extracted.spice") -ne 2 ]]; then
  echo "ERROR: extracted top-level SPICE does not contain both hierarchical instances"
  cat "$OUT/two_nfets_extracted.spice"
  exit 9
fi

if ! grep -qE 'sky130_fd_pr__nfet_01v8 .*w=10 l=0\.5' "$OUT/two_nfets_extracted.spice"; then
  echo "ERROR: extracted child MOS does not preserve w=10 l=0.5"
  cat "$OUT/two_nfets_extracted.spice"
  exit 10
fi

echo
echo "===== FINAL RESULT ====="
echo "PASS: Magic generated W=10um L=0.5um"
echo "PASS: Laygo2 accepted the Magic device as a NativeInstanceTemplate"
echo "PASS: Laygo2 placed two external device instances"
echo "PASS: Laygo2 -> Magic export created the hierarchical physical layout"
echo "PASS: Magic extraction recovered two hierarchical instances"
echo "PASS: physical MOS geometry remained w=10 l=0.5"
echo
echo "Artifacts: $OUT"
echo "Extracted SPICE: $OUT/two_nfets_extracted.spice"
echo "GDS: $OUT/two_nfets.gds"

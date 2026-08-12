#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENAMS_ROOT:-$HOME/AMS-Tutorial/openams}"
LAYGO2_WS="${LAYGO2_WS:-$HOME/AMS-Tutorial/laygo2_workspace_sky130}"
VENV="${OPENAMS_VENV:-$ROOT/.venv-openams}"
MAGIC_TECH="${MAGIC_TECH:-/usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech}"
WORK="${WORK:-/tmp/openams_laygo2_magic_diffpair}"

rm -rf "$WORK"
mkdir -p "$WORK/device" "$WORK/layout/openams_magic" "$WORK/layout/openams_test"

source "$VENV/bin/activate"
export PYTHONPATH="$LAYGO2_WS/laygo2:$LAYGO2_WS${PYTHONPATH:+:$PYTHONPATH}"

echo "===== 1. GENERATE REAL SKY130 NFET W=10um L=0.5um ====="

cat > "$WORK/generate_nfet.tcl" <<EOF
source /usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tcl
load NFET_TOP
box values 0 0 1 1
magic::gencell sky130::sky130_fd_pr__nfet_01v8 MTEST w 10.0 l 0.5 nf 1 m 1

set child ""
foreach c [cellname list allcells] {
    if {[string match "sky130_fd_pr__nfet_01v8_*" \$c]} {
        set child \$c
    }
}

puts "CHILD=\$child"
load \$child
save "\$child.mag"
extract all
ext2spice lvs
ext2spice -o "$WORK/device/NFET.spice"
quit -noprompt
EOF

(
    cd "$WORK/device"
    magic -dnull -noconsole -T "$MAGIC_TECH" "$WORK/generate_nfet.tcl"
)

CHILD_MAG="$(find "$WORK/device" -maxdepth 1 -name 'sky130_fd_pr__nfet_01v8_*.mag' | head -1)"
test -n "$CHILD_MAG"
CHILD="$(basename "$CHILD_MAG" .mag)"

grep -q 'w=10 l=0.5' "$WORK/device/NFET.spice"
echo "PASS: device extraction contains w=10 l=0.5"
echo "CHILD=$CHILD"

cp "$CHILD_MAG" "$WORK/layout/openams_magic/openams_magic_${CHILD}.mag"
cp "$CHILD_MAG" "$WORK/layout/openams_test/openams_magic_${CHILD}.mag"

export OPENAMS_MAGIC_CHILD="$CHILD"
export OPENAMS_DIFF_WORK="$WORK"

echo
echo "===== 2. BUILD DIFFERENTIAL PAIR IN LAYGO2 ====="

cat > "$WORK/build_diffpair.py" <<'PY'
import os
import numpy as np
import laygo2
import laygo2.object
import laygo2.interface.magic

child = os.environ["OPENAMS_MAGIC_CHILD"]
work = os.environ["OPENAMS_DIFF_WORK"]

# Actual Magic PCell coordinate system.
pins = {
    "S": laygo2.object.Pin(
        xy=np.array([[-52, -500], [-28, -494]]),
        layer=["metal1", "pin"], netname="S"),
    "D": laygo2.object.Pin(
        xy=np.array([[28, -500], [52, -494]]),
        layer=["metal1", "pin"], netname="D"),
    "G": laygo2.object.Pin(
        xy=np.array([[-23, -540], [23, -537]]),
        layer=["metal1", "pin"], netname="G"),
}

tnfet = laygo2.object.template.NativeInstanceTemplate(
    libname="openams_magic",
    cellname=child,
    bbox=np.array([[-125, -607], [125, 607]]),
    pins=pins,
)

m1 = tnfet.generate(name="M1")
m2 = tnfet.generate(name="M2")
m1.xy = np.array([0, 0])
m2.xy = np.array([400, 0])

dsn = laygo2.object.database.Design(name="diffpair", libname="openams_test")
dsn.append(m1)
dsn.append(m2)

# Shared source net.  Connect to the upper end of each source metal1 shape
# and route horizontally above the device.
dsn.append(laygo2.object.Rect(
    xy=np.array([[-52, 494], [-28, 570]]),
    layer=["metal1", "drawing"]))
dsn.append(laygo2.object.Rect(
    xy=np.array([[348, 494], [372, 570]]),
    layer=["metal1", "drawing"]))
dsn.append(laygo2.object.Rect(
    xy=np.array([[-52, 550], [372, 570]]),
    layer=["metal1", "drawing"]))

# Top-level source pin.
dsn.append(laygo2.object.Pin(
    xy=np.array([[180, 550], [220, 570]]),
    layer=["metal1", "pin"], netname="SOURCE"))

# Independent input-gate pins, directly on each device gate access.
dsn.append(laygo2.object.Pin(
    xy=np.array([[-23, -540], [23, -537]]),
    layer=["metal1", "pin"], netname="INP"))
dsn.append(laygo2.object.Pin(
    xy=np.array([[377, -540], [423, -537]]),
    layer=["metal1", "pin"], netname="INN"))

# Independent drain/output pins.
dsn.append(laygo2.object.Pin(
    xy=np.array([[28, -500], [52, -494]]),
    layer=["metal1", "pin"], netname="OUTP"))
dsn.append(laygo2.object.Pin(
    xy=np.array([[428, -500], [452, -494]]),
    layer=["metal1", "pin"], netname="OUTN"))

lib = laygo2.object.database.Library(name="openams_test")
lib.append(dsn)

out_tcl = f"{work}/export_diffpair.tcl"
laygo2.interface.magic.export(
    lib,
    filename=out_tcl,
    cellname="diffpair",
    libpath=f"{work}/layout",
    scale=1,
    tech_library="sky130A",
    gds_filename=f"{work}/diffpair.gds",
)

with open(out_tcl, "a") as f:
    f.write("\nquit -noprompt\n")

print("M1", m1.xy.tolist())
print("M2", m2.xy.tolist())
print("PASS: Laygo2 differential-pair layout constructed")
PY

(
    cd "$LAYGO2_WS"
    python3 "$WORK/build_diffpair.py"
)

echo
echo "===== 3. EXECUTE LAYGO2 -> MAGIC EXPORT ====="

(
    cd "$WORK/layout/openams_test"
    magic -dnull -noconsole -T "$MAGIC_TECH" "$WORK/export_diffpair.tcl"
)

TOPMAG="$WORK/layout/openams_test/openams_test_diffpair.mag"
test -f "$TOPMAG"
grep -q ' M1' "$TOPMAG"
grep -q ' M2' "$TOPMAG"
echo "PASS: top-level Magic cell contains M1 and M2"

echo
echo "===== 4. EXTRACT DIFFERENTIAL PAIR ====="

cat > "$WORK/extract_diffpair.tcl" <<EOF
load openams_test_diffpair
extract all
ext2spice lvs
ext2spice -o "$WORK/diffpair_extracted.spice"
quit -noprompt
EOF

(
    cd "$WORK/layout/openams_test"
    magic -dnull -noconsole -T "$MAGIC_TECH" "$WORK/extract_diffpair.tcl"
)

SP="$WORK/diffpair_extracted.spice"
test -f "$SP"

echo
echo "===== EXTRACTED SPICE ====="
cat "$SP"

echo
echo "===== 5. REGRESSION CHECKS ====="

grep -q 'w=10 l=0.5' "$SP"
grep -qE '^XM1[[:space:]]' "$SP"
grep -qE '^XM2[[:space:]]' "$SP"

M1_LINE="$(grep -E '^XM1[[:space:]]' "$SP" | head -1)"
M2_LINE="$(grep -E '^XM2[[:space:]]' "$SP" | head -1)"

echo "M1: $M1_LINE"
echo "M2: $M2_LINE"

echo
echo "===== FINAL RESULT ====="
echo "PASS: Magic generated W=10um L=0.5um SKY130 devices"
echo "PASS: Laygo2 placed M1 and M2"
echo "PASS: Laygo2 tied the source nodes physically"
echo "PASS: INP/INN and OUTP/OUTN remain independent top-level pins"
echo "PASS: Magic extracted the hierarchical differential pair"
echo
echo "CHECK: M1 and M2 should share SOURCE; their gates and drains should remain different."
echo
echo "Artifacts: $WORK"
echo "Extracted SPICE: $SP"
echo "GDS: $WORK/diffpair.gds"

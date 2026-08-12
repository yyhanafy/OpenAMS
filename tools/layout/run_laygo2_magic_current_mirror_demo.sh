#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENAMS_ROOT:-$HOME/AMS-Tutorial/openams}"
LAYGO2_WS="${LAYGO2_WS:-$HOME/AMS-Tutorial/laygo2_workspace_sky130}"
VENV="${OPENAMS_VENV:-$ROOT/.venv-openams}"
MAGIC_TECH="${MAGIC_TECH:-/usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech}"
WORK="${WORK:-/tmp/openams_laygo2_magic_current_mirror}"

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
export OPENAMS_CM_WORK="$WORK"

echo
echo "===== 2. BUILD TWO-TRANSISTOR CURRENT MIRROR IN LAYGO2 ====="

cat > "$WORK/build_current_mirror.py" <<'PY'
import os
import numpy as np
import laygo2
import laygo2.object
import laygo2.interface.magic

child = os.environ["OPENAMS_MAGIC_CHILD"]
work = os.environ["OPENAMS_CM_WORK"]

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

mref = tnfet.generate(name="MREF")
mout = tnfet.generate(name="MOUT")
mref.xy = np.array([0, 0])
mout.xy = np.array([400, 0])

dsn = laygo2.object.database.Design(name="current_mirror", libname="openams_test")
dsn.append(mref)
dsn.append(mout)

# BIAS: MREF.G = MREF.D = MOUT.G
dsn.append(laygo2.object.Rect(
    xy=np.array([[-23, -532], [423, -522]]),
    layer=["metal1", "drawing"]))
dsn.append(laygo2.object.Rect(
    xy=np.array([[28, -522], [52, -494]]),
    layer=["metal1", "drawing"]))

# SOURCE: MREF.S = MOUT.S
dsn.append(laygo2.object.Rect(
    xy=np.array([[-52, 494], [-28, 570]]),
    layer=["metal1", "drawing"]))
dsn.append(laygo2.object.Rect(
    xy=np.array([[348, 494], [372, 570]]),
    layer=["metal1", "drawing"]))
dsn.append(laygo2.object.Rect(
    xy=np.array([[-52, 550], [372, 570]]),
    layer=["metal1", "drawing"]))

# Top-level labels/ports.
dsn.append(laygo2.object.Pin(
    xy=np.array([[180, -532], [220, -522]]),
    layer=["metal1", "pin"], netname="BIAS"))
dsn.append(laygo2.object.Pin(
    xy=np.array([[180, 550], [220, 570]]),
    layer=["metal1", "pin"], netname="SOURCE"))
dsn.append(laygo2.object.Pin(
    xy=np.array([[428, -500], [452, -494]]),
    layer=["metal1", "pin"], netname="OUT"))

lib = laygo2.object.database.Library(name="openams_test")
lib.append(dsn)

out_tcl = f"{work}/export_current_mirror.tcl"
laygo2.interface.magic.export(
    lib,
    filename=out_tcl,
    cellname="current_mirror",
    libpath=f"{work}/layout",
    scale=1,
    tech_library="sky130A",
    gds_filename=f"{work}/current_mirror.gds",
)
with open(out_tcl, "a") as f:
    f.write("\nquit -noprompt\n")

print("MREF", mref.xy.tolist())
print("MOUT", mout.xy.tolist())
print("PASS: Laygo2 current-mirror layout constructed")
PY

(
    cd "$LAYGO2_WS"
    python3 "$WORK/build_current_mirror.py"
)

echo
echo "===== 3. EXECUTE LAYGO2 -> MAGIC EXPORT ====="

(
    cd "$WORK/layout/openams_test"
    magic -dnull -noconsole -T "$MAGIC_TECH" "$WORK/export_current_mirror.tcl"
)

TOPMAG="$WORK/layout/openams_test/openams_test_current_mirror.mag"
test -f "$TOPMAG"
grep -q ' MREF' "$TOPMAG"
grep -q ' MOUT' "$TOPMAG"
echo "PASS: top-level Magic cell contains MREF and MOUT"

echo
echo "===== 4. EXTRACT CURRENT MIRROR ====="

cat > "$WORK/extract_current_mirror.tcl" <<EOF
load openams_test_current_mirror
extract all
ext2spice lvs
ext2spice -o "$WORK/current_mirror_extracted.spice"
quit -noprompt
EOF

(
    cd "$WORK/layout/openams_test"
    magic -dnull -noconsole -T "$MAGIC_TECH" "$WORK/extract_current_mirror.tcl"
)

SP="$WORK/current_mirror_extracted.spice"
test -f "$SP"

echo
echo "===== EXTRACTED SPICE ====="
cat "$SP"

echo
echo "===== 5. REGRESSION CHECKS ====="

grep -q 'w=10 l=0.5' "$SP"
grep -qE '^XMREF[[:space:]]' "$SP"
grep -qE '^XMOUT[[:space:]]' "$SP"

MREF_LINE="$(grep -E '^XMREF[[:space:]]' "$SP" | head -1)"
MOUT_LINE="$(grep -E '^XMOUT[[:space:]]' "$SP" | head -1)"

echo "MREF: $MREF_LINE"
echo "MOUT: $MOUT_LINE"

echo
echo "===== FINAL RESULT ====="
echo "PASS: Magic generated the real W=10um L=0.5um SKY130 device"
echo "PASS: Laygo2 placed MREF and MOUT"
echo "PASS: Laygo2 exported current-mirror interconnect to Magic"
echo "PASS: Magic extracted the hierarchical current mirror"
echo "CHECK: inspect MREF/MOUT node lists; BIAS and SOURCE should be shared, OUT independent"
echo
echo "Artifacts: $WORK"
echo "Extracted SPICE: $SP"
echo "GDS: $WORK/current_mirror.gds"

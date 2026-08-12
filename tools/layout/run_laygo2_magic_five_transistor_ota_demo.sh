#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENAMS_ROOT:-$HOME/AMS-Tutorial/openams}"
LAYGO2_WS="${LAYGO2_WS:-$HOME/AMS-Tutorial/laygo2_workspace_sky130}"
VENV="${OPENAMS_VENV:-$ROOT/.venv-openams}"
MAGIC_TECH="${MAGIC_TECH:-/usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech}"
WORK="${WORK:-/tmp/openams_laygo2_magic_five_transistor_ota}"

rm -rf "$WORK"
mkdir -p \
  "$WORK/device_n" \
  "$WORK/device_p" \
  "$WORK/layout/openams_magic" \
  "$WORK/layout/openams_test"

source "$VENV/bin/activate"
export PYTHONPATH="$LAYGO2_WS/laygo2:$LAYGO2_WS${PYTHONPATH:+:$PYTHONPATH}"

echo "===== 1. GENERATE REAL SKY130 NMOS + PMOS ====="

cat > "$WORK/generate_devices.tcl" <<EOF
source /usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tcl

# ---------------- NMOS ----------------
load NFET_TOP
box values 0 0 1 1
magic::gencell sky130::sky130_fd_pr__nfet_01v8 MNDEV w 10.0 l 0.5 nf 1 m 1

set nchild ""
foreach c [cellname list allcells] {
    if {[string match "sky130_fd_pr__nfet_01v8_*" \$c]} {
        set nchild \$c
    }
}
puts "NCHILD=\$nchild"
load \$nchild
save "$WORK/device_n/\$nchild.mag"
extract all
ext2spice lvs
ext2spice -o "$WORK/device_n/NFET.spice"

# ---------------- PMOS ----------------
load PFET_TOP
box values 0 0 1 1
magic::gencell sky130::sky130_fd_pr__pfet_01v8 MPDEV w 10.0 l 0.5 nf 1 m 1

set pchild ""
foreach c [cellname list allcells] {
    if {[string match "sky130_fd_pr__pfet_01v8_*" \$c]} {
        set pchild \$c
    }
}
puts "PCHILD=\$pchild"
load \$pchild
save "$WORK/device_p/\$pchild.mag"
extract all
ext2spice lvs
ext2spice -o "$WORK/device_p/PFET.spice"

quit -noprompt
EOF

(
  cd "$WORK"
  magic -dnull -noconsole -T "$MAGIC_TECH" "$WORK/generate_devices.tcl"
)

NCHILD_MAG="$(find "$WORK/device_n" -maxdepth 1 -name 'sky130_fd_pr__nfet_01v8_*.mag' | head -1)"
PCHILD_MAG="$(find "$WORK/device_p" -maxdepth 1 -name 'sky130_fd_pr__pfet_01v8_*.mag' | head -1)"

test -n "$NCHILD_MAG"
test -n "$PCHILD_MAG"

NCHILD="$(basename "$NCHILD_MAG" .mag)"
PCHILD="$(basename "$PCHILD_MAG" .mag)"

grep -q 'w=10 l=0.5' "$WORK/device_n/NFET.spice"
grep -q 'w=10 l=0.5' "$WORK/device_p/PFET.spice"

echo "PASS: NMOS extraction contains w=10 l=0.5"
echo "PASS: PMOS extraction contains w=10 l=0.5"
echo "NCHILD=$NCHILD"
echo "PCHILD=$PCHILD"

# Laygo2 Magic exporter expects <libname>_<cellname>.mag.
for d in openams_magic openams_test; do
  cp "$NCHILD_MAG" "$WORK/layout/$d/openams_magic_${NCHILD}.mag"
  cp "$PCHILD_MAG" "$WORK/layout/$d/openams_magic_${PCHILD}.mag"
done

export OPENAMS_OTA_NCHILD="$NCHILD"
export OPENAMS_OTA_PCHILD="$PCHILD"
export OPENAMS_OTA_WORK="$WORK"

echo
echo "===== 2. BUILD FIVE-TRANSISTOR OTA IN LAYGO2 ====="

cat > "$WORK/build_five_transistor_ota.py" <<'PY'
import os
import numpy as np
import laygo2
import laygo2.object
import laygo2.interface.magic

nchild = os.environ["OPENAMS_OTA_NCHILD"]
pchild = os.environ["OPENAMS_OTA_PCHILD"]
work = os.environ["OPENAMS_OTA_WORK"]

# Proven Magic MOS physical access rectangles.
# These use the actual Magic PCell coordinate system.
mos_pins = {
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

tn = laygo2.object.template.NativeInstanceTemplate(
    libname="openams_magic",
    cellname=nchild,
    bbox=np.array([[-125, -607], [125, 607]]),
    pins=mos_pins,
)

tp = laygo2.object.template.NativeInstanceTemplate(
    libname="openams_magic",
    cellname=pchild,
    bbox=np.array([[-125, -607], [125, 607]]),
    pins=mos_pins,
)

# ------------------------------------------------------------
# Placement
#
# PM3             PM4
#
# NM1             NM2
#
#          NM5
#
# All cells are kept R0 for this first topology regression.
# ------------------------------------------------------------

m1 = tn.generate(name="M1")
m2 = tn.generate(name="M2")
m3 = tp.generate(name="M3")
m4 = tp.generate(name="M4")
m5 = tn.generate(name="M5")

m1.xy = np.array([0, 0])
m2.xy = np.array([400, 0])
m3.xy = np.array([0, 1600])
m4.xy = np.array([400, 1600])
m5.xy = np.array([200, -1600])

dsn = laygo2.object.database.Design(
    name="five_transistor_ota",
    libname="openams_test",
)

for inst in (m1, m2, m3, m4, m5):
    dsn.append(inst)

# Helper.
def rect(x1, y1, x2, y2, layer="metal1"):
    dsn.append(laygo2.object.Rect(
        xy=np.array([[x1, y1], [x2, y2]]),
        layer=[layer, "drawing"],
    ))

def pin(name, x1, y1, x2, y2, layer="metal1"):
    dsn.append(laygo2.object.Pin(
        xy=np.array([[x1, y1], [x2, y2]]),
        layer=[layer, "pin"],
        netname=name,
    ))

# ============================================================
# NTAIL:
# M1.S = M2.S = M5.D
# ============================================================

# M1/M2 source access routed DOWNWARD to avoid crossing the
# M1 drain / N1 vertical spine on metal1.
rect(-52, -700, -28, -494)
rect(348, -700, 372, -494)

# Shared NTAIL bus below the input pair.
rect(-52, -720, 372, -700)

# M5 drain access:
# M5 xy=(200,-1600), D local [28,-500]..[52,-494]
# => [228,-2100]..[252,-2094]
# route upward only to the NTAIL bus.
rect(228, -2100, 252, -700)

# ============================================================
# LEFT NODE N1:
# M1.D = M3.D = M3.G = M4.G
# diode-connected PM3 + mirror gate
# ============================================================

# M1 drain lower access.
rect(28, -500, 52, -250)

# M3 drain: translation (0,1600) -> [28,1100]..[52,1106]
rect(28, 1100, 52, 1350)

# vertical N1 spine
rect(28, -250, 52, 1350)

# M3 gate: [-23,1060]..[23,1063]
rect(-23, 1050, 52, 1075)

# M4 gate: [377,1060]..[423,1063]
rect(-23, 1050, 423, 1075)

# ============================================================
# OUTPUT:
# M2.D = M4.D
# ============================================================

# M2 drain [428,-500]..[452,-494]
rect(428, -500, 452, 1350)

# M4 drain [428,1100]..[452,1106]
# already reached by the same spine.

# ============================================================
# VDD:
# M3.S = M4.S
# ============================================================

# M3 source [-52,2094]..[-28,2100]
rect(-52, 2094, -28, 2250)

# M4 source [348,2094]..[372,2100]
rect(348, 2094, 372, 2250)

rect(-52, 2230, 372, 2250)

# ============================================================
# VSS:
# M5.S
# ============================================================

# M5 source = [148,-2100]..[172,-2094]
rect(148, -2250, 172, -2094)

# ============================================================
# VBIAS:
# M5.G
# ============================================================

# M5 gate = [177,-2140]..[223,-2137]
rect(177, -2145, 223, -2125)

# ============================================================
# INP / INN:
# M1.G / M2.G
# ============================================================

# Leave gate shapes independent, just expose pins.

# ============================================================
# Top-level pins
# ============================================================

pin("INP", -23, -540, 23, -537)
pin("INN", 377, -540, 423, -537)
pin("OUT", 428, 600, 452, 650)
pin("VDD", 150, 2230, 200, 2250)
pin("VSS", 148, -2250, 172, -2225)
pin("VBIAS", 177, -2145, 223, -2125)

lib = laygo2.object.database.Library(name="openams_test")
lib.append(dsn)

out_tcl = f"{work}/export_five_transistor_ota.tcl"

laygo2.interface.magic.export(
    lib,
    filename=out_tcl,
    cellname="five_transistor_ota",
    libpath=f"{work}/layout",
    scale=1,
    tech_library="sky130A",
    gds_filename=f"{work}/five_transistor_ota.gds",
)

with open(out_tcl, "a") as f:
    f.write("\nquit -noprompt\n")

for inst in (m1, m2, m3, m4, m5):
    print(inst.name, inst.xy.tolist())

print("PASS: Laygo2 five-transistor OTA layout constructed")
PY

(
  cd "$LAYGO2_WS"
  python3 "$WORK/build_five_transistor_ota.py"
)

echo
echo "===== 3. EXECUTE LAYGO2 -> MAGIC EXPORT ====="

(
  cd "$WORK/layout/openams_test"
  magic -dnull -noconsole -T "$MAGIC_TECH" "$WORK/export_five_transistor_ota.tcl"
)

TOPMAG="$WORK/layout/openams_test/openams_test_five_transistor_ota.mag"
test -f "$TOPMAG"

for m in M1 M2 M3 M4 M5; do
  grep -q " $m" "$TOPMAG"
done

echo "PASS: top-level Magic layout contains M1..M5"

echo
echo "===== 4. MAGIC EXTRACTION ====="

cat > "$WORK/extract_five_transistor_ota.tcl" <<EOF
load openams_test_five_transistor_ota
extract all
ext2spice lvs
ext2spice -o "$WORK/five_transistor_ota_extracted.spice"
quit -noprompt
EOF

(
  cd "$WORK/layout/openams_test"
  magic -dnull -noconsole -T "$MAGIC_TECH" "$WORK/extract_five_transistor_ota.tcl"
)

SP="$WORK/five_transistor_ota_extracted.spice"
test -f "$SP"

echo
echo "===== EXTRACTED SPICE ====="
cat "$SP"

echo
echo "===== 5. TOPOLOGY REGRESSION ====="

for m in M1 M2 M3 M4 M5; do
  grep -qE "^X${m}[[:space:]]" "$SP"
done

M1_LINE="$(grep -E '^XM1[[:space:]]' "$SP" | head -1)"
M2_LINE="$(grep -E '^XM2[[:space:]]' "$SP" | head -1)"
M3_LINE="$(grep -E '^XM3[[:space:]]' "$SP" | head -1)"
M4_LINE="$(grep -E '^XM4[[:space:]]' "$SP" | head -1)"
M5_LINE="$(grep -E '^XM5[[:space:]]' "$SP" | head -1)"

echo "M1: $M1_LINE"
echo "M2: $M2_LINE"
echo "M3: $M3_LINE"
echo "M4: $M4_LINE"
echo "M5: $M5_LINE"

# ------------------------------------------------------------
# Automatic topology checks.
#
# Extracted hierarchical instance ordering observed for these
# Magic-generated cells:
#
#   NMOS:  S D B G <subckt>
#   PMOS:  G S D   <subckt>   (bulk is internal to PMOS child)
#
# The checks below are deliberately based on node relationships,
# not on Magic's generated internal node names.
# ------------------------------------------------------------
read -r _ M1_S M1_D M1_B M1_G _ <<< "$M1_LINE"
read -r _ M2_S M2_D M2_B M2_G _ <<< "$M2_LINE"
read -r _ M3_G M3_S M3_D _ <<< "$M3_LINE"
read -r _ M4_G M4_S M4_D _ <<< "$M4_LINE"
read -r _ M5_S M5_D M5_B M5_G _ <<< "$M5_LINE"

test "$M1_G" = "INP"
test "$M2_G" = "INN"

# Critical regression: M1 drain and source must NOT be shorted.
if [ "$M1_D" = "$M1_S" ]; then
  echo "FAIL: M1 drain/source short detected: $M1_D"
  exit 1
fi

# Shared tail node.
test "$M1_S" = "$M2_S"
test "$M1_S" = "$M5_D"

# Left mirror/reference node.
test "$M1_D" = "$M3_D"
test "$M1_D" = "$M3_G"
test "$M1_D" = "$M4_G"

# Output node.
test "$M2_D" = "OUT"
test "$M4_D" = "OUT"

# Supplies / bias.
test "$M3_S" = "VDD"
test "$M4_S" = "VDD"
test "$M5_S" = "VSS"
test "$M5_G" = "VBIAS"

echo "PASS: extracted OTA topology matches intended five-transistor connectivity"

echo
echo "===== FINAL RESULT ====="
echo "PASS: Magic generated real SKY130 NMOS/PMOS devices at W=10um L=0.5um"
echo "PASS: Laygo2 placed five externally generated devices"
echo "PASS: Laygo2 exported the OTA interconnect to Magic"
echo "PASS: Magic extracted the hierarchical five-transistor OTA"
echo "PASS: M1 drain/source are distinct"
echo "PASS: M1.S=M2.S=M5.D"
echo "PASS: M1.D=M3.D=M3.G=M4.G"
echo "PASS: M2.D=M4.D=OUT"
echo "PASS: M3.S=M4.S=VDD"
echo "PASS: M5.S=VSS"
echo "PASS: M5.G=VBIAS"
echo
echo "Artifacts: $WORK"
echo "Extracted SPICE: $SP"
echo "GDS: $WORK/five_transistor_ota.gds"

#!/usr/bin/env bash
set -euo pipefail

WORK="${WORK:-/tmp/openams_laygo2_magic_two_stage_opamp}"
SP="$WORK/two_stage_opamp_extracted.spice"
OUTDIR="$WORK/exploratory_ac"

mkdir -p "$OUTDIR"
test -f "$SP"

cat > "$OUTDIR/two_stage_exploratory.spice" <<'EOF'
* OpenAMS exploratory post-layout two-stage op-amp test
* Equal-sized W=10um/L=0.5um devices; not a final design point.

.lib /usr/local/share/pdk/sky130A/libs.tech/ngspice/sky130.lib.spice tt
.include /tmp/openams_laygo2_magic_two_stage_opamp/two_stage_opamp_extracted.spice

VDD VDD 0 1.8
VSS VSS 0 0

* Common-mode inputs. Differential AC is applied on INP only for this exploratory test.
VINP INP 0 DC 0.8 AC 1
VINN INN 0 DC 0.8 AC 0

* Tail / second-stage bias.
VBIAS VBIAS 0 0.6

* Exploratory ideal compensation/load capacitors.
CC N2 OUT 1p
CL OUT 0 1p

XOP INN INP N2 OUT VBIAS VDD VSS openams_test_two_stage_opamp

.control
set noaskquit

echo
echo ===== VBIAS SWEEP =====
dc VBIAS 0.35 1.00 0.025
wrdata /tmp/openams_laygo2_magic_two_stage_opamp/exploratory_ac/vbias_sweep.dat v(VBIAS) v(N2) v(OUT) i(VDD)

alter VBIAS 0.6
op

echo
echo ===== NOMINAL OP @ VBIAS=0.6V =====
print v(INP) v(INN) v(N2) v(OUT) i(VDD)

echo
echo ===== AC SWEEP =====
ac dec 50 1 1e10
wrdata /tmp/openams_laygo2_magic_two_stage_opamp/exploratory_ac/ac.dat frequency vdb(OUT) vp(OUT)

quit
.endc

.end
EOF

ngspice -b "$OUTDIR/two_stage_exploratory.spice"

echo
echo "Artifacts:"
echo "  $OUTDIR/vbias_sweep.dat"
echo "  $OUTDIR/ac.dat"

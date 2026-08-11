#!/usr/bin/env bash
set -euo pipefail

# Reproduce the authors' published LDO1 ngspice environment.
# Requires a local SKY130A open_pdks installation.

REPO_DIR=${1:-sky130_ldo_rl}

if [ ! -d "$REPO_DIR/.git" ]; then
  git clone https://github.com/ChrisZonghaoLi/sky130_ldo_rl.git "$REPO_DIR"
fi

cd "$REPO_DIR/python/simulations"

# The checked-in ldo_tb.spice contains absolute paths from the authors' machine
# for ldo_tb_analysis.spice and ldo_tb_vars.spice. Patch only those include paths
# to local relative paths; the circuit itself is unchanged.
sed -i 's#^\.include /autofs/.*/ldo_tb_analysis\.spice#.include ldo_tb_analysis.spice#' ldo_tb.spice
sed -i 's#^\.include /autofs/.*/ldo_tb_vars\.spice#.include ldo_tb_vars.spice#' ldo_tb.spice

# If your PDK is installed under /usr/share/pdk rather than /usr/local/share/pdk,
# adjust only the four SKY130 include prefixes in ldo_tb.spice before running.
ngspice -b -o ldo_tb.reproduction.log ldo_tb.spice

echo "Done. Key generated outputs include:"
echo "  ldo_tb_dc"
echo "  ldo_tb_load_reg"
echo "  ldo_tb_load_reg_current"
echo "  ldo_tb_loop_gain_minload"
echo "  ldo_tb_loop_gain_maxload"
echo "  ldo_tb_psrr_minload"
echo "  ldo_tb_psrr_maxload"
echo "  ldo_tb.reproduction.log"

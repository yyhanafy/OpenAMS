#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# When copied into the current OpenAMS repository, ROOT should be that repo.
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${1:-$HOME/openams_pipeline_pre_clean_${STAMP}.tar.gz}"
cd "$ROOT"

CANDIDATES=(
  pyproject.toml
  README.md
  docs/OPENAMS_PRODUCTION_PIPELINE.md
  src/openams
  scripts
  tools/validation
  tools/technology
  examples/two_stage_opamp/inputs
  examples/two_stage_opamp/generated
  examples/folded_cascode/inputs
  examples/folded_cascode/generated
  technology
  runtime/mlp_dense_validation
  runtime/two_stage_all_2025_mlp_witnesses.csv
  runtime/two_stage_best100_ngspice_dc_ac_validation_v6.csv
  runtime/folded_cascode_all_2025_generic_mlp_witnesses.csv
  MVP_archive_July_30/technology/train_sky130_mos_mlp.py
  MVP_archive_July_30/tools/technology/train_sky130_mlp.py
  MVP_archive_July_30/runtime/mlp_validation/sky130_nmos_mlp.pt
  MVP_archive_July_30/runtime/mlp_validation/sky130_pmos_mlp.pt
)

EXISTING=()
for path in "${CANDIDATES[@]}"; do
  [[ -e "$path" ]] && EXISTING+=("$path")
done

if [[ ${#EXISTING[@]} -eq 0 ]]; then
  echo "No pipeline files found under $ROOT" >&2
  exit 1
fi

tar -czf "$OUT" "${EXISTING[@]}"
echo "Created: $OUT"
ls -lh "$OUT"

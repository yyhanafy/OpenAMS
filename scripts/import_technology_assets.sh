#!/usr/bin/env bash
set -euo pipefail
TARGET="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${1:?usage: scripts/import_technology_assets.sh /path/to/current/openams}"
SOURCE="$(cd "$SOURCE" && pwd)"

copy_if_present() {
  local src="$1" dst="$2"
  if [[ -e "$src" ]]; then
    mkdir -p "$(dirname "$dst")"
    cp -a "$src" "$dst"
    echo "[COPIED] $src -> $dst"
  else
    echo "[MISSING] $src"
  fi
}

copy_if_present "$SOURCE/technology/sky130_tt_27c_mlp_dense.csv" \
                "$TARGET/technology/sky130_tt_27c_mlp_dense.csv"
copy_if_present "$SOURCE/technology/sky130_tt_27c_mlp_dense.csv.metadata.json" \
                "$TARGET/technology/sky130_tt_27c_mlp_dense.csv.metadata.json"
copy_if_present "$SOURCE/technology/train_sky130_mos_mlp.py" \
                "$TARGET/technology/train_sky130_mos_mlp.py"

copy_if_present "$SOURCE/MVP_archive_July_30/technology/train_sky130_mos_mlp.py" \
                "$TARGET/archive_manifest/MVP_archive_July_30/technology/train_sky130_mos_mlp.py"
copy_if_present "$SOURCE/MVP_archive_July_30/tools/technology/train_sky130_mlp.py" \
                "$TARGET/archive_manifest/MVP_archive_July_30/tools/technology/train_sky130_mlp.py"
copy_if_present "$SOURCE/MVP_archive_July_30/runtime/mlp_validation/sky130_nmos_mlp.pt" \
                "$TARGET/archive_manifest/MVP_archive_July_30/runtime/mlp_validation/sky130_nmos_mlp.pt"
copy_if_present "$SOURCE/MVP_archive_July_30/runtime/mlp_validation/sky130_pmos_mlp.pt" \
                "$TARGET/archive_manifest/MVP_archive_July_30/runtime/mlp_validation/sky130_pmos_mlp.pt"

# Preserve current technology-generation tools as reference until one canonical
# table generator is explicitly identified.
if [[ -d "$SOURCE/tools/technology" ]]; then
  mkdir -p "$TARGET/archive_manifest/current_tools"
  cp -a "$SOURCE/tools/technology" "$TARGET/archive_manifest/current_tools/"
  echo "[COPIED] current tools/technology reference"
else
  echo "[MISSING] $SOURCE/tools/technology"
fi

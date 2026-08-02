#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SOURCE_DIR="${REPO_ROOT}/examples/two_stage_opamp/generated/assignment_synthesis/coarse_independent_ac_scan_v3_reproduced"

BENCHMARK_ROOT="${REPO_ROOT}/benchmarks"

BENCHMARK_NAME="two_stage_opamp_deterministic_constructor_v1"

DEST_DIR="${BENCHMARK_ROOT}/${BENCHMARK_NAME}"

FILES=(
coarse_scan_results.csv
coarse_scan_summary.json
COARSE_SCAN_REPORT.md
constructed_assignments.jsonl
run_configuration.json
run.log
)

echo
echo "===== Freeze OpenAMS Benchmark ====="
echo

test -d "$SOURCE_DIR" || {
    echo "[FAIL] source benchmark not found"
    exit 1
}

test ! -e "$DEST_DIR" || {
    echo "[FAIL] destination already exists"
    exit 1
}

mkdir -p "$DEST_DIR"

for f in "${FILES[@]}"; do
    cp "$SOURCE_DIR/$f" "$DEST_DIR/"
done

(
cd "$DEST_DIR"

sha256sum "${FILES[@]}" > SHA256SUMS
)

python3 <<'PY'
import csv
import json
from pathlib import Path

root=Path("benchmarks/two_stage_opamp_deterministic_constructor_v1")

rows=list(csv.DictReader(open(root/"coarse_scan_results.csv")))

passed=sum(r["status"]=="PASS" for r in rows)
rejected=sum(r["status"]=="REJECT" for r in rows)

assert len(rows)==10000
assert passed==6555
assert rejected==3445

manifest={
    "status":"FROZEN",
    "rows":len(rows),
    "constructed":passed,
    "rejected":rejected
}

(root/"benchmark_manifest.json").write_text(
    json.dumps(manifest,indent=2)
)
PY

cat > "${DEST_DIR}/README.md" <<EOF
# OpenAMS Frozen Benchmark V1

This directory is immutable.

Expected invariants

- Rows: 10000
- Constructed: 6555
- Rejected: 3445

Verify integrity

    sha256sum -c SHA256SUMS
EOF

chmod -R a-w "$DEST_DIR"

echo
echo "[PASS] benchmark frozen"

echo
echo "$DEST_DIR"


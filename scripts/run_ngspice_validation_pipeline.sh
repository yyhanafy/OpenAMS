#!/usr/bin/env bash
#
# OpenAMS Benchmark V1 ngspice Validation Pipeline
#
# Validation stages:
#
#   Stage 1  Select representative benchmark points
#   Stage 2  Generate ngspice decks
#   Stage 3  DC validation
#   Stage 4  AC validation
#   Stage 5  Specification validation
#   Stage 6  Aggregate reports
#
# This script never modifies the frozen benchmark.
#

set -euo pipefail

################################################################################
# Configuration
################################################################################

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"

BENCHMARK_DIR="${REPO_ROOT}/benchmarks/two_stage_opamp_deterministic_constructor_v1"

VALIDATION_DIR="${REPO_ROOT}/validation/ngspice/two_stage_opamp_benchmark_v1"

POINTS=100

SEED=7

################################################################################

echo
echo "========================================================="
echo " OpenAMS Benchmark V1 ngspice Validation Pipeline"
echo "========================================================="
echo

################################################################################
# Verify benchmark
################################################################################

if [[ ! -d "${BENCHMARK_DIR}" ]]; then
    echo "[FAIL] Frozen benchmark not found."
    exit 1
fi

echo "[PASS] benchmark found"

################################################################################
# Verify benchmark hashes
################################################################################

pushd "${BENCHMARK_DIR}" >/dev/null

sha256sum -c SHA256SUMS
sha256sum -c MANIFEST_SHA256SUMS

popd >/dev/null

################################################################################
# Prepare output directory
################################################################################

mkdir -p "${VALIDATION_DIR}"

################################################################################
# Stage 1
################################################################################

echo
echo "========================================================="
echo " Stage 1 : Selecting benchmark points"
echo "========================================================="
echo

python tools/validation/select_validation_points.py \
    --benchmark "${BENCHMARK_DIR}" \
    --output "${VALIDATION_DIR}" \
    --count "${POINTS}" \
    --seed "${SEED}"

################################################################################
# Stage 2
################################################################################

echo
echo "========================================================="
echo " Stage 2 : Building ngspice decks"
echo "========================================================="
echo

python tools/validation/build_validation_decks.py \
    --benchmark "${BENCHMARK_DIR}" \
    --selection "${VALIDATION_DIR}/selected_points.csv" \
    --output "${VALIDATION_DIR}/points"

################################################################################
# Stage 3
################################################################################

echo
echo "========================================================="
echo " Stage 3 : DC validation"
echo "========================================================="
echo

python tools/validation/run_ngspice_dc_validation.py \
    --points "${VALIDATION_DIR}/points"

################################################################################
# Stage 4
################################################################################

echo
echo "========================================================="
echo " Stage 4 : AC validation"
echo "========================================================="
echo

python tools/validation/run_ngspice_ac_validation.py \
    --points "${VALIDATION_DIR}/points"

################################################################################
# Stage 5
################################################################################

echo
echo "========================================================="
echo " Stage 5 : Specification comparison"
echo "========================================================="
echo

python tools/validation/evaluate_specification_validation.py \
    --points "${VALIDATION_DIR}/points"

################################################################################
# Stage 6
################################################################################

echo
echo "========================================================="
echo " Stage 6 : Aggregate reports"
echo "========================================================="
echo

python tools/validation/build_validation_summary.py \
    --benchmark "${BENCHMARK_DIR}" \
    --validation "${VALIDATION_DIR}"

################################################################################

echo
echo "========================================================="
echo " Validation complete"
echo "========================================================="
echo

echo "Results"

echo "  ${VALIDATION_DIR}"

echo

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
root="${OUT:-$PWD/proof/runs/$(date -u +%Y%m%dT%H%M%S)-suite-$$}"
mkdir -p "$root"
root=$(realpath "$root")
stage_seconds="${STAGE_DURATION:-15s}"
# Exploration is sequential; rejected stages are retained and do not stop the ladder.
for workers in ${LADDER:-16 64 256 1024}; do
  set +e
  MODE=active VUS="$workers" DURATION="$stage_seconds" OUT="$root/active-$workers" scripts/benchmark.sh
  status=$?
  set -e
  printf '%s %s\n' "$workers" "$status" >> "$root/ladder-status.txt"
done
# Explicit selection prevents silently turning a failed stage into a capacity claim.
if [[ -n ${HOLD_VUS:-} ]]; then
  MODE=active VUS="$HOLD_VUS" DURATION="${HOLD_DURATION:-5m}" OUT="$root/active-hold" scripts/benchmark.sh
fi
if [[ -n ${ORIGINAL_VUS:-} ]]; then
  MODE=original VUS="$ORIGINAL_VUS" DURATION="${ORIGINAL_DURATION:-5m}" RAMP_UP="${RAMP_UP:-60s}" OUT="$root/original-hold" scripts/benchmark.sh
fi
if [[ -n ${OPEN_RATE:-} ]]; then
  MODE=open RATE="$OPEN_RATE" VUS="${OPEN_VUS:-256}" MAX_VUS="${OPEN_MAX_VUS:-1024}" DURATION="${OPEN_DURATION:-60s}" OUT="$root/open-confirmation" scripts/benchmark.sh
fi
printf 'Suite evidence: %s\n' "$root"

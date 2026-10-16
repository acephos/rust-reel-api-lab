#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MODE="${MODE:-active}" VUS="${VUS:-16}" DURATION="${DURATION:-15s}"
export BASE_URL="${BASE_URL:-http://127.0.0.1:3000}"
export TOKENS="${TOKENS:-$PWD/third_party/challenge/seed/tokens.json}"
[[ -s "$TOKENS" ]] || { echo 'Generate challenge seed/tokens.json before benchmarking.' >&2; exit 1; }
if [[ -n ${SERVER_PID:-} ]]; then kill -0 "$SERVER_PID"; fi
k6=$(scripts/install-k6.sh)
stamp=$(date -u +%Y%m%dT%H%M%S)
out="${OUT:-$PWD/proof/runs/${stamp}-${MODE}-${VUS}vu-$$}"
mkdir -p "$out"
out=$(realpath "$out")
[[ ! -e "$out/exit-code" && ! -e "$out/raw-reference.json" ]] || { echo "Refusing to overwrite run $out" >&2; exit 1; }
raw_dir="${RAW_DIR:-$PWD/.tools/benchmark-raw/$(basename "$out")-$$}"
mkdir -p "$raw_dir"
raw="$(realpath "$raw_dir")/raw.json.gz"
[[ ! -e "$raw" ]] || { echo "Refusing to overwrite raw evidence $raw" >&2; exit 1; }
export SUMMARY_PATH="$out/summary.json"
port=$(python -c 'from urllib.parse import urlsplit; import os; u=urlsplit(os.environ["BASE_URL"]); print(u.port or (443 if u.scheme=="https" else 80))')
pid_args=()
if [[ -n ${SERVER_PID:-} ]]; then pid_args=(--pid "$SERVER_PID"); fi
python bench/evidence.py machine "${pid_args[@]}" --k6 "$k6" > "$out/machine.json"
printf '%q ' "$k6" run --out "json=$raw" bench/load.js > "$out/command.txt"
printf '\n' >> "$out/command.txt"
date -u +%FT%TZ > "$out/started-utc"
"$k6" run --out "json=$raw" bench/load.js > "$out/k6.log" 2>&1 &
client=$!
python bench/evidence.py sample "${pid_args[@]}" --client "$client" --port "$port" > "$out/resources.jsonl" &
sampler=$!
cleanup() { kill "$client" "$sampler" 2>/dev/null || true; }
trap cleanup INT TERM
set +e
wait "$client"
status=$?
set -e
kill "$sampler" 2>/dev/null || true
wait "$sampler" 2>/dev/null || true
trap - INT TERM
printf '%s\n' "$status" > "$out/exit-code"
date -u +%FT%TZ > "$out/finished-utc"
if [[ -s "$out/summary.json" && -s "$raw" ]]; then
  python bench/evidence.py report "$out" --raw "$raw" > "$out/report.log"
  if ! python -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))["passed_all_checks"] else 1)' "$out/accounting.json"; then
    [[ "$status" != 0 ]] || status=1
  fi
else
  [[ "$status" != 0 ]] || status=1
fi
printf '%s\n' "$status" > "$out/final-exit-code"
(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tail -n 70 "$out/k6.log"
printf '\nEvidence: %s\nExit status: %s\n' "$out" "$status"
exit "$status"

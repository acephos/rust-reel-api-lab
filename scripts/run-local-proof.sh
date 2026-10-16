#!/usr/bin/env bash
# Sequential full proof on fresh, private SQLite copies. Leaves the phone demo alone.
set -euo pipefail
cd "$(dirname "$0")/.."
root="${OUT:-$PWD/proof/runs}"
mkdir -p "$root"
root=$(realpath "$root")
fixture=$(mktemp -d)
pid=''
cleanup() { if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi; rm -rf "$fixture"; }
trap cleanup EXIT
export BASE_URL="http://127.0.0.1:${PROOF_PORT:-3120}"
export HOST=127.0.0.1 PORT="${PROOF_PORT:-3120}" JWT_SECRET=twelve-dollar-challenge
unset DEMO_CONFIG_PATH DEMO_PROOF_PATH
seed="$PWD/third_party/challenge/seed/feed.db"
start_server() {
  cp "$seed" "$fixture/$1.db"
  export SQLITE_PATH="$fixture/$1.db"
  target/release/twelve-rust-poll > "$root/$1-server.log" 2>&1 &
  pid=$!
  export SERVER_PID="$pid"
  for _ in {1..100}; do
    kill -0 "$pid"
    if curl -fsS "$BASE_URL/health" > /dev/null 2>&1; then return; fi
    sleep 0.1
  done
  echo 'Server readiness deadline exceeded' >&2
  return 1
}
stop_server() { kill "$pid"; wait "$pid" 2>/dev/null || true; pid=''; }
start_server active
MODE=active VUS="${ACTIVE_VUS:-1024}" DURATION=5m OUT="$root/active-hold" scripts/benchmark.sh
stop_server
python3 scripts/check-loaded-database.py --seed "$seed" --database "$fixture/active.db" --run "$root/active-hold" > "$root/active-database-check.json"
start_server original
MODE=original VUS=1000 RAMP_UP=1s RAMP_DOWN=1s DURATION=2m OUT="$root/original-warmup" scripts/benchmark.sh
MODE=original VUS="${BROWSING_VUS:-5000}" RAMP_UP=60s RAMP_DOWN=30s DURATION=5m OUT="$root/original-hold" scripts/benchmark.sh
stop_server
python3 scripts/check-loaded-database.py --seed "$seed" --database "$fixture/original.db" --run "$root/original-warmup" --run "$root/original-hold" > "$root/original-database-check.json"
start_server open
MODE=open RATE="${OPEN_RATE:-5000}" VUS=256 MAX_VUS=1024 DURATION=60s OUT="$root/open-confirmation" scripts/benchmark.sh
stop_server
python3 scripts/check-loaded-database.py --seed "$seed" --database "$fixture/open.db" --run "$root/open-confirmation" > "$root/open-database-check.json"
python3 bench/http-concurrency.py --run "$root/active-hold" --output docs/proof/http-active.json
python3 scripts/summarize-proof.py --active "$root/active-hold" --users "$root/original-hold" --open "$root/open-confirmation"

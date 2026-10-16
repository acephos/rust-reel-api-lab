#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p docs/proof
fixture=$(mktemp -d)
server_pid=''
cleanup() { if [[ -n "$server_pid" ]]; then kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true; fi; rm -rf "$fixture"; }
trap cleanup EXIT
cp third_party/challenge/seed/feed.db "$fixture/feed.db"
export HOST=127.0.0.1 PORT="${PORT:-3100}" SQLITE_PATH="$fixture/feed.db" JWT_SECRET=twelve-dollar-challenge
unset DEMO_CONFIG_PATH DEMO_PROOF_PATH
./target/release/twelve-rust-poll "$@" > "$fixture/server.log" 2>&1 &
server_pid=$!
for _ in {1..100}; do
  if curl -fsS "http://$HOST:$PORT/health" > /dev/null 2>&1; then break; fi
  sleep 0.1
done
bash third_party/challenge/test/test.sh "http://$HOST:$PORT"

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data run
if [[ ! -f data/demo.db ]]; then
  cp third_party/challenge/seed/feed.db data/demo.db
fi
python3 - <<'PY'
import json
from pathlib import Path
sample=json.loads(Path('third_party/challenge/seed/tokens.json').read_text())[0]
Path('data/demo-config.json').write_text(json.dumps({**sample,'user_id':sample.get('id',1)}))
PY
export HOST="${HOST:-0.0.0.0}" PORT="${PORT:-8080}"
export SQLITE_PATH="$PWD/data/demo.db" JWT_SECRET=twelve-dollar-challenge
export DEMO_CONFIG_PATH="$PWD/data/demo-config.json" DEMO_PROOF_PATH="$PWD/docs/proof/demo.json"
exec target/release/twelve-rust-poll "$@"

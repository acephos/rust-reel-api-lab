#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Uses the unmodified upstream generator and verifies all rows against its hash.
bash third_party/challenge/seed/make-seed.sh

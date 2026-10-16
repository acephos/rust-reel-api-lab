#!/usr/bin/env bash
# Linux setup guide. Installs no global tools automatically.
set -euo pipefail
for tool in cc curl python3 sqlite3 jq openssl node; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Install your distro's package, then retry." >&2; exit 1; }
done
export PATH="${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
command -v rustup >/dev/null || { echo 'Install rustup from https://rustup.rs, then rerun.' >&2; exit 1; }
rustup toolchain install 1.98.1 --profile minimal --component rustfmt --component clippy

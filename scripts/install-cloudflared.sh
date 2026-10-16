#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .tools
version=2026.10.1
expected=3bfc539f45d2620c71debb7a86be0efa737ed5ccbad9eb85c787116900e5c586
curl -fL --retry 2 "https://github.com/cloudflare/cloudflared/releases/download/$version/cloudflared-linux-amd64" -o .tools/cloudflared
printf '%s  %s\n' "$expected" .tools/cloudflared | sha256sum -c -
chmod +x .tools/cloudflared

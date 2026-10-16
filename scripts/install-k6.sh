#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
version=v2.3.0
archive="k6-${version}-linux-amd64.tar.gz"
expected=39c3117b6af817592dcd0ce4242105c0a7af10948c2a425306f0be8f7a8a8ab1
dest=".tools/k6-${version}"
[[ $(uname -m) == x86_64 ]] || { echo 'This pinned installer targets Linux x86_64.' >&2; exit 1; }
mkdir -p "$dest"
if [[ -x "$dest/k6" && -f "$dest/binary.sha256" ]] && (cd "$dest" && sha256sum -c --status binary.sha256); then
  printf '%s\n' "$PWD/$dest/k6"
  exit 0
fi
base="https://github.com/grafana/k6/releases/download/${version}"
curl -fsSL --retry 3 "$base/k6-${version}-checksums.txt" -o "$dest/release-checksums.txt"
official=$(awk -v name="$archive" '$2 == name { print $1 }' "$dest/release-checksums.txt")
[[ "$official" == "$expected" ]] || { echo 'Official checksum differs from repository pin.' >&2; exit 1; }
curl -fL --retry 3 "$base/$archive" -o "$dest/$archive"
printf '%s  %s\n' "$expected" "$dest/$archive" | sha256sum -c - >&2
tar -xzf "$dest/$archive" -C "$dest" --strip-components=1 "k6-${version}-linux-amd64/k6"
(cd "$dest" && sha256sum k6 > binary.sha256)
"$dest/k6" version >&2
printf '%s\n' "$PWD/$dest/k6"

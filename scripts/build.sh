#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
mkdir -p vendor
checksum=0e9483900e92cd5de8fd48d16bf9200145a61f7fd5be542a5ac81d8a9516eb9c
if [[ ! -f vendor/sqlite3.c || ! -f vendor/sqlite3.h ]]; then
  curl -fL --retry 3 https://www.sqlite.org/2026/sqlite-autoconf-3530400.tar.gz -o vendor/sqlite.tar.gz
  printf '%s  %s\n' "$checksum" vendor/sqlite.tar.gz | sha256sum -c -
  tar -xzf vendor/sqlite.tar.gz -C vendor --strip-components=1 sqlite-autoconf-3530400/sqlite3.c sqlite-autoconf-3530400/sqlite3.h
  rm vendor/sqlite.tar.gz
fi
printf '%s  %s\n' \
  b1dd5d74ec7f29055a6684fa06fb3c2f6821c87dd38f9a458dfd2e8a1db28189 vendor/sqlite3.c \
  919e7f2e8ed1d8f56ac17b412b8971c76aa5d1a879752cc6058f75e7d5910e1d vendor/sqlite3.h \
  | sha256sum -c -
export RUSTFLAGS="-C target-cpu=native ${RUSTFLAGS:-}"
cargo build --release --locked "$@"

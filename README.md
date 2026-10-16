# Rust Reel API Lab

A working Rust implementation and reproducible study of [Arjay McCandless's SQLite/io_uring API reel](https://www.instagram.com/reel/Deh4spFuAdz/). It serves a social feed, posts and likes over HTTP/1.1, with a responsive live demo, API explorer, and measured-capacity view.

The optimized engine is **derived from the MIT-licensed submission featured in the reel**, pinned to PR#19 revision `bd517fa7c8a57b135579ae02fdddb6196b4cd9a4`. Credit belongs to its original authors. This project adds the study, reproducible setup, demo, additional tests, independent reviews and proof collected on this machine. See [provenance/licenses](THIRD_PARTY.md) and [what changed](docs/review.md).

## Measured on this machine

On this Ryzen 5 5600H laptop, a five minute hold served **2,048 active workers at 10,497 validated requests/s**, with zero errors. HTTP transport overlap was **744 mean / 2,048 peak**; client-operation counts are reported separately. Full request p95/p99 were 235/323ms. Separately, 5,000 browsing users passed a five minute hold, and 5,000 offered requests/s passed with zero drops. This is a tested load on a shared loopback host, not an absolute maximum; the 4,096-worker exploratory stage failed the p95 target.

[Complete functional and capacity proof](docs/proof/README.md) · [Standalone interactive report](docs/proof/report.html) · [Run the full proof](scripts/run-local-proof.sh)

## Run locally

Linux 6.1+ with working io_uring, C compiler, curl, Python3, SQLite CLI, jq, openssl, Node 18+ and Rust 1.98.1. Use [scripts/install-deps.sh](scripts/install-deps.sh) to check utilities and install the pinned Rust toolchain through an existing rustup installation. No root or kernel tuning is needed. Initial SQLite PGO compilation takes several minutes.

```bash
bash scripts/build.sh
bash scripts/seed.sh       # ~238 MiB DB, deterministic hash verified
bash scripts/demo.sh       # http://localhost:8080
```

From a phone on the same Wi-Fi, open `http://<this-machine-LAN-IP>:8080`. The demo binds `0.0.0.0`; its sample token writes as a fictional seeded user in `data/demo.db`. Tailscale's device address also works for connected tailnet devices. For an optional temporary HTTPS URL accessible outside that network:

```bash
bash scripts/install-cloudflared.sh
.tools/cloudflared tunnel --url http://127.0.0.1:8080 --protocol http2 --no-autoupdate
```

The temporary tunnel requires the local server, tunnel process, machine and network to stay running. The seed and demo databases, tools and build output are ignored by Git. Delete only `data/demo.db*` while the demo is stopped to reset the fictional dataset.

## API

```bash
cp third_party/challenge/seed/feed.db /tmp/api-benchmark.db
HOST=127.0.0.1 PORT=3000 SQLITE_PATH=/tmp/api-benchmark.db \
  JWT_SECRET=twelve-dollar-challenge bash scripts/start.sh
```

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | SQLite query and uptime |
| `GET /feed` | Latest 20 posts and current like counts |
| `GET /posts/:id` | Post detail |
| `POST /posts` | Commit a post, bearer JWT required |
| `POST /posts/:id/like` | Commit an idempotent like, bearer JWT required |

Read the [exact upstream API contract](third_party/challenge/SPEC.md). There are no login/registration endpoints; the unchanged seed generator produces test JWTs in `third_party/challenge/seed/tokens.json`. Every signature is verified on every authenticated request. Omit `DEMO_CONFIG_PATH` to disable the three demo routes. Use a different database file for each process. `--epoll` explicitly selects the fallback backend; io_uring is the measured default.

## Strategies implemented

Custom HTTP/1.1, keep-alive/pipelining/chunked framing; io_uring shared completion/submission rings; multishot direct accept and receive; provided receive buffers; 64-byte **aligned** connection records; reusable stable output allocations; batched completions, reads and committed writes; one serialized SQLite connection; WAL/NORMAL, prepared plans, mmap and live range scans; checksum-verified SQLite 3.53.4 built with PGO; native CPU instructions and Rust fat LTO. No cross-request response, query-data or JWT-validation cache. See the [timestamped reel analysis](docs/reel-analysis.md), [design](docs/design.md) and [primary-source research](docs/research/challenge.md).

## Correctness and proof

```bash
bash scripts/check-upstream.sh
bash scripts/check-upstream.sh --epoll
python3 tests/functional.py --seed third_party/challenge/seed/feed.db \
  --server target/release/twelve-rust-poll --backend both --output docs/proof/functional-final.json
```

The upstream suite checks 42 exact responses against a fresh full dataset. Additional checks exercise Unicode, authentication, framing, fragmented/pipelined traffic, slow clients, connection churn, live mutations and process-kill recovery. Tests use disposable copies. Results/review: [functional evidence](docs/proof/functional-final.json), [review](docs/review.md).

Capacity evidence and exact commands are in [the machine-specific proof](docs/proof/README.md) and [benchmark tooling guide](bench/README.md). These are co-located loopback measurements, with the generator sharing this laptop's resources. Virtual users with think time, established sockets, outstanding requests and requests/second are distinct. Five-minute passes demonstrate the stated tested load; they do not establish an absolute maximum or production/Internet capacity. The reel's64,000-user result is not this project's measurement.

WAL/NORMAL can lose recent transactions after power loss while preserving consistency; process-kill recovery is a narrower guarantee. Native builds must be rebuilt for other CPUs. See [limitations and methodology](docs/research/benchmark.md).

# Reel analysis and project specification

Source: [Arjay McCandless, Instagram reel Deh4spFuAdz](https://www.instagram.com/reel/Deh4spFuAdz/), posted 15 October 2026. Inspected on 16 October 2026. Duration approximately 100.77 seconds. Analysis used the original public page, locally downloaded video, and a second-by-second visual inspection with OCR of the on-screen diagrams/captions. This is a paraphrased analysis, not a verbatim transcript; the media are not redistributed.

The reel explicitly identifies [`arjaythedev/twelve-dollar-server-challenge` PR #19](https://github.com/arjaythedev/twelve-dollar-server-challenge/pull/19), `rust-epoll-scooter1337`. Its API/schema/rules are the authoritative design, rather than guesses based on the video. Challenge main is pinned to `026bdb68d94d0d932bb5981321ad82c70618d752`; engine PR source is pinned to `bd517fa7c8a57b135579ae02fdddb6196b4cd9a4`. The latter includes improvements after the version featured in the reel.

## Extracted concepts and implementation mapping

Times are approximate video positions, not word-level transcript timestamps.

| Reel position | Concept/technique | Implementation and verification in this project |
| --- | --- | --- |
| 0–17 s | Compare maximum concurrent users on a 1-vCPU/2-GB droplet. Original app: Axum 0.8, Tokio, sqlx, file-backed SQLite. Baseline shown: 14,050 users, 1,305 req/s, p99 459 ms. | Same challenge workload and schema; record this laptop separately. Baseline numbers are the creator's claims, not our measurements. |
| 18–27 s | No response caches or copied database tables. SQLite and schema fixed, HTTP/server/I/O/threading/build/memory choices free. | Unchanged schema in `third_party/challenge/schema.sql`. Every API request reads current SQLite; prepared plans and SQLite's own cache/mmap are allowed. Official 42 checks plus additional tests. |
| 28–35 s | Remove Nginx, Axum, Tokio and sqlx; own HTTP/1.1 server with httparse/serde_json/hmac/sha2. | `src/main.rs`, `src/net.rs`, `src/uring.rs`, `src/db.rs`; no application framework/ORM/executor/proxy in measured path. Per-request JWT signature verification. |
| 35–49 s | `io_uring` shares submission/completion rings with kernel; submit/consume operations in batches. | `Worker` in `src/uring.rs`; batching target32 and wait250μs, immediate handling at low load. Retain completed responses until database commit. |
| 50–55 s | Multishot accept/receive avoid resubmitting an operation for every connection/packet. | Direct multishot accept/recv, provided-buffer ring, terminal-CQE rearm; actual runtime on Linux7.2.5, plus connection churn/protocol tests. |
| 56–61 s | Connection bookkeeping is64 bytes (one CPU cache line); reusable buffers; almost no warmed-request allocations. | Compile-time `size_of::<Client>() ==64`; stable input/output/in-flight buffers and bounded pool. Do not claim zero allocations: cold paths, JSON escapes, growth, SQLite and kernel allocations exist. |
| 62–65 s | Batch reads in transactions and group writes; one SQLite connection, WAL, synchronous=NORMAL. | `Db::begin/commit/checkpoint`, one mutex serializes NOMUTEX connection across ring workers. Replies wait for commit; recovery tests check acknowledged writes. NORMAL protects database consistency but can lose recent commits on power failure. |
| 66–70 s | Compile SQLite3.53.4 from source; profile-guided optimization, fat LTO and native CPU tuning. | Checksum-verified source, `build.rs`, `bench/train_sqlite.c`, release Cargo profile, `scripts/build.sh`. Synthetic PGO training is independent of benchmark fixture. Native artifacts must be rebuilt on different CPUs. |
| 71–80 s | Leading submission shown at64,000 users, about5,950 req/s, approximately4.6× baseline; held5min; ~52% droplet CPU. | These are source claims. This project's proof reports only locally observed results and the actual workload/measurement interval. |
| 81–97 s | Kernel conntrack limit65,536 became full and dropped packets while application had CPU room. | Record local conntrack/FD/port limits. No kernel tuning. A failed connection ceiling does not establish a CPU/SQLite ceiling. |
| 98–101 s | Source and submission identified. | MIT license and exact provenance in `THIRD_PARTY.md`. |

## Functional scope

Implement all five endpoints and exact compact-JSON/error contracts in [the vendored specification](../third_party/challenge/SPEC.md):

- `GET /health`: execute `SELECT 1`, return database status and uptime.
- `GET /feed`: newest20 posts ordered by timestamp then id; current author and like counts.
- `GET /posts/:id`: one current post, or exact validation/not-found error.
- `POST /posts`: verify HS256/expiry/payload on every call, then validate/trim body, commit post, return201.
- `POST /posts/:id/like`: verify auth before ID; one durable like per(user,post),201 first time/200 repeats.

This is a social feed API; the reel does not describe account registration or login. Seeded JWTs identify existing users. Keep the fixed users/posts/likes schema and indexes, default timestamps, JSON field order, and no cross-request data/response/JWT-verification cache. Batching reads/writes does not mean caching their results.

Project additions: optional responsive demo, API explorer, live proof view, reproducible scripts, functional/network/recovery testing, and machine-specific capacity evidence. The UI is enabled only with `DEMO_CONFIG_PATH`; normal challenge execution exposes only the five challenge routes. Demo and benchmark databases are separate copies.

## Research and plan

Three research subagents investigated [challenge semantics](research/challenge.md), [io_uring/SQLite safety](research/io-uring.md), and [capacity methodology](research/benchmark.md) against primary sources. Implementation reuses the attributed featured engine, adds the optional UI and operational scripts, then undergoes functional/protocol/recovery checks, independent code/spec reviews, staged load, five-minute confirmation, and independent arrival-rate checks. Results and limitations belong in `docs/proof/`, not in the study as untested claims.

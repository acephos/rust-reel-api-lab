# Design

The data path is a custom Rust HTTP/1.1 server with Linux io_uring. Each issuer owns its ring, registered socket slots, page-aligned receive pool, 64-byte connection records, stable response allocations, and completion queues. A tag combines operation, slot and generation, so delayed completions cannot mutate a replacement connection. Sends retain their allocation through their final completion and track partial progress. Backpressure stops reads when queued output is high; stalled partial requests/sends time out. Keep-alive connections remain available.

Completed HTTP requests use httparse and full serde JSON validation. Routing/authentication/validation precede prepared SQLite operations. A single `Mutex<App>` serializes all database calls; SQLite is built `THREADSAFE=0`, so entering it outside this lock would be a correctness bug. Every completion batch shares a deferred transaction, live reads and writes use the database, COMMIT happens before successful output is submitted, and failed commit replaces tentative responses with errors. WAL/NORMAL, foreign keys, mmap, page cache and checkpointing remain SQLite's responsibility.

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `src/main.rs` | Config, HTTP framing, JWT validation, request JSON validation and five-route domain behavior |
| `src/db.rs` | Raw SQLite bindings, prepared plans, live feed range scans/fallback, transactions and serialization |
| `src/uring.rs` | Completion I/O, fixed descriptors, multishot operations, pool ownership and send/backpressure lifecycle |
| `src/net.rs` | Explicit `--epoll` fallback and comparison backend; no silent fallback |
| `src/demo.rs` | Opt-in static UI and disposable sample-token/report endpoints, outside the five-route contract |
| `web/demo.html` | Responsive client: real HTTP fetches, posts, likes, JSON inspection and recorded proof |
| `build.rs` | SQLite optimized source build and PGO using synthetic independent data |
| `bench/` | Semantically checked workloads and measurement tooling |

## Configuration and deployment

The normal binary reads `HOST`, `PORT`, `SQLITE_PATH`, and `JWT_SECRET`. It fails on startup errors; pass `--epoll` explicitly on hosts without usable io_uring. The optimized backend requires Linux6.1+ operations. No root permission or kernel changes are needed on ports above1024; inherited file limits may constrain rings. It may raise its own soft limit within its hard limit, as the featured implementation does.

Use one database file per running server: exclusive SQLite locking means separate instances must not share that file. The demo's sample token intentionally permits writes as a seeded fictional user. It exposes no secret signing key, external files, accounts, or operating-system controls. Disable the three study routes by omitting `DEMO_CONFIG_PATH`. Public tunnels use the isolated demo dataset; benchmark traffic uses localhost and its own fresh seed copy.

## Scope and limitations

This is a source-attributed implementation/study of a benchmark API, with tests and evidence. No claim of production hardening or portable cross-platform support is implied. NORMAL does not guarantee every recent transaction survives power loss; process-kill recovery is a narrower test. Native CPU compilation and PGO produce machine-specific binaries. The SQLite page cache/mmap and kernel memory are distinct from process RSS. A k6 user can be sleeping, an open socket can be idle, an outstanding request can be queued, and SQLite work remains serialized; all four quantities must be named accurately.

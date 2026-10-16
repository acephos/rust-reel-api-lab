# The reel's API and performance challenge

Research date: 2026-10-16. This study follows the reel to its author's source repository and to the Rust submission visible in the video. It does not treat an Instagram performance number as a measurement of this project or this machine.

## Source identity and revision control

The primary repository is [arjaythedev/twelve-dollar-server-challenge](https://github.com/arjaythedev/twelve-dollar-server-challenge). The challenge revision inspected was [`026bdb68d94d0d932bb5981321ad82c70618d752`](https://github.com/arjaythedev/twelve-dollar-server-challenge/tree/026bdb68d94d0d932bb5981321ad82c70618d752).

The visible submission is [PR #19, Add Rust/raw io_uring SQLite submission](https://github.com/arjaythedev/twelve-dollar-server-challenge/pull/19), by Scooter1337. Its head at inspection was [`bd517fa7c8a57b135579ae02fdddb6196b4cd9a4`](https://github.com/Scooter1337/twelve-dollar-server-challenge/tree/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337). The branch/directory still says `rust-epoll-scooter1337`, although the current implementation defaults to io_uring and retains an epoll comparison path. The PR is an evolving submission, so the current source and its later results must not be attributed to the earlier reel snapshot.

## What the API actually does

The domain is a small social feed: users author posts; users can like posts once. There are **no registration or login endpoints** in the authoritative specification. Credentials are presigned JWTs supplied with the seed. [API specification](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/SPEC.md)

| Route | Behavior |
|---|---|
| `GET /health` | Execute `SELECT 1`; return healthy status and integer uptime, or HTTP 503 if the database is unavailable. |
| `GET /feed` | Return the newest 20 posts, ordered by timestamp descending and ID descending. |
| `GET /posts/:id` | Return one post, or HTTP 404 when absent. |
| `POST /posts` | Authenticate, parse and trim a post body, validate 1–500 characters, persist it, then return HTTP 201. |
| `POST /posts/:id/like` | Authenticate and persist a unique user/post like. Return HTTP 201 initially and HTTP 200 on a repeat. |

The post wire representation uses this ordered field sequence: `id`, `body`, `created_at`, `author`, `like_count`. Feed and single-post wrappers are `posts` and `post` respectively. Creation uses the token's username; reads join the users table. Counts must reflect current database contents. JSON must be compact and maintain the specified key order. Timestamps use the stored UTC millisecond representation. [Exact response contract and errors](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/SPEC.md)

The 42-check shell suite compares golden response bytes on a fresh seed, exercises authentication errors and malformed bodies, writes and rereads posts/likes, and checks feed ordering and immediate count updates. Tests take precedence if prose and test expectations disagree. Reusing a mutated database for that suite invalidates golden comparisons. [Authoritative functional checks](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/test/test.sh)

## Data model and authentication

The fixed schema contains:

- `users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)`.
- `posts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 500), created_at TEXT NOT NULL)`.
- `likes(user_id INTEGER NOT NULL REFERENCES users(id), post_id INTEGER NOT NULL REFERENCES posts(id), created_at TEXT NOT NULL, PRIMARY KEY(user_id, post_id))`.
- Indexes on posts' descending `(created_at, id)`, posts' `user_id`, and likes' `post_id`.

All timestamp defaults use SQLite's UTC `strftime` with fractional seconds. The feed order therefore has an index, and counting likes has a `post_id` index. No extra index, table, column, or trigger is permitted in a challenge submission. [Schema source](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/schema.sql)

JWTs use HS256 and the configured secret. Every authenticated request must verify its signature and expiry and reject other algorithms. The `sub` claim must be a string containing a positive integer; `username` must be a string. Signature/expiry errors and validly signed but invalid application claims have different response messages. Authenticated routes check credentials before interpreting an invalid post ID. The runtime contract is `SQLITE_PATH`, `JWT_SECRET`, `HOST`, and `PORT`. [Specification](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/SPEC.md)

The deterministic data generator creates 50,000 users and 500,000 posts; its approximately two million likes are a generated distribution rather than exactly the `LIKES` constant. Posts have correlated ID/timestamp order, authorship is skewed, and occasional posts are much more popular. It supplies tokens for the first 20,000 users, with ten-year expiry. Seed token bytes depend on generation time even though database rows are deterministic. [Generator](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/seed/generate.mjs)

The seed builder verifies ordered row content using SHA-256 `738d11ab3164c13177e347f75038d1e80b43c64e754544a42d1c32bd8d7bcf1d`. Its unsafe import pragmas apply during offline construction only; it restores WAL before the file is served. Every test/benchmark starts from a disposable copy. [Seed builder](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/seed/make-seed.sh)

## Constraints that determine the architecture

The official target is Ubuntu 24.04 x86-64, one vCPU, 2 GB RAM, no swap. The API shares those resources with the OS and, if selected, Nginx. SQLite runs in process against the provided on-disk file. External databases/services and application-level data caches are forbidden. Every request must query SQLite, and every token signature must be checked again. SQLite's own page cache/mmap and reused prepared statements are allowed.

Writes must commit before a success response; group commit is explicitly permitted when all affected responses await that commit. WAL with `synchronous=NORMAL` or stronger is required. Direct serving avoids proxy CPU cost but requires holding many idle sockets. The alternate Nginx configuration uses a small upstream keep-alive pool, and the API must not prematurely close those sockets. Dependencies must be pinned and built from source. Host kernel tuning and process/CPU pinning are outside the challenge rules. [Challenge rules](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/README.md)

## Techniques demonstrated by the referenced Rust implementation

These are source-backed strategies, not a claim that every strategy appeared explicitly in the reel's narration. The reel's batching discussion concerns **reads and writes**. It does not introduce registration/login into this five-route API.

1. **A direct HTTP transport.** The submission avoids a proxy, HTTP framework, executor, and ORM. It parses HTTP/1.1 with `httparse`, validates JSON with `serde_json`, and verifies JWT HMACs with `hmac`/`sha2`. Borrowed strings, reusable buffers, and integer formatting reduce ordinary-path allocation. Custom JSON output preserves exact field order and escaping. [Application source](https://github.com/Scooter1337/twelve-dollar-server-challenge/blob/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337/src/main.rs)

2. **One serialized SQLite owner.** A single NOMUTEX connection is protected across workers, and prepared statements are reused. WAL, NORMAL synchronization, foreign-key enforcement, a small page cache, mmap, exclusive locking, and explicit checkpoints are configured inside the process. A batch can share a deferred transaction, with writes upgrading it and responses delayed until commit. This trades database parallelism for low coordination and pager overhead. [Database implementation](https://github.com/Scooter1337/twelve-dollar-server-challenge/blob/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337/src/db.rs)

3. **Live locality-aware SQL.** Every feed first discovers the current top IDs. When their span is small, a bounded range fetch obtains rows and likes, then restores the required timestamp/ID ordering. Sparse spans fall back to the general indexed query. This exploits locality without remembering results across requests or hardcoding seed IDs. [Database source](https://github.com/Scooter1337/twelve-dollar-server-challenge/blob/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337/src/db.rs)

4. **Batched network completions and compact idle connections.** io_uring uses registered socket tables, multishot accepts/receives, provided buffers, and bounded completion waits. The I/O path separates send-buffer ownership from connection records, guards reused slots with generations, and pauses reads under backpressure. These measures are relevant because a browsing VU spends most of its lifetime idle while still retaining a socket. [io_uring implementation and rationale](https://github.com/Scooter1337/twelve-dollar-server-challenge/blob/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337/IO_URING.md)

5. **Compilation and measured iteration.** The release profile uses fat LTO, one codegen unit, and abort-on-panic. The submission compiles pinned SQLite 3.53.4 source, trains SQLite profile-guided optimization on a disposable synthetic database, and uses native CPU instructions. It enables Linux's fdatasync path. These are performance hypotheses that need controlled comparisons on the target machine; source complexity or unsafe code alone proves no improvement. [Pinned manifest and release settings](https://github.com/Scooter1337/twelve-dollar-server-challenge/blob/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337/Cargo.toml), [build process](https://github.com/Scooter1337/twelve-dollar-server-challenge/blob/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337/build.rs)

## Mapping the proposed derived build to the original rules

The project will reuse the MIT-licensed engine from the pinned PR head with attribution and preserve its core behavior. New work comprises the demonstration surface, study, functional verification, and machine-specific load evidence. It should not be described as a clean-room reimplementation or as a new performance invention.

| Original rule | Implementation and verification requirement |
|---|---|
| 1. Language/framework freedom | Rust engine with raw Linux I/O and in-process SQLite is permitted. |
| 2. SQLite only | Pass `SQLITE_PATH` to the file database; use no external database/cache service. |
| 3. Fixed schema/data | Reuse upstream schema/seed exactly; inspect database schema before and after tests. |
| 4. Exact correctness | Run the unmodified 42-check upstream suite on a fresh seed copy. |
| 5. No application data caches | Preserve live SQL reads and per-request HS256 verification; buffer and statement reuse are allowed. |
| 6. Commit before success | Preserve WAL/NORMAL-or-stronger and commit gating; test persisted acknowledged posts/likes and failed-commit behavior. |
| 7. No benchmark detection | Use identical request handling for interactive users and load clients; no fixed seed IDs or hardcoded feed/count responses. |
| 8. Original VM budget | State this machine's actual resources; report any constrained run separately from an unconstrained workstation run. |
| 9. Nginx optional | Choose direct serving, report open connections separately, and test keep-alive reuse. A demo's separate UI/proxy is outside a claimed core-engine benchmark unless explicitly included. |
| 10. Source build/pinned dependencies | Keep Cargo.lock, source checksum validation and build scripts; verify normal startup rather than committing binary artifacts. |
| 11. No host tuning | Do not change host kernel settings or apply application affinity. Document inherited limits and any external measurement constraints. |

This table is an implementation checklist derived from the [original numbered rules](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/README.md). It is not a statement that verification has already passed.

## What the original benchmark measures

One k6 VU models a browsing person, not an always-in-flight request. Its loop reads the feed, thinks for 3–7 seconds, reads a selected post, thinks for 3–8 seconds, likes with 15% probability, creates with 2% probability, then waits 5–15 seconds. Authentication tokens rotate modulo the token list. At steady state, expected think time is 20.5 seconds per 2.17 requests, approximately 0.106 requests/second per VU before latency. Thus tens of thousands of VUs can correspond to only thousands of requests/second. [Official load model](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/bench/load.js)

The script defaults to a 60-second ramp, five-minute hold, and 30-second ramp-down. Thresholds require p95 below 500 ms, p99 below 1,000 ms, and HTTP failure rate below 1%. Functional `check` calls also run, although the script does not assign them a separate threshold. A reproduction should explicitly report failed semantic checks alongside HTTP failures. k6's aggregate summaries include ramp periods, which should be identified separately from hold-only metrics. [Load script](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/bench/load.js)

The organizer warms at 1,000 users for two minutes, doubles from 2,500 to find a failure, narrows the bracket to 250 users, then confirms the highest pass with a five-minute hold. The load generator belongs on a separate machine in official scoring. A local run on this workstation is a local measurement, even if it uses the same workload. [Scoring protocol](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/README.md)

## Evidence and pitfalls for this build

- Report **active closed-loop request concurrency**, **open keep-alive sockets**, and **think-time VUs** separately. They measure different resources.
- Record source commit, release settings, binary hash, seed hash and row counts, CPU/RAM/storage/OS, descriptor limits, generator placement, run duration, workload mix, error count, semantic verification, p50/p95/p99, throughput, and server/client memory.
- Every success under write load must be checked against persisted state after graceful restart; an additional killed-process recovery test should target acknowledged writes. Do not call `synchronous=NORMAL` proof of power-loss durability.
- Preserve failed and invalid runs. A generator OOM, ephemeral-port ceiling, connection limit, or competing process can stop a run before the server reaches its own CPU limit.
- Use fresh files for comparable trials. Likes become repeats and feeds change as a run writes; both affect later trials. Compare balanced run orders and distinguish warmup from measured data.
- Keep raw evidence, not only rounded headline numbers. A highest passing tested concurrency is a lower bound unless a repeatable failing bracket and sustained confirmation have also been established.
- Test partial requests, pipelining, malformed framing, stale connection events, backpressure, timeout/idle reuse, token validation, sparse feed IDs, timestamp ties, and commit failure when using a custom transport or SQL optimization.

The original submission's own history illustrates these limitations: an older descriptor-bound run passed 68,750 users with approximately 0.99% failures, whereas 65,000 had zero failures; later io_uring source records a 100,000-VU five-minute pass on its Xeon host. Neither figure describes this workstation, and neither is automatically the official droplet score. [Historical benchmark record](https://github.com/Scooter1337/twelve-dollar-server-challenge/blob/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337/BENCHMARKS.md), [current submission README](https://github.com/Scooter1337/twelve-dollar-server-challenge/blob/bd517fa7c8a57b135579ae02fdddb6196b4cd9a4/submissions/rust-epoll-scooter1337/README.md)

The evidence checklist above is a project recommendation derived from the inspected workload and failure histories. It is not an additional original challenge rule.

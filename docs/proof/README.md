# Capacity proof on this machine

Generated from the checked-in artifacts by `scripts/summarize-proof.py` on 2026-10-16T06:30:27.216006+00:00. [Machine-readable report](demo.json).

The API served **2,048 continuously active request workers for five minutes** at 10,496.9 validated requests/s and zero errors. Actual HTTP transport overlap was **mean 743.8, peak 2,048 requests** sending/waiting/receiving over 300.10s. This is a demonstrated load, not the machine's absolute maximum. Separately, **5,000 browsing virtual users** passed a five-minute hold with the reel's pacing.

The [HTTP-only reconstruction](http-active.json) uses [k6's end timestamp and transport duration](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/), excluding setup, validation and recording. The broader client-operation mean 1778.6 / peak 2,048 below includes those extra client costs and must not be called HTTP-only concurrency. SQLite execution remains serialized.

| Workload | Offered load | Hold | Validated req/s | Full p95 / p99 ms | Client-operation mean / peak | Errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Active mixed | 2,048 workers | 300s | 10,496.9 | 235 / 323 | 1778.6 / 2,048 | 0 |
| Original browsing | 5,000 VUs | 300s | 529.5 | 1 / 2 | 0.3 / 18 | 0 |
| Independent arrivals | 5,000 req/s offered | 60s | 5,000.0 | 4 / 8 | 6.1 / 146 | 0 |

## Acceptance fixed before testing

Every returned body is decoded and checked for status, JSON field order/schema and endpoint meaning. Creates verify authored content, likes verify idempotence status, feed checks 20 ordered posts with valid fields. All semantic checks and HTTP requests pass; every endpoint has coverage and full p95<500ms, p99<1000ms; open arrivals have zero drops. `passed_all_checks` additionally requires balanced start/finish counts and no unfinished requests. The corrected short smoke preceded the ladder. Tests use the full deterministic seed, not a tiny synthetic fixture.

The separate functional proof passes the unchanged 42 upstream checks on each backend and 12 additional groups per backend. [Final extended result](functional-final.json), [io_uring exact checks](upstream-uring-final.log), [epoll exact checks](upstream-epoll-final.log), [Clippy](clippy.log). It verifies all acknowledged writes after SIGKILL; this is not power-loss durability.

After stopping each load-test server, every acknowledged post creation and first-time like was reconciled with persisted row counts. SQLite integrity, foreign keys and unchanged schema also passed. Active: 787,257 posts / 787,204 first likes. Browsing including warm-up: 1,864 / 13,802. Open: 75,002 / 74,994. See the three `*-database-check.json` files under [the run artifacts](../../proof/runs/).

## Reproduce

Follow the build/seed commands in [README](../../README.md). Start an io_uring server against a disposable fresh seed copy on 127.0.0.1:3000 with the challenge secret and no demo configuration. Capture its actual PID. [Benchmark commands and metric definitions](../../bench/README.md). Execute runs sequentially; the server binaries must have the same checksum. The original-user run is preceded by a separately recorded 1,000-VU/two-minute warm-up; its ramp and drain are separate from the 300-second hold. Active/open runs have their own declared protocol; no CPU pinning or sysctl changes.

```bash
SERVER_PID=<pid> BASE_URL=http://127.0.0.1:3000 MODE=active VUS=2048 DURATION=5m OUT=proof/runs/active-hold scripts/benchmark.sh
SERVER_PID=<pid> BASE_URL=http://127.0.0.1:3000 MODE=original VUS=5000 RAMP_UP=60s DURATION=5m OUT=proof/runs/original-hold scripts/benchmark.sh
SERVER_PID=<pid> BASE_URL=http://127.0.0.1:3000 MODE=open RATE=5000 VUS=256 MAX_VUS=1024 DURATION=60s OUT=proof/runs/open-confirmation scripts/benchmark.sh
python3 bench/http-concurrency.py --run proof/runs/active-hold --output docs/proof/http-active.json
python3 scripts/summarize-proof.py --active proof/runs/active-hold --users proof/runs/original-hold --open proof/runs/open-confirmation
```

Exact run settings, tool/source/binary checksums, actual process argv/allowlisted configuration, limits, CPU affinity, cgroups, host state and source revisions are inside each run's `machine.json`. Endpoint latency/count results and resource peaks are retained in [demo.json](demo.json). Never silently replace a failed run; exploratory stages and the initial validator failure remain available.

## Artifacts

- Active hold: [proof/runs/active-hold](../../proof/runs/active-hold)
- Original hold: [proof/runs/original-hold](../../proof/runs/original-hold)
- Open confirmation: [proof/runs/open-confirmation](../../proof/runs/open-confirmation)
- Separate browsing warm-up: [proof/runs/original-warmup](../../proof/runs/original-warmup)
- [Exploratory ladder](../../proof/runs/ladder/), [initial failed validator smoke](../../proof/runs/smoke/), [corrected smoke](../../proof/runs/smoke-fixed/), [validator diagnosis](benchmark-validation.md)
- Binary SHA256: `9a652c867a36449ab0acfc3988a8b16c149f4bd4b44faca2aac40bea33fc26e5`. Rust 1.98.1, native CPU flags, fat LTO, SQLite 3.53.4 PGO.

## Practical limits

- HTTP transport during the active hold: mean 743.8, peak 2,048 requests sending/waiting/receiving. This is separate from 2,048 configured workers and client-operation overlap.
- Single-machine loopback measurements on Ryzen 5 5600H (6 cores / 12 threads), Linux 7.2.5. The load generator shares CPU, memory, disk and network stack with the API.
- Active: no think time; rotation is 25% feed, 25% post, 25% like, 25% create. Original browsing: upstream think times, 15% like and 2% create chances per user loop.
- Configured workers are not simultaneous server execution. Client-operation overlap includes connection/pool waits, body consumption, validation and metric recording. The separate HTTP-only reconstruction excludes setup/validation/metric recording. SQLite remains serialized.
- Throughput is validated completions of requests STARTED during the hold divided by configured hold seconds; those requests may finish in the bounded drain. Exact observed spans, starts/finishes and unfinished counts are in each accounting.json.
- Latencies are full HTTP plus JSON validation, at 1-ms resolution, for requests started during the hold. Every endpoint also passes p95<500ms / p99<1000ms. Semantic and HTTP failures are zero.
- This is a demonstrated passing load, not an absolute maximum or an official droplet score. The generator is a material bottleneck; more server CPU headroom is not proof of a higher untested capacity.
- Open arrivals use k6 constant-arrival-rate and require zero drops. Latencies are not wrk2 planned-schedule-corrected; arrival accounting and any theoretical scheduling-boundary residual are retained.
- Resource CPU means include all sampled phases and the raw-export tail after requests stop; inspect timestamped samples for the request-active window. CPU 100% means one logical core.
- Complete per-request gzip events are retained locally with SHA256 references. GitHub contains exact summaries, interval histograms, concurrency accounting and resource samples; large raw event streams are not published.

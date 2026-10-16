# Reproduce the feed API capacity evidence

`scripts/benchmark.sh` installs **official Grafana k6 v2.3.0**, verifies its archive against the official release checksum list and a digest pinned in this repository, then runs the release API you already started. Installation stays under ignored `.tools/`; no system limits are changed. The pinned archive targets Linux x86_64. Scripts require Bash, Python 3.11+, curl, tar and sha256sum. Start the server against a disposable fresh copy of the verified challenge seed database; never load-test the phone demo's writable database.

```bash
# The seed database and seed/tokens.json must already exist.
# Replace PID and port with the actual benchmark server, e.g. $! after starting it.
export SERVER_PID=12345 BASE_URL=http://127.0.0.1:3000

# Small functional/performance smoke: every endpoint is exercised, no think time.
MODE=active VUS=16 DURATION=2s scripts/benchmark.sh

# Sequential exploration; failures are retained in ladder-status.txt.
LADDER='16 64 256 1024' STAGE_DURATION=15s scripts/benchmark-suite.sh

# Select a passing candidate based on its evidence, then prove it for five minutes.
MODE=active VUS=256 DURATION=5m scripts/benchmark.sh

# Original challenge browsing behavior: 60-s ramp + five-minute hold +30-s ramp-down.
MODE=original VUS=10000 RAMP_UP=60s DURATION=5m scripts/benchmark.sh

# Independent offered load: one request per scheduled iteration, no think time.
MODE=open RATE=2000 VUS=256 MAX_VUS=1024 DURATION=60s scripts/benchmark.sh
```

These commands are examples, not pre-established passing capacities. A 10,000-VU original workload is substantially heavier for the co-located generator than 256 active workers. Begin with smaller stages, inspect CPU/RSS/descriptor use and abort if the generator becomes the bottleneck. The one-second sampler runs concurrently; account for that small observer overhead. Do not run benchmark commands simultaneously.

`OUT=/absolute/path` selects a new evidence directory. Existing runs are never overwritten. Default output is `proof/runs/<UTC>-<mode>-<vus>vu-<pid>/`. `TOKENS=/absolute/path/to/tokens.json` overrides the challenge tokens. `SEED` defaults to 7263, `TIMEOUT` to 5s, and `POST_IDS` to 10000, which must refer to existing seed posts. Random seeds are per VU; exact interleaving is still scheduler-dependent. `SERVER_PID` enables process CPU/RSS/FD sampling and effective affinity/limit recording. Without it, the reports explicitly omit server process measurements and therefore provide weaker host evidence.

An optional combined sequential command is:

```bash
# 4x15-s exploration, five-minute active hold, 60-s independent arrival confirmation.
HOLD_VUS=256 OPEN_RATE=2000 OPEN_VUS=256 OPEN_MAX_VUS=1024 scripts/benchmark-suite.sh
```

The selected hold must pass before the combined script proceeds. Add `ORIGINAL_VUS=10000` only when also budgeting its independent original challenge hold. A full active five-minute proof plus a full original five-minute proof cannot honestly fit within a ten-minute load window. `HOLD_DURATION`, `ORIGINAL_DURATION`, `OPEN_DURATION`, `RAMP_UP` and `RAMP_DOWN` customize durations. Use single-unit duration strings (`2s`, `5m`, `500ms`), not composite strings.

## Workloads and acceptance

The upstream challenge is a five-route feed API; **there is no registration/login endpoint**. The benchmark uses supplied HS256 seed tokens for create/like operations. `/health` belongs to preflight/recovery verification outside the workload. Seed-generation, upstream correctness tests, and durability checks remain separate prerequisites.

- `MODE=original` preserves the original feed → think 3–7 s → selected post → think 3–8 s → 15% like → 2% create → idle 5–15 s loop. The first iteration retains its 0–5-s start spread. It uses a ramping-VU executor, defaulting to 60-s ramp, configured hold, then 30-s ramp-down. Hold is explicitly tagged; ramp/drain requests are separate in the raw and compact reports.
- `MODE=active` uses constant VUs, zero think time and one outstanding synchronous request per VU. The action rotates through feed/post/like/create, approximately 25% each in a long run. It is intentionally a much more write-heavy workload than the reel. Worker count is an upper bound on client requests outstanding; measure actual outstanding requests from the event accounting.
- `MODE=open` uses k6's constant-arrival-rate executor. Each iteration is exactly one request from the same rotating mix, so `RATE` means offered HTTP requests per second. `VUS` preallocates worker slots, `MAX_VUS` caps them, and **any dropped iteration fails the run**. It reports scheduling drops rather than claiming wrk2-style corrected schedule latency.

Every response is parsed and checked for compact API shape/key order, expected status, field types, timestamp precision, identity/body on creation, feed order and 20-post length, selected post identity, and consistency between like status and `already_liked`. A malformed JSON body, incorrect HTTP-200 payload, or incorrect identity fails `semantic_success` and `checks`. Each endpoint must have at least one validated success during hold; a tiny original/think-time run can therefore fail because random 2% creates never occurred. Active mode is the correct small smoke.

Acceptance preserves the challenge latency bounds on **each endpoint during hold**, using a stricter full request duration: p95 <500 ms and p99 <1000 ms. Full duration starts immediately before the synchronous HTTP call and ends after full response-body consumption and semantic validation; it includes connection/pool wait time. HTTP failure rate must remain <1%, while **all semantic checks must succeed**, effectively requiring no unexpected statuses, rejected requests, transport failures or wrong payloads. Open mode also requires zero dropped arrivals. Empty workload/endpoint coverage and unfinished request accounting cannot pass. Threshold failure exits nonzero and is retained in the evidence.

## Published evidence and locally retained raw events

Each run publishes compact files:

| File | Evidence |
| --- | --- |
| `machine.json` | CPU/kernel/memory/storage, ancestor cgroups, server affinity/limits when supplied, k6 version, source hashes, source commit and dirty status, workload settings |
| `summary.json` | Exact k6 aggregate metrics, endpoint/hold submetrics, percentiles and thresholds from `handleSummary()`; no recomputed histogram approximation |
| `accounting.json` | Counts, statuses, validated successes, dropped arrivals, true client-outstanding peak/time-weighted mean, interrupted/unbalanced request counts, pass flag |
| `resources.jsonl` | Approximately one-second client/server CPU, RSS, descriptors, affinity, matching TCP states and host load/conntrack count |
| `intervals.jsonl` | Per-second completed-event / validated-success / semantic-error / dropped-arrival counts |
| `endpoint-intervals.jsonl` | Per-second, per-phase, per-endpoint counts, full-duration sum/max and noncumulative millisecond histogram bins |
| `raw-reference.json` | Complete raw gzip location on this host, compressed size and SHA256 |
| `command.txt`, `k6.log`, timestamps, exit-code files | Invocation, diagnostic log, execution boundaries and status |
| `SHA256SUMS` | Checksums of all compact evidence files |

Complete k6 metric events stream directly to gzip under **ignored `.tools/benchmark-raw/`**, avoiding multi-million-event files in GitHub. `RAW_DIR=/absolute/path` changes the local retention directory. Raw events are retained, not deleted. They contain no request headers, bearer tokens or request/response bodies. Use the `raw-reference.json` checksum to verify local originals; external readers can inspect compact evidence immediately and reproduce fresh raw events. Historical raw data is not available from the Git repository unless separately attached as a release artifact.

The per-second histogram's upper boundaries are `[0.1,0.25,0.5,1,2,5,10,20,50,100,250,500,1000,2500,5000,10000,+Inf]` milliseconds, with **noncumulative** counts. This compact histogram supports trends and audit counts; cite k6's exact exported percentiles for SLO conclusions. JSON output and gzip support are [documented by Grafana](https://grafana.com/docs/k6/latest/results-output/real-time/json/).

Client concurrency comes from paired `client_inflight_delta` raw metric events emitted immediately before/after each HTTP request and validation. The analyzer sorts their timestamps globally, integrates outstanding count over elapsed time, and reports its observed peak and time-weighted mean. Requests started during hold include their eventual drain for accounting. Exact-timestamp ties process completion first, giving a conservative peak. This is **client outstanding work**, including connection waits; it does not claim equal server handler concurrency. The `client_inflight_delta` gauge's ordinary k6 min/max is meaningless on its own and must not be reported as concurrency.

`hold_started_validated_successes_per_configured_second` divides validated successes for requests **started in hold** by the configured hold duration; a few finish during drain. Use per-second completion intervals and final-request accounting to assess sustained throughput and tail behavior. The ordinary k6 overall request rate includes ramp/drain and must not be mislabeled as hold-only throughput. Interrupted requests remain visible through unbalanced start/end events and make the final wrapper status fail.

The closed worker model self-throttles during slow responses; the open test provides a separate offered-load check. k6 scheduling drops are explicit, but its request latency is not automatically corrected to the planned arrival time. See [k6 open/closed models](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/open-vs-closed/), [constant arrival rate](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/), and [dropped iterations](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/dropped-iterations/).

A passing laptop test establishes the highest **tested** passing load under its stated workload, duration and configuration. It does not establish an absolute maximum, a production Internet limit, or a speedup over the reel's 1-vCPU/2-GB box. The generator shares CPU, memory and kernel resources with the server; Wi-Fi, TLS and a public tunnel add different costs.

## Attribution

The original browsing loop is derived from [`third_party/challenge/bench/load.js`](../third_party/challenge/bench/load.js), pinned with the rest of the upstream challenge. Copyright (c) 2026 arjaythedev and the challenge contributors. The original MIT notice and complete license are retained at [`third_party/challenge/LICENSE`](../third_party/challenge/LICENSE). This suite adds semantic validation, endpoint SLOs, independent active/open workloads and reproducible evidence collection. k6 itself is downloaded unmodified from [official Grafana release v2.3.0](https://github.com/grafana/k6/releases/tag/v2.3.0); its AGPL-3.0 license remains upstream.

## Complete local proof orchestration

`ACTIVE_VUS=2048 BROWSING_VUS=5000 OPEN_RATE=5000 scripts/run-local-proof.sh` runs sequentially on port3120, creates fresh private database copies for the active, browsing and open scenarios, holds activeworkers for5minutes, records a separate1000-user/two-minute browsingwarmup, then a60-second ramp/five-minute browsinghold/30-second rampdown, then60seconds of open arrivals. It stops each server and reconciles **every acknowledged post and first-like response** against persisted row counts, checks SQLite integrity/foreign keys and unchanged schema, then generates the public proof from passing artifacts. It refuses to overwrite an existing run. Choose candidate loads from exploratory evidence before executing; defaults are examples, not guaranteed passes.

Use `PROOF_PORT` to choose another unused port and `OUT` for a new output root inside the repository. The runner removes its temporary database copies after checks and leaves the separate phone demo alone. `scripts/summarize-proof.py` verifies artifact checksums, actual binary/configuration identity, exact modes, zero unfinished requests, passing thresholds, real five-minute hold durations and the actualwarmup artifact before publishing. CPU and socket resource statistics cover all sampled phases; requestlatencies/throughput use the documented hold-start classification.

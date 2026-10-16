# Defensible capacity proof on this machine

Research date: 2026-10-16. This is a methodology and a machine inspection, **not a benchmark result**. Execution results must be reported separately with their raw artifacts.

## What must be proved

The reel's reported 14,050 / 64,000 users and 1,305 / approximately 5,950 requests per second are separate quantities. Neither user count establishes that all those requests were simultaneously executing. The original workload's pacing and connection behavior must accompany any comparison. This project's host is also substantially larger than the reel's stated 1-vCPU, 2-GB machine, so a result here cannot establish an improvement over the reel.

Record four independent measurements:

| Quantity | Operational definition | Required evidence |
| --- | --- | --- |
| Virtual users / workers | Independent workload loops, potentially sleeping or waiting | Configured and active worker counts; exact think time |
| Open TCP connections | Established client/server transport connections, potentially idle | Socket snapshots or connection counters |
| Outstanding requests | Requests begun by clients whose complete response bodies have not been received | Client in-flight gauge, observed peak and time-weighted mean |
| Throughput | Completed HTTP requests divided by the measured wall-clock interval | Total completions, successful validated completions, elapsed seconds |

A fixed worker count is an upper bound on client concurrency when each worker awaits one request at a time. It is not evidence that all workers were sending requests throughout the interval. Server handler concurrency excludes socket queues and can differ substantially from client in-flight concurrency. A burst's peak is not sustained concurrency. Report all measurements using their own names.

## Why two load models are necessary

A closed model sends the next request only after the previous response. Under overload it automatically reduces the arrival rate. Grafana documents this feedback and its coordinated-omission problem; use a closed model to demonstrate behavior with a specific number of request-making workers, but identify that limitation explicitly. An independent arrival model verifies whether a declared offered rate is sustainable. [k6 open and closed models](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/open-vs-closed/)

An open-model scheduler must record planned start time, actual start time, completed-body time, and any request that could not start. Report both service observation (`completed - actual start`) and schedule-inclusive delay (`completed - planned start`). Never silently omit missed arrivals. k6 supplies arrival-rate executors and a dropped-iterations metric; wrk2 explicitly measures latency against the intended schedule. [k6 constant arrival rate](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/), [k6 dropped iterations](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/dropped-iterations/), [wrk2 original source and measurement rationale](https://github.com/giltene/wrk2)

An implementation can use a single monotonic-clock scheduler and a bounded number of in-flight tasks. Each planned arrival either gets a request task or increments a dropped-arrival counter. Do not pause the schedule while waiting for a semaphore: that converts overload into a self-throttling workload. Preallocate generator resources where practical, and cap catch-up bursts so a stalled generator reports missed work instead of generating a different workload.

## Functional workload

The authoritative specification is a feed API, not an account-registration service. There are five endpoints: GET /health, GET /feed, GET /posts/:id, POST /posts, POST /posts/:id/like. Tokens are seeded HS256 JWTs; there is no login or registration. [Pinned specification](https://github.com/arjaythedev/twelve-dollar-server-challenge/blob/026bdb68d94d0d932bb5981321ad82c70618d752/SPEC.md)

Before performance testing, run the official 42 exact-response checks and additional network/recovery checks. Validate full JSON responses: exactly ordered post fields, newest 20 posts, positive identifiers, nonnegative live like counts, actual stored content and identity, correct Unicode trimming/length, per-request JWT rejection, first/repeated likes and committed writes surviving process termination. Never count an HTTP 200 with an incorrect body as success.

Name these workloads separately:

- **Original users:** reproduce the upstream k6 loop with its original think times, 15% chance of a like and 2% chance of creating a post per iteration. This yields about 0.10 requests per second per virtual user. Validate response content in addition to upstream status checks.
- **Active concurrency:** fixed workers continuously execute the real feed/post/like/create cycle with no think time; each worker has at most one HTTP request outstanding. Report worker count as a configured upper bound; it is not CPU-parallel handler count.
- **Open arrival:** independently schedule the same active iteration at a fixed rate, count every dropped iteration, and disclose requests per iteration when comparing iterations/s with requests/s.

Use the unchanged 50,000-user, 500,000-post, 2,016,005-like deterministic fixture, and fresh copies for independent runs. Keep response bodies enabled. Seed tokens are intentional disposable challenge fixtures; the public demo uses an isolated database. Record actual per-endpoint completed counts, unexpected statuses, semantic failures, and durations.

## Acceptance criteria and meaning of capacity

Choose the SLO before selecting the winning run. The original challenge target is p95 < 500 ms and p99 < 1000 ms with <1% HTTP failures. This study additionally requires zero semantic failures, zero HTTP failures and zero dropped arrivals; per-endpoint p95/p99 are also checked. The exact thresholds are committed in the load script; a useful stricter exploratory target is p99 ≤ 500 ms for each endpoint, no transport/time-out/body-validation/unexpected-status errors, zero dropped arrivals for an open-model pass, and successful post-load functional checks. State any different threshold explicitly before running. Aggregate p99 alone can conceal slow write requests when reads dominate.

During an intentionally overloaded stage, count 429/503/backpressure responses as rejected work, even when the rejection is correct API behavior. Report successful throughput separately from total response throughput. If a stage fails, it still belongs in the evidence.

The result should read: “For workload W, version/configuration V, and duration D, the highest **tested** passing worker count was C; observed outstanding requests were mean M / peak P, at R validated successful requests/s, with latency/error metrics E.” An open-rate result adds offered arrivals, launched arrivals, dropped arrivals, and achieved throughput. If the highest attempted stage passes, call it a demonstrated lower bound; do not invent a maximum. If a lower stage passes and the next fails, describe the tested bracket rather than asserting the exact boundary.

## Representative suite within ten minutes

Build and dependency installation are outside the timed suite. Start the release binary with a fresh benchmark database and the exact intended settings. Record configuration before setup. This proposal takes at most 550 seconds of load/check windows, plus a small process-start allowance; stop or reduce later exploratory stages once overload is clear.

| Phase | Maximum budget | Purpose |
| --- | ---: | --- |
| HTTP functional preflight and setup | 30 s | Confirm create/read/like, identity, and rejection semantics |
| Warm-up | 20 s | Trigger runtime/database allocation and establish keep-alive reuse |
| Closed-worker exploration | 60 s | Six 10-s stages, e.g. 1 / 4 / 16 / 64 / 256 / 1,024 workers; stop once failures become material |
| Open-arrival exploration | 60 s | Three 20-s stages near 50% / 80% / 110% of observed successful throughput |
| Selected fixed-worker proof | 300 s | Five minutes at the highest stable passing candidate with per-endpoint validation |
| Independent offered-rate confirmation | 60 s | Sustained rate around 80% of successful proof throughput; count all missed arrivals |
| Drain, recovery and post-load correctness | 20 s | Account for unfinished work, check recovery, verify a new create/read/like cycle |
| Total | **550 s** | Under ten minutes before exceptional startup delays |

The 10-s stages locate a candidate; they are not sufficient for a long-run stability claim. If the selected five-minute run fails, report that failure and either rerun at a lower candidate (with a separate disclosed time budget) or report the shorter passing stages honestly. Do not label a 10-s result a five-minute result. If the reel's exact workload specifies think time or a different mix, use it as an additional named scenario and adjust the suite explicitly.

The five-minute proof must identify its mix and pacing. The active-worker and original-user workloads require separate results; neither establishes the other. Never run competing capacity tests simultaneously on this laptop. A short correctness smoke establishes no untested throughput ceiling.

## Artifacts that make the result reviewable

Save these in a timestamped directory, e.g. `proof/runs/<UTC timestamp>/`:

- Exact source commit, `Cargo.lock`, release profile, compiler/tool versions, server arguments and sanitized configuration, benchmark arguments, start/end timestamps and monotonic elapsed time.
- Host CPU/core count, total/available memory, kernel, storage type/filesystem, process and ancestor cgroup quotas, affinity, file-descriptor limits, TCP ephemeral-port range, conntrack settings, and relevant existing host load.
- Raw machine-readable run reports for every stage, including failures: planned/launched/completed/validated-success counts; endpoint counts; statuses; timeout/connection/JSON/identity errors; p50/p95/p99/max; in-flight mean/peak; dropped arrivals; actual interval and drain interval.
- One-second or similarly fine interval samples of throughput, in-flight requests, server/client CPU and RSS, queue/admission depth when available, and socket counts. A five-minute aggregate can hide a final-minute collapse.
- Server logs without credentials; preflight and postflight outcomes; database row count and any integrity check after stopping the benchmark server safely; checksums of result files.
- A generated summary tied to those reports, with exact reproduction commands. The summary must not require a reviewer to trust manually typed headline numbers.

Use a bounded histogram rather than retaining millions of per-request samples in memory; record units and histogram precision. Response timing should include complete body consumption and validation. If using k6, note that its built-in `http_req_duration` omits DNS/connection-establishment time, so add a custom full request-duration metric when those costs matter. Report setup and warm-up separately from the measured interval. [k6 metric definitions](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/)

Record completed-in-window and post-window-drained counts separately. Include a bounded request timeout and graceful drain period. Averages/RPS must use the stated interval consistently; do not include late completions in the numerator while excluding their elapsed drain time without labeling that convention. Termination must count canceled outstanding work as unfinished/failure, not erase it.

## Host inspection, 2026-10-16

These are direct read-only observations from this session, not results inferred from the reel:

| Attribute | Observed value |
| --- | --- |
| Processor | AMD Ryzen 5 5600H with Radeon Graphics |
| CPU topology | 6 physical cores, 12 online logical CPUs, SMT 2 threads/core |
| RAM | `/proc/meminfo`: 32,187,748 KiB total (approximately 30.70 GiB); about 22 GiB available at inspection |
| Swap | About 61 GiB configured; unused at inspection |
| Kernel | Linux 7.2.5-3-omarchy, x86_64 |
| Workspace filesystem | `/dev/mapper/omarchy_root`, approximately 56 GiB free at inspection |
| Agent cgroup ceiling | Shared ancestor `app-t3code-agents.slice`: 28,665,286,656 bytes (about 26.70 GiB) memory ceiling; no observed ancestor CPU quota; CPUs 0–11 available |
| Shell soft open-file limit | 524,288 |
| Automatic TCP source ports | 32,768–60,999 inclusive: 28,232 possible ports before reservations/other use |
| Conntrack | `nf_conntrack_max=262144`; `nf_conntrack_count=241` at inspection |
| io_uring sysctl | `kernel.io_uring_disabled=0`; this alone does not prove a particular operation/runtime works |
| Existing load tools | k6/wrk/wrk2/vegeta/hey/bombardier/oha absent from PATH at inspection |
| Available utilities | curl, taskset, timeout, ss, jq, Python; Rust and Go through mise shims |
| Rust shell behavior | cargo/rustc shims initially required explicit tool selection; installed choices listed `rust@stable` and `rust@1.88.0` |

Capture the effective limits of the **actual server and client processes** again when benchmarking; this agent's limits are context, not proof of their eventual process configuration. No sysctl, global file limit, CPU governor, or firewall setting was changed during this inspection.

For many simultaneous HTTP/1 connections to a single destination from one source address, the automatic source-port range can limit the generator well before server CPU is exhausted. Keep-alive reduces socket churn; `TIME_WAIT`, reservations, existing sockets and multiple address/destination tuples affect the actual ceiling. The kernel documents automatic port allocation and conntrack's flow-entry limit. The reel's 65,536 conntrack setting is not this machine's setting. [Linux IP sysctls](https://docs.kernel.org/networking/ip-sysctl.html), [Linux conntrack sysctls](https://docs.kernel.org/networking/nf_conntrack-sysctl.html)

## Tool choice and limits of the experiment

k6 offers readable functional scripts and both workload models. wrk2 is useful for a preseeded endpoint with a fixed offered request rate and planned-schedule latency, but its own README warns that response callbacks reduce generated load and that its calibration makes very short runs unhelpful. Vegeta is another constant-rate generator with reusable connections and machine-readable reports. A repository-owned Rust generator is reasonable when needed for full response validation and artifact control, provided its source, scheduler, accounting and limitations are reviewed. [k6 scenario executors](https://grafana.com/docs/k6/latest/using-k6/scenarios/), [wrk2](https://github.com/giltene/wrk2), [Vegeta](https://github.com/tsenart/vegeta)

The generator and API share the same laptop, scheduler, memory subsystem, network stack, power budget and storage. Loopback omits Wi-Fi, Internet, TLS and proxy costs. Report the result as **co-located loopback application capacity**, including generator CPU/RSS and any CPU affinity, rather than remote-client or Internet capacity. Affinity can reduce competition but also changes the workload allocation; record it and avoid claiming the process had all 12 logical CPUs if it was pinned to fewer.

An idle-connection test can demonstrate connection handling, but is distinct from useful work. A phone demonstration over LAN/Tailscale/public tunnel is a reachability and functional check, not a capacity measurement. Do not run the public demo and disposable benchmark server against the same writable database. A separate external load generator and longer repeat runs would be needed for a stronger production capacity estimate.

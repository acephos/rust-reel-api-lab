# Independent proof publication review

Reviewed `scripts/summarize-proof.py` at `ee4ba05`, the current request/event recorder, and completed exploratory artifacts on 2026-10-16. This was a read-only source/artifact review; no load was generated. The reviewer authored the additional functional harness, so that part is not an independent reimplementation of the tests.

## Observed evidence

The four completed 15-second ladder stages (16/64/256/1024 active workers) have valid compact-file SHA256 manifests. Each stage's endpoint validated counts sum to its recorded hold count; all start/finish counts balance and every endpoint passes the declared latency and semantic thresholds. For 1024 workers, `125426 / 15 = 8361.7333` validated requests/s, observed outstanding mean is 1015.17 and peak is 1024. Endpoint p99 values are 244–247 ms. These are exploratory results, not five-minute holds.

The later completed 2048-worker stage records 127533 validated hold requests (8502.2/s), outstanding mean 1984.71 / peak 2048, and worst endpoint p95 372 ms / p99 422.2 ms. The 4096-worker stage was still running when inspected.

All inspected stages identify binary SHA256 `9a652c867a36449ab0acfc3988a8b16c149f4bd4b44faca2aac40bea33fc26e5`, matching the final 24/24 functional report. Recorded configuration selects the default io_uring backend, localhost port 3000, a separate benchmark database, and no demo environment. Source revisions and dirty status are retained; later recorder changes must not be presented as though every earlier run used identical instrumentation.

## Findings / publication recommendations

1. **P2: validate identity before publication** (`summarize-proof.py:10–16,70–72`). Equality of three missing hashes succeeds (`None == None == None`). Require nonempty 64-digit digests, actual server argv/configuration and expected modes (`active`, `original`, `open`). Check final exit status and balanced, nonnegative request accounting explicitly. This prevents incomplete metadata from becoming a machine-specific proof. Use explicit exceptions rather than `assert`, which Python optimization disables.
2. **P2: link factual warm-up claims to evidence** (`summarize-proof.py:111`). The generated text asserts a separately recorded 1000-VU/two-minute warm-up without accepting/checking that artifact. Publish this sentence only after that run exists, and link its settings/results. Likewise, the supplied five-minute holds and open confirmation must actually complete before publishing `status=complete`.
3. **Clarify provenance scope.** The recorded Git revision is the measurement checkout, not independently attested binary build provenance. Preserve the matching binary digest and source-file hashes, verify compact manifests when publishing, and describe any dirty files. The current actual artifacts are internally consistent; unsigned checksums detect changes but are not an independent attestation.
4. **Label resource aggregation.** CPU means and socket/RSS peaks use all resource samples, including original-workload ramp/drain. Name that scope or restrict to hold timestamps. Do not label those means as hold-only CPU measurements.

## Mathematical interpretation and readiness

The recorder correctly tags each request once at its start and retains that tag through completion. Hold throughput therefore counts validated requests *started* in hold divided by configured hold seconds, including their eventual bounded drain. Outstanding mean uses first hold start to final hold-tagged event; it is not a mean over exactly 300 seconds. The publication notes explain this distinction. Phase-separated completion intervals retain the timing evidence. Earlier ladder summaries lack the later aggregate `full_request_ms{phase:hold}` metric, so publish new holds rather than deriving aggregate percentiles from endpoint percentiles.

Configured active workers, observed outstanding requests, browsing VUs, established socket samples, and requests/s are correctly distinct. Neither peak client outstanding work nor available server CPU proves parallel handler execution or an absolute maximum. Open-mode planned/started/finished/drop/residual accounting should be inspected alongside zero-drop thresholds; a scheduling-boundary residual is not silently equivalent to achieved offered rate.

Ready to run a conservatively selected five-minute active hold, the recorded warm-up plus 5000-user original hold, and independent open confirmation, sequentially. Publication is ready only after passing artifacts and the checks above. Existing short-stage passes do not supply the missing duration evidence. Lint-only source collapses do not invalidate the current binary identity; any actual rebuild must be identified by its digest and revalidated before claiming equivalence.

## Final active-hold / HTTP transport audit

Follow-up reviewed through `8c59873`. The publisher now verifies compact manifests, final exit status, nonempty binary identity/configuration, exact workload modes, balanced request accounting, five-minute active/original durations, the separately recorded 1000-user/two-minute warm-up, matching binaries, and matching transport raw/run identity. Earlier publication findings are addressed. CPU summaries now explicitly identify all-phase/export-tail scope and separately label approximate request-period samples.

The wrapper delta events include validation and metric-recording time; their mean **1778.61** must therefore be called **client-operation overlap**, not HTTP-only outstanding requests. The updated publisher makes that distinction. Full-request SLO timers and wrapper overlap also have different endpoints, because the timer is sampled before the remaining custom metric emissions.

`bench/http-concurrency.py` instead reconstructs each hold-tagged HTTP interval as `[response_end - http_req_duration, response_end)`. This matches Grafana's primary definition: HTTP metric timestamps correspond to response completion, and duration sums sending, waiting and receiving while excluding initial connection establishment. [Official k6 metric definitions](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/).

The script verifies the raw gzip digest, parses every selected duration event, rejects nonfinite/negative durations, and checks sample count against recorded HTTP events. Sorting starts and ends with end-before-start ties gives the overlap peak for half-open intervals; independent overlapping, disjoint and exact-boundary fixtures passed. Zero-width intervals are handled separately and none occur in this run. Microsecond timestamp conversion limits temporal precision; this is reconstructed client transport overlap, not instrumented simultaneous SQLite execution.

The derived report matches the active run's raw digest, binary digest, and **3149069** hold HTTP/validated samples. Its mathematics independently checks: `3149069 × 70.8857865434 ms / 1000 / 300.1017587185 s = 743.8284730407` mean HTTP requests in progress. This also agrees with k6's separately aggregated approximately 70.8858-ms mean HTTP duration. The reported transport peak is **2048**, with zero unfinished or negative accounting. I inspected the parser, derived report, compact summaries and identities; I did not repeat the large gzip scan during concurrent measurement.

The five-minute active result is therefore **2048 configured workers, approximately 744 mean / 2048 peak HTTP transport overlap, 10496.90 validated requests/s**, full-request p95/p99 **235/323 ms**, and zero HTTP/semantic failures. The maximum full latency is 2414 ms: the passing p99 target does not imply every request completed within one second. All acknowledged active-load creates and first likes reconcile exactly to persisted row-count increases (787257 and 787204), with SQLite integrity, foreign keys and fixed schema checks passing; this remains process-stop recovery evidence, not power-loss durability.

The phone card title was considered as a presentation judgment: its unit explicitly says concurrent request workers, and prominently loaded report notes disclose HTTP mean/peak. The standalone report uses “Active request workers” and separate HTTP rows. Retaining the embedded UI preserves the exact measured/functional binary identity; this is a reasonable resolution rather than a material proof defect. The reports must continue to avoid describing 2048 as continuously pending HTTP requests.

**Verdict: no material unresolved defect in the active measurement or corrected publication definitions.** Original browsing and independent arrival claims remain conditional on their own completed passing artifacts; no final result is inferred from an in-progress run. No application HTML or benchmark files were changed by this review.

## Final publication verdict

Audited the completed report, README, all four run manifests/summaries/accounting files, and three database reconciliations. Compact checksums match; final exits and thresholds pass; request counts balance. Active/original five-minute holds, recorded warm-up, open confirmation, HTTP reconstruction and 24-group functional proof identify the same measured binary. All acknowledged writes reconcile with persisted row counts; integrity, foreign keys and unchanged schema pass.

The 5000-user hold achieved 529.47 validated requests/s, full p95/p99 1/2 ms. Open load offered 5000/s for 60 seconds, achieved 4999.983 hold-validated requests/s, p95/p99 4/8 ms, and zero drops/errors. Its 300001 total starts versus 300000 theoretical arrivals produce the explicitly retained -1 boundary residual, not a concealed drop.

**Ready to publish; no material unresolved proof issue.** Loopback/generator, duration, concurrency-definition, raw-retention and durability limits remain visible. No load or raw-stream rescans were performed for this final audit.

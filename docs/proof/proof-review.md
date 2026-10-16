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

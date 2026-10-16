# Benchmark generator validation

The first two-second smoke run exposed a defect in the benchmark validator, before any sustained capacity claims were made. The failed evidence is retained at [`proof/runs/smoke/`](../../proof/runs/smoke/): HTTP responses succeeded, but the validator reported semantic failures, including all feed responses.

The validator correctly required the API's documented JSON property order, but obtained objects through k6 `Response.json()`. That path converted JSON objects through Go maps and did not preserve wire property order. A single-VU, single-request diagnostic against the live API on 2026-10-16 produced:

```text
Object.keys(response.json().posts[0]):
like_count,id,body,created_at,author

Object.keys(JSON.parse(response.body).posts[0]):
id,body,created_at,author,like_count
```

The server returned HTTP 200 with `Content-Type: application/json`. Native JavaScript parsing preserved the actual correct wire order. [`bench/load.js`](../../bench/load.js) now uses `JSON.parse(response.body)`; all schema, property-order, status, identity, sorting and payload checks remain enforced. The earlier run is a generator-validation failure, not evidence that the API's wire order was incorrect.

The corrected two-second run is retained at [`proof/runs/smoke-fixed/`](../../proof/runs/smoke-fixed/). It completed 12,268 requests, validated every response, exercised all four workload endpoints, recorded zero interrupted iterations, and passed every k6 threshold. Global outstanding-request event reconstruction found 12,268 starts and 12,268 finishes, peak 16 and mean approximately 15.04 over a 2.017-second observed span. These are **smoke-validation observations**, not a five-minute capacity claim.

Additional checks before sustained testing:

- The installer verified official Grafana k6 v2.3.0's Linux x86_64 archive against both the release checksum list and the repository's pinned digest.
- Bash syntax, Python syntax, and k6's script inspection passed for original, active and independent-arrival modes.
- A synthetic overlapping-event check independently established that starts at 0/1/2 seconds and completions at 2/3/4 seconds reconstruct peak 2 and time-weighted mean 1.5, with three validated completions. Exact-timestamp ties process completions first.
- Code review confirmed that local raw events are streamed to ignored gzip storage; public reports retain their SHA256 and path, compact intervals, exact k6 threshold summaries, and complete error accounting.
- Metadata captures the actual server executable SHA256, source-file hashes, compiler/k6 versions, dirty working-tree status, effective cgroup limits, CPU affinity and descriptors. Subsequent recorder hardening also captures exact server arguments and public HOST/PORT/SQLITE_PATH settings while excluding secrets, and rejects negative/unbalanced concurrency event accounting.

The corrected smoke already demonstrated generator overhead: k6 consumed approximately 332–430% CPU in the available one-second samples, while the server consumed approximately 20–28% (100% represents one logical CPU's worth of execution). Consequently, a co-located benchmark plateau must not be described as a saturated server maximum without further evidence. The complete run artifacts preserve these observations.

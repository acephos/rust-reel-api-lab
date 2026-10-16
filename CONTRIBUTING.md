# Contributing

Preserve the exact five-route challenge contract and schema. Keep the demo opt-in. Do not add application data/response/JWT-verification caches. Respect upstream MIT attribution and pin imported source/dependency revisions. Do not copy benchmark numbers from another host into local results.

SQLite is compiled without its mutexes. Every call must remain under the shared App lock. Kernel I/O pointers must outlive their terminal completion. Document safety invariants adjacent to unsafe operations. Keep output ordered under pipelining and preserve partial-send progress. Successful writes must commit before bytes are sent.

Use rustfmt and cargo clippy. Functional changes require meaningful HTTP/protocol/recovery checks; run the upstream suite on a fresh database copy. Benchmark source changes require a new artifact directory and clear workload, source revision, binary checksum and limitations. Never overwrite a failed run to make a later result look uniformly successful.

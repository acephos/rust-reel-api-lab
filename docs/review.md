# Review and validation

The changes were reviewed from the pinned import commit `0cec49222b595316acb2147b0b6d8d370976591a` through implementation commit `4a5f3a5609e0a3f9ec0e4208b96a98a97061c196`, with follow-up fixes checked in the working tree. The originating spec is the user request as captured in `docs/reel-analysis.md` and the pinned upstream API contract. No external issue number is invented.

## Standards

See [the independent standards report](review-standards.md). One documented-standard finding: already-extracted SQLite sources bypassed the version/checksum pin. Fixed by validating both expanded-source digests on every build. One evidence judgment: binary checksum alone did not identify backend/tuning arguments. Fixed by recording actual process argv and allowlisted runtime environment, compiler and source checksums. An initial concern about compiler selection was withdrawn: `rust-toolchain.toml` already pins1.98.1.

A separate safety/strategy inspection found that a64-byte record was not guaranteed to be cache-line aligned. Fixed with `repr(C,align(64))` plus compile-time size/alignment assertions. No new unsafe lifetime defect was identified in changed hunks. The reviewer authored the protocol tests, so their review of those tests is less independent.

## Spec

See [the independent specification report](review-spec.md). No confirmed API regression or unmet implementation technique in the reviewed changes. The derived original browsing script preserves sequence/probabilities/think time but strengthens response/endpoint/full-duration gates; it must not be described as the unmodified official k6 test. The independent organizer warm-up is separate from a ramp: the proof documents what was actually executed. The reviewer authored the UI, so that part has weaker independence.

## Follow-up validation

- Both io_uring and explicit epoll pass the unchanged upstream42 checks on fresh full seed copies.
- Extended suite:12 substantive groups per backend,24 groups total. A first-run JWT test incorrectly expected “invalid token” for an empty bearer credential; HTTP field whitespace normalization makes this a missing-bearer error. Corrected the test; preserved the first result and the focused recheck. It was a test defect, not an API fix.
- The suite validates47 acknowledged posts and36 acknowledged likes after SIGKILL for each backend, SQLite integrity/foreign keys and unchanged schema, then restarts and reads posts through HTTP. This is process recovery, not power-loss proof.
- Desktop and390px browser checks exercised real creation, live feed, liking, post inspection, explorer, health and pending proof. A mobile request-history overflow was found and fixed by bounding the nested grid track; post bodies use text nodes and a script-looking payload remained literal text.
- Rust formatting, release Clippy with warnings denied, Bash/Python/JavaScript syntax checks and live demo reachability are recorded with the proof artifacts. No claim of exhaustive memory-safety auditing or a sanitizer run.

Standards:1 historical documented finding plus1 engineering judgment, both resolved; worst historical issue was source pin bypass. Spec:0 confirmed defects. Capacity conclusions are separately reviewed against the measured artifacts in `docs/proof/README.md`.

# Standards review

Reviewed `git diff 0cec49222b595316acb2147b0b6d8d370976591a...4a5f3a5609e0a3f9ec0e4208b96a98a97061c196`. One commit: `4a5f3a5 Add opt-in Rust demo, reproducible build, functional checks and capacity tooling`. Sources: `CONTRIBUTING.md`, `docs/design.md`, and the code-review skill's Fowler smell baseline. Formatting/lint findings excluded. This reviewer authored `tests/functional.py`; assessment of those tests is consequently less independent. Runtime verification is being run separately.

## Documented-standard finding

- **P2 — SQLite source pin can be bypassed** (`scripts/build.sh:7–12`). `CONTRIBUTING.md` requires pinned imported source/dependency revisions. The checksum verifies the downloaded archive only when either extracted file is absent. Existing ignored `vendor/sqlite3.c` and `.h` are trusted without verification. A stale vendor directory from another SQLite version, or a modified amalgamation, silently builds while documentation advertises checksum-verified SQLite 3.53.4. Verify pinned expanded-source hashes on every build, or re-extract from the verified archive when the hashes differ.

## Engineering judgments, not hard standard violations

- **P2 — Server configuration is missing from proof metadata** (`bench/evidence.py:53–79`). Executable identity does not distinguish the same binary launched with `--epoll`, `--no-group`, or different io_uring tuning. Consequently the artifacts alone cannot establish which documented backend/transaction policy produced a result. Capture `/proc/<pid>/cmdline` and a safe allowlist of runtime configuration; omit JWT secrets. This strengthens the reproducibility rule in `CONTRIBUTING.md`.

No additional actionable Fowler smell is reported; extracting thin abstractions here would add little value.

## Resolved / preserved

The earlier 64-byte-record concern is resolved: `Client` now has `repr(C, align(64))` and size/alignment assertions. The existing `rust-toolchain.toml` correctly selects Rust 1.98.1; the initial compiler-selection concern is withdrawn. Follow-up `99be6f9` and its working-tree extension record server arguments and allowlisted environment, addressing the configuration finding above. The current `scripts/build.sh` verifies pinned hashes of both expanded SQLite files on every build, resolving the source-pin finding. Both historical findings above are therefore addressed in the reviewed follow-up files.

The reviewed engine changes preserve stable send allocations, ordered pipeline output, deferred commit-before-send behavior, and an opt-in demo. No new unsafe lifetime defect was identified in the changed hunks. This is static review, not exhaustive safety proof.

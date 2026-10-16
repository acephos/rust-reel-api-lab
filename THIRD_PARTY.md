# Provenance and licenses

This is an attributed study and extension of the implementation featured in the reel, not an independent invention of that engine.

- Source reel: [Arjay McCandless, 15 October 2026](https://www.instagram.com/reel/Deh4spFuAdz/). Video and audio are not redistributed.
- Engine: [scooter1337's PR #19](https://github.com/arjaythedev/twelve-dollar-server-challenge/pull/19), revision `bd517fa7c8a57b135579ae02fdddb6196b4cd9a4`. Imported `src/{main,db,net,uring}.rs`, `Cargo.toml`, `Cargo.lock`, `build.rs`, and `bench/train_sqlite.c`; license retained in `third_party/engine-LICENSE`. The PR has evolved since the reel; this pinned revision contains later improvements too. Its historical results do not establish this project's capacity.
- Challenge specification, fixed schema, deterministic seed generator, 42-check suite/golden fixtures and original k6 workload: `third_party/challenge/`, from upstream main (exact revision recorded in `docs/reel-analysis.md`), MIT, license retained there.
- SQLite 3.53.4: [official source](https://www.sqlite.org/2026/sqlite-autoconf-3530400.tar.gz), downloaded locally, verified with SHA-256 `0e9483900e92cd5de8fd48d16bf9200145a61f7fd5be542a5ac81d8a9516eb9c`. [Public domain dedication](https://www.sqlite.org/copyright.html). Not committed.
- Rust crates: exact versions and checksums in `Cargo.lock`; licenses belong to their respective authors.

Project additions include the interactive demo, reproducible local workflow, functional/network/recovery tests, load-test instrumentation, review, research, and this machine's evidence. Compare changes after the initial import commit to inspect local modifications.

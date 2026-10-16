# Research: a custom Rust io_uring HTTP and SQLite server

Research date: 2026-10-16. Scope: implementation techniques extracted from the linked reel by the parent analysis: a custom HTTP/1.1 parser, replacing Tokio/sqlx with io_uring and direct SQLite, multishot accept/receive, reusable buffers, a 64-byte connection record, and batched transactions. This note validates implementation choices against upstream documentation; it does not independently establish that the reel's performance claims are reproducible.

## Recommendation

Build one event loop that owns its io_uring instance, socket state, buffer pool, and one SQLite connection. Collect completions, parse all complete bounded requests, execute a bounded batch of database work, enqueue ordered responses, then submit the next batch of I/O. Keep the API/application logic independent of this transport. This is a design inference, not a claim that single-threaded execution is always faster. SQLite work and password derivation on this thread also pause network progress, so measure the full endpoint workload rather than extrapolating from a static response.

The Rust `io-uring` crate provides direct opcode builders and submission/completion queues; using this crate does not require a Tokio runtime. Its upstream TCP example demonstrates a buffer pool, a submission backlog, and tracking write progress. Treat that example as guidance rather than a production HTTP server. [Rust crate source](https://github.com/tokio-rs/io-uring), [upstream TCP example](https://raw.githubusercontent.com/tokio-rs/io-uring/master/examples/tcp_echo.rs).

## Machine observations

These were read directly on this machine, with no system configuration changes:

| Property | Observed value |
| --- | --- |
| Kernel | Linux 7.2.5-3-omarchy, x86_64 |
| CPU | AMD Ryzen 5 5600H, 6 physical cores, 12 logical CPUs |
| L1 data cache coherency line | 64 bytes (`/sys/devices/system/cpu/cpu0/cache/index0/coherency_line_size`) |
| `kernel.io_uring_disabled` | 0 |
| Shell soft / hard file descriptor limits | 524288 / 524288 |
| Actual `io_uring_setup(64, zeroed params)` | Succeeded; SQ entries 64, CQ entries 128, feature bits `0x3ffff`; descriptor then closed |

The actual successful ring setup is stronger evidence than the kernel version alone. It does not prove every modifier, endpoint, or concurrency level works. File descriptor limits are ceilings, not a measured request capacity.

## Multishot operation lifecycle

Multishot accept exists since Linux 5.19. Submit `AcceptMulti` against the listener with null peer-address pointers if peer identity is unnecessary: a shared output address can be overwritten by a subsequent accepted connection. Each successful CQE yields a new ordinary socket descriptor. Set close-on-exec on accepted descriptors. Check `IORING_CQE_F_MORE` on every completion; absence ends that multishot request, requiring rearm if service should continue. [Upstream liburing accept manual](https://man7.org/linux/man-pages/man3/io_uring_prep_multishot_accept.3.html).

Multishot receive exists since 6.0. `RecvMulti::new(fd, buffer_group)` selects a buffer for each received completion; it cannot be used with `MSG_WAITALL`. Its builder sets buffer selection internally, as the current source shows. A portable baseline uses the default zero length; avoid newer modifiers such as receive bundles or incremental consumption unless implemented and tested deliberately. For every CQE, inspect both result and `MORE`; a successful receive can also be the final completion. [Rust RecvMulti API](https://docs.rs/io-uring/latest/io_uring/opcode/struct.RecvMulti.html), [opcode builder source](https://raw.githubusercontent.com/tokio-rs/io-uring/master/src/opcode.rs).

A depleted provided pool reports `-ENOBUFS`. Return consumed buffers promptly, and rearm receive after replenishment when `MORE` is absent. Extract a buffer ID only when the CQE has `IORING_CQE_F_BUFFER`; the ID occupies the upper 16 flag bits. These are buffer IDs, not connection IDs. Legacy `ProvideBuffers` is usable, but returning buffers consumes submission entries; a registered provided-buffer ring removes that per-return SQE cost. [Provided buffers overview](https://man7.org/linux/man-pages/man7/io_uring_provided_buffers.7.html), [Rust ProvideBuffers API](https://docs.rs/io-uring/latest/io_uring/opcode/struct.ProvideBuffers.html).

## Buffer ring and Rust ownership

A registered provided-buffer ring requires page-aligned ring metadata, a power-of-two entry count no greater than 32768, and zeroed reserved fields. Entries describe an address, length, and 16-bit buffer ID. Keep backing allocations and registration alive while the kernel may use them. Buffer-pool registration and fixed/registered I/O buffers are different mechanisms. [Registration requirements](https://man7.org/linux/man-pages/man3/io_uring_register_buf_ring.3.html).

Encapsulate unsafe ownership in one module. Each buffer transitions `available to kernel -> completed to userspace -> recycled`. Parse or copy its data before recycling; do not retain borrowed slices into a buffer that the kernel can overwrite. For fragments spanning receives, copy only retained bytes to connection-owned storage. Publish filled ring entries with release ordering on the tail; do not replace the first entry wholesale because the ring tail shares its reserved layout. Rust's `BufRingEntry::tail` specifically requires a valid, initialized, page-aligned base. [Rust BufRingEntry API](https://docs.rs/io-uring/latest/io_uring/types/struct.BufRingEntry.html), [crate registration implementation](https://raw.githubusercontent.com/tokio-rs/io-uring/master/src/submit.rs).

For every raw-pointer send or receive, the pointed allocation must remain stable and alive until its operation finishes. Moving a `Vec` value retains its allocation, but appending can reallocate; never mutate a response allocation while a send points into it. Use owned immutable output allocations or a pool with explicit in-flight ownership. This is a safety inference from the pointer-based opcode API.

## Sends, EOF, cancellation, and slot reuse

An ordinary send may finish short. Maintain a fixed total length plus an absolute offset: on positive result `n`, advance `offset += n` and send `[offset..total]` until complete. Treat a zero result on a nonempty send as failure to progress. Use `MSG_NOSIGNAL` so a disconnected peer does not terminate the process with SIGPIPE. [Linux send semantics](https://man7.org/linux/man-pages/man2/send.2.html).

Allow only one ordinary send in flight per socket. Multiple independent sends can reorder the outgoing stream; a queue of responses plus completion-driven serialization avoids that issue. Keep each response alive until its final send completion. Linked sends alone do not solve short writes. [Upstream send manual](https://man7.org/linux/man-pages/man3/io_uring_prep_send.3.html).

On receive zero, record EOF rather than freeing connection state immediately. A client can finish writing its request and still read its response; flush any complete queued response, and reject an incomplete request. For deliberate shutdown, cancel the multishot receive and observe its terminal completion before dropping state that it references. Cancellation itself produces a CQE, while the target operation has its own completion lifecycle. A cancellation can lose a race with a completing operation. [Cancellation semantics](https://man7.org/linux/man-pages/man3/io_uring_prep_cancel64.3.html).

Encode operation kind, slot ID, and generation in `user_data`. Keep a closing slot unavailable until outstanding operations complete, and ignore stale-generation completions. This recommended invariant prevents a completion from an old connection modifying a newly reused slot. Bound the SQ backlog, output bytes, request bytes, connection count, and requests processed per loop. Exhaustion must lead to controlled backpressure or rejection rather than unbounded allocation.

## HTTP framing requirements

`httparse` parses the request line and headers; application framing must still distinguish partial headers, partial bodies, and multiple requests received together. Apply size limits before further buffering. Preserve response order for pipelining, fully consume a request body before reusing a persistent connection, honor `Connection: close`, and suppress response body bytes for HEAD. Reject invalid/conflicting Content-Length values and Transfer-Encoding ambiguity. Implement chunked request decoding if claiming general HTTP/1.1 support; otherwise document a Content-Length-only API profile and close after explicitly rejecting unsupported transfer coding. Header names and Connection tokens require case-insensitive handling. [HTTP/1.1 RFC 9112, message lengths and connection management](https://www.rfc-editor.org/rfc/rfc9112.html).

Recommended functional tests: headers/body split at many byte boundaries; coalesced pipelined GET/POST requests; response order when database and immediate routes mix; slow readers and forced short sends; reset during send; request followed by write-side shutdown; EOF mid-body; invalid Content-Length; Transfer-Encoding rejection/decoding; pool exhaustion/replenishment; rapid slot reuse; and clients exceeding configured bounds. These are project design recommendations, not results already measured.

## SQLite batching, WAL, and durability

Use one owning connection with prepared statements and explicitly bounded transactions. SQLite already permits only one writer at a time; WAL permits readers to proceed while a writer appends, but does not create parallel writers. Automatic checkpointing can introduce occasional latency. WAL's shared memory design requires all users to be on the same host. [SQLite WAL design](https://sqlite.org/wal.html).

Transactions amortize commit work over many inserts. SQLite's FAQ explicitly distinguishes insert speed from transaction/commit speed. Batch only work that is already available, or use a strict maximum delay. A maximum batch size without an independent flush condition can stall a lone request forever. A suitable loop processes all available completions up to a fairness bound, executes that batch, and submits responses before waiting again. [SQLite FAQ on insert performance](https://sqlite.org/faq.html#q19).

Do not emit successful registration responses before COMMIT succeeds. If commit fails, return errors for all operations whose writes were rolled back. Expected uniqueness failures should be isolated with suitable statement conflict behavior or savepoints so one duplicate cannot accidentally invalidate unrelated reported successes. Reads within the transaction can observe preceding writes on the same connection. Choose batch ordering explicitly; preserving completion/request order makes a register-then-login sequence predictable. [SQLite transactions](https://sqlite.org/lang_transaction.html).

`journal_mode=WAL; synchronous=NORMAL` is a deliberate performance/durability tradeoff. In WAL mode NORMAL preserves consistency, but acknowledged commits can be lost after OS crash or power failure; application crashes are a different case. FULL adds commit synchronization for stronger durability. Record this setting with benchmark results and expose FULL when callers need it. Do not describe NORMAL results as proving fully durable commit throughput. [SQLite synchronous documentation](https://sqlite.org/pragma.html#pragma_synchronous).

## Feature checks and honest fallback

At startup, attempt ring creation and report its actual error. Probe base opcodes, but remember that opcode support does not prove support for every flag: multishot receive shares the ordinary RECV opcode. A loopback runtime exercise plus checking CQE errors validates the required modifier path. If multishot is unavailable, an explicit single-shot transport can be provided, but telemetry and proof must identify the transport used. A version check alone is insufficient. [Opcode probe API](https://man7.org/linux/man-pages/man3/io_uring_register_probe.3.html), [io_uring setup features/errors](https://man7.org/linux/man-pages/man2/io_uring_setup.2.html).

Start with ordinary interrupt-driven submission rather than SQPOLL/IOPOLL. Extra polling modes add CPU/resource constraints, and IOPOLL is not a generic TCP acceleration flag. Do not silently enable expensive polling or change kernel sysctls for benchmark numbers. [io_uring setup flags](https://man7.org/linux/man-pages/man2/io_uring_setup.2.html).

For the cache-line strategy, use `#[repr(C, align(64))]` and a compile-time size assertion for the hot record. Store variable-size request/response buffers separately. A 64-byte record does not mean a connection consumes only 64 bytes: account for heap allocations, socket memory, outstanding CQEs, and database work. Treat locality as a hypothesis to measure, not a throughput guarantee.

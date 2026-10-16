#!/usr/bin/env python3
"""Additional black-box API, TCP, and process-crash checks (stdlib only).

Run after cargo build --release:
  python3 tests/functional.py --seed third_party/challenge/seed/feed.db \
    --server target/release/twelve-rust-poll --backend both \
    --output artifacts/functional.json

Every backend gets an isolated SQLite backup. No live production/seed database is
modified. The crash check proves application-crash recovery, not power-loss
durability of WAL/NORMAL. Backpressure checks byte integrity; they do not count
kernel short-send events or measure request capacity.
"""

import argparse
import base64
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import traceback


SECRET = "functional-test-secret-only"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def compact(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def jwt(claims=None, *, alg="HS256", secret=SECRET):
    if claims is None:
        claims = {
            "sub": "1", "username": "user_1", "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
    unsigned = b64(compact({"alg": alg, "typ": "JWT"})) + "." + b64(compact(claims))
    signature = hmac.new(secret.encode(), unsigned.encode(), hashlib.sha256).digest()
    return unsigned + "." + b64(signature)


def schema(connection):
    return connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()


class ResponseReader:
    """Keep unread pipeline bytes between responses, including interim 100."""

    def __init__(self, connection):
        self.stream = connection.makefile("rb")
        self.bytes_read = 0

    def response(self):
        status_line = self.stream.readline(8192)
        check(status_line.startswith(b"HTTP/1."), f"invalid/missing status: {status_line!r}")
        status = int(status_line.split(b" ", 2)[1])
        headers = {}
        self.bytes_read += len(status_line)
        while True:
            line = self.stream.readline(65537)
            self.bytes_read += len(line)
            check(bool(line), "EOF in response headers")
            if line == b"\r\n":
                break
            name, value = line.split(b":", 1)
            headers[name.strip().lower()] = value.strip()
        if 100 <= status < 200:
            return status, headers, b""
        check(b"content-length" in headers, "response needs explicit Content-Length")
        length = int(headers[b"content-length"])
        body = self.stream.read(length)
        self.bytes_read += len(body)
        check(len(body) == length, f"truncated body: expected {length}, received {len(body)}")
        check(headers.get(b"content-type", b"").startswith(b"application/json"),
              f"unexpected content type: {headers}")
        return status, headers, body

    def close(self):
        self.stream.close()


class Fixture:
    def __init__(self, server, seed, backend, directory):
        self.server = str(server)
        self.backend = backend
        self.directory = Path(directory)
        self.database = self.directory / "feed.db"
        self.log_path = self.directory / "server.log"
        self.process = None
        self.log = None
        self.created = {}
        self.likes = set()
        self.usernames = {}
        with closing(sqlite3.connect(f"file:{seed}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(self.database)) as target:
                source.backup(target)
            self.original_schema = schema(source)
            self.usernames = dict(source.execute("SELECT id,username FROM users WHERE id<=3"))
        check(1 in self.usernames and 2 in self.usernames, "seed must contain users 1 and 2")
        self.token = self.user_token(1)
        try:
            self.start()
        except Exception:
            self.stop()
            raise

    def user_token(self, user):
        return jwt({"sub": str(user), "username": self.usernames[user],
                    "iat": int(time.time()), "exp": int(time.time()) + 3600})

    def start(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        env = dict(os.environ, HOST="127.0.0.1", PORT=str(self.port),
                   SQLITE_PATH=str(self.database), JWT_SECRET=SECRET)
        args = [self.server] + (["--epoll"] if self.backend == "epoll" else [])
        self.log = self.log_path.open("ab")
        self.process = subprocess.Popen(args, env=env, stdout=self.log, stderr=self.log)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            check(self.process.poll() is None, "server exited during startup: " + self.logs())
            try:
                status, value = self.request("GET", "/health", timeout=0.5)
                if status == 200 and value.get("db") == "ok":
                    return
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.03)
        raise AssertionError("server readiness timeout: " + self.logs())

    def stop(self, crash=False):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGKILL if crash else signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def logs(self):
        return self.log_path.read_text(errors="replace")[-6000:]

    def connect(self, receive_buffer=None):
        connection = socket.socket()
        connection.settimeout(20)
        if receive_buffer is not None:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, receive_buffer)
        connection.connect(("127.0.0.1", self.port))
        return connection

    def request(self, method, path, body=None, token=None, timeout=10):
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            body = compact(body) if not isinstance(body, bytes) else body
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            check(response.getheader("Content-Type", "").startswith("application/json"),
                  f"non-JSON content type on {method} {path}")
            result = json.loads(raw)
            if method == "POST" and path == "/posts" and response.status == 201:
                self.created[result["post"]["id"]] = result["post"]["body"]
            return response.status, result
        finally:
            connection.close()

    def create(self, body):
        status, value = self.request("POST", "/posts", {"body": body}, self.token)
        check(status == 201, f"create failed ({status}): {value}")
        post = value["post"]
        check(list(post) == ["id", "body", "created_at", "author", "like_count"],
              f"post key order changed: {list(post)}")
        check(post["author"] == self.usernames[1] and post["like_count"] == 0,
              f"unexpected created post: {post}")
        return post

    def expect_error(self, body, status, message, token=None, path="/posts"):
        actual, value = self.request("POST", path, body, self.token if token is None else token)
        check((actual, value) == (status, {"error": message}),
              f"expected {(status, message)}, received {(actual, value)}")

    def wire_request(self, method="GET", path="/health", body=b"", extra=b""):
        return (method.encode() + b" " + path.encode() + b" HTTP/1.1\r\nHost: localhost\r\n"
                + extra + (b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                           if method == "POST" else b"") + b"\r\n" + body)

    def unicode_and_json(self):
        values = [
            'quotes " \\ and / <>&\n\r\t\b\f\x00\x01 end',
            "日本語 café 👩🏽‍💻 नमस्ते", "é" * 500, "🦀" * 500,
            "a" * 499 + "\u0301",
        ]
        for body in values:
            post = self.create(body)
            check(post["body"] == body, f"Unicode/escape round trip failed: {body!r}")
            status, value = self.request("GET", f'/posts/{post["id"]}')
            check(status == 200 and value["post"]["body"] == body, "persisted body differs")
        post = self.create("\ufeff\u2003\t  trimmed 🦀  \n\u00a0\ufeff")
        check(post["body"] == "trimmed 🦀", "Unicode whitespace trimming failed")
        for body in ["x" * 501, "🦀" * 501]:
            self.expect_error({"body": body}, 400, "body must be at most 500 characters")
        for value in [{}, {"body": None}, {"body": 4}, {"body": []}, {"body": {}},
                      {"body": "\t\n\ufeff\u2003"}, [], "body"]:
            self.expect_error(value, 400, "body is required")
        for body in [b'{"body":', b'{"body":"\\ud800"}', b'{"body":"ok"} trailing',
                     b'{"body":"\xff"}', b'{"body":"ok","ignored":[1,]}']:
            self.expect_error(body, 400, "malformed JSON body")
        post = self.request("POST", "/posts", b'{"body":"first","body":"last"}', self.token)
        check(post[0] == 201 and post[1]["post"]["body"] == "last", "duplicate JSON key semantics")
        return {"round_trip_cases": len(values), "boundary": "500 Unicode scalar values"}

    def jwt_validation(self):
        good = {"sub": "1", "username": self.usernames[1], "exp": int(time.time()) + 3600}
        invalid = [jwt(good, secret="wrong-key"), jwt(good, alg="none"),
                   jwt(good, alg="HS512"), jwt(dict(good, exp=1)),
                   jwt(dict(good, exp="tomorrow")), jwt(dict(good, nbf=int(time.time()) + 3600)),
                   jwt({k: v for k, v in good.items() if k != "exp"}),
                   "a.b.c", "", self.token + ".extra", jwt([1, 2])]
        for token in invalid:
            self.expect_error({"body": "should fail"}, 401, "invalid or expired token", token)
        payloads = [dict(good, sub=value) for value in [0, "0", "-1", "1.2", "abc", None]]
        payloads += [dict(good, username=value) for value in [12, None, [], {}]]
        payloads += [{k: v for k, v in good.items() if k != name} for name in ["sub", "username"]]
        for payload in payloads:
            self.expect_error({"body": "should fail"}, 401, "invalid token payload", jwt(payload))
        status, value = self.request("POST", "/posts/abc/like")
        check((status, value) == (401, {"error": "missing bearer token"}), "auth must precede id")
        self.expect_error(None, 400, "invalid post id", path="/posts/abc/like")
        escaped = dict(good, username='token "name" 🦀\\\n')
        status, value = self.request("POST", "/posts", {"body": "token author"}, jwt(escaped))
        check(status == 201 and value["post"]["author"] == escaped["username"],
              "creation author must use the signed token username")
        return {"invalid_jwts": len(invalid), "invalid_payloads": len(payloads)}

    def live_reads_and_likes(self):
        post = self.create("live update from the first HTTP connection")
        pid = post["id"]
        status, feed = self.request("GET", "/feed")
        check(status == 200 and feed["posts"][0]["id"] == pid, "feed omitted acknowledged create")
        for user in [1, 2]:
            token = self.user_token(user)
            for expected, repeated in [(201, False), (200, True), (200, True)]:
                status, value = self.request("POST", f"/posts/{pid}/like", token=token)
                check((status, value) == (expected, {"liked": True, "already_liked": repeated,
                                                    "post_id": pid}), "like not idempotent")
            self.likes.add((user, pid))
        status, value = self.request("GET", f"/posts/{pid}")
        check(status == 200 and value["post"]["like_count"] == 2, "post like count is stale")
        status, value = self.request("GET", "/feed")
        check(status == 200 and next(p for p in value["posts"] if p["id"] == pid)["like_count"] == 2,
              "feed like count is stale")
        return {"fresh_post_id": pid, "unique_likes": 2, "repeat_likes": 4,
                "read_model": "new HTTP connection after every acknowledged write"}

    def fragmented_request(self):
        body = compact({"body": "fragmented 🦀 request"})
        wire = self.wire_request("POST", "/posts", body,
                                 b"Authorization: Bearer " + self.token.encode() + b"\r\n")
        with self.connect() as connection:
            reader = ResponseReader(connection)
            try:
                # Force distinct receive opportunities across headers, body, and UTF-8 bytes.
                split = wire.index(b"\r\n\r\n") + 4
                chunks = [wire[:3], wire[3:19], wire[19:split - 1], wire[split - 1:split + 2]]
                chunks += [wire[i:i + 1] for i in range(split + 2, len(wire))]
                for piece in chunks:
                    connection.sendall(piece)
                    time.sleep(0.001)
                status, _, raw = reader.response()
                value = json.loads(raw)
                check(status == 201 and value["post"]["body"] == "fragmented 🦀 request",
                      "fragmented request failed")
                self.created[value["post"]["id"]] = value["post"]["body"]
            finally:
                reader.close()
        return {"fragments": len(chunks)}

    def concurrent_like_idempotence(self):
        post = self.create("same like raced across independent HTTP connections")
        pid = post["id"]
        token = self.user_token(2)
        with ThreadPoolExecutor(max_workers=32) as workers:
            results = list(workers.map(
                lambda _: self.request("POST", f"/posts/{pid}/like", token=token), range(64)))
        check(sum(status == 201 for status, _ in results) == 1,
              "a concurrent first-like race must insert exactly once")
        check(sum(status == 200 for status, _ in results) == 63,
              "all concurrent duplicate likes must succeed idempotently")
        for status, value in results:
            check(value == {"liked": True, "already_liked": status == 200, "post_id": pid},
                  "concurrent like response mismatch")
        self.likes.add((2, pid))
        status, value = self.request("GET", f"/posts/{pid}")
        check(status == 200 and value["post"]["like_count"] == 1, "concurrent likes duplicated rows")
        return {"requests": 64, "client_threads": 32, "inserted": 1, "duplicates": 63}

    def pipeline_order(self):
        post = self.create("pipeline target")
        with self.connect() as connection:
            reader = ResponseReader(connection)
            try:
                paths = ["/health", "/not-found", f'/posts/{post["id"]}', "/feed"] * 40
                connection.sendall(b"".join(self.wire_request(path=p) for p in paths))
                for path in paths:
                    status, _, raw = reader.response()
                    value = json.loads(raw)
                    expected = 404 if path == "/not-found" else 200
                    check(status == expected, f"pipeline response order at {path}: {status}")
                    if path.startswith("/posts/"):
                        check(value["post"]["id"] == post["id"], "pipeline body order")
                # Prove the socket remains usable after deferred pipeline batches.
                connection.sendall(self.wire_request())
                check(reader.response()[0] == 200, "pipeline socket cannot be reused")
                # Read-after-write ordering must also hold inside one pipeline,
                # including an immediate route between database operations.
                auth = b"Authorization: Bearer " + self.token.encode() + b"\r\n"
                new_body = compact({"body": "mixed mutation pipeline"})
                connection.sendall(
                    self.wire_request("POST", "/posts", new_body, auth)
                    + self.wire_request(path="/health") + self.wire_request(path="/feed")
                    + self.wire_request("POST", f'/posts/{post["id"]}/like', extra=auth)
                    + self.wire_request(path=f'/posts/{post["id"]}'))
                status, _, raw = reader.response()
                inserted = json.loads(raw)["post"]
                check(status == 201, "pipelined create failed")
                self.created[inserted["id"]] = inserted["body"]
                check(reader.response()[0] == 200, "mixed pipeline health response order")
                status, _, raw = reader.response()
                check(status == 200 and json.loads(raw)["posts"][0]["id"] == inserted["id"],
                      "pipeline feed did not observe its preceding write")
                check(reader.response()[0] == 201, "pipelined first like failed")
                self.likes.add((1, post["id"]))
                status, _, raw = reader.response()
                check(status == 200 and json.loads(raw)["post"]["like_count"] == 1,
                      "pipeline post did not observe its preceding like")
            finally:
                reader.close()
        return {"pipelined_requests": len(paths) + 5, "socket_reused": True,
                "mixed_write_read_pipeline": True}

    def chunked_and_continue(self):
        body = compact({"body": "chunked 🦀 body"})
        chunks = [body[:7], body[7:16], body[16:]]
        encoded = b"".join(format(len(v), "x").encode() + b";test=yes\r\n" + v + b"\r\n"
                           for v in chunks) + b"0\r\nX-Test-Trailer: ignored\r\n\r\n"
        with self.connect() as connection:
            reader = ResponseReader(connection)
            try:
                header = (b"POST /posts HTTP/1.1\r\nHost: local\r\nTransfer-Encoding: chunked\r\n"
                          b"Authorization: Bearer " + self.token.encode() + b"\r\n\r\n")
                connection.sendall(header + encoded + self.wire_request())
                status, _, raw = reader.response()
                value = json.loads(raw)
                check(status == 201 and value["post"]["body"] == "chunked 🦀 body", "chunked decoding")
                self.created[value["post"]["id"]] = value["post"]["body"]
                check(reader.response()[0] == 200, "chunked consumed pipeline boundary incorrectly")
            finally:
                reader.close()
        with self.connect() as connection:
            reader = ResponseReader(connection)
            try:
                header = self.wire_request("POST", "/posts", body,
                    b"Expect: 100-continue\r\nAuthorization: Bearer " + self.token.encode() + b"\r\n")
                connection.sendall(header[:-len(body)])
                check(reader.response()[0] == 100, "server did not send 100 Continue before body")
                connection.sendall(body)
                status, _, raw = reader.response()
                value = json.loads(raw)
                check(status == 201, "continued request failed")
                self.created[value["post"]["id"]] = value["post"]["body"]
            finally:
                reader.close()
        return {"chunk_extensions": True, "trailers": True, "continue_handshake": True}

    def ambiguous_framing_rejected(self):
        malformed = [
            b"Content-Length: 2\r\nContent-Length: 2\r\n",
            b"Content-Length: 2\r\nContent-Length: 3\r\n",
            b"Content-Length: +2\r\n", b"Content-Length: 2, 2\r\n",
            b"Content-Length: 2\r\nTransfer-Encoding: chunked\r\n",
            b"Transfer-Encoding: chunked\r\nTransfer-Encoding: chunked\r\n",
        ]
        for extra in malformed:
            with self.connect() as connection:
                reader = ResponseReader(connection)
                try:
                    connection.sendall(b"POST /posts HTTP/1.1\r\nHost: local\r\n" + extra + b"\r\n{}")
                    status, headers, raw = reader.response()
                    check(status == 400 and headers.get(b"connection") == b"close",
                          f"ambiguous framing accepted: {extra!r} => {(status, raw)!r}")
                    check(reader.stream.read(1) == b"", "malformed connection did not close")
                finally:
                    reader.close()
        return {"rejected_framing_variants": len(malformed)}

    def half_close(self):
        with self.connect() as connection:
            reader = ResponseReader(connection)
            try:
                connection.sendall(self.wire_request(path="/feed"))
                connection.shutdown(socket.SHUT_WR)
                status, _, raw = reader.response()
                check(status == 200 and len(json.loads(raw)["posts"]) == 20,
                      "write-side shutdown lost complete response")
                check(reader.stream.read(1) == b"", "half-closed peer was not reclaimed")
            finally:
                reader.close()
        return {"complete_response_after_SHUT_WR": True}

    def slow_reader(self):
        # Enough queued output to exceed ordinary socket send capacity. Increasing
        # the reader buffer after the pause keeps this integrity check inexpensive.
        requests = 1024
        with self.connect(receive_buffer=65536) as connection:
            reader = ResponseReader(connection)
            try:
                connection.sendall(self.wire_request(path="/feed") * requests)
                time.sleep(0.25)
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
                first = None
                for _ in range(requests):
                    status, _, raw = reader.response()
                    check(status == 200, "backpressure response status")
                    value = json.loads(raw)
                    check(len(value["posts"]) == 20, "backpressure truncated feed")
                    if first is None:
                        first = raw
                    check(raw == first, "response bytes corrupted/reordered under backpressure")
                transferred = reader.bytes_read
                connection.sendall(self.wire_request())
                check(reader.response()[0] == 200, "slow-reader socket lost keep-alive")
            finally:
                reader.close()
        return {"responses": requests, "verified_wire_bytes": transferred,
                "read_pause_ms": 250, "short_send_events": "not instrumented"}

    def reset_churn(self):
        resets = 192
        for i in range(resets):
            with self.connect() as connection:
                connection.sendall(self.wire_request(path="/feed") * (1 + i % 8))
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            if i % 16 == 15:
                status, value = self.request("GET", "/health")
                check(status == 200 and value["db"] == "ok", "reset churn damaged live connections")
        # Fresh sockets repeatedly reuse descriptor/slot space vacated by resets.
        for _ in range(64):
            status, value = self.request("GET", "/feed")
            check(status == 200 and len(value["posts"]) == 20, "post-reset descriptor reuse failure")
        return {"reset_connections": resets, "verified_fresh_connections": 64}

    def crash_recovery_and_schema(self):
        for i in range(32):
            post = self.create(f"acknowledged crash recovery row {i}")
            status, value = self.request("POST", f'/posts/{post["id"]}/like', token=self.user_token(2))
            check(status == 201 and not value["already_liked"], "recovery like failed")
            self.likes.add((2, post["id"]))
        self.stop(crash=True)
        with closing(sqlite3.connect(self.database)) as recovered:
            check(recovered.execute("PRAGMA integrity_check").fetchone() == ("ok",), "SQLite integrity check")
            check(recovered.execute("PRAGMA foreign_key_check").fetchall() == [], "foreign key violations")
            check(schema(recovered) == self.original_schema, "API modified fixed challenge schema")
            for pid, body in self.created.items():
                check(recovered.execute("SELECT body FROM posts WHERE id=?", (pid,)).fetchone() == (body,),
                      f"acknowledged post {pid} lost after SIGKILL")
            for user, pid in self.likes:
                check(recovered.execute("SELECT count(*) FROM likes WHERE user_id=? AND post_id=?",
                                        (user, pid)).fetchone() == (1,),
                      f"acknowledged like {(user, pid)} lost after SIGKILL")
        self.start()
        for pid, body in self.created.items():
            status, value = self.request("GET", f"/posts/{pid}")
            check(status == 200 and value["post"]["body"] == body, "restarted API cannot read recovered post")
        return {"acknowledged_posts_verified": len(self.created),
                "acknowledged_likes_verified": len(self.likes), "signal": "SIGKILL",
                "sqlite_integrity_check": "ok", "foreign_key_check": "ok",
                "schema_unchanged": True, "restarted_HTTP_reads": len(self.created),
                "scope": "process crash; no power-loss durability claim"}


TESTS = [
    "unicode_and_json", "jwt_validation", "live_reads_and_likes", "fragmented_request",
    "concurrent_like_idempotence",
    "pipeline_order", "chunked_and_continue", "ambiguous_framing_rejected", "half_close",
    "slow_reader", "reset_churn", "crash_recovery_and_schema",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--server", required=True, type=Path)
    parser.add_argument("--backend", choices=["uring", "epoll", "both"], default="both")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--only", choices=TESTS, help="run one group for a minimal bug reproduction")
    args = parser.parse_args()
    check(args.seed.is_file(), f"seed missing: {args.seed}")
    check(args.server.is_file(), f"server missing: {args.server}")
    backends = ["uring", "epoll"] if args.backend == "both" else [args.backend]
    report = {"kind": "functional-proof", "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "server_sha256": hashlib.sha256(args.server.read_bytes()).hexdigest(),
              "kernel": os.uname().release, "backends": [], "passed": True}
    for backend in backends:
        result = {"backend": backend, "tests": [], "passed": True}
        with tempfile.TemporaryDirectory(prefix=f"twelve-functional-{backend}-") as directory:
            fixture = None
            try:
                fixture = Fixture(args.server.resolve(), args.seed.resolve(), backend, directory)
                for name in [args.only] if args.only else TESTS:
                    started = time.monotonic()
                    record = {"name": name}
                    try:
                        record["evidence"] = getattr(fixture, name)()
                        record["passed"] = True
                    except Exception as error:
                        record.update(passed=False, error=f"{type(error).__name__}: {error}",
                                      traceback=traceback.format_exc())
                        result["passed"] = False
                    record["elapsed_s"] = round(time.monotonic() - started, 4)
                    result["tests"].append(record)
                    print(f'{backend}: {name}: {"PASS" if record["passed"] else "FAIL"} '
                          f'({record["elapsed_s"]:.3f}s)', flush=True)
                    if not record["passed"]:
                        print(record["error"], file=sys.stderr, flush=True)
            except Exception as error:
                result.update(passed=False, setup_error=f"{type(error).__name__}: {error}",
                              traceback=traceback.format_exc())
            finally:
                if fixture is not None:
                    fixture.stop()
                    result["server_log"] = fixture.logs()
                elif (Path(directory) / "server.log").exists():
                    result["server_log"] = (Path(directory) / "server.log").read_text(errors="replace")
        report["backends"].append(result)
        report["passed"] &= result["passed"]
    report["test_groups"] = sum(len(b["tests"]) for b in report["backends"])
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

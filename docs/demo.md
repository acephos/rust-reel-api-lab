# Access and operate the live demo

The demo is a real Rust HTTP server on `0.0.0.0:8080`. The live feed, compose action, likes, detail view and API explorer all use the five challenge endpoints and an isolated writable copy of the full fictional dataset. The capacity tab reads the published `docs/proof/demo.json`; it stays explicitly pending until complete evidence exists.

On this machine, the temporary services created for this task are:

```bash
systemctl --user status rust-reel-api-demo rust-reel-api-tunnel
journalctl --user -u rust-reel-api-demo -u rust-reel-api-tunnel
systemctl --user stop rust-reel-api-tunnel rust-reel-api-demo
```

They are transient user services, not installed boot-time services. They keep running after the coding session while the user session/machine/network remain available; reboot or stopping the services ends the demo. The tunnel's public HTTPS address is temporary and changes when recreated. No account or paid deployment was created. Start locally again with `bash scripts/demo.sh`; see the root README for the pinned tunnel installer.

Phone routes verified during the task:

- Same Wi-Fi: `http://192.168.88.13:8080` (address may change with DHCP).
- Connected Tailscale device: `http://100.103.202.33:8080`.
- Temporary HTTPS: address printed by the tunnel and included in the task's final response. This was verified with a public HTTPS health request and the collaborative browser at390px width; this is not a physical-phone or remote-load benchmark.

The configured sample token belongs to a fictional seeded user. Its signing secret is the public challenge fixture, not an external credential. The normal four-variable API configuration does not enable the demo/token/report routes. Use distinct database files for benchmark and demo; exclusive SQLite locking prevents concurrent server ownership of a file. The public tunnel terminates TLS outside the Rust process; the measured benchmark path is direct loopback HTTP without the tunnel.

To reset the demo, stop its server, remove only `data/demo.db`, `data/demo.db-wal`, and `data/demo.db-shm`, then restart. The next `scripts/demo.sh` run copies the unchanged seed. Source, proof, and seed-generation scripts are on GitHub; large generated databases, tools and raw event streams remain ignored locally.

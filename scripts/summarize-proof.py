#!/usr/bin/env python3
"""Generate the public proof/phone report only from passing recorded runs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics


def load_run(path):
    folder = Path(path)
    for line in (folder / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        item = folder / name.strip()
        with item.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError(f'Artifact checksum mismatch: {item}')
    if (folder / 'final-exit-code').read_text().strip() != '0':
        raise ValueError(f'Nonzero final exit code: {folder}')
    accounting = json.loads((folder / 'accounting.json').read_text())
    summary = json.loads((folder / 'summary.json').read_text())
    machine = json.loads((folder / 'machine.json').read_text())
    if not accounting['passed_all_checks']:
        raise ValueError(f'Refusing to publish failed run {folder}')
    metrics = summary['metrics']
    latencies = metrics['full_request_ms{phase:hold}']['values']
    settings = machine['settings']
    binary = machine.get('server_executable_sha256')
    if not isinstance(binary, str) or len(binary) != 64 or not machine.get('server_configuration', {}).get('argv'):
        raise ValueError(f'Missing actual server identity/configuration: {folder}')
    if any(value.get('ok') is not True for metric in metrics.values() for value in metric.get('thresholds', {}).values()):
        raise ValueError(f'A recorded threshold failed: {folder}')
    for phase in ['client_outstanding_all_phases', 'client_outstanding_requests_started_in_hold']:
        record = accounting[phase]
        if record['unfinished'] != 0 or record.get('minimum', 0) < 0:
            raise ValueError(f'Unbalanced request accounting: {folder}')
    resources = [json.loads(line) for line in (folder / 'resources.jsonl').read_text().splitlines()]
    def resource(role, field, reduction):
        samples = [r[role][field] for r in resources if r.get(role) and r[role].get(field) is not None]
        return reduction(samples) if samples else None
    hold = accounting['counts']['hold']
    outstanding = accounting['client_outstanding_requests_started_in_hold']
    result = {
        'mode': settings['MODE'], 'duration_s': accounting['configured_hold_seconds'],
        'rps': accounting['hold_started_validated_successes_per_configured_second'],
        'validated_requests_started_in_hold': hold['validated_successes'],
        'p95_ms': latencies['p(95)'], 'p99_ms': latencies['p(99)'],
        'errors': hold.get('semantic_errors', 0),
        'outstanding_peak': outstanding['peak'],
        'outstanding_mean': outstanding['mean_over_first_start_to_last_event'],
        'outstanding_span_s': outstanding['observed_span_seconds'],
        'unfinished': outstanding['unfinished'],
        'established_connections_sample_peak': max((r['sockets'].get('server_state_01', 0) for r in resources), default=0),
        'server_cpu_mean_percent_one_core': resource('server', 'cpu_percent_one_core', statistics.mean),
        'server_rss_peak_bytes': resource('server', 'rss_bytes', max),
        'generator_cpu_mean_percent_one_core': resource('client', 'cpu_percent_one_core', statistics.mean),
        'generator_rss_peak_bytes': resource('client', 'rss_bytes', max),
        'resource_sampling_scope': 'All sampled phases, including ramp, drain and raw-export tail; CPU100% means one logical core.',
        'source_commit': machine['git']['stdout'].strip(),
        'binary_sha256': machine['server_executable_sha256'],
        'artifact_path': str(folder.resolve().relative_to(Path.cwd().resolve())),
        'endpoints': {endpoint: {
            'p95_ms': metrics[f'full_request_ms{{phase:hold,endpoint:{endpoint}}}']['values']['p(95)'],
            'p99_ms': metrics[f'full_request_ms{{phase:hold,endpoint:{endpoint}}}']['values']['p(99)'],
            'validated_requests': metrics[f'validated_requests{{phase:hold,endpoint:{endpoint}}}']['values']['count'],
        } for endpoint in ['feed', 'post', 'like', 'create']},
    }
    if result['mode'] == 'active':
        result['concurrency'] = int(settings['VUS'])
    elif result['mode'] == 'original':
        result['vus'] = int(settings['VUS'])
    else:
        result['rate'] = int(settings['RATE'])
        result['dropped'] = accounting['counts'].get('scheduler', {}).get('dropped_iterations', 0)
        result['planned_arrivals'] = result['rate'] * result['duration_s']
        result['started_arrivals'] = accounting['client_outstanding_all_phases']['started']
        result['finished_arrivals'] = accounting['client_outstanding_all_phases']['finished']
        result['arrival_accounting_residual'] = result['planned_arrivals'] - result['started_arrivals'] - result['dropped']
    return result


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--active', required=True)
parser.add_argument('--users', required=True)
parser.add_argument('--open', required=True)
parser.add_argument('--warmup', help='Defaults to original-warmup alongside the users run')
parser.add_argument('--repo', default='https://github.com/acephos/rust-reel-api-lab')
args = parser.parse_args()
a, u, o = [load_run(getattr(args, name)) for name in ['active', 'users', 'open']]
w = load_run(args.warmup or Path(args.users).with_name('original-warmup'))
if [a['mode'], u['mode'], o['mode'], w['mode']] != ['active', 'original', 'open', 'original']:
    raise ValueError('Incorrect workload modes')
if a['duration_s'] < 300 or u['duration_s'] < 300:
    raise ValueError('Require real five-minute holds')
if w['duration_s'] != 120 or w['vus'] != 1000:
    raise ValueError('Require the recorded1,000-user/two-minute warm-up')
if len({run['binary_sha256'] for run in [a, u, o, w]}) != 1:
    raise ValueError('Different binaries require separate reports')
notes = [
    'Single-machine loopback measurements on Ryzen 5 5600H (6 cores / 12 threads), Linux 7.2.5. The load generator shares CPU, memory, disk and network stack with the API.',
    'Active: no think time; rotation is 25% feed, 25% post, 25% like, 25% create. Original browsing: upstream think times, 15% like and 2% create chances per user loop.',
    'Configured workers are not simultaneous server execution. Outstanding measurements include client connection/pool waits, full body consumption and semantic validation; SQLite remains serialized.',
    'Throughput is validated completions of requests STARTED during the hold divided by configured hold seconds; those requests may finish in the bounded drain. Exact observed spans, starts/finishes and unfinished counts are in each accounting.json.',
    'Latencies are full HTTP plus JSON validation, at 1-ms resolution, for requests started during the hold. Every endpoint also passes p95<500ms / p99<1000ms. Semantic and HTTP failures are zero.',
    'This is a demonstrated passing load, not an absolute maximum or an official droplet score. The generator is a material bottleneck; more server CPU headroom is not proof of a higher untested capacity.',
    'Open arrivals use k6 constant-arrival-rate and require zero drops. Latencies are not wrk2 planned-schedule-corrected; arrival accounting and any theoretical scheduling-boundary residual are retained.',
    'Resource CPU means include all sampled phases and the raw-export tail after requests stop; inspect timestamped samples for the request-active window. CPU100% means one logical core.',
    'Complete per-request gzip events are retained locally with SHA256 references. GitHub contains exact summaries, interval histograms, concurrency accounting and resource samples; large raw event streams are not published.',
]
report = {'status': 'complete', 'generated_utc': datetime.now(timezone.utc).isoformat(),
          'repo_url': args.repo, 'machine': {'cpu': 'AMD Ryzen 5 5600H · 6 cores / 12 threads', 'memory_gib': 30.70},
          'active': a, 'users': u, 'open': o, 'warmup': w, 'notes': notes}
out = Path('docs/proof'); out.mkdir(parents=True, exist_ok=True)
(out / 'demo.json').write_text(json.dumps(report, indent=2) + '\n')
rows = []
for title, r, load in [('Active mixed', a, f"{a['concurrency']:,} workers"),
                       ('Original browsing', u, f"{u['vus']:,} VUs"),
                       ('Independent arrivals', o, f"{o['rate']:,} req/s offered")]:
    rows.append(f"| {title} | {load} | {r['duration_s']:g}s | {r['rps']:,.1f} | {r['p95_ms']:g} / {r['p99_ms']:g} | {r['outstanding_mean']:.1f} / {r['outstanding_peak']:,} | {r['errors']} |")
text = f'''# Capacity proof on this machine

Generated from the checked-in artifacts by `scripts/summarize-proof.py` on {report['generated_utc']}. [Machine-readable report](demo.json).

The API demonstrated **{a['concurrency']:,} continuously active request workers for five minutes**, with observed mean {a['outstanding_mean']:.1f} / peak {a['outstanding_peak']:,} outstanding requests, at {a['rps']:,.1f} validated requests/s and zero errors. This is a tested lower bound, not the machine's absolute maximum. Separately, **{u['vus']:,} browsing virtual users** passed a five-minute hold with the reel's pacing.

| Workload | Offered load | Hold | Validated req/s | Full p95 / p99 ms | Outstanding mean / peak | Errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## Acceptance fixed before testing

Every returned body is decoded and checked for status, JSON field order/schema and endpoint meaning. Creates verify authored content, likes verify idempotence status, feed checks20 ordered posts with valid fields. All semantic checks and HTTP requests pass; every endpoint has coverage and full p95<500ms, p99<1000ms; open arrivals have zero drops. `passed_all_checks` additionally requires balanced start/finish counts and no unfinished requests. The corrected short smoke preceded the ladder. Tests use the full deterministic seed, not a tiny synthetic fixture.

The separate functional proof passes the unchanged42 upstream checks on each backend and12 additional groups per backend. [Final extended result](functional-final.json), [io_uring exact checks](upstream-uring-final.log), [epoll exact checks](upstream-epoll-final.log), [Clippy](clippy.log). It verifies all acknowledged writes after SIGKILL; this is not power-loss durability.

## Reproduce

Follow the build/seed commands in [README](../../README.md). Start an io_uring server against a disposable fresh seed copy on127.0.0.1:3000 with the challenge secret and no demo configuration. Capture its actual PID. [Benchmark commands and metric definitions](../../bench/README.md). Execute runs sequentially; the server binaries must have the same checksum. The original-user run is preceded by a separately recorded1,000-VU/two-minute warm-up; its ramp and drain are separate from the300-second hold. Active/open runs have their own declared protocol; no CPU pinning or sysctl changes.

```bash
SERVER_PID=<pid> BASE_URL=http://127.0.0.1:3000 MODE=active VUS={a['concurrency']} DURATION=5m OUT=proof/runs/active-hold scripts/benchmark.sh
SERVER_PID=<pid> BASE_URL=http://127.0.0.1:3000 MODE=original VUS={u['vus']} RAMP_UP=60s DURATION=5m OUT=proof/runs/original-hold scripts/benchmark.sh
SERVER_PID=<pid> BASE_URL=http://127.0.0.1:3000 MODE=open RATE={o['rate']} VUS=256 MAX_VUS=1024 DURATION=60s OUT=proof/runs/open-confirmation scripts/benchmark.sh
python3 scripts/summarize-proof.py --active proof/runs/active-hold --users proof/runs/original-hold --open proof/runs/open-confirmation
```

Exact run settings, tool/source/binary checksums, actual process argv/allowlisted configuration, limits, CPU affinity, cgroups, host state and source revisions are inside each run's `machine.json`. Endpoint latency/count results and resource peaks are retained in [demo.json](demo.json). Never silently replace a failed run; exploratory stages and the initial validator failure remain available.

## Artifacts

- Active hold: [{a['artifact_path']}]({('../../' + a['artifact_path'])})
- Original hold: [{u['artifact_path']}]({('../../' + u['artifact_path'])})
- Open confirmation: [{o['artifact_path']}]({('../../' + o['artifact_path'])})
- Separate browsing warm-up: [{w['artifact_path']}]({('../../' + w['artifact_path'])})
- [Exploratory ladder](../../proof/runs/ladder/), [initial failed validator smoke](../../proof/runs/smoke/), [corrected smoke](../../proof/runs/smoke-fixed/), [validator diagnosis](benchmark-validation.md)
- Binary SHA256: `{a['binary_sha256']}`. Rust1.98.1, native CPU flags, fatLTO, SQLite3.53.4 PGO.

## Practical limits

'''
text += '\n'.join(f'- {note}' for note in notes) + '\n'
(out / 'README.md').write_text(text)
print(json.dumps({'active_workers': a['concurrency'], 'users': u['vus'], 'open_rate': o['rate'], 'report': str(out / 'demo.json')}))

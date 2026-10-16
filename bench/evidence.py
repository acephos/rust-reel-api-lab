#!/usr/bin/env python3
"""Read-only host evidence, resource sampling and raw k6 result accounting."""
import argparse
from array import array
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time
import bisect


def read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, ValueError):
        return None


def command(*args):
    try:
        result = subprocess.run(args, text=True, capture_output=True, check=False)
        return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except OSError as error:
        return {"exit_code": 127, "stdout": '', "stderr": str(error)}


def cgroups(pid):
    text = read(f'/proc/{pid}/cgroup') or ''
    paths = []
    for line in text.splitlines():
        if line.startswith('0::'):
            p = Path('/sys/fs/cgroup') / line[3:].lstrip('/')
            while str(p).startswith('/sys/fs/cgroup'):
                paths.append({"path": str(p), **{key: read(p / key) for key in
                             ['cpu.max', 'memory.max', 'cpuset.cpus.effective']}})
                if p == Path('/sys/fs/cgroup'):
                    break
                p = p.parent
    return paths


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def machine(args):
    chosen = ['MODE', 'VUS', 'MAX_VUS', 'RATE', 'DURATION', 'RAMP_UP', 'RAMP_DOWN',
              'BASE_URL', 'TIMEOUT', 'SEED', 'POST_IDS', 'SERVER_PID']
    server_config = {}
    if args.pid:
        server_config['argv'] = (read(f'/proc/{args.pid}/cmdline') or '').split('\0')
        allowed = {'HOST', 'PORT', 'SQLITE_PATH', 'DEMO_CONFIG_PATH', 'DEMO_PROOF_PATH'}
        environment = (read(f'/proc/{args.pid}/environ') or '').split('\0')
        server_config['environment'] = {
            key: value for item in environment if '=' in item
            for key, value in [item.split('=', 1)] if key in allowed
        }
    result = {
        'captured_utc': datetime.now(timezone.utc).isoformat(),
        'kernel': platform.uname()._asdict(), 'cpu': command('lscpu', '-J'),
        'memory': read('/proc/meminfo'), 'loadavg': read('/proc/loadavg'),
        'disk': command('df', '-T', '.'), 'lsblk': command('lsblk', '-o', 'NAME,TYPE,SIZE,FSTYPE,ROTA'),
        'nofile_inherited': resource.getrlimit(resource.RLIMIT_NOFILE),
        'sysctls': {name: read('/proc/sys/' + name.replace('.', '/')) for name in [
            'net.ipv4.ip_local_port_range', 'net.ipv4.ip_local_reserved_ports',
            'net.netfilter.nf_conntrack_max', 'net.netfilter.nf_conntrack_count',
            'net.core.somaxconn', 'kernel.io_uring_disabled']},
        'generator_parent_cgroups': cgroups(os.getpid()),
        'server_cgroups': cgroups(args.pid) if args.pid else None,
        'server_limits': read(f'/proc/{args.pid}/limits') if args.pid else None,
        'server_affinity': sorted(os.sched_getaffinity(args.pid)) if args.pid else None,
        'server_executable': os.readlink(f'/proc/{args.pid}/exe') if args.pid else None,
        'server_executable_sha256': sha(f'/proc/{args.pid}/exe') if args.pid else None,
        'server_configuration': server_config,
        'git': command('git', 'rev-parse', 'HEAD'), 'git_status': command('git', 'status', '--porcelain'),
        'k6': command(args.k6, 'version'),
        'rustc': command(str(Path.home() / '.cargo/bin/rustc'), '--version'),
        'settings': {k: os.environ.get(k) for k in chosen},
        'source_sha256': {str(p): sha(p) for p in [*Path('src').glob('*.rs'), Path('Cargo.toml'),
                                                   Path('build.rs'), Path('bench/load.js'), Path('bench/evidence.py'),
                                                   Path('scripts/benchmark.sh'), Path('Cargo.lock')]
                          if p.is_file()},
        'warning': 'Co-located loopback client and server share host resources. Socket samples are point-in-time observations.',
    }
    print(json.dumps(result, indent=2))


def process(pid, previous):
    stat = read(f'/proc/{pid}/stat')
    if not stat:
        return {'pid': pid, 'alive': False}
    fields = stat[stat.rfind(')') + 2:].split()
    now = time.monotonic()
    ticks = int(fields[11]) + int(fields[12])
    prior = previous.get(pid)
    cpu = None if prior is None else (ticks - prior[1]) / os.sysconf('SC_CLK_TCK') / (now - prior[0]) * 100
    previous[pid] = (now, ticks)
    try:
        fds = len(list(Path(f'/proc/{pid}/fd').iterdir()))
        affinity = sorted(os.sched_getaffinity(pid))
    except OSError:
        fds, affinity = None, None
    return {'pid': pid, 'alive': True, 'cpu_percent_one_core': cpu,
            'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE'), 'threads': int(fields[17]),
            'fds': fds, 'affinity': affinity}


def sockets(port):
    result = Counter()
    for path in ['/proc/net/tcp', '/proc/net/tcp6']:
        data = read(path)
        for line in (data or '').splitlines()[1:]:
            parts = line.split()
            local = int(parts[1].rsplit(':', 1)[1], 16)
            remote = int(parts[2].rsplit(':', 1)[1], 16)
            if local == port:
                result['server_state_' + parts[3]] += 1
            if remote == port:
                result['client_state_' + parts[3]] += 1
    return dict(result)


def sample(args):
    running = True
    def stop(_signum, _frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    previous = {}
    while running:
        client = process(args.client, previous)
        print(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'monotonic': time.monotonic(),
                          'client': client, 'server': process(args.pid, previous) if args.pid else None,
                          'sockets': sockets(args.port), 'loadavg': read('/proc/loadavg'),
                          'conntrack_count': read('/proc/sys/net/netfilter/nf_conntrack_count')}), flush=True)
        if not client['alive']:
            break
        time.sleep(args.interval)


def epoch(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def report(args):
    directory = Path(args.directory)
    starts, finishes = array('d'), array('d')
    counts = defaultdict(Counter)
    intervals = defaultdict(Counter)
    hold_starts, hold_finishes = array('d'), array('d')
    per_endpoint = defaultdict(lambda: {'requests': 0, 'full_ms_sum': 0, 'full_ms_max': 0, 'histogram': Counter()})
    boundaries = [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
    raw_path = Path(args.raw)
    for line in gzip.open(raw_path, 'rt'):
        item = json.loads(line)
        if item.get('type') != 'Point':
            continue
        data, name = item['data'], item['metric']
        tags = data.get('tags') or {}
        at = epoch(data['time'])
        bucket = intervals[int(at)]
        if name == 'full_request_ms':
            key = (int(at), tags.get('phase', 'unknown'), tags.get('endpoint', 'unknown'))
            group = per_endpoint[key]
            group['requests'] += 1
            group['full_ms_sum'] += data['value']
            group['full_ms_max'] = max(group['full_ms_max'], data['value'])
            bin_index = bisect.bisect_left(boundaries, data['value'])
            group['histogram'][str(boundaries[bin_index]) if bin_index < len(boundaries) else '+Inf'] += 1
        if name == 'client_inflight_delta':
            destination = starts if data['value'] > 0 else finishes
            destination.append(at)
            if tags.get('phase') == 'hold':
                (hold_starts if data['value'] > 0 else hold_finishes).append(at)
        if name == 'http_reqs':
            counts[tags.get('phase', 'unknown')]['http_request_events'] += data['value']
            counts['statuses'][tags.get('status', 'unknown')] += data['value']
            bucket['responses'] += data['value']
        elif name == 'validated_requests':
            counts[tags.get('phase', 'unknown')]['validated_successes'] += data['value']
            counts['endpoints'][tags.get('endpoint', 'unknown')] += data['value']
            bucket['validated_successes'] += data['value']
        elif name == 'semantic_success' and data['value'] == 0:
            counts[tags.get('phase', 'unknown')]['semantic_errors'] += 1
            bucket['semantic_errors'] += 1
        elif name == 'dropped_iterations':
            counts['scheduler']['dropped_iterations'] += data['value']
            bucket['dropped_iterations'] += data['value']

    def concurrency(begin, end):
        # Two compact sorted arrays avoid retaining JSON events or a tuple per request.
        a, b = sorted(begin), sorted(end)
        if not a:
            return {'started': 0, 'finished': len(b), 'peak': 0, 'mean': None}
        i = j = current = peak = 0
        exposure = 0.0
        previous = first = min(a[0], b[0] if b else a[0])
        while i < len(a) or j < len(b):
            # Completion before start on an exact timestamp tie gives a conservative peak.
            start = i < len(a) and (j >= len(b) or a[i] < b[j])
            now = a[i] if start else b[j]
            exposure += current * (now - previous)
            current += 1 if start else -1
            peak = max(peak, current)
            if start:
                i += 1
            else:
                j += 1
            previous = now
        return {'started': len(a), 'finished': len(b), 'unfinished': current, 'peak': peak,
                'mean_over_first_start_to_last_event': exposure / (previous - first) if previous > first else None,
                'observed_span_seconds': previous - first}
    exit_code = int((directory / 'exit-code').read_text())
    all_concurrency = concurrency(starts, finishes)
    hold_concurrency = concurrency(hold_starts, hold_finishes)
    complete = len(starts) == len(finishes) and len(starts) > 0
    settings = json.loads((directory / 'machine.json').read_text())['settings']
    import re
    match = re.fullmatch(r'(\d+(?:\.\d+)?)(ms|s|m|h)', settings['DURATION'])
    hold_seconds = float(match[1]) * {'ms': .001, 's': 1, 'm': 60, 'h': 3600}[match[2]]
    result = {'k6_exit_code': exit_code, 'passed_k6_thresholds': exit_code == 0,
              'complete_request_accounting': complete,
              'passed_all_checks': exit_code == 0 and complete,
              'counts': {k: dict(v) for k, v in counts.items()},
              'configured_hold_seconds': hold_seconds,
              'hold_started_validated_successes_per_configured_second': counts['hold']['validated_successes'] / hold_seconds,
              'client_outstanding_all_phases': all_concurrency,
              'client_outstanding_requests_started_in_hold': hold_concurrency,
              'concurrency_definition': 'Start to full body consumption and semantic validation; includes client connection/pool waits. Hold classification is based on request start, and includes its drain.',
              'limitations': ['Peak timestamp resolution is k6 metric emission precision; exact timestamp ties complete before starts.',
                              'Fixed VUs and TCP connections are not simultaneous server handler execution.',
                              'k6 arrival model reports scheduling drops; it does not supply wrk2 schedule-corrected latency.',
                              'An interrupted request may have a start event without an end; unfinished counts remain visible.']}
    (directory / 'accounting.json').write_text(json.dumps(result, indent=2) + '\n')
    (directory / 'raw-reference.json').write_text(json.dumps({
        'path_on_measurement_machine': str(raw_path.resolve()), 'sha256': sha(raw_path),
        'compressed_bytes': raw_path.stat().st_size,
        'retention': 'Complete gzip JSON events retained locally outside git. Compact derived intervals and exact k6 summaries are published.'
    }, indent=2) + '\n')
    with open(directory / 'intervals.jsonl', 'w') as output:
        for second, metrics in sorted(intervals.items()):
            output.write(json.dumps({'epoch_second': second, **metrics}) + '\n')
    with open(directory / 'endpoint-intervals.jsonl', 'w') as output:
        for (second, phase, endpoint), metrics in sorted(per_endpoint.items()):
            output.write(json.dumps({'epoch_second': second, 'phase': phase, 'endpoint': endpoint,
                                     **metrics, 'histogram': dict(metrics['histogram'])}) + '\n')
    print(json.dumps(result, indent=2))


parser = argparse.ArgumentParser(description=__doc__)
sub = parser.add_subparsers(dest='action', required=True)
p = sub.add_parser('machine'); p.add_argument('--pid', type=int); p.add_argument('--k6', required=True)
p = sub.add_parser('sample'); p.add_argument('--pid', type=int); p.add_argument('--client', type=int, required=True)
p.add_argument('--port', type=int, required=True); p.add_argument('--interval', type=float, default=1.0)
p = sub.add_parser('report'); p.add_argument('directory'); p.add_argument('--raw', required=True)
args = parser.parse_args()
{'machine': machine, 'sample': sample, 'report': report}[args.action](args)

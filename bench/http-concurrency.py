#!/usr/bin/env python3
"""Reconstruct HTTP transport overlap from k6's end timestamp and duration.

Primary definition: https://grafana.com/docs/k6/latest/using-k6/metrics/reference/
http_req_duration = sending + waiting + receiving, timestamped at response end.
This excludes initial connection setup, JavaScript validation and metric emission.
"""
import argparse
from array import array
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path


def overlap(starts, ends):
    a, b = sorted(starts), sorted(ends)
    if not a or len(a) != len(b):
        raise ValueError('Need paired, nonempty HTTP intervals')
    i = j = current = peak = minimum = 0
    while i < len(a) or j < len(b):
        begin = i < len(a) and (j >= len(b) or a[i] < b[j])
        current += 1 if begin else -1
        peak, minimum = max(peak, current), min(minimum, current)
        if begin:
            i += 1
        else:
            j += 1
    if current != 0 or minimum < 0:
        raise ValueError('Invalid HTTP interval accounting')
    return {'peak': peak, 'minimum': minimum, 'unfinished': current,
            'first_start_epoch_s': a[0], 'last_end_epoch_s': b[-1],
            'observed_span_s': b[-1] - a[0]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    accounting = json.loads((args.run / 'accounting.json').read_text())
    reference = json.loads((args.run / 'raw-reference.json').read_text())
    machine = json.loads((args.run / 'machine.json').read_text())
    raw = Path(reference['path_on_measurement_machine'])
    with raw.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != reference['sha256']:
        raise ValueError('Raw source hash mismatch')
    starts, ends = array('d'), array('d')
    count = zero = 0
    duration_sum_ms = 0.0
    with gzip.open(raw, 'rb') as stream:
        for line in stream:
            # Filter before parsing: other metric lines cannot affect transport
            # concurrency. Native JSON parsing still validates every selected row.
            if b'"metric":"http_req_duration"' not in line:
                continue
            item = json.loads(line)
            if item.get('type') != 'Point' or item.get('metric') != 'http_req_duration':
                continue
            data = item['data']
            if data['tags'].get('phase') != 'hold':
                continue
            duration_ms = data['value']
            if not math.isfinite(duration_ms) or duration_ms < 0:
                raise ValueError('Invalid duration')
            end = datetime.fromisoformat(data['time'].replace('Z', '+00:00')).timestamp()
            start = end - duration_ms / 1000
            count += 1
            duration_sum_ms += duration_ms
            if start == end:
                zero += 1
            else:
                starts.append(start)
                ends.append(end)
    expected = accounting['counts']['hold']['http_request_events']
    if count != expected:
        raise ValueError(f'HTTP sample count mismatch: {count} != {expected}')
    result = overlap(starts, ends)
    result.update({'mean': duration_sum_ms / 1000 / result['observed_span_s'],
                   'requests': count, 'zero_width_intervals': zero,
                   'http_duration_mean_ms': duration_sum_ms / count,
                   'scope': 'HTTP requests tagged at wrapper start as hold; transport interval reconstructed from end minus sending+waiting+receiving duration. Excludes connection setup, JS validation and metric recording; does not count simultaneous SQLite execution.',
                   'source_run': str(args.run.resolve().relative_to(Path.cwd().resolve())),
                   'raw_sha256': digest, 'binary_sha256': machine['server_executable_sha256'],
                   'method_source': 'https://grafana.com/docs/k6/latest/using-k6/metrics/reference/',
                   'precision': 'Timestamp parsed to microsecond resolution; zero-width intervals excluded from peak, retained in request count.'})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    # A meaningful mathematical fixture: two overlapping2s intervals in a3s span.
    if overlap([5.0, 6.0], [7.0, 8.0])['peak'] != 2:
        raise RuntimeError('Overlap fixture failed')
    main()

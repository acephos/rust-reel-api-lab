#!/usr/bin/env python3
"""After stopping a load-test server, reconcile every acknowledged write with SQLite."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--seed', required=True)
p.add_argument('--database', required=True)
p.add_argument('--run', action='append', required=True)
a = p.parse_args()
def inspect(path):
    with sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True) as db:
        counts = {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ['users', 'posts', 'likes']}
        integrity = [r[0] for r in db.execute('PRAGMA integrity_check')]
        foreign_keys = list(db.execute('PRAGMA foreign_key_check'))
        schema = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name"))
    return counts, integrity, foreign_keys, hashlib.sha256(json.dumps(schema).encode()).hexdigest()
seed_counts, _, _, seed_schema = inspect(a.seed)
counts, integrity, foreign_keys, schema = inspect(a.database)
creates = first_likes = 0
for run in a.run:
    accounting = json.loads((Path(run) / 'accounting.json').read_text())
    if not accounting['passed_all_checks']:
        raise ValueError(f'Failed run {run}')
    created = accounting['counts']['endpoints']['create']
    creates += created
    first_likes += accounting['counts']['statuses'].get('201', 0) - created
expected = {'users': seed_counts['users'], 'posts': seed_counts['posts'] + creates,
            'likes': seed_counts['likes'] + first_likes}
result = {'seed_counts': seed_counts, 'persisted_counts': counts, 'expected_counts': expected,
          'all_acknowledged_creates': creates, 'all_acknowledged_first_likes': first_likes,
          'integrity_check': integrity, 'foreign_key_check': foreign_keys,
          'schema_sha256': schema, 'schema_unchanged': schema == seed_schema,
          'passed': counts == expected and integrity == ['ok'] and not foreign_keys and schema == seed_schema,
          'scope': 'Persisted row-count reconciliation after process stop, not power-loss durability.'}
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['passed'] else 1)

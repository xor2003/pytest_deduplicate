"""Bounded real-project runs; reports/logs stay in an explicit output directory."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SCRIPT = Path(__file__).resolve().parents[1] / 'pytest_deduplicate.py'


def fingerprint(root):
    """Hash current tracked source/config bytes, including local modifications."""
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).split(b'\0')
    digest = hashlib.sha256()
    for raw in sorted(filter(None, paths)):
        path = root / os.fsdecode(raw)
        if path.suffix not in ('.py', '.toml', '.ini', '.cfg', '.lark'):
            continue
        digest.update(raw + b'\0')
        digest.update(path.read_bytes() if path.is_file() else b'<missing>')
    return {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
            'tracked_source_sha256': digest.hexdigest(),
            'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain', '-uno'], cwd=root))}


def observations(report):
    return {t['nodeid']: {'eligible': t['eligible'], 'file_arcs': t['file_arcs'],
                         'phases': {k: (v['outcome'], v['xfail']) for k, v in t['phases'].items()}}
            for t in report['tests']}


def summarize(reports):
    return {'runs': {mode: {'tests': len(r['tests']), 'exit_code': r['exit_code'],
                           'elapsed': r['elapsed'], 'errors': r['errors'],
                           'empty_coverage_tests': sum(not t['file_arcs'] for t in r['tests']),
                           'findings': dict(Counter(f['kind'] for f in r['findings']))}
                     for mode, r in reports.items()},
            'collector_parity': observations(reports['contexts']) == observations(reports['restart'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--python', required=True)
    parser.add_argument('--source', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixed-order', action='store_true', help='replay first collection order for collector parity')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('tests', nargs='+')
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = fingerprint(root)
    reports, commands, wall = {}, {}, {}
    for mode in ('contexts', 'restart'):
        target = output / (mode + '.json')
        command = [str(Path(args.python).absolute()), str(SCRIPT), '--collector', mode, '--json', str(target)]
        for source in args.source:
            command += ['--source', source]
        command += ['-q', '-p', 'no:cacheprovider', '--tb=short', *args.tests]
        if args.fixed_order and reports:
            request = output / 'order-request.json'
            request.write_text(json.dumps({'pytest_args': ['-q', '-p', 'no:cacheprovider', '--tb=short', *args.tests],
                'source': [str(root / source) for source in args.source], 'omit': [], 'collector': mode,
                'order': [t['nodeid'] for t in reports['contexts']['tests']], 'output': str(target)}))
            command = [str(Path(args.python).absolute()), str(SCRIPT), '--_request', str(request)]
        commands[mode] = command
        started = time.perf_counter()
        with (output / (mode + '.log')).open('w') as log:
            subprocess.run(command, cwd=root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                           stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout, check=False)
        wall[mode] = time.perf_counter() - started
        reports[mode] = json.loads(target.read_text())
    result = dict(summarize(reports), before=before, after=fingerprint(root),
                  commands=commands, wall_seconds=wall,
                  limitation='Bounded working-tree evaluation, not whole-suite accuracy or redundancy proof.')
    result['tracked_snapshot_unchanged'] = result['before'] == result['after']
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return int(not result['tracked_snapshot_unchanged'] or not result['collector_parity'] or any(r['exit_code'] for r in reports.values()))


if __name__ == '__main__':
    sys.exit(main())

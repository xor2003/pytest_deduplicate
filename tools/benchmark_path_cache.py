"""Run a bounded many-module benchmark against pristine and cached analyzer sources."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def child(source, metrics_path, report_path):
    sys.path.insert(0, os.getcwd())
    sys.path.insert(0, source)
    analyzer = importlib.import_module('pytest_deduplicate')
    metrics = {'requests': 0, 'hits': 0, 'misses': 0}
    original = getattr(analyzer.FindDuplicateCoverage, 'source_path', None)
    if original:
        def source_path(self, filename):
            metrics['requests'] += 1
            metrics['hits' if filename in self._source_path_cache else 'misses'] += 1
            return original(self, filename)
        analyzer.FindDuplicateCoverage.source_path = source_path
    status = analyzer.main(['--source', 'app', '--coverage-phase', 'call', '--json', report_path, '-q', 'tests'])
    Path(metrics_path).write_text(json.dumps(metrics))
    return status


def snapshot(report):
    return {
        'tests': [dict({key: test[key] for key in ('nodeid', 'eligible', 'file_arcs', 'phase_file_arcs')},
                       phases={phase: {key: values[key] for key in ('outcome', 'xfail')}
                               for phase, values in test['phases'].items()}) for test in report['tests']],
        'findings': [{key: item[key] for key in ('kind', 'tests', 'other_tests', 'shared', 'unique', 'other_unique')} for item in report['findings']],
        'errors': report['errors'], 'exit_code': report['exit_code'],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', nargs=3)
    parser.add_argument('--modules', type=int, default=80)
    parser.add_argument('--tests', type=int, default=240)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--baseline-source')
    parser.add_argument('--candidate-source')
    parser.add_argument('--workdir', type=Path)
    options = parser.parse_args()
    if options.child:
        return child(*options.child)
    if not options.baseline_source or not options.candidate_source:
        parser.error('--baseline-source and --candidate-source are required')
    if min(options.modules, options.tests, options.runs) < 1:
        parser.error('module, test and run counts must be positive')
    root = options.workdir or Path(tempfile.mkdtemp(prefix='pytest-deduplicate-path-cache-'))
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        parser.error('--workdir must be empty so previous modules cannot affect measurement')
    (root / 'app').mkdir(exist_ok=True)
    (root / 'tests').mkdir(exist_ok=True)
    for index in range(options.modules):
        (root / 'app' / f'module_{index}.py').write_text(f'def choose(value):\n    if value < {index}:\n        return False\n    return True\n')
    tests = ['import importlib', 'import pytest', f'@pytest.mark.parametrize("index", range({options.tests}))',
             f'def test_choose(index):\n    module = importlib.import_module(f"app.module_{{index % {options.modules}}}")\n    assert module.choose(index) is True']
    (root / 'tests' / 'test_cases.py').write_text('\n'.join(tests) + '\n')
    sources = {'baseline': str(Path(options.baseline_source).resolve()),
               'cached': str(Path(options.candidate_source).resolve())}
    result = {'modules': options.modules, 'tests': options.tests, 'python': sys.version, 'samples_seconds': {mode: [] for mode in sources}, 'observations': []}
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', COVERAGE_RCFILE='/dev/null')
    env.pop('PYTEST_ADDOPTS', None)
    expected = None
    for run in range(options.runs):
        modes = list(sources) if run % 2 == 0 else list(reversed(sources))
        for mode in modes:
            report_path = root / f'{mode}-{run}.json'
            metrics_path = root / f'{mode}-{run}-metrics.json'
            started = time.perf_counter()
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', sources[mode], str(metrics_path), str(report_path)], cwd=root, env=env, capture_output=True, text=True)
            elapsed = time.perf_counter() - started
            if completed.returncode:
                raise RuntimeError((completed.stdout + completed.stderr)[-6000:])
            report = json.loads(report_path.read_text())
            exact = snapshot(report)
            if expected is None:
                expected = exact
            if exact != expected:
                raise AssertionError(f'coverage/outcome parity failed for {mode} run {run}')
            result['samples_seconds'][mode].append(elapsed)
            result['observations'].append({'mode': mode, 'run': run, 'cache': json.loads(metrics_path.read_text()), 'report_sha256': hashlib.sha256(json.dumps(exact, sort_keys=True).encode()).hexdigest()})
            print(f'{mode} run {run}: {elapsed:.3f}s', flush=True)
    result['median_seconds'] = {mode: statistics.median(samples) for mode, samples in result['samples_seconds'].items()}
    result['speedup'] = result['median_seconds']['baseline'] / result['median_seconds']['cached']
    result['exact_coverage_outcome_findings_parity'] = True
    destination = root / 'benchmark.json'
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(destination, flush=True)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

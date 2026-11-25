"""Compare coverage importers using generated, sparse per-test branch evidence."""
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

from coverage import CoverageData


def child(source):
    sys.path.insert(0, source)
    analyzer = importlib.import_module('pytest_deduplicate')
    importer = importlib.import_module('pytest_deduplicate_import')
    plugin = analyzer.FindDuplicateCoverage(source=['app'], coverage_phase='call')
    started = time.perf_counter()
    importer.import_coverage(plugin, '.coverage', 'outcomes.json')
    elapsed = time.perf_counter() - started
    evidence = [dict(test, file_arcs=analyzer.serialize_arcs(test['file_arcs']),
                     phase_file_arcs={phase: analyzer.serialize_arcs(arcs) if arcs is not None else None
                                      for phase, arcs in test['phase_file_arcs'].items()})
                for test in plugin.observations]
    print(json.dumps({'seconds': elapsed, 'tests': len(evidence),
                      'evidence_sha256': hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()}))


def fixture(root, modules, tests):
    app = root / 'app'
    app.mkdir()
    paths = [app / ('module_%d.py' % index) for index in range(modules)]
    for path in paths:
        path.write_text('def value():\n    return 1\n')
    data = CoverageData(basename=str(root / '.coverage'))
    observations = []
    for index in range(tests):
        nodeid = 'test_generated.py::test_case_%d' % index
        phases = {}
        for offset, (phase, suffix) in enumerate([('setup', 'setup'), ('call', 'run'), ('teardown', 'teardown')]):
            data.set_context(nodeid + '|' + suffix)
            data.add_arcs({str(paths[(index + offset) % modules]): [(-1, 2), (2, -1)]})
            phases[phase] = {'outcome': 'passed', 'duration': 0.001, 'xfail': False}
        observations.append({'nodeid': nodeid, 'location': {'file': 'test_generated.py', 'line': index + 1},
                             'phases': phases})
    data.write()
    manifest = {'schema_version': 1, 'root': str(root), 'pytest_exit_code': 0, 'errors': [],
                'coverage_cores': ['CTracer'], 'expected': [test['nodeid'] for test in observations],
                'tests': observations, 'excluded_test_lines': {},
                'coverage_sha256': hashlib.sha256((root / '.coverage').read_bytes()).hexdigest(),
                'source_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}
    (root / 'outcomes.json').write_text(json.dumps(manifest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', help=argparse.SUPPRESS)
    parser.add_argument('--baseline-source')
    parser.add_argument('--candidate-source')
    parser.add_argument('--modules', type=int, default=80)
    parser.add_argument('--tests', type=int, default=240)
    parser.add_argument('--runs', type=int, default=3)
    options = parser.parse_args()
    if options.child:
        child(options.child)
        return
    if not options.baseline_source or not options.candidate_source:
        parser.error('--baseline-source and --candidate-source are required')
    if min(options.modules, options.tests, options.runs) < 1:
        parser.error('module, test and run counts must be positive')
    root = Path(tempfile.mkdtemp(prefix='pytest-deduplicate-import-')).resolve()
    fixture(root, options.modules, options.tests)
    sources = {'baseline': str(Path(options.baseline_source).resolve()),
               'candidate': str(Path(options.candidate_source).resolve())}
    result = {'modules': options.modules, 'tests': options.tests, 'phases': 3, 'python': sys.version,
              'samples_seconds': {mode: [] for mode in sources}, 'observations': []}
    env = dict(os.environ, COVERAGE_RCFILE=os.devnull)
    expected = None
    for run in range(options.runs):
        modes = list(sources) if run % 2 == 0 else list(reversed(sources))
        for mode in modes:
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', sources[mode]],
                                       cwd=root, env=env, capture_output=True, text=True)
            if completed.returncode:
                raise RuntimeError(completed.stdout + completed.stderr)
            observation = json.loads(completed.stdout)
            if expected is None:
                expected = observation['evidence_sha256']
            if observation['tests'] != options.tests or observation['evidence_sha256'] != expected:
                raise AssertionError('coverage/outcome parity failed for %s run %d' % (mode, run))
            result['samples_seconds'][mode].append(observation['seconds'])
            result['observations'].append(dict(observation, mode=mode, run=run))
            print('%s run %d: %.3fs' % (mode, run, observation['seconds']), flush=True)
    result['median_seconds'] = {mode: statistics.median(samples)
                                for mode, samples in result['samples_seconds'].items()}
    result['speedup'] = result['median_seconds']['baseline'] / result['median_seconds']['candidate']
    result['exact_coverage_and_outcome_parity'] = True
    destination = root / 'benchmark.json'
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(destination)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

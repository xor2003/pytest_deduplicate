"""pytest-cov companion outcomes and strict import of a single combined data file.

Load with pytest -p pytest_deduplicate_import --cov=... --cov-branch
--cov-context=test --deduplicate-outcomes outcomes.json. xdist is supported by
collecting worker inventories and validating the final combined coverage file.
"""
import hashlib
import inspect
import dis
import json
import os
from pathlib import Path
from types import CodeType

from coverage import CoverageData
from coverage.exceptions import CoverageException
import pytest


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pytest_addoption(parser):
    group = parser.getgroup('deduplicate evidence')
    group.addoption('--deduplicate-outcomes', help='write coverage-bound outcome manifest')
    group.addoption('--deduplicate-coverage-file', default='.coverage', help='final combined pytest-cov data file')


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    # Wrap pytest-cov's startup, before it constructs Coverage on master/workers.
    # Explicit contexts need the tracing core on Python 3.14 as well.
    if getattr(early_config.known_args_namespace, 'deduplicate_outcomes', None):
        previous = os.environ.get('COVERAGE_CORE')
        os.environ['COVERAGE_CORE'] = 'ctrace'
        def restore_core():
            if previous is None:
                os.environ.pop('COVERAGE_CORE', None)
            else:
                os.environ['COVERAGE_CORE'] = previous
        early_config.add_cleanup(restore_core)
    yield


def pytest_configure(config):
    if config.getoption('deduplicate_outcomes'):
        config.pluginmanager.register(OutcomeManifest(config), 'deduplicate-outcomes-recorder')


class OutcomeManifest:
    def __init__(self, config):
        self.config = config
        self.expected = set()
        self.excluded = {}
        self.tests = {}
        self.errors = []
        self.core = None
        self.worker_cores = []

    @pytest.hookimpl(trylast=True)
    def pytest_sessionstart(self, session):
        plugin = self.config.pluginmanager.get_plugin('_cov')
        try:
            self.core = dict(plugin.cov_controller.cov.sys_info()).get('core')
        except AttributeError:
            pass

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        def add(code):
            self.excluded.setdefault(str(Path(code.co_filename).resolve()), set()).update(
                n for _, n in dis.findlinestarts(code) if n is not None)
            for const in code.co_consts:
                if isinstance(const, CodeType):
                    add(const)
        for item in items:
            self.expected.add(item.nodeid)
            code = getattr(inspect.unwrap(getattr(item, 'obj', None)), '__code__', None)
            if code:
                add(code)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node, ids):
        current = set(ids)
        if self.expected and self.expected != current:
            self.errors.append('workers collected different test inventories')
        self.expected = current

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        if error:
            self.errors.append('worker did not finish normally')
        self.worker_cores.append(node.workeroutput.get('deduplicate_core'))
        if 'deduplicate_excluded' not in node.workeroutput:
            self.errors.append('worker did not provide test-body exclusions')
        for path, lines in node.workeroutput.get('deduplicate_excluded', {}).items():
            self.excluded.setdefault(path, set()).update(lines)

    def pytest_runtest_logreport(self, report):
        file, line, _ = report.location
        test = self.tests.setdefault(report.nodeid, {'nodeid': report.nodeid,
            'location': {'file': file, 'line': (line or 0) + 1}, 'phases': {}})
        if report.when in test['phases']:
            self.errors.append('repeated test phase: ' + report.nodeid)
        test['phases'][report.when] = {'outcome': report.outcome, 'duration': report.duration,
                                     'xfail': hasattr(report, 'wasxfail')}

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        excluded = {p: sorted(lines) for p, lines in self.excluded.items()}
        if hasattr(self.config, 'workerinput'):
            self.config.workeroutput['deduplicate_excluded'] = excluded
            self.config.workeroutput['deduplicate_core'] = self.core
            return
        target = Path(self.config.getoption('deduplicate_coverage_file')).resolve()
        result = {'schema_version': 1, 'root': str(Path.cwd().resolve()),
                  'pytest_exit_code': int(exitstatus), 'expected': sorted(self.expected),
                  'tests': list(self.tests.values()), 'excluded_test_lines': excluded,
                  'coverage_file': str(target), 'errors': self.errors,
                  'coverage_cores': [self.core, *self.worker_cores]}
        try:
            if (not self.config.getoption('cov_source', default=None)
                    or self.config.getoption('no_cov', default=False)
                    or self.config.getoption('cov_append', default=False)):
                raise ValueError('an active fresh non-append pytest-cov run is required')
            if any(core not in ('CTracer', 'PyTracer') for core in result['coverage_cores']):
                raise ValueError('full context arcs require a tracing core on every worker')
            cov_plugin = self.config.pluginmanager.get_plugin('_cov')
            live_data_file = cov_plugin.cov_controller.cov.get_option('run:data_file')
            if Path(live_data_file).resolve() != target:
                raise ValueError('manifest must reference the active combined coverage data file')
            if self.config.getoption('cov_context', default=None) != 'test':
                raise ValueError('pytest-cov --cov-context=test is required')
            if not target.is_file():
                raise ValueError('combined coverage file is missing')
            data = CoverageData(basename=str(target)); data.read()
            if not data.has_arcs():
                raise ValueError('--cov-branch is required')
            result['coverage_sha256'] = digest(target)
            paths = set(data.measured_files()) | set(excluded)
            result['source_sha256'] = {str(Path(p).resolve()): digest(p) for p in sorted(paths)}
        except (OSError, ValueError, AttributeError, CoverageException) as exc:
            self.errors.append(str(exc))
        Path(self.config.getoption('deduplicate_outcomes')).write_text(json.dumps(result, indent=2) + '\n')


def import_coverage(plugin, coverage_file, manifest_file):
    """Reject stale, unbound, failing, partial, repeated, or line-only input."""
    from coverage.files import GlobMatcher, prep_patterns
    manifest = json.loads(Path(manifest_file).read_text())
    if manifest.get('schema_version') != 1 or manifest.get('errors') or manifest.get('pytest_exit_code') != 0:
        raise ValueError('outcome manifest is incomplete or unsuccessful')
    cores = manifest.get('coverage_cores', [])
    if not cores or any(core not in ('CTracer', 'PyTracer') for core in cores):
        raise ValueError('manifest does not verify tracing cores; regenerate coverage with the companion plugin')
    if manifest.get('root') != str(Path.cwd().resolve()):
        raise ValueError('import must use the recorded project root')
    if digest(coverage_file) != manifest.get('coverage_sha256'):
        raise ValueError('coverage data does not match outcome manifest')
    for path, expected in manifest['source_sha256'].items():
        if digest(path) != expected:
            raise ValueError('source changed since coverage measurement: ' + path)
    expected = set(manifest['expected'])
    observations = manifest['tests']
    if not expected or len(observations) != len(expected) or {t['nodeid'] for t in observations} != expected:
        raise ValueError('outcomes do not match complete collected inventory')
    data = CoverageData(basename=str(Path(coverage_file).resolve())); data.read()
    if not data.has_arcs():
        raise ValueError('branch coverage is required')
    contexts = data.measured_contexts()
    supported = {n + '|' + p for n in expected for p in ('setup', 'run', 'teardown')}
    if contexts - supported - {''}:
        raise ValueError('unknown/stale coverage contexts; use a fresh non-append run')
    measured = data.measured_files()
    if not {str(Path(p).resolve()) for p in measured} <= set(manifest['source_sha256']):
        raise ValueError('manifest does not fingerprint every measured file')
    # Use coverage.py's own matcher so ** and directory globs retain live semantics.
    omit = GlobMatcher(prep_patterns(plugin.coverage.get_option('run:omit')))
    scoped_files = []
    for filename in sorted(measured):
        path = plugin.source_path(filename)
        if path is None or omit.match(str(path)):
            continue
        excluded = set(manifest['excluded_test_lines'].get(str(path), []))
        scoped_files.append((filename, str(path), excluded))
    for test in observations:
        phases = test['phases']
        if set(phases) != {'setup', 'call', 'teardown'}:
            raise ValueError('missing phase outcome: ' + test['nodeid'])
        test['eligible'] = all(p['outcome'] == 'passed' and not p['xfail'] for p in phases.values())
        test['duration'] = sum(p['duration'] for p in phases.values())
        test['file_arcs'], test['phase_file_arcs'] = {}, {}
        for phase, suffix in [('setup', 'setup'), ('call', 'run'), ('teardown', 'teardown')]:
            context = test['nodeid'] + '|' + suffix
            # pytest-cov versions may only attribute call. Missing context is
            # unmeasured, never proof of an empty phase.
            if context not in contexts:
                test['phase_file_arcs'][phase] = None
                continue
            data.set_query_context(context)
            arcs_by_file = {}
            for filename, path, excluded in scoped_files:
                arcs = {arc for arc in data.arcs(filename) or [] if not any(abs(n) in excluded for n in arc)}
                if arcs:
                    arcs_by_file[path] = arcs
                    test['file_arcs'].setdefault(path, set()).update(arcs)
            test['phase_file_arcs'][phase] = arcs_by_file
        if plugin.coverage_phase == 'call':
            test['file_arcs'] = test['phase_file_arcs']['call'] or {}
        plugin.observations.append(test)
    data.set_query_contexts(None)
    plugin.collector = 'pytest-cov-import'
    return {'coverage_sha256': manifest['coverage_sha256'], 'phase_scope': 'available explicit pytest-cov contexts',
            'unattributed_context_ignored': '' in contexts, 'inventory_validated': True}

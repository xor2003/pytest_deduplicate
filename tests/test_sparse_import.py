"""Coverage imports preserve observations when tests touch disjoint source files."""
import json

from coverage import CoverageData
import pytest

from pytest_deduplicate import FindDuplicateCoverage, build_report
from pytest_deduplicate_import import digest, import_coverage


def import_dataset(tmp_path, monkeypatch, contexts, phase='all', source=(), omit=(), excluded=None):
    monkeypatch.chdir(tmp_path)
    files = {name for arcs_by_file in contexts.values() for name in arcs_by_file}
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('def value():\n    return 1\n')
    coverage_file = tmp_path / '.coverage'
    data = CoverageData(basename=str(coverage_file))
    for context, arcs_by_file in contexts.items():
        data.set_context(context)
        data.add_arcs({str(tmp_path / name): arcs for name, arcs in arcs_by_file.items()})
    data.write()
    nodeids = sorted({context.rsplit('|', 1)[0] for context in contexts if context})
    manifest = {
        'schema_version': 1,
        'root': str(tmp_path.resolve()),
        'pytest_exit_code': 0,
        'expected': nodeids,
        'tests': [
            {'nodeid': nodeid, 'location': {'file': 'test_example.py', 'line': 1},
             'phases': {name: {'outcome': 'passed', 'duration': 0.1, 'xfail': False}
                        for name in ('setup', 'call', 'teardown')}}
            for nodeid in nodeids
        ],
        'excluded_test_lines': {str(tmp_path / name): lines for name, lines in (excluded or {}).items()},
        'coverage_file': str(coverage_file),
        'coverage_sha256': digest(coverage_file),
        'source_sha256': {str(tmp_path / name): digest(tmp_path / name) for name in files},
        'errors': [],
        'coverage_cores': ['CTracer'],
    }
    manifest_file = tmp_path / 'outcomes.json'
    manifest_file.write_text(json.dumps(manifest))
    plugin = FindDuplicateCoverage(source=source, omit=omit, coverage_phase=phase)
    metadata = import_coverage(plugin, coverage_file, manifest_file)
    return plugin, metadata


@pytest.mark.parametrize('phase', ['all', 'call'])
def test_disjoint_file_import_retains_phase_scope_and_file_identity(tmp_path, monkeypatch, phase):
    ordinary = {(-1, 2), (2, -1)}
    cleanup = {(-3, 4), (4, -3)}
    plugin, metadata = import_dataset(tmp_path, monkeypatch, {
        'test_example.py::test_first|setup': {'fixture.py': ordinary},
        'test_example.py::test_first|run': {'first.py': ordinary},
        'test_example.py::test_first|teardown': {'fixture.py': cleanup},
        'test_example.py::test_second|run': {'second.py': ordinary},
        '': {'unattributed.py': ordinary},
    }, phase=phase)
    first, second = plugin.observations
    first_file, second_file, fixture_file = [str(tmp_path / name) for name in
                                             ('first.py', 'second.py', 'fixture.py')]
    assert first['phase_file_arcs'] == {
        'setup': {fixture_file: ordinary},
        'call': {first_file: ordinary},
        'teardown': {fixture_file: cleanup},
    }
    assert second['phase_file_arcs'] == {
        'setup': None, 'call': {second_file: ordinary}, 'teardown': None,
    }
    expected_first = {first_file: ordinary}
    if phase == 'all':
        expected_first[fixture_file] = ordinary | cleanup
    assert first['file_arcs'] == expected_first
    assert second['file_arcs'] == {second_file: ordinary}
    assert metadata['unattributed_context_ignored']
    assert plugin.collector == 'pytest-cov-import'
    # Equal arc numbers in distinct source files must not become duplicates.
    assert build_report(plugin, 0, 0)['findings'] == []


def test_missing_coverage_is_distinct_from_filtered_empty_phases(tmp_path, monkeypatch):
    ordinary = {(-1, 2), (2, -1)}
    plugin, _ = import_dataset(tmp_path, monkeypatch, {
        'test_example.py::test_value|setup': {'outside.py': ordinary},
        'test_example.py::test_value|run': {'product.py': ordinary},
    }, source=('product.py',), excluded={'product.py': [2]})
    observation, = plugin.observations
    assert observation['phase_file_arcs'] == {'setup': {}, 'call': {}, 'teardown': None}
    assert observation['file_arcs'] == {}
    assert observation['eligible']


def test_negative_only_context_arcs_survive_alongside_line_contexts(tmp_path, monkeypatch):
    negative = {(-7, -7)}
    ordinary = {(-1, 2), (2, -1)}
    contexts = {
        'test_example.py::test_negative|run': {'product.py': negative},
        'test_example.py::test_mixed|run': {'product.py': negative | ordinary},
        'test_example.py::test_positive|run': {'product.py': ordinary},
    }
    plugin, _ = import_dataset(tmp_path, monkeypatch, contexts)
    by_nodeid = {test['nodeid']: test for test in plugin.observations}
    for context, arcs_by_file in contexts.items():
        expected = {str(tmp_path / 'product.py'): arcs_by_file['product.py']}
        observation = by_nodeid[context.rsplit('|', 1)[0]]
        assert observation['phase_file_arcs'] == {'setup': None, 'call': expected, 'teardown': None}
        assert observation['file_arcs'] == expected


def test_sparse_import_preserves_source_omit_and_test_body_filters(tmp_path, monkeypatch):
    ordinary = {(-1, 2), (2, -1)}
    test_body = {(-3, 4), (4, -3)}
    plugin, _ = import_dataset(tmp_path, monkeypatch, {
        'test_example.py::test_value|run': {
            'product/core.py': ordinary,
            'product/test_helpers.py': ordinary | test_body,
            'product/ignored/deep/client.py': ordinary,
            'outside/client.py': ordinary,
        },
    }, source=('product',), omit=('*/product/ignored/**',),
        excluded={'product/test_helpers.py': [3, 4]})
    expected = {str(tmp_path / name): ordinary for name in ('product/core.py', 'product/test_helpers.py')}
    observation, = plugin.observations
    assert observation['phase_file_arcs'] == {'setup': None, 'call': expected, 'teardown': None}
    assert observation['file_arcs'] == expected

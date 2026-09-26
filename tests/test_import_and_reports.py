import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_deduplicate_artifacts import apply_reviews, compare_reports, review_template
from tests.test_analyzer import run_suite
from tests.test_features import PAIR, load_report


@pytest.mark.parametrize('workers', [0, 2])
@pytest.mark.parametrize('context_manager', [False, True])
def test_import_real_pytest_cov_and_reject_stale_data(tmp_path, workers, context_manager):
    pytest.importorskip('pytest_cov')
    pytest.importorskip('xdist')
    for name, source in PAIR.items():
        if context_manager and name == 'test_example.py':
            source = (
                'from contextlib import nullcontext\nfrom product import nonnegative\n'
                'def test_zero():\n    with nullcontext():\n        assert nonnegative(0)\n'
                'def test_two():\n    with nullcontext():\n        assert nonnegative(2)\n'
            )
        (tmp_path / name).write_text(source)
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    env.pop('PYTEST_ADDOPTS', None)
    # The companion must override a backend that lacks full explicit contexts.
    env['COVERAGE_CORE'] = 'sysmon'
    command = [sys.executable, '-m', 'pytest', '-q', '-p', 'pytest_cov.plugin', '-p', 'xdist.plugin',
               '-p', 'pytest_deduplicate_import', '--cov=product', '--cov-branch', '--cov-context=test',
               '--deduplicate-outcomes=outcomes.json']
    if workers:
        command += ['-n', str(workers)]
    run = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    manifest = json.loads((tmp_path / 'outcomes.json').read_text())
    assert manifest['errors'] == [], manifest
    assert all(core in ('CTracer', 'PyTracer') for core in manifest['coverage_cores'])
    result = run_suite(tmp_path, {}, '--source', 'product.py', '--import-coverage', '.coverage',
                       '--outcomes', 'outcomes.json', '--json', 'report.json')
    assert result.returncode == 0, result.stdout + result.stderr
    report = load_report(tmp_path)
    assert report['collector'] == 'pytest-cov-import'
    assert report['import']['inventory_validated']
    assert len(report['findings']) == 1
    assert report['findings'][0]['shared'] == {'product.py': [[-1, 2], [2, -1]]}
    assert all(t['phase_file_arcs']['call'] == t['file_arcs'] for t in report['tests'])
    if workers == 0:
        for damage in ('missing_phase', 'missing_test', 'failed_run', 'wrong_digest'):
            altered = copy.deepcopy(manifest)
            if damage == 'missing_phase':
                altered['tests'][0]['phases'].pop('teardown')
            elif damage == 'missing_test':
                altered['tests'].pop()
            elif damage == 'failed_run':
                altered['pytest_exit_code'] = 1
            else:
                altered['coverage_sha256'] = 'wrong'
            (tmp_path / 'bad-outcomes.json').write_text(json.dumps(altered))
            bad = run_suite(tmp_path, {}, '--import-coverage', '.coverage', '--outcomes', 'bad-outcomes.json', '--json', 'bad.json')
            assert bad.returncode == 2, damage
            assert json.loads((tmp_path / 'bad.json').read_text())['findings'] == []
    (tmp_path / 'product.py').write_text(PAIR['product.py'] + '# changed\n')
    result = run_suite(tmp_path, {}, '--import-coverage', '.coverage', '--outcomes', 'outcomes.json', '--json', 'report.json')
    assert result.returncode == 2
    assert 'source changed' in load_report(tmp_path)['errors'][0]
    assert load_report(tmp_path)['findings'] == []


def test_phase_only_comparison_excludes_fixture_overlap(tmp_path):
    files = {'product.py': 'def fixture():\n    return 1\ndef body():\n    return 2\n',
             'conftest.py': 'import pytest, product\n@pytest.fixture\ndef common():\n    product.fixture()\n    yield\n    product.fixture()\n',
             'test_example.py': 'import product\ndef test_a(common):\n    pass\ndef test_b(common):\n    pass\ndef test_c(common):\n    assert product.body() == 2\n'}
    result = run_suite(tmp_path, files, '--source', 'product.py', '--json', 'report.json')
    assert result.returncode == 0, result.stderr
    report = load_report(tmp_path)
    assert any(f['kind'] == 'identical' for f in report['findings'])
    for test in report['tests']:
        assert test['phase_file_arcs']['setup'] == {'product.py': [[-1, 2], [2, -1]]}
        assert test['phase_file_arcs']['teardown'] == test['phase_file_arcs']['setup']
    result = run_suite(tmp_path, files, '--source', 'product.py', '--coverage-phase', 'call', '--json', 'report.json')
    assert result.returncode == 0, result.stderr
    assert load_report(tmp_path)['findings'] == []


def test_review_invalidation_and_baseline_scope(tmp_path):
    result = run_suite(tmp_path, PAIR, '--source', 'product.py', '--json', 'report.json')
    assert result.returncode == 0, result.stderr
    report = load_report(tmp_path)
    document = review_template(report)
    document['reviews'][0].update(reason='Separate zero boundary and positive input contracts', reviewed_at='2026-09-09')
    apply_reviews(report, document)
    assert report['findings'][0]['review']['status'] == 'reviewed'
    changed = copy.deepcopy(report)
    changed['findings'][0]['evidence_sha256'] = 'changed'
    apply_reviews(changed, document)
    assert changed['findings'][0]['review']['status'] == 'needs_revalidation'
    changed['findings'] = []
    assert compare_reports(changed, report)['resolved'] == [report['findings'][0]['id']]
    changed['evidence']['inventory_sha256'] = 'other tests'
    diff = compare_reports(changed, report)
    assert not diff['resolved'] and diff['unobserved']
    document['reviews'][0]['reason'] = ' '
    with pytest.raises(ValueError, match='reason'):
        apply_reviews(report, document)


def test_html_cli_and_real_source_change_invalidate_review(tmp_path):
    result = run_suite(tmp_path, PAIR, '--source', 'product.py', '--json', 'report.json',
                       '--html', 'report.html', '--review-template', 'reviews.json')
    assert result.returncode == 0, result.stderr
    baseline = load_report(tmp_path)
    (tmp_path / 'baseline.json').write_text(json.dumps(baseline))
    reviews = json.loads((tmp_path / 'reviews.json').read_text())
    reviews['reviews'][0].update(reason='</script><script>alert(1)</script>', reviewed_at='2026-09-09')
    (tmp_path / 'reviews.json').write_text(json.dumps(reviews))
    result = run_suite(tmp_path, {}, '--source', 'product.py', '--json', 'report.json', '--html', 'report.html',
                       '--baseline', 'baseline.json', '--suppressions', 'reviews.json')
    assert result.returncode == 0, result.stderr
    html = (tmp_path / 'report.html').read_text()
    assert '</script><script>alert(1)</script>' not in html
    assert '\\u003c/script>' in html
    assert 'matches report hash' in html
    assert 'def nonnegative(x):' in html
    assert load_report(tmp_path)['findings'][0]['review']['status'] == 'reviewed'
    (tmp_path / 'product.py').write_text(PAIR['product.py'] + '# contract changed\n')
    result = run_suite(tmp_path, {}, '--source', 'product.py', '--json', 'report.json', '--suppressions', 'reviews.json')
    assert result.returncode == 0, result.stderr
    assert load_report(tmp_path)['findings'][0]['review']['status'] == 'needs_revalidation'


def test_snapshot_limit_and_confirmation_trials(tmp_path):
    result = run_suite(tmp_path, PAIR, '--source', 'product.py', '--mutations', '1', '--json', 'report.json')
    assert result.returncode == 0, result.stderr
    mutations = load_report(tmp_path)['mutations']
    assert mutations['confirmation_runs'] == 2
    assert all(len(trials) == 2 for trials in mutations['mutants'][0]['trials'].values())
    (tmp_path / 'large.bin').write_bytes(b'x' * (1024 * 1024 + 1))
    result = run_suite(tmp_path, {}, '--source', 'product.py', '--mutations', '1', '--mutation-snapshot-mb', '1', '--json', 'report.json')
    assert result.returncode == 0, result.stderr
    assert load_report(tmp_path)['mutations']['status'] == 'snapshot_limit_exceeded'
    assert load_report(tmp_path)['findings'][0]['assessment']['status'] == 'incomplete'


@pytest.mark.parametrize('flag', ['--cov-append', '--no-cov'])
def test_manifest_cannot_rebind_old_coverage(tmp_path, flag):
    pytest.importorskip('pytest_cov')
    for name, source in PAIR.items():
        (tmp_path / name).write_text(source)
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    env.pop('PYTEST_ADDOPTS', None)
    run = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'pytest_cov.plugin',
                          '-p', 'pytest_deduplicate_import', '--cov=product', '--cov-branch', '--cov-context=test',
                          '--deduplicate-outcomes=outcomes.json', flag],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'active fresh non-append' in json.loads((tmp_path / 'outcomes.json').read_text())['errors'][0]


def test_inconsistent_mutant_repeats_cannot_distinguish(tmp_path, monkeypatch):
    import pytest_deduplicate_checks as checks
    from pytest_deduplicate import parse_args
    run = run_suite(tmp_path, PAIR, '--source', 'product.py', '--json', 'report.json')
    assert run.returncode == 0, run.stderr
    report = load_report(tmp_path)
    ids = [t['nodeid'] for t in report['tests']]
    original = {t['nodeid']: t for t in report['tests']}
    repeats = {}
    def fake_run(root, options, pytest_args, selected, order):
        nodeid = selected[0]
        test = copy.deepcopy(original[nodeid])
        changed = (root / 'product.py').read_text() != PAIR['product.py']
        killed = changed and repeats.get(nodeid, 0) % 2 == 0
        if changed:
            repeats[nodeid] = repeats.get(nodeid, 0) + 1
        if killed:
            test['eligible'] = False
            test['phases']['call']['outcome'] = 'failed'
        return {'status': 'complete', 'returncode': int(killed), 'report': {'tests': [test]}}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(checks, 'run_child', fake_run)
    options, args = parse_args(['--source', 'product.py', '--mutations', '1'])
    result = checks.check_mutations(report, options, args, ids, [])
    assert set(result['mutants'][0]['outcomes'].values()) == {'inconclusive'}
    assert result['comparisons'][0]['status'] == 'inconclusive'

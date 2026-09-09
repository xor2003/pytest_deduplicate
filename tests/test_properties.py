"""Independent set oracles and generated real programs, with reproducible examples."""
from itertools import combinations

from hypothesis import given, settings, strategies as st

from pytest_deduplicate import TestCoverage as Coverage, coverage_signature, find_fully_overlapped_sets
from pytest_deduplicate_review import assess_findings, select_candidates
from tests.test_analyzer import run_suite
from tests.test_features import load_report

ARCS = st.dictionaries(st.sampled_from(['a.py', 'b.py', 'c.py']),
                       st.sets(st.tuples(st.integers(-3, 9), st.integers(-3, 9)), max_size=12))


def flat(arcs):
    return {(file, a, b) for file, pairs in arcs.items() for a, b in pairs}


@given(ARCS, ARCS)
def test_set_algebra_matches_flat_oracle(left, right):
    a, b = Coverage([], left), Coverage([], right)
    x, y = flat(left), flat(right)
    assert flat((a & b).file_arcs) == x & y
    assert flat((a - b).file_arcs) == x - y
    assert flat(Coverage.union(a, b).file_arcs) == x | y
    assert a.issubset(b) == (x <= y)
    assert (coverage_signature(left) == coverage_signature(right)) == (x == y)


@given(st.lists(ARCS, max_size=12))
def test_combined_detection_matches_exhaustive_union_oracle(arcs):
    groups = [Coverage([], a) for a in arcs if flat(a)]
    found = {id(big) for big, small in find_fully_overlapped_sets(groups)}
    expected = {id(big) for big in groups
                if flat(big.file_arcs) <= set().union(*(flat(other.file_arcs) for other in groups if len(other) < len(big)))}
    assert found == expected
    for big, small in find_fully_overlapped_sets(groups):
        assert flat(big.file_arcs) <= set().union(*(flat(s.file_arcs) for s in small))
        assert all(len(s) < len(big) for s in small)


def report_for_groups(groups):
    ids = sorted(set(n for group in groups for n in group))
    return {'errors': [], 'pytest_exit_code': 0,
            'tests': [{'nodeid': n, 'duration': i / 10, 'location': {'file': n.split('::')[0]}}
                      for i, n in enumerate(ids)],
            'findings': [{'kind': 'identical', 'tests': sorted(group), 'other_tests': [], 'shared_arc_count': 10}
                         for group in groups if len(group) >= 2]}


@given(st.lists(st.sets(st.sampled_from(['a::1', 'a::2', 'b::1', 'b::2', 'c::1']), min_size=2), max_size=8),
       st.integers(1, 8))
def test_selection_budget_and_comparison_integrity(groups, limit):
    report = report_for_groups(groups)
    result = select_candidates(report, limit)
    chosen = set(result['selected'])
    wanted = set().union(*groups)
    assert len(chosen) <= limit
    assert chosen <= wanted
    assert chosen.isdisjoint(result['unchecked'])
    assert chosen | set(result['unchecked']) == wanted
    assert not chosen or len(chosen) >= 2
    assert select_candidates(report, limit) == result
    for reason in result['reasons']:
        assert len(reason['tests']) >= 2
        assert set(reason['tests']) <= chosen


def test_assessment_does_not_hide_incomplete_group_or_unstable_evidence():
    report = report_for_groups([{'a', 'b', 'c'}])
    report['stability'] = {'tests': {'a': {'status': 'stable_in_checked_runs'}, 'b': {'status': 'stable_in_checked_runs'}}}
    assess_findings(report)
    assert report['findings'][0]['assessment']['status'] == 'incomplete'
    report['stability']['tests']['a']['status'] = 'unstable'
    report['mutations'] = {'comparisons': [{'tests': ['a', 'b'], 'status': 'different_fault_detection'}]}
    assess_findings(report)
    assert report['findings'][0]['assessment']['status'] == 'unstable'
    assert not report['findings'][0]['assessment']['automatic_removal_safe']


@settings(max_examples=5, deadline=None)
@given(st.integers(-100, 100))
def test_generated_program_has_known_overlap(boundary):
    # Fresh directory per generated example, independent of pytest fixture lifetime.
    import tempfile
    from pathlib import Path
    files = {'product.py': f'def value(x):\n    if x >= {boundary}:\n        return 1\n    return 0\n',
             'test_example.py': f'from product import value\ndef test_a():\n    assert value({boundary}) == 1\ndef test_b():\n    assert value({boundary + 1}) == 1\ndef test_c():\n    assert value({boundary - 1}) == 0\ndef test_both():\n    assert value({boundary}) == 1\n    assert value({boundary - 1}) == 0\n'}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = run_suite(root, files, '--source', 'product.py', '--json', 'report.json')
        assert run.returncode == 0, run.stderr
        report = load_report(root)
        identical = [f for f in report['findings'] if f['kind'] == 'identical']
        assert len(identical) == 1
        assert set(identical[0]['tests']) == {'test_example.py::test_a', 'test_example.py::test_b'}
        assert len([f for f in report['findings'] if f['kind'] == 'contained']) == 2
        assert len([f for f in report['findings'] if f['kind'] == 'combined']) == 1


@given(st.lists(ARCS, max_size=15))
def test_inverted_containment_matches_quadratic_oracle(arcs):
    from pytest_deduplicate_index import ArcIndex
    groups = [Coverage([], a) for a in arcs]
    expected = {(i, j) for i, a in enumerate(arcs) for j, b in enumerate(arcs)
                if i != j and flat(a) and flat(a) <= flat(b)}
    assert set(ArcIndex(groups).containment_pairs()) == expected

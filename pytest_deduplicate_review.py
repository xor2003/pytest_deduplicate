"""Conservative evidence aggregation and bounded comparison selection."""


def members(finding):
    return sorted(set(finding['tests'] + finding['other_tests']))


def assess_findings(report):
    """Keep observed overlap, stability and sampled faults as separate evidence."""
    stability = report.get('stability', {}).get('tests', {})
    comparisons = {frozenset(c['tests']): c for c in report.get('mutations', {}).get('comparisons', [])}
    invalid = bool(report['errors'] or report['pytest_exit_code'])
    observations = {t['nodeid']: t for t in report['tests']}
    for finding in report['findings']:
        ids = members(finding)
        states = {n: stability.get(n, {}).get('status', 'unchecked') for n in ids}
        id_set = set(ids)
        pairs = [c for pair, c in comparisons.items() if len(pair) == 2 and pair <= id_set]
        expected_pairs = len(ids) * (len(ids) - 1) // 2
        differences = [c for c in pairs if c and c['status'] == 'different_fault_detection']
        stable = bool(states) and all(s == 'stable_in_checked_runs' for s in states.values())
        mutations_complete = bool(pairs) and len(pairs) == expected_pairs and all(c and c['status'] in
                            ('same_on_sampled_mutants', 'different_fault_detection') for c in pairs)
        requested_phases = ('call',) if report.get('scope', {}).get('coverage_phase') == 'call' else ('setup', 'call', 'teardown')
        coverage_complete = not report.get('import') or all(
            observations[n].get('phase_file_arcs', {}).get(phase) is not None
            for n in ids for phase in requested_phases)
        if invalid or not coverage_complete:
            status = 'incomplete'
        elif 'unstable' in states.values():
            status = 'unstable'
        elif differences:
            status = 'different_fault_detection'
        elif 'inconclusive' in states.values() or ('mutations' in report and not mutations_complete):
            status = 'incomplete'
        elif stable and mutations_complete:
            status = 'consistent_in_checked_sample'
        elif 'stability' in report and not stable:
            status = 'incomplete'
        elif stable:
            status = 'stable_coverage_only'
        else:
            status = 'unchecked'
        finding['assessment'] = {
            'status': status, 'coverage_complete': bool(coverage_complete), 'stability': states,
            'stability_complete': stable, 'mutation_comparisons_complete': mutations_complete,
            'distinguishing_pairs': differences,
            'meaning': 'Pairwise sampled fault evidence; not semantic equivalence or proof about a combined union.',
            'automatic_removal_safe': False,
        }


def select_candidates(report, limit):
    """Select whole findings first, then useful pairs for oversized identical groups.

    Greedy priority balances new test modules, measured duration, and shared arcs.
    A combined finding is indivisible; omitted members remain explicitly unchecked.
    """
    tests = {t['nodeid']: t for t in report['tests']}
    wanted = {n for f in report['findings'] for n in members(f)}
    units = []
    for index, finding in enumerate(report['findings']):
        ids = members(finding)
        if len(ids) >= 2:
            units.append((index, ids))
        if finding['kind'] == 'identical' and len(ids) > limit and limit >= 2:
            # A bounded set of pairs avoids quadratic memory for large groups.
            ranked = sorted(ids, key=lambda n: (-tests[n]['duration'], n))
            units.extend((index, [ranked[0], n]) for n in ranked[1:])
    selected, reasons, modules = set(), [], set()
    while True:
        available = [(i, ids) for i, ids in units
                     if set(ids) - selected and len(selected | set(ids)) <= limit]
        if not available:
            break
        def priority(unit):
            i, ids = unit
            added = set(ids) - selected
            new_modules = {tests[n]['location']['file'] for n in added} - modules
            return (-len(new_modules), -sum(tests[n]['duration'] for n in added),
                    -report['findings'][i]['shared_arc_count'], len(added), tuple(ids), i)
        i, ids = min(available, key=priority)
        selected.update(ids)
        modules.update(tests[n]['location']['file'] for n in ids)
        reasons.append({'finding_index': i, 'tests': ids, 'reason': 'complete comparison unit; module diversity, duration, overlap'})
    return {'strategy': 'comparison_units', 'limit': limit, 'selected': [t['nodeid'] for t in report['tests'] if t['nodeid'] in selected],
            'unchecked': sorted(wanted - selected), 'reasons': reasons,
            'findings': [{'index': i, 'complete': set(members(f)) <= selected,
                          'unchecked': sorted(set(members(f)) - selected)}
                         for i, f in enumerate(report['findings'])]}

#!/usr/bin/env python
import argparse
from contextlib import redirect_stdout
import dis
import json
from pathlib import Path
import time
import inspect
import logging
import os
import sys
from dataclasses import dataclass
from types import CodeType
from typing import Optional

import pytest
from coverage import Coverage
from coverage.exceptions import ConfigError, CoverageException

Arc = tuple[int, int]
Location = tuple[str, Optional[int], str]


@dataclass
class TestCoverage:
    """
    A class that represents the test coverage of a set of files.

    Attributes:
        tests_locations: A list of Location objects that indicate where the tests are located.
        file_arcs: A dictionary that maps filenames to sets of Arc objects that represent the executed arcs in each file.

    >>> loc1 = Location(("test1.py", 10, "test1")) # A Location object with filename, start line and function name
    >>> loc2 = Location(("test2.py", 20, "test2"))
    >>> arc1 = Arc((1, 2)) # An Arc object with source and destination line numbers
    >>> arc2 = Arc((2, 3))
    >>> arc3 = Arc((3, 4))
    >>> arc4 = Arc((4, 5))
    >>> tc1 = TestCoverage([loc1], {"file1.py": {arc1, arc2}, "file2.py": {arc3}})
    >>> tc2 = TestCoverage([loc2], {"file1.py": {arc2, arc4}, "file3.py": {arc4}})
    >>> len(tc1) # The number of arcs in the test coverage
    3
    >>> TestCoverage.union(tc1, tc2) # The union of two test coverages
    TestCoverage(tests_locations=[], file_arcs={'file1.py': {(2, 3), (4, 5), (1, 2)}, 'file2.py': {(3, 4)}, 'file3.py': {(4, 5)}})
    >>> tc1.issubset(tc2) # Check if one test coverage is a subset of another
    False
    >>> tc1 & tc2 # The intersection of two test coverages
    TestCoverage(tests_locations=[], file_arcs={'file1.py': {(2, 3)}})
    >>> bool(tc1 & tc2)
    True
    >>> tc1 - tc2 # The difference of two test coverages
    TestCoverage(tests_locations=[], file_arcs={'file1.py': {(1, 2)}, 'file2.py': {(3, 4)}})
    >>> bool(tc1 - tc2)
    True
    """

    tests_locations: list[Location]
    file_arcs: dict[str, set[Arc]]

    def __len__(self):
        """
        Return the number of arcs in the test coverage.

        >>> tc = TestCoverage([], {"file1.py": {Arc((1, 2)), Arc((2, 3))}, "file2.py": {Arc((3, 4))}})
        >>> len(tc)
        3
        """
        return sum(map(len, self.file_arcs.values()))

    @staticmethod
    def union(*obj_list):
        """
        Return a new TestCoverage object that is the union of the given objects.

        >>> tc1 = TestCoverage([], {"file1.py": {Arc((1, 2)), Arc((2, 3))}, "file2.py": {Arc((3, 4))}})
        >>> tc2 = TestCoverage([], {"file1.py": {Arc((2, 3)), Arc((4, 5))}, "file3.py": {Arc((5, 6))}})
        >>> tc3 = TestCoverage([], {"file4.py": {Arc((6, 7))}})
        >>> tc_union = TestCoverage.union(tc1, tc2, tc3)
        >>> tc_union.file_arcs == {"file1.py": {Arc((1, 2)), Arc((2, 3)), Arc((4, 5))}, "file2.py": {Arc((3, 4))}, "file3.py": {Arc((5, 6))}, "file4.py": {Arc((6, 7))}}
        True
        """
        result_dict = {}
        for obj in obj_list:
            for filename, arcs_set in obj.file_arcs.items():
                if filename in result_dict:
                    result_dict[filename] |= arcs_set
                else:
                    result_dict[filename] = arcs_set.copy()
        return TestCoverage([], result_dict)

    def issubset(self, other):
        """
        Check if this test coverage is a subset of another test coverage.

        >>> tc1 = TestCoverage([], {"file1.py": {Arc((1, 2)), Arc((2, 3))}, "file2.py": {Arc((3, 4))}})
        >>> tc2 = TestCoverage([], {"file1.py": {Arc((1, 2)), Arc((2, 3)), Arc((4, 5))}, "file2.py": {Arc((3, 4))}, "file3.py": {Arc((5, 6))}})
        >>> tc1.issubset(tc2)
        True
        >>> tc2.issubset(tc1)
        False
        >>> tc2.issubset(tc2)
        True
        >>> tc3 = TestCoverage([], {"file1.py": {Arc((1, 2)), Arc((2, 3))}, "file2.py": {Arc((3, 4))}, "file5.py": {Arc((6, 7))}})
        >>> tc3.issubset(tc2)
        False
        >>> tc4 = TestCoverage([], {})
        >>> tc4.issubset(tc2)
        True
        >>> tc2.issubset(tc4)
        False
        >>> tc4.issubset(tc4)
        True
        """
        return all(file_set.issubset(other.file_arcs.get(filename, set()))
                   for filename, file_set in self.file_arcs.items())

    def __and__(self, other):
        """
        Return a new TestCoverage object that is the intersection of this and another test coverage.

        >>> tc1 = TestCoverage([], {"file1.py": {Arc((1, 2)), Arc((2, 3))}, "file2.py": {Arc((3, 4))}, "file4.py": {Arc((3, 4))}})
        >>> tc2 = TestCoverage([], {"file1.py": {Arc((2, 3)), Arc((4, 5))}, "file3.py": {Arc((5, 6))}, "file4.py": {Arc((1, 2))}})
        >>> tc_and = tc1 & tc2
        >>> tc_and.file_arcs
        {'file1.py': {(2, 3)}}
        >>> bool(tc_and)
        True
        >>> bool(TestCoverage([], {}))
        False
        """
        result_dict = {filename: and_
                       for filename, file_set in self.file_arcs.items()
                       if filename in other.file_arcs and (and_ := file_set & other.file_arcs[filename])}
        return TestCoverage([], result_dict)

    def __sub__(self, other):
        """
        Return a new TestCoverage object that is the difference of this and another test coverage.

        >>> tc1 = TestCoverage([], {"file1.py": {Arc((1, 2)), Arc((2, 3))}, "file2.py": {Arc((3, 4))}})
        >>> tc2 = TestCoverage([], {"file1.py": {Arc((2, 3)), Arc((4, 5))}, "file3.py": {Arc((5, 6))}})
        >>> tc_sub = tc1 - tc2
        >>> tc_sub.file_arcs == {"file1.py": {Arc((1, 2))}, "file2.py": {Arc((3, 4))}}
        True
        """
        result_dict = {filename: sub
                       for filename, file_set in self.file_arcs.items()
                       if (sub := file_set - other.file_arcs.get(filename, set()))}
        return TestCoverage([], result_dict)


def coverage_signature(file_arcs):
    """An exact, order-independent key including file identity and executed arcs."""
    return tuple(sorted((filename, tuple(sorted(arcs)))
                        for filename, arcs in file_arcs.items() if arcs))


class FindDuplicateCoverage:
    def __init__(self, source=(), omit=(), collector="contexts", selected=None, order=None, coverage_phase="all"):
        self.coverage_phase = coverage_phase
        self.phase_contexts = {}
        self.groups = {}
        self.observations = []
        self.test_lines = {}
        self.reports = []
        self.errors = []
        self.location = None
        self.nodeid = None
        self.source = [Path(path).resolve() for path in source]
        self.collector = collector
        self.selected = selected
        self.order = order
        self.running = False
        self.seen_nodeids = set()
        self.coverage = Coverage(branch=True, data_file=None)
        # sysmon (the Python 3.14 default) cannot switch test contexts and
        # does not provide the same complete arcs as the tracing cores.
        try:
            self.coverage.set_option("run:core", "ctrace")
        except ConfigError:
            # coverage < 7.9 has no public core option and defaults to ctrace.
            if os.environ.get("COVERAGE_CORE") == "sysmon":
                raise pytest.UsageError("Remove COVERAGE_CORE=sysmon: full per-test arcs require a tracing core")
        configured_omit = self.coverage.get_option("run:omit") or []
        self.coverage.set_option("run:omit", [*configured_omit, *omit,
                                 str(Path(__file__).with_name('pytest_deduplicate*.py'))])
        if self.source:
            self.coverage.set_option("run:source", sorted({str(p if p.is_dir() else p.parent)
                                                          for p in self.source}))
        # Context labels belong to this collector, not application configuration.
        self.coverage.set_option("run:context", "")
        self.coverage.set_option("run:dynamic_context", None)
        self.coverage.set_option("run:relative_files", False)

    def pytest_configure(self, config):
        if getattr(config.option, "numprocesses", 0) or getattr(config.option, "dist", "no") != "no":
            raise pytest.UsageError("pytest_deduplicate requires a serial run; distributed workers are not aggregated")
        if getattr(config.option, "cov_source", None) and not getattr(config.option, "no_cov", False):
            raise pytest.UsageError("Use pytest_deduplicate without --cov; simultaneous collectors are unsupported")

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items, config):
        # Exclude all collected test bodies, including those deselected by a check.
        def add_code(code):
            filename = os.path.abspath(code.co_filename)
            lines = self.test_lines.setdefault(filename, set())
            lines.update(line for _, line in dis.findlinestarts(code))
            for constant in code.co_consts:
                if isinstance(constant, CodeType):
                    add_code(constant)

        for item in items:
            obj = getattr(item, "obj", None)
            if obj is not None:
                code = getattr(inspect.unwrap(obj), "__code__", None)
                if code is not None:
                    add_code(code)
        if self.selected is not None:
            wanted = set(self.selected)
            deselected = [item for item in items if item.nodeid not in wanted]
            items[:] = [item for item in items if item.nodeid in wanted]
            config.hook.pytest_deselected(items=deselected)
            missing = wanted - {item.nodeid for item in items}
            if missing:
                raise pytest.UsageError("Check could not collect: " + ", ".join(sorted(missing)))
        if self.order:
            ranks = {nodeid: i for i, nodeid in enumerate(self.order)}
            items.sort(key=lambda item: ranks.get(item.nodeid, len(ranks)))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        if item.nodeid in self.seen_nodeids:
            raise pytest.UsageError("Repeated node IDs/retry plugins are unsupported: " + item.nodeid)
        self.seen_nodeids.add(item.nodeid)
        file, line, _ = item.location
        self.nodeid = item.nodeid
        self.location = (file, line, item.nodeid.split("::", 1)[-1])
        self.reports = []
        self.phase_contexts = {}
        started = False
        try:
            if self.collector != "off":
                if self.collector == "restart":
                    self.coverage.erase()
                if not self.running:
                    self.coverage.start()
                    self.running = True
                if self.collector == "contexts":
                    self.coverage.switch_context(item.nodeid)
                started = True
        except Exception as exc:
            self.errors.append(str(exc))
            logging.exception("Unable to start coverage")
        try:
            yield
        finally:
            phases = {r.when: {"outcome": r.outcome, "duration": r.duration,
                              "xfail": hasattr(r, "wasxfail")} for r in self.reports}
            passed = (set(phases) == {"setup", "call", "teardown"}
                      and all(p["outcome"] == "passed" and not p["xfail"] for p in phases.values()))
            observation = {"nodeid": item.nodeid,
                           "location": {"file": file, "line": (line + 1) if line is not None else 1},
                           "phases": phases, "eligible": passed,
                           "duration": sum(r.duration for r in self.reports), "file_arcs": {}}
            try:
                if started:
                    if self.collector == "restart":
                        self.coverage.stop()
                        self.running = False
                    observation['phase_file_arcs'] = {
                        phase: self.collect_coverage(False, self.phase_contexts.get(phase, '__unmeasured__'))
                        for phase in ('setup', 'call', 'teardown')}
                    if self.coverage_phase == 'call':
                        observation['file_arcs'] = observation['phase_file_arcs']['call']
                    else:
                        observation["file_arcs"] = self.collect_coverage(passed)
            except Exception as exc:
                self.errors.append(str(exc))
                logging.exception("Unable to process coverage")
                observation["eligible"] = False
            finally:
                if started and self.collector == "contexts":
                    self.coverage.switch_context("")
                self.observations.append(observation)
                self.location = None

    def phase_context(self, phase):
        if self.running:
            # JSON encoding avoids collisions with arbitrary parameterized node IDs.
            context = json.dumps([self.nodeid, phase], separators=(',', ':'))
            self.phase_contexts[phase] = context
            self.coverage.switch_context(context)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_setup(self, item):
        self.phase_context('setup')
        yield
        if self.running:
            self.coverage.switch_context(self.nodeid)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_call(self, item):
        self.phase_context('call')
        yield
        if self.running:
            self.coverage.switch_context(self.nodeid)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        self.phase_context('teardown')
        yield
        if self.running:
            self.coverage.switch_context(self.nodeid)

    def pytest_sessionfinish(self, session, exitstatus):
        self.close()

    def close(self):
        if self.running:
            self.coverage.stop()
            self.running = False

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        self.reports.append(outcome.get_result())

    def collect_coverage(self, eligible=True, context=None):
        import re
        data = self.coverage.get_data()
        if context is not None:
            data.set_query_context(context)
        elif self.collector == "contexts":
            data.set_query_contexts(['^' + re.escape(c) + '$'
                                    for c in [self.nodeid, *self.phase_contexts.values()]])
        file_arcs = {}
        try:
            for filename in sorted(data.measured_files()):
                path = Path(filename).resolve()
                if self.source and not any(path == root or root in path.parents for root in self.source):
                    continue
                excluded = self.test_lines.get(os.path.abspath(filename), set())
                arcs = {arc for arc in data.arcs(filename) or []
                        if not any(abs(line) in excluded for line in arc)}
                if arcs:
                    file_arcs[filename] = arcs
        finally:
            data.set_query_contexts(None)
        if eligible and file_arcs:
            signature = coverage_signature(file_arcs)
            if signature in self.groups:
                self.groups[signature].tests_locations.append(self.location)
            else:
                self.groups[signature] = TestCoverage([self.location], file_arcs)
        return file_arcs


def find_fully_overlapped_sets(list_of_sets: list[TestCoverage]) -> list[tuple[TestCoverage, list[TestCoverage]]]:
    """Returns a list of sets that are fully overlapped by multiple sets."""
    sorted_sets = sorted((cov for cov in list_of_sets if cov), key=len, reverse=True)
    from pytest_deduplicate_index import ArcIndex
    inverted = ArcIndex(sorted_sets)
    fully_overlapped_sets = []
    for index, big_set in enumerate(sorted_sets):
        # Only genuinely smaller observations belong in this report.
        candidates = [sorted_sets[i] for i in inverted.overlapping_smaller(index)]
        remaining = big_set
        small_sets = []
        for candidate in candidates:
            if not remaining:
                break
            if remaining & candidate:
                remaining = remaining - candidate
                small_sets.append(candidate)
        if not remaining:
            fully_overlapped_sets.append((big_set, small_sets))
    return fully_overlapped_sets


def report_path(path):
    path = Path(path).resolve()
    try:
        return os.path.relpath(path, Path.cwd().resolve())
    except ValueError:
        # Windows has no relative path between different drives.
        return str(path)


def serialize_arcs(file_arcs):
    return {report_path(path): [list(arc) for arc in sorted(arcs)]
            for path, arcs in sorted(file_arcs.items()) if arcs}


def build_report(plugin, exit_code, elapsed):
    tests = []
    groups = {}
    for observation in plugin.observations:
        test = dict(observation, file_arcs=serialize_arcs(observation["file_arcs"]))
        if 'phase_file_arcs' in observation:
            test['phase_file_arcs'] = {phase: serialize_arcs(arcs) if arcs is not None else None
                                       for phase, arcs in observation['phase_file_arcs'].items()}
        test["arc_count"] = sum(map(len, test["file_arcs"].values()))
        tests.append(test)
        if observation["eligible"] and observation["file_arcs"]:
            key = coverage_signature(observation["file_arcs"])
            groups.setdefault(key, []).append(observation)
    representatives = [CoverageGroup(members) for members in groups.values()]
    findings = []

    def finding(kind, left, right, left_tests, right_tests):
        shared = left & right
        findings.append({"kind": kind, "tests": left_tests, "other_tests": right_tests,
                         "shared": serialize_arcs(shared.file_arcs),
                         "unique": serialize_arcs((left - right).file_arcs),
                         "other_unique": serialize_arcs((right - left).file_arcs),
                         "shared_arc_count": len(shared), "unique_arc_count": len(left - right),
                         "other_unique_arc_count": len(right - left)})

    for group in representatives:
        if len(group.ids) > 1:
            finding("identical", group.coverage, group.coverage, group.ids, [])
    from pytest_deduplicate_index import ArcIndex
    inverted = ArcIndex([group.coverage for group in representatives])
    for left_index, right_index in inverted.containment_pairs():
        left, right = representatives[left_index], representatives[right_index]
        finding("contained", left.coverage, right.coverage, left.ids, right.ids)
    by_identity = {id(group.coverage): group for group in representatives}
    for big, small in find_fully_overlapped_sets([group.coverage for group in representatives]):
        finding("combined", big, TestCoverage.union(*small), by_identity[id(big)].ids,
                [by_identity[id(cov)].ids[0] for cov in small])
    return {"schema_version": 1, "root": os.getcwd(), "collector": plugin.collector,
            "pytest_exit_code": int(exit_code), "elapsed": elapsed, "errors": plugin.errors,
            "scope": {"coverage_phase": plugin.coverage_phase, "source": [report_path(p) for p in plugin.source],
                      "omit": plugin.coverage.get_option("run:omit")},
            "warning": "Coverage overlap candidates only; matching coverage does not prove equivalent assertions.",
            "tests": tests, "findings": findings}


class CoverageGroup:
    def __init__(self, observations):
        self.ids = [item["nodeid"] for item in observations]
        self.coverage = TestCoverage([], observations[0]["file_arcs"])


def print_report(report):
    print(report["warning"])
    tests = {test["nodeid"]: test for test in report["tests"]}
    codes = {"identical": "W001", "combined": "W002", "contained": "W003"}
    for finding in report["findings"]:
        for nodeid in finding["tests"]:
            test = tests[nodeid]
            location = test["location"]
            print(f"{location['file']}:{location['line']}:1: {codes[finding['kind']]} {nodeid}: "
                  f"{finding['kind']} observed coverage; review assertions and inputs "
                  f"({test['duration']:.6f}s, {test['arc_count']} arcs)")
        print("  Assessment: " + finding.get("assessment", {}).get("status", "unchecked"))
        if finding["other_tests"]:
            print("  Compared with: " + ", ".join(finding["other_tests"]))
        print(f"  Shared: {finding['shared_arc_count']} arcs; unique: {finding['unique_arc_count']}; "
              f"other unique: {finding['other_unique_arc_count']}")
        print("  Files: " + ", ".join(sorted(set(finding["shared"]) | set(finding["unique"]) | set(finding["other_unique"]))))
    if "stability" in report:
        for nodeid, result in report["stability"]["tests"].items():
            print(f"Stability: {nodeid}: {result['status']}")
        print(f"Stability: {len(report['stability']['unchecked'])} candidates unchecked (limit)")
    if "mutations" in report:
        result = report["mutations"]
        print(f"Mutation sample: {result.get('status', 'error')}; {len(result['mutants'])} mutants")
        for comparison in result["comparisons"]:
            print("  " + ", ".join(comparison["tests"]) + ": " + comparison["status"])
    if "benchmark" in report:
        result = report["benchmark"]
        print("Collector benchmark medians (seconds): " + json.dumps(result["median_seconds"], sort_keys=True))
        print("Coverage/outcome parity: " + str(result["coverage_and_outcome_parity"]))
    if "checks" in report:
        print("Optional checks: " + report["checks"]["reason"])
    if report["errors"]:
        print("Coverage analysis incomplete: " + "; ".join(report["errors"]), file=sys.stderr)


def parse_args(args):
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False,
                                     description="Review observed test coverage overlap")
    parser.add_argument("--deduplicate-help", action="help", help="show analyzer options (pytest retains --help)")
    parser.add_argument("--source", action="append", default=[], metavar="PATH", help="application file/directory; repeatable")
    parser.add_argument("--omit", action="append", default=[], metavar="GLOB", help="exclude measured files; repeatable")
    parser.add_argument("--json", metavar="PATH", help="write JSON report; - writes only JSON to stdout")
    parser.add_argument('--coverage-phase', choices=['all', 'call'], default='all',
                        help='compare all observed phases or test call only')
    parser.add_argument("--collector", choices=["restart", "contexts"], default="contexts")
    parser.add_argument("--stability-runs", type=int, default=0, metavar="N")
    parser.add_argument("--mutations", type=int, default=0, metavar="N", help="experimental maximum number of sampled mutants")
    parser.add_argument('--mutation-repeats', type=int, default=2, help='fresh copies per mutant/test (at least 2)')
    parser.add_argument('--mutation-snapshot-mb', type=int, default=256, help='maximum project snapshot size')
    parser.add_argument("--max-candidates", type=int, default=20)
    parser.add_argument("--check-timeout", type=float, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--benchmark-collectors", type=int, default=0, metavar="N")
    parser.add_argument('--html', metavar='PATH', help='standalone interactive report')
    parser.add_argument('--baseline', metavar='PATH', help='compare with a prior JSON report')
    parser.add_argument('--suppressions', metavar='PATH', help='reviewed findings with reason and evidence hash')
    parser.add_argument('--review-template', metavar='PATH', help='write an unreviewed suppression template')
    parser.add_argument('--import-coverage', metavar='PATH', help='read combined pytest-cov data without running tests')
    parser.add_argument('--outcomes', metavar='PATH', help='coverage-bound companion manifest')
    parser.add_argument("--_request", help=argparse.SUPPRESS)
    options, pytest_args = parser.parse_known_args(args)
    if min(options.stability_runs, options.mutations, options.benchmark_collectors) < 0:
        parser.error("check counts must be nonnegative")
    if options.mutation_repeats < 2 or options.mutation_snapshot_mb < 1:
        parser.error('mutation-repeats must be at least 2; snapshot limit must be positive')
    if options.max_candidates < 1 or not 0 < options.check_timeout < float("inf"):
        parser.error("max-candidates and check-timeout must be positive and finite")
    if bool(options.import_coverage) != bool(options.outcomes):
        parser.error('--import-coverage and --outcomes must be supplied together')
    if options.import_coverage and (options.stability_runs or options.mutations or options.benchmark_collectors or pytest_args):
        parser.error('import accepts analysis options only; rerun checks on a live baseline')
    for path in options.source:
        if not Path(path).exists():
            parser.error("source does not exist: " + path)
    if options.mutations and not options.source:
        parser.error("--mutations requires explicit --source paths")
    if options.mutations and any(not Path(p).resolve().is_relative_to(Path.cwd().resolve()) for p in options.source):
        parser.error("mutation source must be inside the current project directory")
    return options, pytest_args


def main(args=None):
    options, pytest_args = parse_args(sys.argv[1:] if args is None else args)
    selected = order = None
    if options._request:
        request = json.loads(Path(options._request).read_text())
        pytest_args = request["pytest_args"]
        options.source = request["source"]
        options.omit = request["omit"]
        options.collector = request["collector"]
        options.coverage_phase = request.get('coverage_phase', 'all')
        options.json = request["output"]
        selected, order = request.get("selected"), request.get("order")
    started = time.perf_counter()
    plugin = FindDuplicateCoverage(options.source, options.omit, options.collector, selected, order, options.coverage_phase)
    imported = None
    try:
        if options.import_coverage:
            from pytest_deduplicate_import import import_coverage
            try:
                imported = import_coverage(plugin, options.import_coverage, options.outcomes)
                exit_code = 0
            except (OSError, ValueError, KeyError, TypeError, CoverageException) as exc:
                plugin.observations.clear()
                plugin.errors.append('Coverage import failed: ' + str(exc))
                exit_code = 2
        else:
            with redirect_stdout(sys.stderr if options.json == "-" else sys.stdout):
                exit_code = pytest.main(pytest_args, plugins=[plugin])
    finally:
        plugin.close()
    report = build_report(plugin, exit_code, time.perf_counter() - started)
    if imported:
        report['import'] = imported
    if not options._request and (options.stability_runs or options.mutations or options.benchmark_collectors):
        from pytest_deduplicate_checks import run_checks
        try:
            run_checks(report, options, pytest_args)
        except (OSError, ValueError) as exc:
            report["errors"].append("Optional check failed: " + str(exc))
    from pytest_deduplicate_review import assess_findings
    assess_findings(report)
    from pytest_deduplicate_artifacts import decorate, compare_reports, apply_reviews, review_template, write_html
    decorate(report)
    try:
        if options.baseline:
            report['comparison'] = compare_reports(report, json.loads(Path(options.baseline).read_text()))
        if options.suppressions:
            apply_reviews(report, json.loads(Path(options.suppressions).read_text()))
        if options.review_template:
            Path(options.review_template).write_text(json.dumps(review_template(report), indent=2) + '\n')
    except (OSError, ValueError, KeyError, TypeError, CoverageException) as exc:
        report['errors'].append('Report review failed: ' + str(exc))
        assess_findings(report)
    report["exit_code"] = int(exit_code) or (1 if report["errors"] else 0)
    if options.html:
        write_html(report, options.html)
    if options.json:
        content = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if options.json == "-":
            print(content, end="")
        else:
            Path(options.json).write_text(content)
    if options.json != "-" and not options._request:
        print_report(report)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())

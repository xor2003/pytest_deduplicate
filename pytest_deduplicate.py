#!/usr/bin/env python
import dis
import inspect
import logging
import os
import sys
from dataclasses import dataclass
from types import CodeType
from typing import Optional

import pytest
from coverage import Coverage

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
    def __init__(self) -> None:
        self.groups = {}
        self.test_lines = {}
        self.reports = []
        self.errors = []
        self.location = None
        self.coverage = Coverage(branch=True, data_file=None,
                                 omit=os.path.abspath(__file__))

    def pytest_collection_modifyitems(self, items):
        # Exclude collected test bodies, retaining helpers in the same module.
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
                obj = inspect.unwrap(obj)
                code = getattr(obj, "__code__", None)
                if code is not None:
                    add_code(code)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        file, line, name = item.location
        self.location = (file, line, item.nodeid.split("::", 1)[-1])
        self.reports = []
        started = False
        try:
            self.coverage.erase()
            self.coverage.start()
            started = True
        except Exception as exc:
            self.errors.append(str(exc))
            logging.exception("Unable to start coverage")
        try:
            yield
        finally:
            if started:
                try:
                    self.coverage.stop()
                    # Failed, skipped, xfailed and incomplete runs are not candidates.
                    if ({r.when for r in self.reports} == {"setup", "call", "teardown"}
                            and all(r.passed and not hasattr(r, "wasxfail")
                                    for r in self.reports)):
                        self.collect_coverage()
                except Exception as exc:
                    self.errors.append(str(exc))
                    logging.exception("Unable to process coverage")
            self.location = None

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        self.reports.append(outcome.get_result())

    def collect_coverage(self):
        data = self.coverage.get_data()
        file_arcs = {}
        for filename in sorted(data.measured_files()):
            excluded = self.test_lines.get(os.path.abspath(filename), set())
            arcs = {arc for arc in data.arcs(filename) or []
                    if not any(abs(line) in excluded for line in arc)}
            if arcs:
                file_arcs[filename] = arcs
        if not file_arcs:
            logging.warning("No comparable coverage for %s", self.location)
            return
        signature = coverage_signature(file_arcs)
        if signature in self.groups:
            self.groups[signature].tests_locations.append(self.location)
        else:
            self.groups[signature] = TestCoverage([self.location], file_arcs)


def find_fully_overlapped_sets(list_of_sets: list[TestCoverage]) -> list[tuple[TestCoverage, list[TestCoverage]]]:
    """Returns a list of sets that are fully overlapped by multiple sets."""
    sorted_sets = sorted((cov for cov in list_of_sets if cov), key=len, reverse=True)
    fully_overlapped_sets = []
    for index, big_set in enumerate(sorted_sets):
        # Only genuinely smaller observations belong in this report.
        candidates = [cov for cov in sorted_sets[index + 1:] if len(cov) < len(big_set)]
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


def main(args=None):
    my_plugin = FindDuplicateCoverage()
    exit_code = pytest.main(sys.argv[1:] if args is None else args, plugins=[my_plugin])
    hash_tests = my_plugin.groups
    print("Coverage overlap candidates only; matching coverage does not prove equivalent assertions.")

    for tests in hash_tests.values():
        if len(tests.tests_locations) == 1:
            continue
        print("1. Tests with identical observed coverage:")
        for item in sorted(tests.tests_locations):
            file, line, name = item
            print(
                f"{file}:{(line + 1) if line is not None else 1}:1: W001 tests with same coverage: {name} review assertions and inputs (identical-coverage)",
            )
        print("\n")

    for big_test, small_tests in find_fully_overlapped_sets(
            [TestCoverage(cov.tests_locations, cov.file_arcs) for cov in hash_tests.values()]):
        print('\n2. Coverage collectively contained in smaller observations:')
        bigger_filename, bigger_linenum, bigger_test_name = big_test.tests_locations[0]
        print(
            f"{bigger_filename}:{(bigger_linenum + 1) if bigger_linenum is not None else 1}:1: W002 test {bigger_test_name} has observed coverage contained in the union below (combined-coverage)",
        )
        for item in small_tests:
            smaller_filename, smaller_linenum, smaller_name = item.tests_locations[0]
            print(
                f"{smaller_filename}:{(smaller_linenum + 1) if smaller_linenum is not None else 1}:1: I002 test {smaller_name} covers part of {bigger_test_name} test (smaller-test)",
            )
        print("\n")

    for coverage_hash2, tests2 in hash_tests.items():
        items = []
        for coverage_hash1, tests1 in hash_tests.items():
            if coverage_hash1 != coverage_hash2 and \
                    set(tests2.file_arcs.keys()) >= set(tests1.file_arcs.keys()) and \
                    all(arcs2_arcs >= tests1.file_arcs.get(arcs2_filename, set()) \
                        for arcs2_filename, arcs2_arcs in tests2.file_arcs.items()):
                items.extend(tests1.tests_locations)
        if not items:
            continue

        print("\n3. Tests with contained observed coverage:")
        bigger_filename, bigger_linenum, bigger_test_name = tests2.tests_locations[0]
        print(
            f"{bigger_filename}:{(bigger_linenum + 1) if bigger_linenum is not None else 1}:1: I003 test {bigger_test_name} has observed coverage containing test(s) below (bigger-coverage)",
        )
        for item in sorted(items):
            smaller_filename, smaller_linenum, smaller_name = item
            print(
                f"{smaller_filename}:{(smaller_linenum + 1) if smaller_linenum is not None else 1}:1: W003 test {smaller_name} has observed coverage contained in {bigger_test_name}; review assertions and inputs (contained-coverage)",
            )
        print("\n")

    if my_plugin.errors:
        print("Coverage analysis incomplete: " + "; ".join(my_plugin.errors), file=sys.stderr)
        return int(exit_code) or 1
    return int(exit_code)


if __name__ == "__main__":
    sys.exit(main())

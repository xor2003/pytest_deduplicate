#!/usr/bin/env python
import logging
import os
import sys
from copy import copy
from dataclasses import dataclass
from typing import Tuple, Optional

import pytest
from _pytest.unittest import TestCaseFunction
from coverage import Coverage
from coverage.data import add_data_to_hash
from coverage.misc import Hasher

# from line_profiler_pycharm import profile

Arc = tuple[int, int]
Location = tuple[str, Optional[int], str]

@dataclass
class TestCoverage:
    """
    A class that represents the test coverage of a set of files.

    Attributes:
        tests_locations: A list of Location objects that indicate where the tests are located.
        file_arcs: A dictionary that maps filenames to sets of Arc objects that represent the executed arcs in each file.

    >>> loc1 = Location(("test1.py", 10, "test1")) # A Location object with filename, start line and end line
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
        result_dict = {filename: file_set & other.file_arcs[filename]
                       for filename, file_set in self.file_arcs.items()
                       if filename in other.file_arcs and file_set & other.file_arcs[filename]}
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
        result_dict = {filename: file_set - other.file_arcs.get(filename, set())
                       for filename, file_set in self.file_arcs.items()}
        return TestCoverage([], result_dict)


hash_tests: dict[str, TestCoverage] = {}


class FindDuplicateCoverage:
    def __init__(self) -> None:
        self.collected = []  # list to store collected test names
        self.location = None  # the name of the current test
        self.coverage = None  # Coverage object to measure code coverage
        self.skipped = False  # flag to track if the test is skipped
        self.coverage = Coverage(branch=True, data_file=None,
                                 omit=os.path.basename(__file__))  # initialize the Coverage object with branch coverage
        # self.coverage = copy(self._coverage)

    # @profile
    def pytest_collection_modifyitems(self, items: list) -> None:
        # append test name to the collected list
        self.collected = [item.name for item in items if isinstance(item, TestCaseFunction)]

    # @profile
    def pytest_runtest_logstart(self, nodeid: str, location: Location) -> None:
        # logging.debug("Start test %s", nodeid)
        self.location = location  # set the name of the current test

    # @profile
    def start_collection(self) -> None:
        try:
            # logging.debug("Coverage created")
            self.coverage.erase()  # start the coverage measurement
            self.coverage.start()  # start the coverage measurement
        except:
            self.coverage = None

    # @profile
    def pytest_report_teststatus(self, report) -> None:
        # logging.debug("pytest_report_teststatus %s", report)
        if report.when == "setup":
            self.start_collection()
        elif report.when == "call":
            self.skipped = report.outcome == "skipped"  # set skipped flag based on test outcome
            logging.debug("Skipped %s", self.skipped)
        elif report.when == "teardown":
            self.stop_collection()

    # @profile
    def pytest_runtest_logfinish(self, nodeid, location):
        logging.debug("Stop test %s", nodeid)

    # @profile
    def stop_collection(self):
        if self.coverage:
            try:
                self.coverage.stop()
                logging.debug("Coverage stopped")
            except Exception as ex:
                logging.exception("Exception %s", ex.args())
        if self.coverage and not self.skipped:
            try:
                data = self.coverage.get_data()
                hasher = Hasher()  # Hasher object to hash the coverage data
                arcs_list = {}
                for file_name in data.measured_files():
                    if os.path.basename(file_name).startswith("test_"):
                        continue
                    logging.debug(file_name)
                    add_data_to_hash(data, file_name, hasher)
                    arcs_list[file_name] = set(data.arcs(file_name))
                if not arcs_list:
                    logging.warning("Empty arcs for %s %s", self.location, arcs_list)
                    return
                text_hash = hasher.hexdigest()

                logging.debug(text_hash)
                if text_hash in hash_tests:
                    hash_tests[text_hash].tests_locations.append(self.location)
                else:
                    hash_tests[text_hash] = TestCoverage(tests_locations=[self.location], file_arcs=arcs_list)
                logging.debug("Coverage collected")

            except Exception as ex:
                logging.exception("Exception %s", ex.args())
        self.location = None
        self.skipped = False



    
def find_fully_overlapped_sets(list_of_sets: list[TestCoverage]) -> list[tuple[TestCoverage, list[TestCoverage]]]:
    """Returns a list of sets that are fully overlapped by multiple sets."""
    sorted_sets = sorted(list_of_sets, key=len, reverse=True)

    fully_overlapped_sets = []
    while (big_set := sorted_sets.pop(0)) and sorted_sets:
        if not big_set.issubset(TestCoverage.union(*sorted_sets)):
            continue
        big_set_ = copy(big_set)
        small_sets = []
        for i in range(len(sorted_sets) - 1, -1, -1):
            if not big_set_:
                break
            if big_set_ & sorted_sets[i]:
                big_set_ -= sorted_sets[i]
                small_sets.append(sorted_sets[i])

        fully_overlapped_sets.append((big_set, small_sets))
    return fully_overlapped_sets



# @profile
def main():
    my_plugin = FindDuplicateCoverage()
    pytest.main(sys.argv[1:], plugins=[my_plugin])

    # print("Hash size: ", len(hash_tests))
    print("Duplicates:")
    for tests in hash_tests.values():
        if len(tests.tests_locations) == 1:
            continue
        for item in sorted(tests.tests_locations):
            file, line, name = item
            print(
                f"{file}:{line}:1: W001 tests with same coverage: {name} consider leave only one (duplicate-test)",
            )
        print("\n")

    print("\nGod tests:")
    for big_test, small_tests in find_fully_overlapped_sets([TestCoverage(cov.tests_locations, cov.file_arcs) for cov in hash_tests.values()]):
        bigger_filename, bigger_linenum, bigger_test_name = big_test.tests_locations[0]
        print(
            f"{bigger_filename}:{bigger_linenum}:1: W002 test {bigger_test_name} can be splitted and replaced by smaller tests below (bigger-coverage)",
        )
        for item in small_tests:
            smaller_filename, smaller_linenum, smaller_name = item.tests_locations[0]
            print(
                f"{smaller_filename}:{smaller_linenum}:1: I002 test {smaller_name} covers part of {bigger_test_name} test (smaller-test)",
            )
        print("\n")

    print("\nSuperseeded:")
    for coverage_hash2, tests2 in hash_tests.items():
        items = []
        for coverage_hash1, tests1 in hash_tests.items():
            if coverage_hash1 != coverage_hash2 and \
                set(tests2.file_arcs.keys()) >= set(tests1.file_arcs.keys()) and \
                    all(arcs2_arcs >= tests1.file_arcs.get(arcs2_filename, set()) \
                        for arcs2_filename, arcs2_arcs in tests2.file_arcs.items()):
                items.extend(tests1.tests_locations)
        if items:
            bigger_filename, bigger_linenum, bigger_test_name = tests2.tests_locations[0]
            print(
                f"{bigger_filename}:{bigger_linenum}:1: I002 test {bigger_test_name} covers more code when test(s) below (bigger-coverage)",
            )
            for item in sorted(items):
                smaller_filename, smaller_linenum, smaller_name = item
                print(
                    f"{smaller_filename}:{smaller_linenum}:1: W003 test {smaller_name} covers less code when {bigger_test_name} test. Consider delete (smaller-coverage)",
                )
            print("\n")


if __name__ == "__main__":
    main()

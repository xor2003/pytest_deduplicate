#!/usr/bin/env python
import logging
import os
import sys
from copy import copy
from dataclasses import dataclass

import pytest
from _pytest.unittest import TestCaseFunction
from coverage import Coverage
from coverage.data import add_data_to_hash
from coverage.misc import Hasher

# from line_profiler_pycharm import profile

Arc = tuple[int, int]

@dataclass
class TestCoverage:

    test_names: list[str]
    file_arcs: dict[str, set[Arc]]

    def __len__(self):
        return sum(map(len, self.file_arcs.values()))

    @staticmethod
    def union(*obj_list):
        result_dict = {}
        for obj in obj_list:
            for filename, file_set in obj.file_arcs.items():
                if filename in result_dict:
                    result_dict[filename].update(file_set)
                else:
                    result_dict[filename] = file_set.copy()
        return TestCoverage(["Union"], result_dict)

    def issubset(self, other):
        return all(file_set.issubset(other.file_arcs.get(filename, set()))
                   for filename, file_set in self.file_arcs.items())

    def __and__(self, other):
        result_dict = {filename: file_set & other.file_arcs[filename]
                       for filename, file_set in self.file_arcs.items()
                       if filename in other.file_arcs}
        return TestCoverage(["Intersection"], result_dict)

    def __sub__(self, other):
        result_dict = {filename: file_set - other.file_arcs.get(filename, set())
                       for filename, file_set in self.file_arcs.items()}
        return TestCoverage(["Difference"], result_dict)

hash_tests: dict[str, TestCoverage] = {}


class FindDuplicateCoverage:
    def __init__(self) -> None:
        self.collected = []  # list to store collected test names
        self.name = None  # the name of the current test
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
    def pytest_runtest_logstart(self, nodeid: str, location: str) -> None:
        # logging.debug("Start test %s", nodeid)
        self.name = location  # set the name of the current test

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
                    logging.warning("Empty arcs for %s %s", self.name, arcs_list)
                    return
                text_hash = hasher.hexdigest()

                logging.debug(text_hash)
                if text_hash in hash_tests:
                    hash_tests[text_hash].test_names.append(self.name)
                else:
                    hash_tests[text_hash] = TestCoverage(test_names=[self.name], file_arcs=arcs_list)
                logging.debug("Coverage collected")

            except Exception as ex:
                logging.exception("Exception %s", ex.args())
        self.name = None
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
    print("\n\nDuplicates:")
    for tests in hash_tests.values():
        if len(tests.test_names) == 1:
            continue
        for item in sorted(tests.test_names):
            file, line, name = item
            print(
                f"{file}:{line}:1: W001 tests with same coverage: {name} (duplicate-test)",
            )
        print("\n")

    print("\n\nGod tests:")
    print(find_fully_overlapped_sets([TestCoverage(cov.test_names, cov.file_arcs) for cov in hash_tests.values()]))

    print("\n\nSuperseeded:")
    for coverage_hash2, tests2 in hash_tests.items():
        items = []
        for coverage_hash1, tests1 in hash_tests.items():
            if coverage_hash1 != coverage_hash2 and \
                set(tests2.file_arcs.keys()) >= set(tests1.file_arcs.keys()) and \
                    all(arcs2_arcs >= tests1.file_arcs.get(arcs2_filename, set()) \
                        for arcs2_filename, arcs2_arcs in tests2.file_arcs.items()):
                items.extend(tests1.test_names)
        if items:
            bigger_filename, bigger_linenum, bigger_test_name = tests2.test_names[0]
            print(
                f"{bigger_filename}:{bigger_linenum}:1: I002 test {bigger_test_name} covers more code when test(s) below (bigger-coverage)",
            )
            for item in sorted(items):
                smaller_filename, smaller_linenum, smaller_name = item
                print(
                    f"{smaller_filename}:{smaller_linenum}:1: W003 test {smaller_name} covers less code when {bigger_test_name} test (smaller-coverage)",
                )
            print("\n")


if __name__ == "__main__":
    main()

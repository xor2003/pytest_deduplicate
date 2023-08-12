#!/usr/bin/env python
import logging
import os
import sys

import pytest
from _pytest.unittest import TestCaseFunction
from coverage import Coverage
from coverage.data import add_data_to_hash
from coverage.misc import Hasher

# from line_profiler_pycharm import profile

hash_tests = {}
hash_arcs = {}


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
                    hash_tests[text_hash] += [self.name]
                else:
                    hash_tests[text_hash] = [self.name]
                    hash_arcs[text_hash] = arcs_list
                logging.debug("Coverage collected")

            except Exception as ex:
                logging.exception("Exception %s", ex.args())
        self.name = None
        self.skipped = False


# @profile
def main():
    my_plugin = FindDuplicateCoverage()
    pytest.main(sys.argv[1:], plugins=[my_plugin])

    # print("Hash size: ", len(hash_tests))
    print("\n\nSuperseeded:")
    for coverage_hash2, tests_names2 in hash_tests.items():
        items = []
        for coverage_hash1, tests_names1 in hash_tests.items():
            if coverage_hash1 != coverage_hash2 and \
                set(hash_arcs[coverage_hash2].keys()) >= set(hash_arcs[coverage_hash2].keys()) and \
                    all(arcs2_arcs >= hash_arcs[coverage_hash1].get(arcs2_filename, set()) \
                        for arcs2_filename, arcs2_arcs in hash_arcs[coverage_hash2].items()):
                items.extend(tests_names1)
        if items:
            bigger_filename, bigger_linenum, bigger_test_name = tests_names2[0]
            print(
                f"{bigger_filename}:{bigger_linenum}:1: I002 test {bigger_test_name} covers more code when test(s) below (bigger-coverage)",
            )
            for item in sorted(items):
                smaller_filename, smaller_linenum, smaller_name = item
                print(
                    f"{smaller_filename}:{smaller_linenum}:1: W003 test {smaller_name} covers less code when {bigger_test_name} test (smaller-coverage)",
                )
            print("\n")

    print("\n\nDuplicates:")
    for tests_names1 in hash_tests.values():
        if len(tests_names1) == 1:
            continue
        for item in sorted(tests_names1):
            file, line, name = item
            print(
                f"{file}:{line}:1: W001 tests with same coverage: {name} (duplicate-test)",
            )
        print("\n")

if __name__ == "__main__":
    main()

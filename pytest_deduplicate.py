#!/usr/bin/env python
import logging
import os
import sys

import pytest
from _pytest.unittest import TestCaseFunction
from coverage import Coverage
from coverage.data import add_data_to_hash
from coverage.misc import Hasher

hash_tests = {}
hash_arcs = {}


class FindDuplicateCoverage:
    def __init__(self) -> None:
        self.collected = []  # list to store collected test names
        self.name = None  # the name of the current test
        self.coverage = None  # Coverage object to measure code coverage
        self.hash = None  # Hasher object to hash the coverage data
        self.skipped = False  # flag to track if the test is skipped

    def pytest_collection_modifyitems(self, items: list) -> None:
        # append test name to the collected list
        self.collected = [item.name for item in items if isinstance(item, TestCaseFunction)]

    def pytest_runtest_logstart(self, nodeid: str, location: str) -> None:
        logging.debug("Start test %s", nodeid)
        self.name = location  # set the name of the current test

    def start_collection(self) -> None:
        try:
            self.hash = Hasher()
            logging.debug("Coverage created")
            self.coverage = Coverage(branch=True)  # initialize the Coverage object with branch coverage
            self.coverage.start()  # start the coverage measurement
        except:
            self.coverage = None

    def pytest_report_teststatus(self, report) -> None:
        logging.debug("pytest_report_teststatus %s", report)
        if report.when == "setup":
            self.start_collection()
        elif report.when == "call":
            self.skipped = report.outcome == "skipped"  # set skipped flag based on test outcome
            logging.debug("Skipped %s", self.skipped)
        elif report.when == "teardown":
            self.stop_collection()

    def pytest_runtest_logfinish(self, nodeid, location):
        logging.debug("Stop test %s", nodeid)

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
                arcs_list = []
                myself = os.path.basename(__file__)
                for file_name in data.measured_files():
                    if os.path.basename(file_name) != myself and not os.path.basename(
                        file_name,
                    ).startswith("test_"):
                        logging.debug(file_name)
                        logging.debug(data.lines(file_name))
                        add_data_to_hash(data, file_name, self.hash)
                        arcs_list += [set(data.arcs(file_name))]
                text_hash = self.hash.hexdigest()

                logging.debug(text_hash)
                if text_hash in hash_tests:
                    hash_tests[text_hash] += [self.name]
                else:
                    hash_tests[text_hash] = [self.name]
                    hash_arcs[text_hash] = arcs_list
                logging.debug("Coverage collected")

            except Exception as ex:
                logging.exception("Exception %s", ex.args())
        if self.coverage:
            try:
                self.coverage.erase()
                logging.debug("Coverage erased")
            except Exception as ex:
                logging.exception("Exception %s", ex.args())
        self.name = None
        self.coverage = None
        self.hash = None
        self.skipped = False


def main():
    my_plugin = FindDuplicateCoverage()
    pytest.main(sys.argv[1:], plugins=[my_plugin])

    print("Hash size: ", len(hash_tests))
    print("\n\nDuplicates:")
    for v in hash_tests.values():
        if len(v) == 1:
            continue
        for i in sorted(v):
            file, line, name = i
            print(
                f"{file}:{line}:1: W001 tests with duplicate coverage: {name} (duplicate-test)",
            )
        print("\n")

    print("\n\nSuperseeded:")
    for k, v in hash_tests.items():
        for kk, vv in hash_tests.items():
            if k != kk and all(ki <= kii for ki, kii in zip(hash_arcs[k], hash_arcs[kk])):
                bigger_test_filename, big_line, bigger_test_name = vv[0]
                print(
                    f"{bigger_test_filename}:{big_line}:1: W002 test {bigger_test_name} covers more when below (bigger-coverage)",
                )
                for i in sorted(v):
                    smaller_filename, small_line, smaller_test_name = i
                    print(
                        f"{smaller_filename}:{small_line}:1: W003 test {smaller_test_name} covers less when {bigger_test_name} (smaller-coverage)",
                    )
                print("\n")

if __name__ == "__main__":
    main()

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
        self.collected = []
        self.name = None
        self.coverage = None
        self.hash = None
        self.skipped = False

    def pytest_collection_modifyitems(self, items):
        for item in items:
            if isinstance(item, TestCaseFunction):
                self.collected.append(item.name)

    def pytest_runtest_logstart(self, nodeid, location):
        logging.debug(f"\nStart test {nodeid}")
        # print(nodeid, location)
        self.name = location

    def start_collection(self):
        try:
            self.hash = Hasher()
            logging.debug("\nCoverage created")
            self.coverage = Coverage(branch=True)
            self.coverage.start()
        except:
            self.coverage = None

    def pytest_report_teststatus(self, report):
        logging.debug("pytest_report_teststatus %s" % str(report))
        if report.when == "setup":
            self.start_collection()
        elif report.when == "call":
            self.skipped = report.outcome == "skipped"
            logging.debug(f"\nSkipped {self.skipped}")
        elif report.when == "teardown":
            self.stop_collection()

    def pytest_runtest_logfinish(self, nodeid, location):
        logging.debug(f"\nStop test {nodeid}")

    def stop_collection(self):
        if self.coverage:
            try:
                self.coverage.stop()
                logging.debug("\nCoverage stopped")
            except Exception as ex:
                logging.error("Exception %s", str(ex.args()))
        if self.coverage and not self.skipped:
            try:
                # logging.debug(f"\nStop test {nodeid}")
                data = self.coverage.get_data()
                arcs_list = []
                # logging.debug(data.measured_files())
                myself = os.path.basename(__file__)
                for f in data.measured_files():
                    if os.path.basename(f) != myself and not os.path.basename(
                        f,
                    ).startswith("test_"):
                        logging.debug(f)
                        logging.debug(data.lines(f))
                        # logging.debug(data.arcs(f))
                        add_data_to_hash(data, f, self.hash)
                        arcs_list += [set(data.arcs(f))]
                text_hash = self.hash.hexdigest()

                logging.debug(text_hash)
                if text_hash in hash_tests:
                    hash_tests[text_hash] += [self.name]
                else:
                    hash_tests[text_hash] = [self.name]
                    hash_arcs[text_hash] = arcs_list
                logging.debug("\nCoverage collected")

            except Exception as ex:
                logging.error("Exception %s", str(ex.args()))
        if self.coverage:
            try:
                self.coverage.erase()
                logging.debug("\nCoverage erased")
            except Exception as ex:
                logging.error("Exception %s", str(ex.args()))
        self.name = None
        self.coverage = None
        self.hash = None
        self.skipped = False


def main():
    my_plugin = FindDuplicateCoverage()
    pytest.main(sys.argv[1:], plugins=[my_plugin])

    print("Hash size: ", len(hash_tests))
    print("\n\nDuplicates:")
    for _k, v in hash_tests.items():
        if len(v) > 1:
            for i in sorted(v):
                #  .trunk/trunk.yaml:7:81: [error] line too long (82 > 80 characters) (line-length)
                file, line, name = i
                print(
                    f"{file}:{line}:4: W001 tests with duplicate coverage: {name} (duplicate-test)",
                )
            print("\n")

    print("\n\nSuperseeded:")
    for k, v in hash_tests.items():
        for kk, vv in hash_tests.items():
            if k != kk and all(ki <= kii for ki, kii in zip(hash_arcs[k], hash_arcs[kk])):
                bigger_test_filename, big_line, bigger_test_name = vv[0]
                print(
                    f"{bigger_test_filename}:{big_line}:4: W002 test {bigger_test_name} covers more when below (bigger-coverage)",
                )
                for i in sorted(v):
                    smaller_filename, small_line, smaller_test_name = i
                    print(
                        f"{smaller_filename}:{small_line}:4: W003 test {smaller_test_name} covers less when {bigger_test_name} (smaller-coverage)",
                    )
                print("\n")

if __name__ == "__main__":
    main()
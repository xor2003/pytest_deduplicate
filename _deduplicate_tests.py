#!/usr/bin/env python
import re, sys, os

import pytest
from _pytest.unittest import TestCaseFunction
from coverage import Coverage
from coverage.data import add_data_to_hash
from coverage.misc import Hasher
import logging

hash_tests = dict()
hash_arcs = dict()


class FindDuplicateCoverage:

    def __init__(self):
        self.collected = []
        self.name = None
        self.cov = None
        self.hash = None
        self.skipped = False

    def pytest_collection_modifyitems(self, items):
        for item in items:
            if isinstance(item, TestCaseFunction):
                self.collected.append(item.name)

    def pytest_runtest_logstart(self, nodeid, location):
        logging.debug(f"\nStart test {nodeid}")
        self.name = re.sub(r'^[^/]+/', '', nodeid)

    def start_collection(self):
        try:
            self.hash = Hasher()
            logging.debug(f"\nCoverage created")
            self.cov = Coverage(branch=True)
            self.cov.start()
        except:
            self.cov = None

    '''
    def pytest_runtest_setup(self, item):
        logging.debug('pytest_runtest_setup')

    def pytest_runtest_teardown(self, item, nextitem):
        logging.debug('pytest_runtest_teardown')
    '''

    def pytest_report_teststatus(self, report):
        logging.debug('pytest_report_teststatus %s' % str(report))
        if report.when == 'setup':
            self.start_collection()
        elif report.when == 'call':
            self.skipped = report.outcome == 'skipped'
            logging.debug(f"\nSkipped {self.skipped}")
        elif report.when == 'teardown':
            self.stop_collection()

    def pytest_runtest_logfinish(self, nodeid, location):
        logging.debug(f"\nStop test {nodeid}")

    def stop_collection(self):
        if self.cov:
            try:
                self.cov.stop()
                logging.debug(f"\nCoverage stopped")
            except Exception as ex:
                logging.error("Exception %s", str(ex.args()))
        if self.cov and not self.skipped:
            try:
                # logging.debug(f"\nStop test {nodeid}")
                data = self.cov.get_data()
                arcs_list = []
                # logging.debug(data.measured_files())
                myself = os.path.basename(__file__)
                for f in data.measured_files():
                    if os.path.basename(f) != myself and not os.path.basename(f).startswith('test_'):
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
                logging.debug(f"\nCoverage collected")

            except Exception as ex:
                logging.error("Exception %s", str(ex.args()))
        if self.cov:
            try:
                self.cov.erase()
                logging.debug(f"\nCoverage erased")
            except Exception as ex:
                logging.error("Exception %s", str(ex.args()))
        self.name = None
        self.cov = None
        self.hash = None
        self.skipped = False


my_plugin = FindDuplicateCoverage()
# directory = '.'
pytest.main(sys.argv[1:], plugins=[my_plugin])

logging.debug(len(hash_tests))
print("\n\nDuplicates:")
for k, v in hash_tests.items():
    if len(v) > 1:
        for i in sorted(v):
            print(i)
        print('\n')

print("\n\nSuperseeded:")
for k, v in hash_tests.items():
    for kk, vv in hash_tests.items():
        if k != kk and all(ki <= kii for ki, kii in zip(hash_arcs[k], hash_arcs[kk])):
            for i in sorted(v):
                print("%s <= %s" % (i, vv[0]))
            print('\n')

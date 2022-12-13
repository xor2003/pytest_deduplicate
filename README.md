# pytest_deduplicate

Finds duplicate tests based on same code coverage.

Useful in case if unit tests were generated automatically based on funciton input/output information
using available big amount of input data. (for example using https://github.com/laffra/auger)
This tool groups each test based on hash of it's code coverage.

Just call unit testing using this tool and it will collect code coverage for each test
and produce list of duplicate tests. 
False-positives possible if for example there are regular expressions the coverage will be same in this case.

./_deduplicate_tests.py .

Example:

```
Duplicates:
test_collect.py:94:0: W001 tests with duplicate coverage: test_minimal_missing_both_mo (duplicate-test)
test_collect.py:195:0: W001 tests with duplicate coverage: test_mapping_couldnt_find_mo (duplicate-test)

Superseeded:
test_collect.py:83:0: W002 test test_minimal_raise_missing_mo covers more when below (bigger_coverage)
test_collect.py:62:0: W003 test test_minimal_raise_valid covers less when test_minimal_missing_mo (smaller_coverage)
```

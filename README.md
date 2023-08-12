# pytest_deduplicate

The pytest_deduplicate is designed to identify duplicate or superseeding unit tests that have the same or bigger code coverage. 
It can be particularly useful when unit tests are automatically generated based on input/output information for a function, 
using a large amount of available input data (for example, with the help of the auger library).

This tool groups each test together based on the coverage set. 
By invoking unit testing with this tool, it will collect code coverage for each test and generate a list of duplicate tests. 
However, it is important to note that false-positives may occur if, for example, there are regular expressions involved, as the code coverage in such cases may appear the same.

To use simply call:

    cd <working_directory>
    pytest_deduplicate <pytest_parameters>

Result example:

```
Duplicates:
test_collect.py:94:0: W001 tests with duplicate coverage: test_minimal_missing_both_mo (duplicate-test)
test_collect.py:195:0: W001 tests with duplicate coverage: test_mapping_couldnt_find_mo (duplicate-test)

Superseeded:
test_collect.py:83:0: W002 test test_minimal_raise_missing_mo covers more when below (bigger_coverage)
test_collect.py:62:0: W003 test test_minimal_raise_valid covers less when test_minimal_missing_mo (smaller_coverage)
```

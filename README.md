# pytest_deduplicate

The pytest_deduplicate helps you analyze your test suite and identify potential issues related to duplicate and overlapping tests. By utilizing code coverage information, it can pinpoint areas for improvement, leading to a more efficient and focused set of tests.

### Benefits:

* **Reduced Test Suite Size:** Eliminating redundant tests leads to a more efficient test suite, saving execution time and resources.
* **Improved Test Focus:** Breaking down large tests into smaller, more specific ones enhances clarity and maintainability.
* **Enhanced Code Coverage Analysis:** Identifying overlaps and gaps in coverage helps you focus your testing efforts effectively.

By using this script and carefully analyzing its output, you can significantly improve the quality and efficiency of your test suite.

### Requirements:

* Python 3.x
* pytest or unittest
* coverage

### Installation:

1. Make sure you have the required libraries installed:

```
pip install -r requirements.txt
```

### Usage:

1. Run your tests with pytest and include the script as a plugin:

```
cd <working_directory>
/path/to/this/tool/find_duplicate_coverage.py [pytest_parameters]
```

2. Review the output:

The script will print three sections of information:

* **Duplicates:** Lists tests with identical coverage, suggesting to keep only one.
* **God Tests:** Identifies tests that can be split into smaller, more focused tests due to their extensive coverage.
* **Superseded:** Points out potentially redundant tests that might be removed because their coverage is entirely contained within other tests.

### Interpreting the Results:

* **Duplicates:** Consider removing duplicate tests, keeping the one that is most readable or representative.
* **God Tests:** Evaluate splitting these tests into smaller units that focus on specific functionality. This can improve test clarity and maintainability.
* **Superseded Tests:** Assess whether these tests are truly redundant and can be safely removed. Ensure that removing them doesn't leave any functionality untested.

However, it is important to note that false-positives may occur if, for example, there are regular expressions involved, as the code coverage in such cases may appear the same.

### Additional Notes:

* Consider using code coverage visualization tools in conjunction with the script for a more comprehensive understanding of your test coverage landscape.

### Result example:

```
def function(x):
    if x % 2 == 0:
        for i in range(1, 3):
            print("even")
        return True
    else:
        print("odd")
        return False


    def test_even0(self):
        self.assertEqual(function(0), True)

    def test_even2(self):
        self.assertEqual(function(2), True)

    def test_odd(self):
        self.assertEqual(function(3), False)

    def test_evenodd(self):
        self.assertEqual(function(2), True)
        self.assertEqual(function(3), False)


Duplicates:
tests/test_simple.py:16:1: W001 tests with same coverage: TestSimple.test_even0 consider leave only one (duplicate-test)
tests/test_simple.py:19:1: W001 tests with same coverage: TestSimple.test_even2 consider leave only one (duplicate-test)

God tests:
tests/test_simple.py:25:1: W002 test TestSimple.test_evenodd can be replaced by smaller tests below (bigger-coverage)
tests/test_simple.py:22:1: I002 test TestSimple.test_odd covers part of TestSimple.test_evenodd test (smaller-test)
tests/test_simple.py:16:1: I002 test TestSimple.test_even0 covers part of TestSimple.test_evenodd test (smaller-test)

Superseeded:
tests/test_simple.py:25:1: I002 test TestSimple.test_evenodd covers more code when test(s) below (bigger-coverage)
tests/test_simple.py:16:1: W003 test TestSimple.test_even0 covers less code when TestSimple.test_evenodd test. Consider delete (smaller-coverage)
tests/test_simple.py:19:1: W003 test TestSimple.test_even2 covers less code when TestSimple.test_evenodd test. Consider delete (smaller-coverage)
tests/test_simple.py:22:1: W003 test TestSimple.test_odd covers less code when TestSimple.test_evenodd test. Consider delete (smaller-coverage)
```

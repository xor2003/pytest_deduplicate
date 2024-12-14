# `pytest_deduplicate`

The `pytest_deduplicate` tool assists in analyzing your test suite to identify potential issues related to duplicate and overlapping tests. By utilizing code coverage information, it pinpoints areas for improvement, leading to a more efficient and focused set of tests.

### Benefits
* **Reduced Test Suite Size:** Eliminating redundant tests results in a more efficient test suite, saving execution time and resources.
* **Improved Test Focus:** Breaking down large tests into smaller, more specific ones enhances clarity and maintainability.
* **Enhanced Code Coverage Analysis:** Identifying overlaps and gaps in coverage helps you focus your testing efforts more effectively.

### Requirements
* Python 3.x
* pytest or unittest
* coverage

### Installation
1. Ensure you have the required libraries installed:
    ```sh
    pip install -r requirements.txt
    ```

### Usage
1. Run your tests with pytest and include the script as a plugin:
    ```sh
    cd <working_directory>
    /path/to/this/tool/pytest_deduplicate.py [pytest_parameters]
    ```
2. Review the output, which will include three sections of information:

    | **Case** | **Description** | **Actionable Insights** | **Example** |
    |-----------------------------------|---------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
    | **Case 1: Duplicates**            | Tests with identical code coverage, indicating redundancy.                                                | Remove duplicate tests, keeping the most readable or representative one.    | `TestSimple.test_even0` and `TestSimple.test_even2` have identical coverage.                               |
    | **Case 2: Broad Coverage ("God Tests")** | Tests that cover too much functionality, making them harder to maintain and understand.                   | Split into smaller, focused tests to improve clarity and maintainability.    | `TestSimple.test_evenodd` can be split into smaller tests like `test_even0` and `test_odd`.                |
    | **Case 3: Superseded Tests**      | Tests whose coverage is entirely contained within another test, making them redundant.                     | Remove smaller tests if the larger test sufficiently covers the functionality. | `TestSimple.test_evenodd` supersedes `test_even0`, `test_even2`, and `test_odd`.                           |

### Interpreting the Results
* **Duplicates:** Consider removing duplicate tests, keeping the one that is most readable or representative.
* **God Tests:** Evaluate splitting these tests into smaller units that focus on specific functionality. This can improve test clarity and maintainability.
* **Superseded Tests:** Assess whether these tests are truly redundant and can be safely removed. Ensure that removing them doesn't leave any functionality untested.

**Note:** Be aware of potential false positives, especially in cases involving complex code structures like regular expressions, as the code coverage may appear identical.

### Additional Notes
* Consider using code coverage visualization tools alongside this script for a more comprehensive understanding of your test coverage landscape.

### Result Example
```python
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
```

# Output:
```
1. Duplicate tests detected with identical coverage:
tests/test_simple.py:16:1: W001 tests with same coverage: TestSimple.test_even0 consider keeping only one (duplicate-test)
tests/test_simple.py:19:1: W001 tests with same coverage: TestSimple.test_even2 consider keeping only one (duplicate-test)



2. "God test" detected with broad coverage:
tests/test_simple.py:25:1: W002 test TestSimple.test_evenodd can be replaced by smaller tests below (bigger-coverage)
tests/test_simple.py:16:1: I002 test TestSimple.test_even0 covers part of TestSimple.test_evenodd test (smaller-test)
tests/test_simple.py:22:1: I002 test TestSimple.test_odd covers part of TestSimple.test_evenodd test (smaller-test)



3. Superseeded tests:
tests/test_simple.py:25:1: I003 test TestSimple.test_evenodd covers more code than test(s) below (bigger-coverage)
tests/test_simple.py:16:1: W003 test TestSimple.test_even0 covers less code than TestSimple.test_evenodd test. Consider remove it (smaller-coverage)
tests/test_simple.py:19:1: W003 test TestSimple.test_even2 covers less code than TestSimple.test_evenodd test. Consider remove it (smaller-coverage)
tests/test_simple.py:22:1: W003 test TestSimple.test_odd covers less code than TestSimple.test_evenodd test. Consider remove it (smaller-coverage)
```

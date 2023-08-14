# pytest_deduplicate

The pytest_deduplicate is designed to identify duplicate or superseeding unit tests that have the same or bigger code coverage. 
It can be particularly useful when unit tests are automatically generated based on input/output information for a function, 
using a large amount of available input data (for example, with the help of the auger library).

This tool groups each test together based on the coverage set. 
By invoking unit testing with this tool, it will collect code coverage for each test and generate a list of duplicate tests. 
However, it is important to note that false-positives may occur if, for example, there are regular expressions involved, as the code coverage in such cases may appear the same.

To use simply call:

    cd <working_directory>
    pytest_deduplicate [pytest_parameters]

Result example:

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

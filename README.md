# pytest_deduplicate

Finds duplicate tests based on same code coverage.

Useful in case if unit tests were generated automatically based on funciton input/output information
using available big amount of input data. (for example using https://github.com/laffra/auger)
This tool groups each test based on hash of it's code coverage.

Just call unit testing using this tool and it will collect code coverage for each test
and produce list of duplicate tests. 
False-positives possible if for example there are regular expressions the coverage will be same in this case.

./_deduplicate_tests.py .

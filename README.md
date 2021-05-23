# pytest_deduplicate

Find duplicate tests based on same code coverage.

In case if you generated unit tests automatically based on input/output information
using available big amount of input data.
Tool groups each test based on hash of it's code coverage.

Just call unit testing using this tool and it will collect code coverage for each test
and produce list of most probably duplicate tests. I mean false positives possible if for example
there is regular expressions and coverage is same.

./_deduplicate_tests.py .
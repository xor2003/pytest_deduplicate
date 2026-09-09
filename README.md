# pytest_deduplicate

Find tests with identical or overlapping **observed branch coverage** to help review a test suite.

Coverage overlap is a review signal. It does **not** prove that tests have equivalent assertions, inputs, side effects, or fault-detection ability. Do not delete tests solely because this tool reports a match.

## Installation and usage

Install the dependencies:

```sh
pip install -r requirements.txt
```

Run from the project whose tests you want to inspect:

```sh
python /path/to/pytest_deduplicate.py [pytest arguments]
```

For example:

```sh
python /path/to/pytest_deduplicate.py -q tests/
```

The command preserves pytest’s exit status, including failures and no tests collected. An internal coverage collection error also produces a nonzero exit status.

## Reports

| Code | Meaning | How to use it |
|---|---|---|
| W001 | Tests have identical observed file-and-arc sets. | Compare assertions, inputs and requirements before deciding whether any test is redundant. |
| W002 / I002 | A test’s observed coverage is contained in the union of smaller observations. | Review the listed combination. This is neither a minimal replacement set nor evidence of a poorly designed test. |
| W003 / I003 | One test’s observed coverage is contained in another’s. | Review the different behaviors checked by each test. Containment alone does not establish redundancy. |

Locations use one-based line numbers. Parameterized cases retain their case identifiers.

For example, these tests exercise the same arcs:

```python
def double(x):
    return x * 2


def test_positive():
    assert double(2) == 4


def test_negative():
    assert double(-2) == -4
```

Both are useful: changing the implementation to `abs(x) * 2` breaks only the negative-input test. W001 therefore identifies matching coverage, not interchangeable tests.

## Measurement scope and limitations

- Each observation includes setup, the test call and teardown. Only tests with successful setup, call and teardown enter the comparison; skipped, failed and expected-failure cases are excluded.
- Collected Python test bodies are removed from the comparison, while helper functions and fixtures in those same files remain measurable. Nested code defined inside a test body is excluded along with that body. Custom collectors and decorated callables without an inspectable underlying Python function may retain test scaffolding in their observations.
- File identity and arc sets both participate in equality. Ordering of files and arcs does not affect equality.
- Empty observations are omitted from comparisons.
- Coverage measures executed Python line transitions, not values, assertions, execution counts or complete execution paths. Native code is not measured by these Python arcs.
- Shared fixtures, caches and other state can make observations depend on test order. A module/session fixture runs only when pytest schedules it; its coverage is attributed to the test during which it executes, not copied to every consumer.
- Coverage configuration affects which files are measured. Fixtures and other measured support code can affect overlap results.
- The supported execution model is a serial pytest run in one process. Distributed workers and subprocess coverage are not aggregated by this tool. Integration with other active coverage collectors is not validated.
- The reports are independent review candidates, not a coordinated plan for removing tests.

## Development checks

```sh
python -m pytest -q
```

The regression suite exercises the analyzer through isolated pytest subprocesses, including file identity, helpers in test modules, fixtures, parameterized cases, failed/skipped tests, empty observations, overlap analysis and exit codes.

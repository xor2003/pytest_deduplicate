# Collector benchmark

Recorded on 2026-09-09 using Python 3.12.3, pytest 9.0.1 and coverage.py 7.12.0 on Linux. The workload is 200 parameterized integer-branch tests against one application module, with pytest plugin autoload disabled. Three fresh-process samples per mode were run in rotating order.

| Mode | Median wall time | Overhead versus no coverage |
|---|---:|---:|
| No coverage (outcome observer only) | 0.471 s | baseline |
| Restart per test | 1.463 s | 210.8% |
| One collector with explicit contexts | 0.787 s | 67.2% |

Context collection took about 46% less total wall time than restart collection on this workload. All per-test file/arc observations and outcomes matched across both instrumented modes and repetitions. Tests also verify setup/call/teardown attribution and that failed-test coverage does not leak into the next context.

This bounded result motivated the context default. It is not a prediction for other projects: interpreter startup, framework overhead, fixture structure, source scope, machine load and suite size affect timings. Restart mode remains available for comparisons and troubleshooting.

Raw samples and environment versions are in [collector-benchmark.json](collector-benchmark.json). Reproduce from the checkout:

```sh
python tools/benchmark_collectors.py --tests 200 --runs 3 --output benchmark.json
```

Measure an application suite from its project directory:

```sh
pytest_deduplicate --source src --benchmark-collectors 3 --json benchmark.json -q tests/
```

The implementation uses public [coverage context switching](https://coverage.readthedocs.io/en/7.12.0/api_coverage.html#coverage.Coverage.switch_context) and [exact context queries](https://coverage.readthedocs.io/en/7.12.0/api_coveragedata.html#coverage.CoverageData.set_query_context). It explicitly assigns setup through teardown to one test node ID rather than relying on test-function-name detection.

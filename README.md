# pytest_deduplicate

Review tests with identical or overlapping **observed branch coverage**, inspect the evidence, and optionally check stability and sampled fault detection.

Matching coverage does **not** prove equivalent assertions, inputs, side effects or testing value. Findings are review candidates, not instructions to delete tests.

## Install and run

Requires Python 3.9+, pytest 7.4+ and coverage.py 7.6+.

```sh
pip install .
pytest_deduplicate --source src --json overlap.json -q tests/
```

From a source checkout you can also install `requirements.txt` and run:

```sh
python /path/to/pytest_deduplicate.py --source src --json overlap.json -q tests/
```

Run from the application project directory. `--source` accepts an existing file or directory and can be repeated. Explicit application scope prevents unrelated support/plugin activity from affecting comparisons. `--omit` accepts repeatable coverage.py glob patterns and is added to configured omissions:

```sh
pytest_deduplicate --source src --source lib --omit '*/generated/*' --json overlap.json
```

Without `--source`, coverage.py configuration/default scope applies. With explicit source paths, those paths replace configured source scope; other coverage filters still apply. The analyzer's own modules are always omitted.

Use `--deduplicate-help` for analyzer options. Unrecognized arguments are forwarded to pytest; `--help` remains pytest's help. Analyzer option names are reserved; put `--` before pytest arguments if a pytest plugin needs an option with the same name.

## Understand the evidence

| Code | Meaning | Review question |
|---|---|---|
| W001 | Identical observed file-and-arc sets | Do the assertions protect different requirements or inputs? |
| W002 | Coverage contained in the union of smaller observations | What behavior does the larger test check that the combination does not? |
| W003 | Coverage contained in another observation | Does the smaller test catch faults that the larger one misses? |

Text output shows test identifiers, one-based locations, measured durations, shared/unique arc counts and file names. JSON also contains the exact shared and unique arcs, complete per-test observations, setup/call/teardown outcomes and timings, measurement scope and errors. The reports are independent candidates, not a coordinated removal plan or a minimal set cover.

`--json PATH` writes a versioned report and keeps normal text output. `--json -` writes only JSON to stdout, sending pytest output and check progress to stderr:

```sh
pytest_deduplicate --source src --json - -q > overlap.json
```

See [the JSON schema guide](docs/report-format.md).

## Check stability

```sh
pytest_deduplicate --source src --stability-runs 2 --seed 17 --json stability.json
```

For each repetition, selected candidates run individually in fresh processes. When multiple candidates are selected, they also run together in original, reversed and seeded shuffled order. Coverage and phase outcomes are compared with the original full-suite observations; durations are not compared.

Results distinguish `stable_in_checked_runs`, `unstable` and `inconclusive`. A stable result covers only the checked scenarios. Tests that depend on an initializer outside the candidate set can fail when isolated; this is useful evidence of an order dependency, not a duplicate verdict.

`--max-candidates N` limits optional checks to the first N candidates in collection order (default 20). Unchecked candidates are listed explicitly. `--check-timeout SECONDS` bounds each fresh-process test invocation (default 30). Stability checks rerun tests in the current project and can repeat their normal side effects.

## Sample fault detection (experimental)

```sh
pytest_deduplicate --source src --mutations 10 --max-candidates 5 --json faults.json
```

The built-in sampler makes independent, single-line changes to arithmetic/comparison operators and integer/boolean constants on observed source lines. This is a bounded fault sample, not a complete mutation-testing engine or a mutmut integration.

Mutation sources must be inside the current project directory. The checker copies the project into a temporary directory, verifies each candidate against an unchanged copy, and runs each test/mutant trial in a fresh copy and process. The original source is never patched. Caches, virtual environments, build output and common metadata directories are excluded from copies. Tests that depend on these excluded files, external editable installations, or a different working directory may have inconclusive baselines. A temporary copy is not an OS security sandbox: tests retain their usual network and external-filesystem access.

For each mutant and test, JSON distinguishes `killed`, `survived`, `not_reached`, timeouts and errors. Only a failed test call that reached the mutation counts as a kill; collection/setup/teardown failures and timeouts do not. Per-pair comparisons identify distinguishing mutants. `same_on_sampled_mutants` means every sampled mutant was reached and produced the same conclusive outcome for both tests; it never establishes equivalence. Partial samples remain inconclusive.

Checks are skipped if the initial pytest run fails. Finding instability or different fault detection does not change a passing pytest exit code. Individual optional-check timeouts/errors appear as inconclusive evidence; an analyzer infrastructure failure produces a nonzero exit. Inspect the report when using optional checks in CI.

## Collection and performance

The default `--collector contexts` keeps one coverage collector running and assigns explicit test node IDs as contexts. Setup, call and teardown belong to that test's context; inter-test activity uses an unqueried empty context. The previous `--collector restart` mode remains available for comparison.

```sh
pytest_deduplicate --source src --benchmark-collectors 3 --json benchmark.json
```

The benchmark reruns the selected suite in fresh processes with instrumentation disabled, with restart collection, and with context collection. Mode order rotates. It records raw wall times, medians, overhead relative to the uninstrumented pytest observer, and exact per-test coverage/outcome parity between instrumented modes. Benchmark parity includes repeated observations to expose unstable runs. Timings include interpreter/pytest startup. The tool does not automatically change collector settings.

The context default was selected after a bounded synthetic benchmark and regression checks for phase attribution. See [the recorded benchmark and reproduction command](docs/collector-benchmark.md). Measure your own suite before assuming the same improvement.

## Remaining limits

- Coverage records Python line transitions, not values, assertions, execution counts, complete paths or native-code behavior.
- Collected Python test bodies (including nested code) are excluded, but helpers/fixtures in those files remain measurable. Custom collectors or decorators without inspectable wrapped functions may retain test scaffolding.
- Only fully passed, non-xfail tests with nonempty observations become candidates. JSON still records other test outcomes and available coverage.
- Shared fixtures and caches can make observations order dependent. A module/session fixture is attributed only to the test during which pytest actually executes its setup or teardown.
- One serial pytest process is supported. Distributed execution and simultaneous `--cov` collection are rejected; subprocess coverage is not aggregated. Other externally active collectors are not validated.
- Repeated execution of the same node ID within a run (for example rerun plugins) is not supported. Do not combine this tool with retries.
- Test durations include instrumentation overhead. Comparison analysis can become expensive for many distinct coverage sets; optional checks are bounded separately.

## Development and release checks

```sh
python -m pip install -r requirements.txt build wheel setuptools
python -m pytest -q
python tools/check_distribution.py
```

CI covers Python 3.9–3.14, minimum/current dependency combinations, and a Windows job. The distribution check builds an sdist and a wheel from the sdist, installs that wheel in a temporary environment, verifies imports come from the installed distribution, and exercises its command, optional checks and failure exit status outside the checkout.

The build checker stages an explicit set of release files, excluding unrelated local Cython experiments and untracked `setup.py` files. If such an experimental setup script is present in your working directory, use the checker for release validation; a direct `pip install .` can invoke that script. The committed project uses the pure-Python modules declared in `pyproject.toml`.

Python 3.8 is no longer advertised: the original runtime type aliases already required 3.9, and the mutation sampler now explicitly uses Python 3.9's AST support.

# pytest_deduplicate

Review tests with identical or overlapping **observed branch coverage**, inspect the evidence, and optionally check stability and sampled fault detection.

Matching coverage does **not** prove equivalent assertions, inputs, side effects or testing value. Findings are review candidates, not instructions to delete tests.

## Install and run

Requires Python 3.9+, pytest 7.4.4+ and coverage.py 7.6.1+.

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

`--max-candidates N` bounds optional checks (default 20). Selection prioritizes complete comparisons, new test modules, measured duration and overlap. Oversized identical groups can contribute useful pairs; combined comparisons stay whole. A budget of one selects no tests. `selection` records reasons and incomplete groups; unchecked tests are explicit. `--check-timeout SECONDS` bounds each fresh-process test invocation (default 30). Stability checks rerun tests in the current project and can repeat their normal side effects.

## Sample fault detection (experimental)

```sh
pytest_deduplicate --source src --mutations 10 --max-candidates 5 --json faults.json
```

The seeded sampler distributes its budget across file/function/operator buckets and makes independent, single-line changes to arithmetic/comparison operators and integer/boolean constants on observed source lines. This is a bounded fault sample, not a complete mutation-testing engine or a mutmut integration.

Mutation sources must be inside the current project directory. The checker copies the project into a temporary directory, verifies each candidate against an unchanged copy, and runs each test/mutant trial in a fresh copy and process. Each mutant/test experiment repeats in a fresh copy at least twice (`--mutation-repeats`, default 2); differing repeated outcomes are inconclusive. `--mutation-snapshot-mb` (default 256) rejects oversized project copies before copying. The original source is never patched. Caches, virtual environments, build output and common metadata directories are excluded from copies. Tests that depend on these excluded files, external editable installations, or a different working directory may have inconclusive baselines. A temporary copy is not an OS security sandbox: tests retain their usual network and external-filesystem access.

For each mutant and test, JSON distinguishes `killed`, `survived`, `not_reached`, timeouts and errors. Only a failed test call that reached the mutation counts as a kill; collection/setup/teardown failures and timeouts do not. Per-pair comparisons identify distinguishing mutants. `same_on_sampled_mutants` means every sampled mutant was reached and produced the same conclusive outcome for both tests; it never establishes equivalence. Partial samples remain inconclusive.

Checks are skipped if the initial pytest run fails. Finding instability or different fault detection does not change a passing pytest exit code. Individual optional-check timeouts/errors appear as inconclusive evidence; an analyzer infrastructure failure produces a nonzero exit. Inspect the report when using optional checks in CI.

## Collection and performance

The default `--collector contexts` keeps one coverage collector running and assigns explicit test node IDs as contexts. Both collector modes select coverage.py's tracing core: Python 3.14's default `sysmon` core does not support explicit context switching or the same complete arc observations. Setup, call and teardown have separate contexts attached to that test; inter-test activity uses an unqueried empty context. The previous `--collector restart` mode remains available for comparison.

```sh
pytest_deduplicate --source src --benchmark-collectors 3 --json benchmark.json
```

The benchmark reruns the selected suite in fresh processes with instrumentation disabled, with restart collection, and with context collection. Mode order rotates. It records raw wall times, medians, overhead relative to the uninstrumented pytest observer, and exact per-test coverage/outcome parity between instrumented modes. Benchmark parity includes repeated observations to expose unstable runs. Timings include interpreter/pytest startup. The tool does not automatically change collector settings.

The context default was selected after a bounded synthetic benchmark and regression checks for phase attribution. See [the recorded benchmark and reproduction command](docs/collector-benchmark.md). Measure your own suite before assuming the same improvement.

## Conclusions and phase evidence

Each finding has one `assessment.status`: `unchecked`, `stable_coverage_only`,
`consistent_in_checked_sample`, `different_fault_detection`, `unstable`, or
`incomplete`. Full group membership matters: checking two tests in a larger
group does not validate the whole group. Pairwise mutant differences do not
prove anything about the fault-detection union of a combined finding. No status
authorizes automatic removal.

`tests[].phase_file_arcs` separates setup/call/teardown evidence. By default,
comparisons use all observed protocol activity. Use `--coverage-phase call` to
compare test calls without fixture setup/teardown. Shared fixtures remain
attributed only when executed; phases are not reconstructed for other tests.

## Import pytest-cov and xdist results

Install pytest-cov and, for parallel runs, pytest-xdist. Record outcomes during
the **same fresh, non-append run**, then import without rerunning pytest:

```sh
pytest -p pytest_deduplicate_import --cov=src --cov-branch --cov-context=test \
  --deduplicate-outcomes outcomes.json -n 2 tests/
pytest_deduplicate --source src --import-coverage .coverage --outcomes outcomes.json \
  --coverage-phase call --json overlap.json --html overlap.html
```

`--deduplicate-coverage-file PATH` selects a nondefault final combined data file.
The companion selects a tracing core before pytest-cov starts, including on
Python 3.14 and xdist workers, and verifies the actual cores in the manifest.
It binds outcomes to the data file SHA-256, collected inventory, source/test
hashes and project root. Import rejects mismatches, missing phases, worker
failures, retries, stale contexts and line-only data. Import from the recorded
root before editing source. Missing explicit phase contexts are `null`, not
empty coverage: pytest-cov versions may attribute only calls. Such imports
remain incomplete for `--coverage-phase all`. Empty/unattributed contexts are
not assigned to tests. Import cannot run optional live checks.

## Compare and review reports

```sh
pytest_deduplicate --source src --json current.json --baseline previous.json \
  --html overlap.html --review-template review-draft.json
```

Finding IDs depend on kind and test IDs, not timings or commit paths. Baseline
comparison lists new, changed, unchanged and resolved findings. Resolution
requires successful runs with identical source scope and test inventory;
otherwise absent findings are `unobserved`. This supports reports from different
commits without claiming deselected tests have been fixed.

To record a reviewed finding, copy its template entry into a review document,
fill `reason` and `reviewed_at`, and pass `--suppressions reviews.json`. Empty
reasons are rejected. Source/test, arc, scope or assessment changes invalidate
the recorded evidence hash and mark it `needs_revalidation`. Reviewed entries
remain in JSON; the HTML viewer can hide only unchanged reviewed entries.

The standalone HTML report needs no server or external assets. Filter by module
or test, assessment and total observed duration; expand exact file/arc and
phase evidence. Source excerpts are embedded only when current bytes match the
report hash, capped at 500 lines per file. Displayed durations include coverage overhead and are not
predicted time savings.

## Measured validation

[Real-project evaluation](docs/real-project-evaluation.md) covers bounded suites
in vextest (47 tests) and masm2c (20 tests), including manual counterexamples
and a random-order parser-cache effect. It does not establish whole-project
precision or semantic recall. Hypothesis tests compare set operations and
containment/combined detection with independent oracles and execute generated
programs with known findings.

The exact inverted arc index interns file/arc identities and filters impossible
comparisons. [Recorded analysis benchmark](docs/overlap-benchmark.json) and
`python tools/benchmark_overlap.py` compare it with the quadratic containment
oracle. Dense findings can still require quadratic output; no findings are
silently dropped.

## Remaining limits

- Coverage records Python line transitions, not values, assertions, execution counts, complete paths or native-code behavior.
- Collected Python test bodies (including nested code) are excluded, but helpers/fixtures in those files remain measurable. Custom collectors or decorators without inspectable wrapped functions may retain test scaffolding.
- Only fully passed, non-xfail tests with nonempty observations become candidates. JSON still records other test outcomes and available coverage.
- Shared fixtures and caches can make observations order dependent. A module/session fixture is attributed only to the test during which pytest actually executes its setup or teardown.
- Live collection requires one serial pytest process and rejects simultaneous `--cov`. Existing pytest-cov/xdist data can be imported with the companion manifest below. Arbitrary subprocess coverage and externally active collectors are not validated.
- Repeated execution of the same node ID within a run (for example rerun plugins) is not supported. Do not combine this tool with retries.
- Test durations include instrumentation overhead. Comparison analysis can become expensive for many distinct coverage sets; optional checks are bounded separately.

## Development and release checks

```sh
python -m pip install -r requirements.txt build wheel setuptools "hypothesis>=6.100" "pytest-cov>=5" "pytest-xdist>=3.6"
python -m pytest -q
python tools/check_distribution.py
```

CI covers Python 3.9–3.14, minimum/current dependency combinations, and a Windows job. The distribution check builds an sdist and a wheel from the sdist, installs that wheel in a temporary environment, verifies imports come from the installed distribution, and exercises its command, optional checks and failure exit status outside the checkout.

The build checker stages an explicit set of release files, excluding unrelated local Cython experiments and untracked `setup.py` files. If such an experimental setup script is present in your working directory, use the checker for release validation; a direct `pip install .` can invoke that script. The committed project uses the pure-Python modules declared in `pyproject.toml`.

Python 3.8 is no longer advertised: the original runtime type aliases already required 3.9, and the mutation sampler now explicitly uses Python 3.9's AST support.

# JSON report version 1

`--json PATH` writes one object. `--json -` emits that object without pytest/text-report output on stdout. Paths in coverage evidence are relative to `root` where possible; paths outside the project may contain `..`, or remain absolute on a different Windows drive. Arc endpoints are coverage.py line numbers, with negative entry/exit markers preserved.

Top-level fields:

- `schema_version`: currently 1; consumers should reject unsupported versions.
- `root`, `collector`, `scope`: working directory, collector mode and effective source/omit scope.
- `pytest_exit_code`, `exit_code`: original pytest result and final analyzer result.
- `elapsed`: initial run wall time in seconds, excluding optional checks.
- `errors`: collection/analysis infrastructure errors. An empty list is not a proof of semantic correctness.
- `warning`: the coverage-equivalence limitation.
- `tests`: observations in execution order, including noncandidate outcomes.
- `findings`: review candidates with exact evidence.
- Optional `stability`, `mutations`, `benchmark`, or `checks` (reason checks were skipped).

Each test has `nodeid`, `location` (`file`, one-based `line`), `duration` in seconds, `phases` keyed by setup/call/teardown, `eligible`, `file_arcs` and `arc_count`. Phase entries contain `outcome`, `duration` and `xfail`. Eligibility describes successful completion; an eligible test with zero measured arcs still cannot be a candidate.

Each finding contains:

```json
{
  "kind": "contained",
  "tests": ["tests/test_example.py::test_small"],
  "other_tests": ["tests/test_example.py::test_large"],
  "shared": {"src/product.py": [[-1, 2], [2, -1]]},
  "unique": {},
  "other_unique": {"src/product.py": [[4, 5]]},
  "shared_arc_count": 2,
  "unique_arc_count": 0,
  "other_unique_arc_count": 1
}
```

For `identical`, `tests` contains the whole matching group and `other_tests` is empty. For `contained`, the first group is a subset of the second. For `combined`, `other_tests` contains one representative per smaller coverage group, and its evidence is their union. Join node IDs to `tests` for locations, durations and full individual arcs.

Stability results map node IDs to a status and per-trial observations. Trials record scenario names and actual order. Differences include baseline and observed fingerprints; incomplete trials include diagnostics. `unchecked` lists candidates omitted by the configured limit.

Mutation results contain the operator set, baseline statuses, exact edits (`file`, `line`, `column`, `before`, `after`), per-test outcomes and pair comparisons. Columns are one-based UTF-8 byte offsets. IDs such as `M0001` are local to a report. Pair comparisons list the conclusive shared sample and distinguishing mutants; do not interpret an empty distinguishing list without checking `status` and sample completeness.

Benchmark results contain raw `samples_seconds`, `median_seconds`, `overhead_percent`, `coverage_and_outcome_parity` and failed-run diagnostics. The `off` mode retains a minimal pytest outcome observer but performs no coverage collection.

## Additive fields in release 0.2

- `scope.coverage_phase`: `all` or `call`. `tests[].phase_file_arcs` contains
  exact per-phase arcs; `null` means an unavailable imported context.
- `findings[].assessment`: aggregate status, coverage/stability/sample completeness,
  per-test stability and distinguishing pairs. `automatic_removal_safe` is always false.
- `selection`: strategy, budget, selected/unchecked IDs, reasons, and per-finding
  completeness. It describes the checked subset, not a reduced test suite.
- `mutations.sampling`: seed, bucket count, supported-edit count; `trials` records
  repeated outcomes and `confirmation_runs` their budget. Snapshot-limit failure
  remains incomplete evidence.
- `import`: coverage digest and attribution/inventory checks. Coverage must be
  generated with the `pytest_deduplicate_import` companion outcome plugin.
- `evidence`: source/test file hashes plus scope and inventory hashes. Missing
  files have null hashes and prevent valid reviewed suppressions.
- Each finding has stable `id`, `evidence_sha256`, and optional `review` with
  `reviewed` or `needs_revalidation` status. Every review requires a reason/date.
- `comparison`: new/changed/unchanged/resolved IDs; absent findings from an
  incomparable scope or inventory are unobserved, not resolved.

These fields are additive to schema 1. Consumers should tolerate unknown fields;
older reports without evidence hashes cannot serve as review baselines.

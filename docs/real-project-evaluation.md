# Real-project evaluation, 2026-09-09

Scope: current dirty working trees of `~/vextest` and `~/masm2c`, not their
whole suites or clean commits. Machine-local raw reports and logs are in
`/tmp/pytest-deduplicate-evaluation`. Compact measured results and post-run
tracked-source hashes are in `real-project-evaluation.json`. These initial
runs did not fingerprint before execution; this limits reproducibility.
The reusable `tools/evaluate_local_projects.py` records both before and after.

- vextest: `angr_platforms/tests/test_x86_16_segmented_address_ir.py` and
  `angr_platforms/tests/test_x86_16_stack_lowering.py`, source
  `angr_platforms/angr_platforms/X86_16`. 47 passed with the project's prescribed
  `PYTHON_JIT=1`, `-n 7`, short tracebacks and durations (9.81 s pytest time).
  Analyzer comparison was necessarily serial; both collectors passed all 47.
  Their per-test arcs and outcomes matched. Seven tests had no measured source
  arcs; they are not empty-coverage duplicates.
- masm2c: `tests/test_cli_args.py` and `tests/test_tasm_op.py`, source `masm2c`.
  Both collectors passed all 20. Nine findings in both, one empty observation.
  Exact arcs initially differed for `test_fix_dollar` and
  `test_calculate_data_size`: parser initialization arcs moved to the first
  parser test. The suite randomizes unittest order globally. This is a real
  order-sensitive coverage observation; counts alone would have hidden it.

Timings are single samples with different warm-cache states, not a performance
ranking. The first masm2c run took 24 s, the next 2.27 s. Do not attribute this
difference solely to the collector.

## Manual review: deliberately selected counterexamples

Five identical-coverage findings were inspected in test source. All five
exercise distinct specified cases and should be retained pending stronger
assertion/fault evidence:

| Project | Finding | Why matching arcs do not justify removal |
|---|---|---|
| masm2c | `test_passes_*`, `test_jobs_*` | Defaults, explicit arguments, environment and CPU-count fallback assert different contracts. |
| masm2c | `test_single_listing_conversion_does_not_merge_data_segments` / `test_mixed_multi_module_conversion_merges_data_segments` | Opposite boolean results and single/multiple input boundaries. |
| masm2c | `test_collect_shared_equates_scans_simple_numeric_assignments` / `test_collect_shared_equates_uses_last_numeric_assignment` | Expression evaluation versus overriding earlier assignments. |
| vextest | `test_ds_not_stack` / `test_es_not_stack` / `test_unknown_space_not_stack` | Distinct memory spaces must each remain non-stack. |
| vextest | `test_expr_with_bp_is_stack` / `test_expr_with_sp_is_stack` | Different register expressions are separate regressions. |

This is a purposive sample, not a random sample: **no precision percentage** is
claimed. Coverage overlap is correct for these observations; interpreting it
as redundant assertions would be wrong. Seeded oracle tests separately measure
known structural overlap and cannot establish semantic recall on these projects.

To reproduce bounded serial comparisons with existing project environments:

```sh
python tools/evaluate_local_projects.py --root ~/masm2c \
  --python ~/masm2c/.venv/bin/python --source masm2c \
  --output /tmp/masm2c-deduplicate tests/test_cli_args.py tests/test_tasm_op.py
```

For vextest use its interpreter, the two paths above, and `PYTHON_JIT=1`.
Coverage must be available in that interpreter; the recorded run supplied
coverage 7.16.0 through a temporary PYTHONPATH directory without editing its venv.

A fixed-order repeat of all 20 masm2c tests restored exact collector parity
(2.04 s contexts, 2.27 s restart, single warmed samples). The initial mismatch
is therefore attributable to order for the compared runs, not evidence of a
collector discrepancy.

The updated collector was rerun on both bounded suites with pre/post tracked
source fingerprints and a fixed order for the second collector. Both had exact
arc/outcome parity, and both tracked snapshots remained unchanged. Optional
stability then checked two selected tests per project in isolation and together
in original, reverse and shuffled orders: all four selected tests matched their
baseline. This leaves 11 masm2c and 26 vextest candidates unchecked. No full-project
mutation campaign was performed.

The HTML viewer was exercised in headless Chromium: module/test, conclusion and
duration filters, evidence and source expansion, reviewed-entry visibility,
and JavaScript error checking. Local full
reports remain outside the repository; only compact measurements are committed.

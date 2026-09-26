# Run-local path metadata benchmark

Recorded on 2026-09-25 with Python 3.14.3, pytest 9.1.1 and coverage 7.16.1
on macOS arm64. This bounded synthetic workload uses 80 application modules and
240 parameterized tests. Each mode runs three times in fresh processes, in
rotating order, with pytest plugin autoload disabled. Timings include interpreter
and pytest startup.

| Mode | Median wall time |
| --- | ---: |
| Upstream 8b06969, contexts collector | 3.841 s |
| Same collector with run-local metadata caches | 2.168 s |

Caching reduced median wall time by 43.6% (1.77x speedup) on this workload. Each
cached run made 57,600 source-path lookups, with 80 misses and 57,520 hits
(99.86%). Exact test eligibility, phase outcomes, call/phase file-and-arc sets,
findings and analyzer exit/error status matched across all six runs. Raw samples
and comparison hashes are in [path-cache-benchmark.json](path-cache-benchmark.json).

The cache stores resolved paths and fixed source-scope metadata, never test
results or coverage arcs. It belongs to one analyzer instance; report path
conversions are separately cached for one report build. New measured filenames
are still discovered during collection. Changing source scope or working tree
between commands starts new caches.

This measures repeated filesystem metadata work across many source files. It is
not a prediction for every suite, and it does not benchmark pytest-cov import or
remove its other query costs. File-system topology and source scope must remain
stable during an individual measurement, as with fixed-scope coverage collection.

Reproduce using two source checkouts and the same Python environment:

```sh
python tools/benchmark_path_cache.py \
  --baseline-source /path/to/upstream-at-8b06969 \
  --candidate-source /path/to/candidate \
  --modules 80 --tests 240 --runs 3
```

The command generates a fresh temporary fixture and prints its raw JSON report
path. `--workdir` can select an empty output directory. Only generated synthetic
application and test code is measured.

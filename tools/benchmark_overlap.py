"""Measure exact inverted containment against a quadratic oracle on fixed data."""
import json
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pytest_deduplicate import TestCoverage
from pytest_deduplicate_index import ArcIndex


def main():
    result = {}
    for label in ('sparse', 'shared'):
        rng = random.Random(17)
        count = 600
        groups = []
        for index in range(count):
            start = index * 20 if label == 'sparse' else 0
            arcs = {(n, n + 1) for n in rng.sample(range(start, start + 100), 8)}
            groups.append(TestCoverage([], {'product.py': arcs}))
        samples = {'quadratic': [], 'indexed': []}
        for _ in range(3):
            started = time.perf_counter()
            expected = [(i, j) for i, left in enumerate(groups) for j, right in enumerate(groups)
                        if i != j and left.issubset(right)]
            samples['quadratic'].append(time.perf_counter() - started)
            started = time.perf_counter()
            actual = list(ArcIndex(groups).containment_pairs())
            samples['indexed'].append(time.perf_counter() - started)
            assert actual == expected
        medians = {k: statistics.median(v) for k, v in samples.items()}
        result[label] = {'groups': count, 'samples_seconds': samples, 'median_seconds': medians,
                         'speedup': medians['quadratic'] / medians['indexed'], 'exact_parity': True}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

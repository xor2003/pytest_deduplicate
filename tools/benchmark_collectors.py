"""Reproduce a bounded, synthetic collector benchmark without project fixtures."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

import coverage
import pytest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests", type=int, default=200)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.tests < 1 or args.runs < 1:
        parser.error("tests and runs must be positive")
    script = Path(__file__).resolve().parents[1] / "pytest_deduplicate.py"
    with tempfile.TemporaryDirectory(prefix="pytest-deduplicate-benchmark-") as temp:
        root = Path(temp)
        (root / "product.py").write_text("def transform(x):\n    if x % 2:\n        return x + 1\n    return x * 2\n")
        (root / "test_many.py").write_text(
            "import pytest\nfrom product import transform\n"
            f"@pytest.mark.parametrize(\"x\", range({args.tests}))\n"
            "def test_transform(x):\n    assert transform(x) == (x + 1 if x % 2 else x * 2)\n")
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        env.pop("PYTEST_ADDOPTS", None)
        process = subprocess.run([sys.executable, str(script), "--source", "product.py",
                                  "--benchmark-collectors", str(args.runs), "--json", "-",
                                  "-q", "-p", "no:cacheprovider"],
                                 cwd=root, env=env, text=True, capture_output=True)
        if process.returncode:
            print(process.stderr, file=sys.stderr)
            return process.returncode
        report = json.loads(process.stdout)
        artifact = {"workload": "parameterized integer branch, one application module",
                    "tests": args.tests, "runs": args.runs, "python": platform.python_version(),
                    "platform": platform.system(), "pytest": pytest.__version__,
                    "coverage": coverage.__version__, "benchmark": report["benchmark"]}
        Path(args.output).write_text(json.dumps(artifact, indent=2) + "\n")
        print(json.dumps(artifact, indent=2))
        return 0 if report["benchmark"]["coverage_and_outcome_parity"] else 1


if __name__ == "__main__":
    sys.exit(main())

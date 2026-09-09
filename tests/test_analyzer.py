"""Regression tests of analyzer results, using isolated real pytest runs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_deduplicate import (
    TestCoverage as CoverageSet,
    coverage_signature,
    find_fully_overlapped_sets,
)

SCRIPT = Path(__file__).resolve().parents[1] / "pytest_deduplicate.py"


def run_suite(tmp_path, files, *args):
    for name, source in files.items():
        (tmp_path / name).write_text(source)
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *([] if '--import-coverage' in args else ['-q', '-p', 'no:cacheprovider']), *args],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30,
    )


def test_file_identity_and_order():
    a = {"a.py": {(1, 2)}, "b.py": {(3, 4), (4, 5)}}
    b = dict(reversed(list(a.items())))
    assert coverage_signature(a) == coverage_signature(b)
    assert coverage_signature({"a.py": {(1, 2)}}) != coverage_signature({"b.py": {(1, 2)}})


def test_different_modules_are_not_duplicates(tmp_path):
    result = run_suite(tmp_path, {
        "a.py": "def value():\n    return 1\n",
        "b.py": "def value():\n    return 2\n",
        "test_example.py": "import a, b\ndef test_a():\n    assert a.value() == 1\ndef test_b():\n    assert b.value() == 2\n",
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert "W001" not in result.stdout
    assert "W003" not in result.stdout


def test_helpers_in_test_modules_remain_visible(tmp_path):
    result = run_suite(tmp_path, {
        "test_example.py": "def first():\n    return 1\ndef second():\n    return 2\ndef test_a():\n    assert first() == 1\ndef test_b():\n    assert second() == 2\ndef test_c():\n    assert first() == 1\n",
    })
    assert result.returncode == 0, result.stdout + result.stderr
    warnings = [line for line in result.stdout.splitlines() if "W001" in line]
    assert len(warnings) == 2
    assert any("test_a" in line for line in warnings)
    assert any("test_c" in line for line in warnings)
    assert not any("test_b" in line for line in warnings)
    assert "W003" not in result.stdout


@pytest.mark.parametrize("phase", ["setup", "teardown"])
def test_fixture_work_is_measured(tmp_path, phase):
    body = "    value()\n    yield\n" if phase == "setup" else "    yield\n    value()\n"
    result = run_suite(tmp_path, {
        "product.py": "def value():\n    return 1\n",
        "conftest.py": (
            "import pytest, json\nfrom product import value\n@pytest.fixture\ndef work():\n" + body
            + "\ndef pytest_sessionfinish(session):\n"
            + "    plugin = next(p for p in session.config.pluginmanager.get_plugins() if type(p).__name__ == 'FindDuplicateCoverage')\n"
            + "    with open('observations.json', 'w') as f:\n"
            + "        json.dump([cov.file_arcs and list(cov.file_arcs) for cov in plugin.groups.values()], f)\n"
        ),
        "test_example.py": "def test_a(work):\n    pass\ndef test_b(work):\n    pass\n",
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("W001") == 2
    observations = json.loads((tmp_path / "observations.json").read_text())
    assert observations
    assert all(str(tmp_path / "product.py") in files for files in observations)


def test_different_fixture_calls_are_distinguished(tmp_path):
    result = run_suite(tmp_path, {
        "product.py": "def first():\n    return 1\ndef second():\n    return 2\n",
        "test_example.py": "import pytest\nfrom product import first, second\n@pytest.fixture\ndef one():\n    return first()\n@pytest.fixture\ndef two():\n    return second()\ndef test_a(one):\n    assert one == 1\ndef test_b(two):\n    assert two == 2\n",
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert "W001" not in result.stdout


@pytest.mark.parametrize("source,expected", [
    ("def test_failure():\n    assert False\n", 1),
    ("def test_empty():\n    pass\n", 0),
    ("import pytest\n@pytest.mark.skip\ndef test_skip():\n    pass\n", 0),
    ("", 5),
])
def test_exit_codes_and_empty_observations(tmp_path, source, expected):
    result = run_suite(tmp_path, {"test_example.py": source})
    assert result.returncode == expected, result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_failed_and_skipped_tests_are_not_candidates(tmp_path):
    result = run_suite(tmp_path, {
        "product.py": "def value():\n    return 1\n",
        "test_example.py": "import pytest\nfrom product import value\ndef test_pass():\n    assert value() == 1\ndef test_fail():\n    assert value() == 2\ndef test_skip():\n    value()\n    pytest.skip()\n@pytest.mark.xfail\ndef test_xfail():\n    assert value() == 2\n",
    })
    assert result.returncode == 1
    assert "W001" not in result.stdout
    assert "W003" not in result.stdout


def test_parameter_ids_and_cautious_wording(tmp_path):
    result = run_suite(tmp_path, {
        "product.py": "def double(x):\n    return x * 2\n",
        "test_example.py": "import pytest\nfrom product import double\n@pytest.mark.parametrize(\"x\", [2, -2])\ndef test_double(x):\n    assert double(x) == x * 2\n",
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("W001") == 2
    assert "test_double[2]" in result.stdout
    assert "test_double[-2]" in result.stdout
    assert "does not prove equivalent assertions" in result.stdout
    assert "keeping only one" not in result.stdout
    assert "Consider remove" not in result.stdout


def test_overlap_with_redundant_intermediate_candidate():
    def cov(*values):
        return CoverageSet([], {"product.py": {(i, i + 1) for i in values}})
    big, a, redundant, b = cov(1, 2, 3, 4), cov(1, 2, 3), cov(1, 2), cov(4)
    result = find_fully_overlapped_sets([big, a, redundant, b])
    assert result == [(big, [a, b])]
    assert len(big) == 4
    assert find_fully_overlapped_sets([]) == []
    assert find_fully_overlapped_sets([CoverageSet([], {})]) == []
    assert find_fully_overlapped_sets([a]) == []


def test_teardown_failure_excludes_observation(tmp_path):
    result = run_suite(tmp_path, {
        "product.py": "def value():\n    return 1\n",
        "test_example.py": "import pytest\nfrom product import value\n@pytest.fixture\ndef broken():\n    yield\n    raise RuntimeError('teardown failed')\ndef test_a():\n    assert value() == 1\ndef test_b(broken):\n    assert value() == 1\n",
    })
    assert result.returncode == 1
    assert "W001" not in result.stdout


def test_collection_error_exit_code(tmp_path):
    result = run_suite(tmp_path, {"test_example.py": "raise RuntimeError('collection failed')\n"})
    assert result.returncode == 2
    assert "IndexError" not in result.stderr


def test_groups_are_per_run():
    from pytest_deduplicate import FindDuplicateCoverage
    first, second = FindDuplicateCoverage(), FindDuplicateCoverage()
    first.groups[()] = CoverageSet([], {})
    assert second.groups == {}

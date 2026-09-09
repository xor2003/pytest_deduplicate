import json

import pytest

from tests.test_analyzer import run_suite


PAIR = {
    "product.py": "def nonnegative(x):\n    return x >= 0\n",
    "test_example.py": "from product import nonnegative\ndef test_zero():\n    assert nonnegative(0)\ndef test_two():\n    assert nonnegative(2)\n",
}


def load_report(tmp_path):
    return json.loads((tmp_path / "report.json").read_text())


@pytest.mark.parametrize("collector", ["restart", "contexts"])
def test_source_and_explainable_json(tmp_path, collector):
    result = run_suite(tmp_path, dict(PAIR, helper="unused"), "--source", "product.py",
                       "--collector", collector, "--json", "report.json")
    assert result.returncode == 0, result.stdout + result.stderr
    report = load_report(tmp_path)
    assert report["schema_version"] == 1
    assert len(report["tests"]) == 2
    assert report["findings"][0]["kind"] == "identical"
    evidence = report["findings"][0]
    assert evidence["shared"] == {"product.py": [[-1, 2], [2, -1]]}
    assert evidence["unique"] == evidence["other_unique"] == {}
    assert evidence["shared_arc_count"] == 2
    for test in report["tests"]:
        assert set(test["file_arcs"]) == {"product.py"}
        assert test["duration"] >= 0
        assert set(test["phases"]) == {"setup", "call", "teardown"}


def test_omit_and_json_stdout(tmp_path):
    result = run_suite(tmp_path, PAIR, "--source", ".", "--omit", "*/product.py", "--json", "-")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["findings"] == []
    assert all(not test["file_arcs"] for test in report["tests"])
    assert "2 passed" in result.stderr


def test_contexts_match_restart_with_all_phases(tmp_path):
    files = {
        "product.py": "def setup():\n    return 1\ndef call(x):\n    if x:\n        return 2\n    return 3\ndef teardown():\n    return 4\n",
        "conftest.py": "import pytest, product\n@pytest.fixture\ndef work():\n    product.setup()\n    yield\n    product.teardown()\n",
        "test_example.py": "import product\ndef test_a(work):\n    assert product.call(True) == 2\ndef test_b(work):\n    assert product.call(False) == 3\n",
    }
    snapshots = []
    for collector in ("restart", "contexts"):
        result = run_suite(tmp_path, files, "--source", "product.py", "--collector", collector, "--json", "report.json")
        assert result.returncode == 0, result.stdout + result.stderr
        snapshots.append([test["file_arcs"] for test in load_report(tmp_path)["tests"]])
    assert snapshots[0] == snapshots[1]
    assert snapshots[0][0] != snapshots[0][1]
    for observation in snapshots[0]:
        arcs = observation["product.py"]
        assert [-1, 2] in arcs
        assert [-7, 8] in arcs


def test_stability_detects_order_dependency(tmp_path):
    files = {
        "product.py": "ready = False\ndef initialize():\n    global ready\n    ready = True\ndef value():\n    if ready:\n        return 1\n    return 0\n",
        "test_example.py": "from product import initialize, value\ndef test_initialize():\n    initialize()\ndef test_a():\n    assert value() == 1\ndef test_b():\n    assert value() == 1\n",
    }
    result = run_suite(tmp_path, files, "--source", "product.py", "--stability-runs", "1", "--json", "report.json")
    assert result.returncode == 0, result.stdout + result.stderr
    stability = load_report(tmp_path)["stability"]
    assert stability["tests"]["test_example.py::test_a"]["status"] == "unstable"
    assert stability["tests"]["test_example.py::test_b"]["status"] == "unstable"
    assert any(test["trial"].startswith("reverse-order") for test in stability["tests"]["test_example.py::test_a"]["observations"])


def test_stability_limit_and_stable_pair(tmp_path):
    result = run_suite(tmp_path, PAIR, "--source", "product.py", "--stability-runs", "1",
                       "--max-candidates", "1", "--json", "report.json")
    assert result.returncode == 0, result.stdout + result.stderr
    stability = load_report(tmp_path)["stability"]
    assert len(stability["tests"]) == 1
    assert len(stability["unchecked"]) == 1
    assert next(iter(stability["tests"].values()))["status"] == "stable_in_checked_runs"


def test_mutants_distinguish_equal_coverage_and_preserve_source(tmp_path):
    result = run_suite(tmp_path, PAIR, "--source", "product.py", "--mutations", "1", "--json", "report.json")
    assert result.returncode == 0, result.stdout + result.stderr
    mutations = load_report(tmp_path)["mutations"]
    assert mutations["status"] == "completed_sample"
    assert mutations["mutants"][0]["outcomes"] == {
        "test_example.py::test_zero": "killed", "test_example.py::test_two": "survived",
    }
    assert mutations["comparisons"][0]["status"] == "different_fault_detection"
    assert (tmp_path / "product.py").read_text() == PAIR["product.py"]


def test_mutation_requires_explicit_scope(tmp_path):
    result = run_suite(tmp_path, PAIR, "--mutations", "1")
    assert result.returncode == 2
    assert "requires explicit --source" in result.stderr


def test_benchmark_reports_samples_and_parity(tmp_path):
    result = run_suite(tmp_path, PAIR, "--source", "product.py", "--benchmark-collectors", "1", "--json", "report.json")
    assert result.returncode == 0, result.stdout + result.stderr
    benchmark = load_report(tmp_path)["benchmark"]
    assert benchmark["coverage_and_outcome_parity"] is True
    assert benchmark["failures"] == []
    assert set(benchmark["median_seconds"]) == {"off", "restart", "contexts"}
    assert all(len(values) == 1 for values in benchmark["samples_seconds"].values())


def test_timeout_is_not_a_killed_mutant():
    from pytest_deduplicate_checks import mutation_outcome
    assert mutation_outcome({"status": "timeout"}, "test_a", "product.py", 2) == "timeout"


def test_invalid_scope_and_counts(tmp_path):
    result = run_suite(tmp_path, PAIR, "--source", "absent")
    assert result.returncode == 2
    result = run_suite(tmp_path, PAIR, "--stability-runs", "-1")
    assert result.returncode == 2


def test_collection_failure_skips_checks(tmp_path):
    result = run_suite(tmp_path, {"test_bad.py": "raise RuntimeError()\n"}, "--stability-runs", "1", "--json", "report.json")
    assert result.returncode == 2
    assert load_report(tmp_path)["checks"]["status"] == "not_run"


def test_contexts_do_not_leak_failed_test_coverage(tmp_path):
    files = {
        "product.py": "def a():\n    return 1\ndef b():\n    return 2\n",
        "test_example.py": "from product import a, b\ndef test_fail():\n    assert a() == 0\ndef test_pass():\n    assert b() == 2\n",
    }
    result = run_suite(tmp_path, files, "--source", "product.py", "--collector", "contexts", "--json", "report.json")
    assert result.returncode == 1
    report = load_report(tmp_path)
    assert report["tests"][0]["eligible"] is False
    assert report["tests"][1]["file_arcs"] == {"product.py": [[-3, 4], [4, -3]]}
    assert report["findings"] == []


def test_real_optional_check_timeout_is_inconclusive(tmp_path):
    result = run_suite(tmp_path, PAIR, "--source", "product.py", "--stability-runs", "1",
                       "--max-candidates", "1", "--check-timeout", "0.001", "--json", "report.json")
    assert result.returncode == 0, result.stdout + result.stderr
    result = next(iter(load_report(tmp_path)["stability"]["tests"].values()))
    assert result["status"] == "inconclusive"
    assert result["observations"][0]["status"] == "timeout"


def test_containment_json_has_exact_extra_arcs(tmp_path):
    files = {
        "product.py": "def value(x):\n    if x:\n        return 1\n    return 2\n",
        "test_example.py": "from product import value\ndef test_small():\n    assert value(True) == 1\ndef test_other():\n    assert value(False) == 2\ndef test_both():\n    assert value(True) == 1\n    assert value(False) == 2\n",
    }
    result = run_suite(tmp_path, files, "--source", "product.py", "--json", "report.json")
    assert result.returncode == 0, result.stdout + result.stderr
    findings = load_report(tmp_path)["findings"]
    contained = next(f for f in findings if f["kind"] == "contained" and "test_example.py::test_small" in f["tests"])
    assert contained["unique"] == {}
    assert contained["other_unique"] == {"product.py": [[2, 4], [4, -1]]}
    combined = next(f for f in findings if f["kind"] == "combined")
    assert combined["unique_arc_count"] == 0
    assert combined["shared_arc_count"] == 5


def test_unknown_optional_child_failure_is_reported(tmp_path):
    # An initializer writes a file that removes the module before rerun collection.
    files = dict(PAIR)
    files["conftest.py"] = "from pathlib import Path\ndef pytest_sessionfinish(session):\n    Path('product.py').unlink(missing_ok=True)\n"
    result = run_suite(tmp_path, files, "--source", "product.py", "--stability-runs", "1",
                       "--max-candidates", "1", "--json", "report.json")
    assert result.returncode == 0, result.stdout + result.stderr
    status = next(iter(load_report(tmp_path)["stability"]["tests"].values()))["status"]
    assert status == "inconclusive"

"""Build the release inputs, install its wheel, and test the installed command.

The explicit staging list excludes unrelated local Cython experiments and
untracked setup.py files. No network is used for installing the built wheel;
build, setuptools, wheel, pytest and coverage must already be installed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILES = ("pyproject.toml", "README.md", "LICENSE", "pytest_deduplicate.py", "pytest_deduplicate_checks.py", "pytest_deduplicate_review.py", "pytest_deduplicate_import.py", "pytest_deduplicate_index.py", "pytest_deduplicate_artifacts.py")


def main():
    with tempfile.TemporaryDirectory(prefix="pytest-deduplicate-wheel-") as temp:
        work = Path(temp).resolve()
        source = work / "source"
        source.mkdir()
        for name in RELEASE_FILES:
            shutil.copy2(ROOT / name, source / name)
        subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--outdir", str(work / "dist")],
                       cwd=source, check=True)
        wheel, = (work / "dist").glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            assert "pytest_deduplicate.py" in archive.namelist()
            assert {name for name in RELEASE_FILES if name.endswith('.py')} <= set(archive.namelist())
            assert not any(name.endswith((".so", ".pyd", ".pyx")) for name in archive.namelist())
        envdir = work / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(envdir)
        bindir = envdir / ("Scripts" if os.name == "nt" else "bin")
        python = bindir / ("python.exe" if os.name == "nt" else "python")
        command = bindir / ("pytest_deduplicate.exe" if os.name == "nt" else "pytest_deduplicate")
        subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], check=True)
        consumer = work / "consumer"
        consumer.mkdir()
        (consumer / "product.py").write_text("def positive(x):\n    return x >= 0\n")
        (consumer / "test_example.py").write_text("from product import positive\ndef test_zero():\n    assert positive(0)\ndef test_two():\n    assert positive(2)\n")
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS"):
            env.pop(key, None)
        installed = subprocess.check_output([str(python), "-c", "import pytest_deduplicate; print(pytest_deduplicate.__file__)"],
                                            cwd=consumer, env=env, text=True).strip()
        assert Path(installed).resolve().is_relative_to(envdir), installed
        result = subprocess.run([str(command), "--source", "product.py", "--collector", "contexts",
                                 "--stability-runs", "1", "--max-candidates", "2", "--mutations", "1",
                                 "--html", "report.html", "--review-template", "reviews.json",
                                 "--json", "-", "-q", "-p", "no:cacheprovider"],
                                cwd=consumer, env=env, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout)
        assert report["findings"][0]["kind"] == "identical"
        assert report["stability"]["tests"]
        assert report["mutations"]["mutants"]
        assert report['findings'][0]['assessment']['status'] == 'different_fault_detection'
        assert report['tests'][0]['phase_file_arcs']['call']
        assert (consumer / 'report.html').exists()
        assert json.loads((consumer / 'reviews.json').read_text())['reviews']
        (consumer / "test_example.py").write_text("def test_fail():\n    assert False\n")
        failed = subprocess.run([str(command), "-q"], cwd=consumer, env=env, capture_output=True)
        assert failed.returncode == 1
        print("Wheel installation, installed imports, context collection, optional checks and exit codes passed.")


if __name__ == "__main__":
    main()

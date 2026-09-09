"""Opt-in fresh-process stability, sampled mutation and collector benchmarks."""
import ast
import copy
import json
import os
from pathlib import Path
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import tokenize


SCRIPT = Path(__file__).with_name("pytest_deduplicate.py").resolve()


def fingerprint(test):
    """Ignore timings, retaining outcomes and exact measured file/arc identities."""
    return {
        "eligible": test["eligible"], "file_arcs": test["file_arcs"],
        "phase_file_arcs": test.get('phase_file_arcs'),
        "phases": {name: (phase["outcome"], phase["xfail"])
                   for name, phase in test["phases"].items()},
    }


def candidate_ids(report, limit):
    from pytest_deduplicate_review import select_candidates
    selection = select_candidates(report, limit)
    return selection['selected'], selection['unchecked']


def rebase(value, original, destination):
    """Move absolute paths under the project into a sandbox, including omit globs."""
    value = str(value)
    prefix = str(original) + os.sep
    if value == str(original):
        return str(destination)
    if value.startswith(prefix):
        return str(destination) + value[len(str(original)):]
    return value


def run_child(root, options, pytest_args, selected=None, order=None, collector=None):
    root = Path(root).resolve()
    with tempfile.TemporaryDirectory(prefix="pytest-deduplicate-run-") as temp:
        output = Path(temp) / "report.json"
        request = Path(temp) / "request.json"
        original = Path.cwd().resolve()
        request.write_text(json.dumps({
            "pytest_args": [rebase(arg, original, root) for arg in pytest_args],
            "source": [rebase(str(Path(p).resolve()), original, root) for p in options.source],
            "omit": [rebase(p, original, root) for p in options.omit],
            "coverage_phase": options.coverage_phase,
            "collector": collector or options.collector, "selected": selected,
            "order": order, "output": str(output),
        }))
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = os.pathsep.join(rebase(p, original, root)
                                               for p in env["PYTHONPATH"].split(os.pathsep))
        started = time.perf_counter()
        # A timeout also stops descendants on POSIX, so an abandoned check cannot
        # keep accessing a sandbox while it is being removed.
        process = subprocess.Popen([sys.executable, str(SCRIPT), "--_request", str(request)],
                                   cwd=root, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   start_new_session=os.name == "posix")
        try:
            log, _ = process.communicate(timeout=options.check_timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            log, _ = process.communicate()
            return {"status": "timeout", "wall_seconds": time.perf_counter() - started,
                    "log_tail": log[-2000:]}
        result = {"status": "complete", "returncode": process.returncode,
                  "wall_seconds": time.perf_counter() - started}
        try:
            result["report"] = json.loads(output.read_text())
        except (OSError, ValueError):
            result.update(status="error", log_tail=log[-2000:])
        if "report" in result and result["report"]["errors"]:
            result.update(status="error", log_tail=log[-2000:])
        return result


def compact_run(run):
    return {key: value for key, value in run.items() if key != "report"}


def check_stability(report, options, pytest_args, candidates, unchecked):
    baseline = {test["nodeid"]: test for test in report["tests"]}
    results = {nodeid: {"status": "stable_in_checked_runs", "observations": []} for nodeid in candidates}
    rng = random.Random(options.seed)
    trials = []
    for repeat in range(options.stability_runs):
        trials.extend((f"isolated-{repeat + 1}", [nodeid]) for nodeid in candidates)
        if len(candidates) > 1:
            shuffled = list(candidates)
            rng.shuffle(shuffled)
            trials.extend([(f"original-order-{repeat + 1}", candidates),
                           (f"reverse-order-{repeat + 1}", list(reversed(candidates))),
                           (f"shuffled-order-{repeat + 1}", shuffled)])
    for label, ordered in trials:
        print("Stability check: " + label, file=sys.stderr, flush=True)
        run = run_child(Path.cwd(), options, pytest_args, ordered, ordered)
        observations = {test["nodeid"]: test for test in run.get("report", {}).get("tests", [])}
        for nodeid in ordered:
            item = results[nodeid]
            current = observations.get(nodeid)
            if run["status"] != "complete" or current is None:
                status = "inconclusive"
                evidence = compact_run(run)
            elif fingerprint(current) != fingerprint(baseline[nodeid]):
                status = "unstable"
                evidence = {"observed": fingerprint(current), "baseline": fingerprint(baseline[nodeid])}
            else:
                status, evidence = "matches", {}
            item["observations"].append({"trial": label, "order": list(ordered), "status": status, **evidence})
            if status == "unstable" or (status == "inconclusive" and item["status"] != "unstable"):
                item["status"] = status
    return {"seed": options.seed, "runs_per_scenario": options.stability_runs,
            "tests": results, "unchecked": unchecked}


def mutations_for_source(source):
    """Yield independent, single-line edits; leave line numbers/encoding intact.

    This deliberately small operator set samples faults. It is not a complete
    mutation engine and matching outcomes never imply semantic equivalence.
    """
    tree = ast.parse(source)
    swaps = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Add,
             ast.Div: ast.Mult, ast.FloorDiv: ast.Mult, ast.Mod: ast.Mult,
             ast.GtE: ast.Gt, ast.Gt: ast.GtE, ast.LtE: ast.Lt, ast.Lt: ast.LtE,
             ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
    lines = source.splitlines(keepends=True)
    seen = set()
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for node in sorted(ast.walk(tree), key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0))):
        if not hasattr(node, "end_lineno") or node.end_lineno != node.lineno:
            continue
        mutated = copy.deepcopy(node)
        if isinstance(node, ast.BinOp) and type(node.op) in swaps:
            mutated.op = swaps[type(node.op)]()
        elif isinstance(node, ast.Compare) and type(node.ops[0]) in swaps:
            mutated.ops[0] = swaps[type(node.ops[0])]()
        elif isinstance(node, ast.Constant) and type(node.value) in (bool, int):
            mutated.value = not node.value if type(node.value) is bool else node.value + 1
        else:
            continue
        replacement = ast.unparse(mutated)
        line = lines[node.lineno - 1].encode("utf-8")
        before = line[node.col_offset:node.end_col_offset].decode("utf-8")
        signature = (node.lineno, node.col_offset, replacement)
        if signature in seen:
            continue
        seen.add(signature)
        edited = list(lines)
        edited[node.lineno - 1] = (line[:node.col_offset] + replacement.encode("utf-8")
                                  + line[node.end_col_offset:]).decode("utf-8")
        text = "".join(edited)
        try:
            compile(text, "<mutant>", "exec")
        except SyntaxError:
            continue
        enclosing = [n for n in functions if n.lineno <= node.lineno <= n.end_lineno]
        owner = min(enclosing, key=lambda n: n.end_lineno - n.lineno) if enclosing else None
        yield {"function": f"{owner.name}:{owner.lineno}" if owner else '<module>',
               "operator": type(node.op).__name__ if isinstance(node, ast.BinOp) else
                           type(node.ops[0]).__name__ if isinstance(node, ast.Compare) else type(node.value).__name__,
               "line": node.lineno, "column": node.col_offset + 1,
               "before": before, "after": replacement, "source": text}


def mutation_outcome(run, nodeid, filename, line):
    if run["status"] != "complete":
        return run["status"]
    tests = [test for test in run["report"]["tests"] if test["nodeid"] == nodeid]
    if len(tests) != 1:
        return "error"
    test = tests[0]
    reached = any(line in arc for arc in test["file_arcs"].get(filename, []))
    if not reached:
        return "not_reached"
    phases = test["phases"]
    if set(phases) != {"setup", "call", "teardown"}:
        return "error"
    if any(phases[phase]["outcome"] != "passed" for phase in ("setup", "teardown")):
        return "error"
    if any(phase["xfail"] for phase in phases.values()):
        return "inconclusive"
    if phases["call"]["outcome"] == "failed" and run["returncode"] == 1:
        return "killed"
    if test["eligible"] and run["returncode"] == 0:
        return "survived"
    return "inconclusive"


def check_mutations(report, options, pytest_args, candidates, unchecked):
    root = Path.cwd().resolve()
    result = {"experimental": True, "operator_set": "single-line arithmetic, comparisons, integer/boolean constants",
              "limit": options.mutations, "unchecked": unchecked, "baseline": {}, "mutants": [], "comparisons": []}
    for source in options.source:
        if not Path(source).resolve().is_relative_to(root):
            result["error"] = "Mutation source must be inside the current project directory"
            return result
    observations = {test["nodeid"]: test for test in report["tests"]}
    measured = {}
    for nodeid in candidates:
        for filename, arcs in observations[nodeid]["file_arcs"].items():
            path = (root / filename).resolve()
            if path.is_relative_to(root) and any(path == Path(s).resolve() or Path(s).resolve() in path.parents for s in options.source):
                measured.setdefault(filename, set()).update(line for arc in arcs for line in arc if line > 0)
    buckets = {}
    seen_per_bucket = {}
    rng = random.Random(options.seed)
    for filename, lines in sorted(measured.items()):
        path = root / filename
        if path.suffix != ".py":
            continue
        try:
            with tokenize.open(path) as stream:
                source, encoding = stream.read(), stream.encoding
            for mutant in mutations_for_source(source):
                if mutant["line"] in lines:
                    key = (filename, mutant['function'], mutant['operator'])
                    seen_per_bucket[key] = seen_per_bucket.get(key, 0) + 1
                    bucket = buckets.setdefault(key, [])
                    edit = dict(mutant, file=filename, encoding=encoding)
                    if len(bucket) < options.mutations:
                        bucket.append(edit)
                    else:
                        slot = rng.randrange(seen_per_bucket[key])
                        if slot < options.mutations:
                            bucket[slot] = edit
        except (OSError, SyntaxError, UnicodeError) as exc:
            result.setdefault("skipped_files", []).append({"file": filename, "reason": str(exc)})
    edits = []
    schedules = {}
    for key in sorted(buckets):
        schedules.setdefault(key[0], []).append(key)
    filenames = sorted(schedules)
    rng.shuffle(filenames)
    for keys in schedules.values():
        rng.shuffle(keys)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    while filenames and len(edits) < options.mutations:
        for filename in list(filenames):
            keys = schedules[filename]
            key = keys.pop(0)
            edits.append(buckets[key].pop())
            if buckets[key]:
                keys.append(key)
            if not keys:
                filenames.remove(filename)
            if len(edits) == options.mutations:
                break
    result['sampling'] = {'strategy': 'seeded round-robin file/function/operator buckets',
                          'seed': options.seed, 'available_buckets': len(buckets),
                          'supported_edits': sum(seen_per_bucket.values())}
    result['confirmation_runs'] = options.mutation_repeats
    if not candidates or not edits:
        result["status"] = "no_candidates" if not candidates else "no_supported_mutants"
        return result
    with tempfile.TemporaryDirectory(prefix="pytest-deduplicate-mutations-") as temp:
        temp = Path(temp).resolve()
        snapshot = temp / "snapshot"
        ignored = shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist", ".tox", ".nox", "node_modules", ".idea")
        total = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            excluded = ignored(directory, dirs + files)
            dirs[:] = [d for d in dirs if d not in excluded]
            for name in files:
                path = Path(directory) / name
                if name not in excluded and not path.is_symlink():
                    total += path.stat().st_size
                    if total > options.mutation_snapshot_mb * 1024 * 1024:
                        result.update(status='snapshot_limit_exceeded', snapshot_bytes_at_least=total)
                        return result
        result['snapshot_bytes'] = total
        shutil.copytree(root, snapshot, symlinks=True, ignore=ignored)
        valid = []
        # Every trial receives a fresh copy: test-generated files cannot leak
        # from baseline or one mutant into another trial.
        for nodeid in candidates:
            trial = Path(temp) / "trial"
            shutil.copytree(snapshot, trial, symlinks=True)
            try:
                run = run_child(trial, options, pytest_args, [nodeid], [nodeid])
                tests = run.get("report", {}).get("tests", [])
                healthy = (run["status"] == "complete" and run["returncode"] == 0
                           and len(tests) == 1 and tests[0]["eligible"]
                           and fingerprint(tests[0]) == fingerprint(observations[nodeid]))
                result["baseline"][nodeid] = "passed" if healthy else "inconclusive"
                if not healthy:
                    result.setdefault("baseline_diagnostics", {})[nodeid] = {
                        **compact_run(run), "observed": [fingerprint(test) for test in tests],
                        "expected": fingerprint(observations[nodeid]),
                    }
                if healthy:
                    valid.append(nodeid)
            finally:
                shutil.rmtree(trial)
        for number, edit in enumerate(edits, 1):
            print(f"Mutation check {number}/{len(edits)}: {edit['file']}:{edit['line']}", file=sys.stderr, flush=True)
            mutant = {key: value for key, value in edit.items() if key not in ("source", "encoding")}
            mutant.update(id=f"M{number:04d}", outcomes={})
            for nodeid in valid:
                outcomes = []
                for repeat in range(options.mutation_repeats):
                    trial = Path(temp) / "trial"
                    shutil.copytree(snapshot, trial, symlinks=True)
                    try:
                        target = trial / edit["file"]
                        if not target.resolve().is_relative_to(trial):
                            outcomes.append('external_symlink')
                            break
                        target.write_text(edit["source"], encoding=edit["encoding"])
                        run = run_child(trial, options, pytest_args, [nodeid], [nodeid])
                        outcomes.append(mutation_outcome(run, nodeid, edit["file"], edit["line"]))
                        if run["status"] != "complete":
                            mutant.setdefault("diagnostics", {})[nodeid] = compact_run(run)
                    finally:
                        shutil.rmtree(trial)
                mutant.setdefault('trials', {})[nodeid] = outcomes
                mutant['outcomes'][nodeid] = outcomes[0] if len(set(outcomes)) == 1 else 'inconclusive'
            result["mutants"].append(mutant)
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            distinguishing = []
            compared = []
            for mutant in result["mutants"]:
                a, b = mutant["outcomes"].get(left), mutant["outcomes"].get(right)
                if a in ("killed", "survived") and b in ("killed", "survived"):
                    compared.append(mutant["id"])
                    if a != b:
                        distinguishing.append(mutant["id"])
            verdict = "different_fault_detection" if distinguishing else (
                "same_on_sampled_mutants" if compared and len(compared) == len(result["mutants"]) else "inconclusive")
            result["comparisons"].append({"tests": [left, right], "status": verdict,
                                          "compared": compared, "distinguishing": distinguishing})
    result["status"] = "completed_sample"
    return result


def benchmark_collectors(options, pytest_args):
    samples = {name: [] for name in ("off", "restart", "contexts")}
    observations = {name: [] for name in samples}
    failures = []
    for repeat in range(options.benchmark_collectors):
        modes = list(samples)
        # Rotate order to avoid always giving one mode warmed filesystem caches.
        modes = modes[repeat % 3:] + modes[:repeat % 3]
        for mode in modes:
            print(f"Collector benchmark {repeat + 1}: {mode}", file=sys.stderr, flush=True)
            run = run_child(Path.cwd(), options, pytest_args, collector=mode)
            if run["status"] != "complete" or run["returncode"] != 0:
                failures.append({"collector": mode, "repeat": repeat + 1, **compact_run(run)})
                continue
            samples[mode].append(run["wall_seconds"])
            observations[mode].append({test["nodeid"]: fingerprint(test) for test in run["report"]["tests"]})
    reference = observations["restart"][0] if observations["restart"] else None
    parity = (not failures and reference is not None
              and all(run == reference for mode in ("restart", "contexts") for run in observations[mode]))
    medians = {mode: statistics.median(values) for mode, values in samples.items() if values}
    overhead = {mode: (value / medians["off"] - 1) * 100 for mode, value in medians.items()
                if mode != "off" and medians.get("off")}
    return {"samples_seconds": samples, "median_seconds": medians, "overhead_percent": overhead,
            "coverage_and_outcome_parity": parity, "failures": failures,
            "note": "Fresh-process wall times include interpreter and pytest startup; no automatic default change."}


def run_checks(report, options, pytest_args):
    from pytest_deduplicate_review import select_candidates
    report["selection"] = select_candidates(report, options.max_candidates)
    candidates, unchecked = report["selection"]["selected"], report["selection"]["unchecked"]
    if report["pytest_exit_code"] != 0 or report["errors"]:
        report["checks"] = {"status": "not_run", "reason": "baseline run was unsuccessful"}
        return
    if options.stability_runs:
        report["stability"] = check_stability(report, options, pytest_args, candidates, unchecked)
    if options.mutations:
        report["mutations"] = check_mutations(report, options, pytest_args, candidates, unchecked)
    if options.benchmark_collectors:
        report["benchmark"] = benchmark_collectors(options, pytest_args)

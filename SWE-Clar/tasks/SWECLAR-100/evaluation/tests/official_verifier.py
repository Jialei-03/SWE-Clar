#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
PROJECT_DIR = Path(os.environ.get("SWECLAR_PROJECT_DIR", os.getcwd())).resolve()
LOG_DIR = Path(os.environ.get("SWECLAR_LOG_DIR", "/logs/verifier"))
GATES = [{'test_id': 'RU-001-T01', 'file': 'tests/kiosk_contract.py', 'ru_id': 'RU-001'}, {'test_id': 'RU-002-T01', 'file': 'tests/kiosk_contract.py', 'ru_id': 'RU-002'}, {'test_id': 'RU-003-T01', 'file': 'tests/kiosk_contract.py', 'ru_id': 'RU-003'}, {'test_id': 'RU-004-T01', 'file': 'tests/kiosk_contract.py', 'ru_id': 'RU-004'}, {'test_id': 'RU-005-T01', 'file': 'tests/kiosk_contract.py', 'ru_id': 'RU-005'}]
SOURCE_TEST_CACHE = None

def structured_gate_result(output, ru_id):
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            continue
        harness_ok = not (
            payload.get("harness_ok") is False
            or payload.get("infrastructure_error") is True
        )
        if not harness_ok:
            return {
                "passed": False,
                "harness_ok": False,
                "infrastructure_errors": payload.get("infrastructure_errors") or [],
            }
        observed = [r.get("ru_id", r.get("ru")) for r in results if isinstance(r, dict)]
        expected = {gate["ru_id"] for gate in GATES}
        if (len(observed) != len(results) or any(not isinstance(ru, str) for ru in observed)
                or len(observed) != len(set(observed)) or set(observed) != expected
                or any(type(r.get("passed")) is not bool for r in results)):
            return {"passed": False, "harness_ok": False,
                    "infrastructure_errors": ["Incomplete, duplicate or malformed requirement results"]}
        for result in results:
            if not isinstance(result, dict):
                continue
            observed_ru = result.get("ru_id", result.get("ru"))
            if observed_ru == ru_id and isinstance(result.get("passed"), bool):
                return {
                    "passed": result["passed"],
                    "harness_ok": harness_ok,
                    "infrastructure_errors": payload.get("infrastructure_errors") or [],
                }
    return None

def run_gate(gate):
    global SOURCE_TEST_CACHE
    env = dict(os.environ)
    candidate = PROJECT_DIR / "solution.py"
    env["SWECLAR_SOLUTION_PATH"] = str(candidate)
    env["CANDIDATE_ROOT"] = str(PROJECT_DIR)
    env["TARGET_ROOT"] = str(PROJECT_DIR)
    env["PROJECT_ROOT"] = str(PROJECT_DIR)
    env["SWECLAR_TEST_RU"] = gate["ru_id"]
    path = TEST_DIR / Path(gate["file"]).name
    if not path.is_file():
        return False, f"evaluator file is missing: {path.name}", False
    selector = gate["ru_id"].lower().replace("-", "_")
    if path.is_file():
        source = path.read_text(encoding="utf-8", errors="ignore")
        required_env = set(re.findall(r"os\.environ\[.([A-Z][A-Z0-9_]*).\]", source))
        for name in required_env:
            if name in env:
                continue
            if name.endswith(("_DIR", "_ROOT")):
                env[name] = str(PROJECT_DIR)
            elif name.endswith(("_IMPL", "_IMPLEMENTATION", "_SOLUTION", "_PATH")):
                env[name] = str(candidate)
    try:
        source_test = TEST_DIR / "source_test.sh"
        structured_launcher = (
            source_test.is_file()
            and "SWECLAR_STRUCTURED_RESULTS" in source_test.read_text(
                encoding="utf-8", errors="ignore"
            )
        )
        use_source_test = (
            source_test.is_file()
            and (
                Path(gate["file"]).name == "source_test.sh"
                or structured_launcher
            )
        )
        if use_source_test:
            command = ["bash", str(source_test), str(PROJECT_DIR)]
            if structured_launcher:
                if SOURCE_TEST_CACHE is None:
                    full_env = dict(env)
                    full_env.pop("SWECLAR_TEST_RU", None)
                    SOURCE_TEST_CACHE = subprocess.run(
                        command,
                        cwd=PROJECT_DIR,
                        env=full_env,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                completed = SOURCE_TEST_CACHE
            else:
                completed = subprocess.run(command, cwd=PROJECT_DIR, env=env, text=True, capture_output=True, check=False)
        elif path.suffix == ".py":
            pytest_command = [shutil.which("pytest")] if shutil.which("pytest") else [sys.executable, "-m", "pytest"]
            selector_args = ["-k", selector] if selector in source.casefold() else []
            command = [*pytest_command, "-q", str(path), *selector_args, "-o", "addopts="]
            completed = subprocess.run(command, cwd=PROJECT_DIR, env=env, text=True, capture_output=True, check=False)
        elif path.suffix == ".sh":
            command = ["bash", str(path)]
            completed = subprocess.run(command, cwd=PROJECT_DIR, env=env, text=True, capture_output=True, check=False)
        elif path.suffix in {".js", ".mjs", ".cjs"}:
            env["TARGET_ROOT"] = str(PROJECT_DIR)
            node_require_root = Path("/workspace/package.json")
            if "SWECLAR_NODE_REQUIRE_ROOT" not in env and node_require_root.is_file():
                env["SWECLAR_NODE_REQUIRE_ROOT"] = str(node_require_root)
            command = ["node", str(path)]
            completed = subprocess.run(command, cwd=PROJECT_DIR, env=env, text=True, capture_output=True, check=False)
        elif path.suffix in {".c", ".cc", ".cpp", ".cxx"}:
            cpp = path.suffix != ".c"
            source_suffixes = {".cc", ".cpp", ".cxx"} if cpp else {".c"}
            sources = sorted(
                item for item in PROJECT_DIR.rglob("*")
                if item.is_file()
                and item.suffix in source_suffixes
                and not any(part in {".git", "build", "tests"} for part in item.parts)
            )
            include_dirs = [PROJECT_DIR]
            include_dirs.extend(
                item for item in PROJECT_DIR.rglob("include") if item.is_dir()
            )
            with tempfile.TemporaryDirectory(prefix="fcb-native-gate-") as temp:
                binary = Path(temp) / "gate"
                command = [
                    os.environ.get("CXX" if cpp else "CC", "c++" if cpp else "cc"),
                    "-std=c++11" if cpp else "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    *[f"-I{directory}" for directory in include_dirs],
                    *[str(item) for item in sources],
                    str(path),
                    "-o",
                    str(binary),
                ]
                compiled = subprocess.run(command, cwd=PROJECT_DIR, env=env, text=True, capture_output=True, check=False)
                if compiled.returncode != 0:
                    detail = "\n".join(part.strip() for part in (compiled.stdout, compiled.stderr) if part.strip())
                    return False, (detail or "native test did not compile")[-4000:]
                completed = subprocess.run([str(binary)], cwd=PROJECT_DIR, env=env, text=True, capture_output=True, check=False)
        else:
            return False, f"unsupported evaluator file: {path.name}", False
    except Exception as error:
        return False, f"evaluator adapter error: {type(error).__name__}: {error}"[-4000:], False
    detail = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    structured = structured_gate_result(detail, gate["ru_id"])
    if structured is not None:
        if not structured["harness_ok"]:
            return False, ("evaluator infrastructure error\n" + detail)[-4000:], False
        return structured["passed"], detail[-4000:], True
    if structured_launcher:
        return False, ("structured evaluator omitted a valid requirement result\n" + detail)[-4000:], False
    return completed.returncode == 0, detail[-4000:], True

def main():
    results = []
    for gate in GATES:
        outcome = run_gate(gate)
        if len(outcome) == 2:
            passed, detail = outcome
            evaluator_ok = True
        else:
            passed, detail, evaluator_ok = outcome
        results.append({
            "id": gate["test_id"],
            "verdict": passed,
            "skipped": not evaluator_ok,
            "detail": detail or ("passed" if passed else "failed"),
        })
    harness_ok = bool(results) and all(not item["skipped"] for item in results)
    reward = int(all(item["verdict"] for item in results)) if harness_ok else None
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "gates.json").write_text(json.dumps({"gates": results, "harness_ok": harness_ok}, ensure_ascii=False, indent=2) + "\n")
    reward_path = LOG_DIR / "reward.txt"
    if reward is None:
        reward_path.unlink(missing_ok=True)
    else:
        reward_path.write_text(f"{reward}\n")
    print(json.dumps({"gates": results, "reward": reward, "harness_ok": harness_ok}, ensure_ascii=False))
    return 0 if harness_ok else 2

if __name__ == "__main__":
    raise SystemExit(main())

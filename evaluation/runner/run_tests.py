from __future__ import annotations

import ast
import contextlib
import errno
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path("/workspace/repo")
HIDDEN_TEST_ROOT = Path("/workspace/hidden-tests")
ENVIRONMENT_ALLOWLIST = (
    "HOME",
    "HOSTNAME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONHASHSEED",
    "PYTHONDONTWRITEBYTECODE",
)
NETWORK_PROBE_ADDRESS = ("1.1.1.1", 53)
NETWORK_PROBE_TIMEOUT_SECONDS = 0.25
EVIDENCE_ARTIFACT_ID = "runner_result_json"
HIDDEN_MANIFEST_NAME = "manifest.json"
HIDDEN_MANIFEST_VERSION = "1.0"
MAX_HIDDEN_TESTS = 128
TEST_ID_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,}"
)
CHILD_TIMEOUT_SECONDS = 30
MAX_CHILD_OUTPUT_BYTES = 1_048_576
CHILD_DRAIN_JOIN_SECONDS = 1
CHILD_BOOTSTRAP = (
    "import sys, unittest; "
    "sys.path[:0] = sys.argv[1].split(chr(0x1f)); "
    "program = unittest.main(module=None, argv=['unittest', '-v', sys.argv[2]], exit=False); "
    "raise SystemExit(0 if program.result.wasSuccessful() else 1)"
)
NETWORK_BLOCKED_ERRNOS = frozenset(
    {
        errno.EACCES,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.ENETUNREACH,
        errno.EPERM,
    }
)

_LAST_SANITIZED_ENVIRONMENT: dict[str, str] = {}


def run_evaluator(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    hidden_test_root: Path = HIDDEN_TEST_ROOT,
    connector: Callable[..., Any] = socket.create_connection,
    source_environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repository = _canonical_directory(repository_root)
    sanitized_environment = _sanitize_environment(
        os.environ if source_environment is None else source_environment
    )
    global _LAST_SANITIZED_ENVIRONMENT
    _LAST_SANITIZED_ENVIRONMENT = dict(sanitized_environment)

    with _temporary_environment(sanitized_environment):
        network_result = _network_probe(connector)
        if network_result["status"] != "passed":
            return _result_payload([network_result])
        hidden_tests = _canonical_directory(hidden_test_root)
        if repository == hidden_tests:
            raise ValueError("evaluator roots must be distinct canonical directories")
        _reject_symlinks(hidden_tests)
        test_ids = _load_hidden_manifest(hidden_tests)
        hidden_results = _run_hidden_tests(repository, hidden_tests, test_ids)
    return _result_payload([network_result, *hidden_results])


def last_sanitized_environment() -> dict[str, str]:
    return dict(_LAST_SANITIZED_ENVIRONMENT)


def _canonical_directory(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ValueError("evaluator root must be an absolute canonical path")
    try:
        resolved = value.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("evaluator root must exist") from exc
    if value != resolved or not resolved.is_dir():
        raise ValueError("evaluator root must equal its canonical directory")
    return resolved


def _reject_symlinks(root: Path) -> None:
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("hidden-test root must not contain symlinks")


def _sanitize_environment(source: Mapping[str, str]) -> dict[str, str]:
    return {
        key: str(source[key])
        for key in ENVIRONMENT_ALLOWLIST
        if key in source and isinstance(source[key], str)
    }


@contextlib.contextmanager
def _temporary_environment(environment: Mapping[str, str]) -> Iterator[None]:
    original = dict(os.environ)
    os.environ.clear()
    os.environ.update(environment)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _network_probe(connector: Callable[..., Any]) -> dict[str, Any]:
    started = time.monotonic_ns()
    connection = None
    try:
        connection = connector(
            NETWORK_PROBE_ADDRESS,
            timeout=NETWORK_PROBE_TIMEOUT_SECONDS,
        )
    except OSError as exc:
        status = "passed" if exc.errno in NETWORK_BLOCKED_ERRNOS else "failed"
    except Exception:
        status = "error"
    else:
        status = "failed"
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                status = "error"
    return _test_record("network_probe", status, started)


def _load_hidden_manifest(hidden_tests: Path) -> list[str]:
    manifest_path = hidden_tests / HIDDEN_MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("hidden-test manifest is unreadable") from exc
    if type(payload) is not dict or set(payload) != {"version", "tests"}:
        raise ValueError("hidden-test manifest must be a closed object")
    tests = payload.get("tests")
    if (
        payload.get("version") != HIDDEN_MANIFEST_VERSION
        or not isinstance(tests, list)
        or not tests
        or len(tests) > MAX_HIDDEN_TESTS
        or any(
            not isinstance(test_id, str)
            or TEST_ID_PATTERN.fullmatch(test_id) is None
            for test_id in tests
        )
    ):
        raise ValueError("hidden-test manifest contains invalid test IDs")
    if len(tests) != len(set(tests)):
        raise ValueError("hidden-test manifest test IDs must be unique")
    discovered = _static_hidden_test_inventory(hidden_tests)
    if set(tests) != set(discovered):
        raise ValueError("manifest must equal the complete hidden-test inventory")
    return list(tests)


def _static_hidden_test_inventory(hidden_tests: Path) -> list[str]:
    discovered: list[str] = []
    for path in sorted(hidden_tests.rglob("test*.py")):
        if not path.is_file():
            continue
        relative_module = path.relative_to(hidden_tests).with_suffix("")
        if any(not part.isidentifier() for part in relative_module.parts):
            raise ValueError("hidden tests must use importable module paths")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ValueError("hidden test source is unreadable") from exc
        unittest_aliases, test_case_aliases = _unittest_aliases(tree)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "load_tests" or node.name.startswith("test"):
                    raise ValueError("hidden suite must use a static hidden-test inventory")
                continue
            if not isinstance(node, ast.ClassDef):
                continue
            methods = [
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith("test")
            ]
            if not methods:
                continue
            if not any(
                _is_unittest_case_base(base, unittest_aliases, test_case_aliases)
                for base in node.bases
            ):
                raise ValueError("hidden suite must use a static hidden-test inventory")
            module_name = ".".join(relative_module.parts)
            discovered.extend(
                f"{module_name}.{node.name}.{method_name}"
                for method_name in methods
            )
    if not discovered or len(discovered) != len(set(discovered)):
        raise ValueError("hidden suite must have a unique static hidden-test inventory")
    return discovered


def _unittest_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    module_aliases: set[str] = set()
    case_aliases: set[str] = set()
    supported_cases = {"TestCase", "IsolatedAsyncioTestCase"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "unittest":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "unittest":
            for alias in node.names:
                if alias.name in supported_cases:
                    case_aliases.add(alias.asname or alias.name)
    return module_aliases, case_aliases


def _is_unittest_case_base(
    base: ast.expr,
    module_aliases: set[str],
    case_aliases: set[str],
) -> bool:
    if isinstance(base, ast.Name):
        return base.id in case_aliases
    return (
        isinstance(base, ast.Attribute)
        and isinstance(base.value, ast.Name)
        and base.value.id in module_aliases
        and base.attr in {"TestCase", "IsolatedAsyncioTestCase"}
    )


def _run_hidden_tests(
    repository: Path,
    hidden_tests: Path,
    test_ids: list[str],
) -> list[dict[str, Any]]:
    child_environment = dict(_LAST_SANITIZED_ENVIRONMENT)
    python_paths = [hidden_tests, repository / "src", repository]
    serialized_paths = "\x1f".join(
        str(path) for path in python_paths if path.is_dir()
    )
    return [
        _run_hidden_test(hidden_tests, test_id, serialized_paths, child_environment)
        for test_id in test_ids
    ]


def _run_hidden_test(
    hidden_tests: Path,
    test_id: str,
    serialized_paths: str,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    started = time.monotonic_ns()
    try:
        completed = _run_bounded_child(
            [sys.executable, "-I", "-c", CHILD_BOOTSTRAP, serialized_paths, test_id],
            cwd=hidden_tests,
            environment=environment,
            timeout_seconds=CHILD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return _test_record(test_id, "error", started)
    except Exception:
        return _test_record(test_id, "error", started)
    status = _classify_unittest_process(completed)
    return _test_record(test_id, status, started)


def _run_bounded_child(
    argv: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if process.stdout is None:
        process.kill()
        process.wait()
        raise RuntimeError("child output pipe unavailable")

    retained = bytearray()

    def drain_output() -> None:
        try:
            while chunk := process.stdout.read(65_536):
                remaining = MAX_CHILD_OUTPUT_BYTES - len(retained)
                if remaining > 0:
                    retained.extend(chunk[:remaining])
        except (OSError, ValueError):
            return

    drain_thread = threading.Thread(target=drain_output, daemon=True)
    drain_thread.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        drain_thread.join(CHILD_DRAIN_JOIN_SECONDS)
        process.stdout.close()
        raise
    drain_thread.join(CHILD_DRAIN_JOIN_SECONDS)
    if drain_thread.is_alive():
        process.stdout.close()
        drain_thread.join(CHILD_DRAIN_JOIN_SECONDS)
    else:
        process.stdout.close()
    return subprocess.CompletedProcess(
        args=argv,
        returncode=returncode,
        stdout=bytes(retained),
        stderr=b"",
    )


def _classify_unittest_process(completed: subprocess.CompletedProcess[bytes]) -> str:
    output = _bounded_child_output(completed.stdout) + "\n" + _bounded_child_output(
        completed.stderr
    )
    normalized = output.casefold()
    if "ran 1 test" not in normalized:
        return "error"
    if "skipped=" in normalized or "expected failures=" in normalized:
        return "skipped"
    if completed.returncode == 0 and re.search(r"(?m)^ok(?:\s|$)", normalized):
        return "passed"
    if completed.returncode != 0:
        return "failed"
    return "error"


def _bounded_child_output(value: bytes | None) -> str:
    if not value:
        return ""
    return value[:MAX_CHILD_OUTPUT_BYTES].decode("utf-8", errors="replace")


def _test_record(name: str, status: str, started_ns: int) -> dict[str, Any]:
    duration_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
    return {
        "name": name,
        "status": status,
        "duration_ms": duration_ms,
        "evidence_artifact_id": EVIDENCE_ARTIFACT_ID,
    }


def _result_payload(tests: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(test["status"] == "passed" for test in tests)
    failed = sum(test["status"] in {"failed", "error"} for test in tests)
    full_suite_passed = passed == len(tests) and failed == 0
    return {
        "tests": tests,
        "full_suite_passed": full_suite_passed,
        "passed": passed,
        "failed": failed,
        "exit_code": 0 if full_suite_passed else 1,
        "timed_out": False,
    }


def main() -> int:
    try:
        payload = run_evaluator()
    except Exception:
        payload = _result_payload(
            [
                {
                    "name": "network_probe",
                    "status": "error",
                    "duration_ms": 0,
                    "evidence_artifact_id": EVIDENCE_ARTIFACT_ID,
                }
            ]
        )
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return int(payload["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())

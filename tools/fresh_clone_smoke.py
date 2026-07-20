from __future__ import annotations

import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from recallpack.demo import (  # noqa: E402
    build_demo_payload,
    discover_secondary_hero_fixture_roots,
)
from recallpack.budget import SelectedPack, count_canonical_json_tokens  # noqa: E402
from recallpack.submission_bundle import scan_submission_bundle  # noqa: E402
from recallpack.tokenization import ENCODING_NAME  # noqa: E402


MEMORY_ID_PATTERN = re.compile(r"mem_[0-9a-f]{32}")
EXPECTED_RUNTIME_DEPENDENCIES = {
    "jsonschema": "4.26.0",
    "pyyaml": "6.0.3",
    "tiktoken": "0.13.0",
}

REQUIRED_PUBLIC_FILES = (
    "LICENSE",
    "README.md",
    "requirements-v4.txt",
    "SUBMISSION_MANIFEST.md",
    "deploy/alibaba-cloud/Dockerfile",
    "docs/deployment/alibaba-cloud-proof.md",
    "docs/plans/2026-06-24-recallpack-v3.2.2.md",
    "docs/submission/local-readiness-report.md",
    "docs/submission/public-repo-readiness-report.md",
    "docs/submission/public-release-gate.md",
    "docs/submission/review-packet.md",
    "docs/submission/architecture-diagram.md",
    "docs/submission/demo-media-package.md",
    "docs/submission/demo-video-script.md",
    "docs/submission/skeptical-judge-qa.md",
    "fixtures/project-a/sessions.jsonl",
    "fixtures/project-b/sessions.jsonl",
    "fixtures/project-c/sessions.jsonl",
    "fixtures/project-d/sessions.jsonl",
    "fixtures/project-e/sessions.jsonl",
    "fixtures/project-f-realistic/sessions.jsonl",
    "fixtures/project-g-auth-mode/sessions.jsonl",
    "fixtures/trace-intake/sample-consent-trace.json",
    "src/recallpack/demo_server.py",
    "src/recallpack/trace_intake.py",
    "tests/test_real_trace_intake.py",
    "tests/test_submission_bundle.py",
    "tools/validate_real_trace_intake.py",
    "tools/fresh_clone_smoke.py",
    "tools/judge_smoke.py",
    "tools/capture_demo_screenshots.py",
    "tools/devpost_preflight.py",
    "tools/export_devpost_materials.py",
    "tools/export_evidence_index.py",
    "tools/final_submission_gate.py",
    "tools/public_repo_preflight.py",
    "web/app.js",
    "web/index.html",
)

REQUIRED_MANIFEST_SNIPPETS = (
    "## Judge Quick Checks",
    "MemoryAgent",
    "No credentials are required for local checks.",
    "PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .",
    "PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full",
    "python3 tools/devpost_preflight.py",
    "python3 tools/export_devpost_materials.py",
    "python3 tools/export_evidence_index.py",
    "python3 tools/final_submission_gate.py",
    "python3 tools/public_repo_preflight.py",
    "curl http://127.0.0.1:8789/api/health",
    "python3 tools/judge_smoke.py --url http://127.0.0.1:8789",
    "POST /observe",
    "POST /compile",
)


def run_fresh_clone_smoke(
    source: str | Path,
    timeout: int = 45,
    full: bool = False,
) -> dict[str, Any]:
    source_path = Path(source).resolve()
    if not source_path.is_dir():
        raise FileNotFoundError(f"Fresh-clone source is not a directory: {source_path}")

    with tempfile.TemporaryDirectory(prefix="recallpack-fresh-clone-") as tmp:
        temp_root = Path(tmp)
        clone = temp_root / "repo"
        shutil.copytree(source_path, clone, ignore=_ignore_runtime_artifacts)
        env = _fresh_env(clone, temp_root)
        port = _free_port()

        _assert_public_surface(clone)
        checks: dict[str, str] = {"public_surface": "passed"}
        _run(_py_compile_command(clone), cwd=clone, env=env, timeout=timeout)
        checks["py_compile"] = "passed"
        unit_command = (
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-v",
            ]
            if full
            else [
                sys.executable,
                "-m",
                "unittest",
                "tests.test_demo_server",
                "tests.test_judge_smoke",
                "tests.test_submission_packet",
                "tests.test_submission_docs",
                "-v",
            ]
        )
        _run(unit_command, cwd=clone, env=env, timeout=timeout)
        checks["unit_full" if full else "unit_subset"] = "passed"
        _run(["node", "--check", "web/app.js"], cwd=clone, env=env, timeout=timeout)
        checks["js_check"] = "passed"
        smoke = _run_server_smoke(clone, env, port=port, timeout=timeout)
        checks["server_smoke"] = "passed"

        return {
            "status": "passed",
            "source": str(source_path),
            "copied_to_temp": True,
            "unit_mode": "full" if full else "subset",
            "checks": checks,
            "judge_smoke": "passed",
            "judge_smoke_result": smoke,
        }


def _ignore_runtime_artifacts(directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in {".git", "__pycache__", ".DS_Store"}:
            ignored.add(name)
        elif name.endswith((".pyc", ".sqlite", ".sqlite3", ".db")):
            ignored.add(name)
    return ignored


def _fresh_env(clone: Path, temp_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(clone / "src")
    env["PYTHONPYCACHEPREFIX"] = str(temp_root / "pycache")
    env["RECALLPACK_SQLITE_PATH"] = str(temp_root / "recallpack.sqlite3")
    env["RECALLPACK_FRESH_CLONE_CHILD"] = "1"
    return env


def _assert_public_surface(clone: Path) -> None:
    forbidden = [
        clone / "AGENTS.md",
        clone / "docs" / "execution",
        clone / "dist",
    ]
    present = [path.relative_to(clone).as_posix() for path in forbidden if path.exists()]
    if present:
        raise AssertionError(f"Fresh clone includes private/internal paths: {present}")
    missing = [
        relative
        for relative in REQUIRED_PUBLIC_FILES
        if not (clone / relative).is_file()
    ]
    if missing:
        raise AssertionError(f"Fresh clone missing required public files: {missing}")
    manifest_text = (clone / "SUBMISSION_MANIFEST.md").read_text(encoding="utf-8")
    missing_manifest_snippets = [
        snippet
        for snippet in REQUIRED_MANIFEST_SNIPPETS
        if snippet not in manifest_text
    ]
    if missing_manifest_snippets:
        raise AssertionError(
            "Fresh clone manifest is missing judge quick checks: "
            f"{missing_manifest_snippets}"
        )
    _assert_runtime_dependencies(clone)
    _assert_static_demo_data_current(clone)
    scan = scan_submission_bundle(clone)
    findings = {key: value for key, value in scan.items() if value}
    if findings:
        raise AssertionError(f"Fresh clone scan failed: {findings}")


def _assert_static_demo_data_current(clone: Path) -> None:
    actual = _read_static_demo_payload(clone / "web" / "demo-data.js")
    try:
        _assert_exact_demo_token_counts(actual)
    except (KeyError, TypeError) as exc:
        raise AssertionError(
            "Fresh clone static demo data is stale; invalid payload shape"
        ) from exc
    live_trace_path = clone / "docs" / "submission" / "live-qwen-trace.json"
    live_e2e_trace_path = clone / "docs" / "submission" / "live-qwen-e2e-trace.json"
    fresh_m98_trace_path = clone / "docs" / "submission" / "live-qwen-m98-rerun-trace.json"
    projectodyssey_trace_path = (
        clone / "docs" / "submission" / "projectodyssey-live-qwen-e2e-trace.json"
    )
    expected = build_demo_payload(
        clone / "fixtures" / "project-a",
        clone / "fixtures" / "micro-suite",
        live_qwen_trace_path=live_trace_path if live_trace_path.is_file() else None,
        live_qwen_e2e_trace_path=(
            live_e2e_trace_path if live_e2e_trace_path.is_file() else None
        ),
        fresh_m98_live_rerun_trace_path=(
            fresh_m98_trace_path if fresh_m98_trace_path.is_file() else None
        ),
        projectodyssey_live_qwen_e2e_trace_path=(
            projectodyssey_trace_path if projectodyssey_trace_path.is_file() else None
        ),
        secondary_fixture_roots=discover_secondary_hero_fixture_roots(clone),
    )
    if _canonical_demo_payload(actual) != _canonical_demo_payload(expected):
        raise AssertionError("Fresh clone static demo data is stale; rerun tools/build_demo_data.py")


def _assert_runtime_dependencies(clone: Path) -> None:
    requirements_path = clone / "requirements-v4.txt"
    pinned = _read_pinned_requirements(requirements_path)
    if pinned != EXPECTED_RUNTIME_DEPENDENCIES:
        raise AssertionError(
            "Fresh clone runtime dependency manifest mismatch: "
            f"expected={EXPECTED_RUNTIME_DEPENDENCIES} actual={pinned}"
        )

    mismatches = []
    for package_name, expected_version in EXPECTED_RUNTIME_DEPENDENCIES.items():
        try:
            actual_version = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            actual_version = "missing"
        if actual_version != expected_version:
            mismatches.append(
                f"{package_name}: expected={expected_version} actual={actual_version}"
            )
    if mismatches:
        raise AssertionError(
            "Fresh clone runtime dependency version mismatch: " + "; ".join(mismatches)
        )

    try:
        actual_encoding = _load_runtime_encoding_name()
    except Exception as exc:
        raise AssertionError(
            "Fresh clone runtime tokenizer unavailable: "
            f"required_encoding={ENCODING_NAME}"
        ) from exc
    if actual_encoding != ENCODING_NAME:
        raise AssertionError(
            "Fresh clone runtime tokenizer mismatch: "
            f"expected={ENCODING_NAME} actual={actual_encoding}"
        )


def _read_pinned_requirements(path: Path) -> dict[str, str]:
    pinned: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("==") != 1:
            raise AssertionError(
                f"Fresh clone runtime dependency is not exactly pinned: {line}"
            )
        package_name, version = line.split("==", 1)
        normalized_name = package_name.strip().casefold().replace("_", "-")
        if not normalized_name or not version.strip() or normalized_name in pinned:
            raise AssertionError(
                f"Fresh clone runtime dependency pin is invalid: {line}"
            )
        pinned[normalized_name] = version.strip()
    return pinned


def _load_runtime_encoding_name() -> str:
    import tiktoken  # type: ignore

    return str(tiktoken.get_encoding(ENCODING_NAME).name)


def _read_static_demo_payload(path: Path) -> dict[str, Any]:
    prefix = "window.RECALLPACK_DEMO_DATA = "
    suffix = ";\n"
    text = path.read_text(encoding="utf-8")
    if not text.startswith(prefix) or not text.endswith(suffix):
        raise AssertionError("Fresh clone static demo data is stale; unexpected web/demo-data.js format")
    return json.loads(text[len(prefix) : -len(suffix)])


def _canonical_demo_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "<dynamic_exact_count>"
                if key == "memory_segment_tokens"
                else _canonical_demo_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_canonical_demo_payload(item) for item in value]
    if isinstance(value, str) and MEMORY_ID_PATTERN.fullmatch(value):
        return "mem_<dynamic>"
    return value


def _assert_exact_demo_token_counts(payload: dict[str, Any]) -> None:
    pack = payload["recall"]["pack"]
    _assert_memory_segment_count(pack["memories"], pack["memory_segment_tokens"])
    for variant in payload["recall"]["variants"]:
        _assert_memory_segment_count(
            variant["selected_context"],
            variant["metrics"]["memory_segment_tokens"],
        )


def _assert_memory_segment_count(memories: list[dict[str, Any]], recorded: Any) -> None:
    canonical = SelectedPack(memories=memories).to_canonical_json()
    recomputed = count_canonical_json_tokens(canonical)
    if recorded != recomputed:
        raise AssertionError(
            "Fresh clone static demo data has an invalid exact token count: "
            f"recorded={recorded} recomputed={recomputed}"
        )


def _py_compile_command(clone: Path) -> list[str]:
    files = [
        *sorted((clone / "tests").glob("test_*.py")),
        *sorted((clone / "tools").glob("*.py")),
        *sorted((clone / "src" / "recallpack").glob("*.py")),
    ]
    return [sys.executable, "-m", "py_compile", *[path.as_posix() for path in files]]


def _run(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode != 0:
        rendered = " ".join(command)
        raise RuntimeError(
            f"Command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _run_server_smoke(
    clone: Path,
    env: dict[str, str],
    port: int,
    timeout: int,
) -> dict[str, Any]:
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "recallpack.demo_server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--root",
            ".",
        ],
        cwd=clone,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_server(port, timeout=timeout)
        result = _run(
            [
                sys.executable,
                "tools/judge_smoke.py",
                "--url",
                f"http://127.0.0.1:{port}",
            ],
            cwd=clone,
            env=env,
            timeout=timeout,
        )
        return json.loads(result.stdout)
    finally:
        try:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        finally:
            for stream in (server.stdout, server.stderr):
                if stream is not None:
                    stream.close()


def _wait_for_server(port: int, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - exact socket race varies.
            last_error = exc
        time.sleep(0.2)
    raise TimeoutError(f"Demo server did not become ready: {last_error}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy a RecallPack bundle to a temp directory and run judge-facing smoke checks."
    )
    parser.add_argument(
        "--source",
        default=".",
        help="Sanitized bundle or public repo directory to rehearse from.",
    )
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "Run full public-test discovery inside the temp copy. Recursive smoke "
            "tests and custody-bound tests requiring the excluded private execution "
            "manifest skip with explicit reasons."
        ),
    )
    args = parser.parse_args(argv)
    result = run_fresh_clone_smoke(args.source, timeout=args.timeout, full=args.full)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

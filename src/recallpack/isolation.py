from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

REPO_ROOT_ENV = "RECALLPACK_EVALUATOR_REPO_ROOT"
HIDDEN_TEST_ROOT_ENV = "RECALLPACK_EVALUATOR_HIDDEN_TEST_ROOT"
ENV_ALLOWLIST = (
    "HOME",
    "HOSTNAME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONHASHSEED",
    "PYTHONDONTWRITEBYTECODE",
)
SAFE_ENVIRONMENT = {
    "HOME": "/tmp",
    "HOSTNAME": "recallpack-evaluator",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}
HOST_ROOT_KEYS = {
    "repository": REPO_ROOT_ENV,
    "hidden_tests": HIDDEN_TEST_ROOT_ENV,
}
HOST_PATH_POLICY = {
    "mount_source_rule": "realpath_equals_configured_root",
    "configured_roots_must_be_absolute": True,
    "repository_and_hidden_tests_distinct": True,
    "symlink_escape": "reject",
    "record_resolved_paths": False,
}
CONTAINER_PATHS = {
    "repository": "/workspace/repo",
    "hidden_tests": "/workspace/hidden-tests",
    "tmp": "/tmp",
}
RESOURCE_LIMITS = {
    "cpus": 1,
    "memory_bytes": 1073741824,
    "pids": 128,
    "wall_timeout_seconds": 120,
    "tmpfs_size_bytes": 67108864,
}
EXECUTION_USER = {
    "username": "recallpack",
    "uid": 65532,
    "gid": 65532,
    "non_root": True,
}
ISOLATION_FLAGS = {
    "network": "none",
    "read_only_root": True,
    "drop_all_capabilities": True,
    "no_new_privileges": True,
    "docker_socket_mounted": False,
    "tmp_is_tmpfs": True,
    "repository_mount_mode": "rw",
    "hidden_test_mount_mode": "ro",
}
SAFE_COMMAND = (
    "/usr/bin/env",
    "-i",
    "HOME=/tmp",
    "HOSTNAME=recallpack-evaluator",
    "LANG=C.UTF-8",
    "LC_ALL=C.UTF-8",
    "PATH=/usr/local/bin:/usr/bin:/bin",
    "PYTHONHASHSEED=0",
    "PYTHONDONTWRITEBYTECODE=1",
    "/usr/local/bin/python",
    "/runner/run_tests.py",
)
TIMEOUT_SECONDS = 120
TIMEOUT_OUTPUT_LIMIT = 8192
CONTAINER_CLEANUP_TIMEOUT_SECONDS = 10
_CONTAINER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_TEST_RESULT_KEYS = {
    "tests",
    "full_suite_passed",
    "passed",
    "failed",
    "exit_code",
    "timed_out",
}
_TEST_KEYS = {"name", "status", "duration_ms", "evidence_artifact_id"}
_TEST_STATUSES = {"passed", "failed", "error", "skipped"}
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_RECEIPT_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class HostRoots:
    repository_root: Path
    hidden_test_root: Path


@dataclass(frozen=True)
class IsolatedExecutionBinding:
    variant_id: str
    patch_sha256: str
    repository_tree_sha256: str
    hidden_test_tree_sha256: str
    execution_nonce: str
    docker_argv_sha256: str
    authority_mode: str
    execution_manifest_sha256: str | None = None
    scenario_id: str | None = None
    slot_index: int | None = None
    attempt_no: int | None = None
    repository_snapshot_sha256: str | None = None
    frozen_hidden_test_tree_sha256: str | None = None


@dataclass(frozen=True)
class ProductionExecutionIdentity:
    execution_manifest_sha256: str
    scenario_id: str
    slot_index: int
    attempt_no: int
    repository_snapshot_sha256: str
    hidden_test_tree_sha256: str


@dataclass(frozen=True)
class _ProductionExecutionReceipt:
    payload_sha256: str
    hmac_sha256: str


@dataclass(frozen=True)
class IsolatedSuiteResult:
    exit_code: int | None
    stdout: str
    stderr: str
    json_result: dict[str, Any] | None
    blocked: bool
    timed_out: bool
    failure_code: str | None
    host_fallback_used: bool
    container_name: str | None = None
    cleanup_attempted: bool = False
    cleanup_succeeded: bool | None = None
    execution_binding: IsolatedExecutionBinding | None = None
    execution_receipt: object | None = None


class DockerRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: int,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        ...


def resolve_host_roots(configured_env: Mapping[str, str]) -> HostRoots:
    if set(configured_env) != {REPO_ROOT_ENV, HIDDEN_TEST_ROOT_ENV}:
        raise ValueError(
            "host roots must use only "
            f"{REPO_ROOT_ENV} and {HIDDEN_TEST_ROOT_ENV}"
        )
    repository_root = _resolve_root_value(configured_env[REPO_ROOT_ENV])
    hidden_test_root = _resolve_root_value(configured_env[HIDDEN_TEST_ROOT_ENV])
    if repository_root == hidden_test_root:
        raise ValueError("host roots must be distinct")
    return HostRoots(
        repository_root=repository_root,
        hidden_test_root=hidden_test_root,
    )


def build_docker_argv(
    *,
    evaluator_contract: Mapping[str, Any],
    image_digest: str,
    repository_root: str | Path,
    hidden_test_root: str | Path,
    command: Sequence[str],
    container_name: str,
    inherited_env: Mapping[str, str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    _validate_evaluator_contract(evaluator_contract)
    if image_digest != evaluator_contract["image_digest"]:
        raise ValueError("invalid_sandbox_evidence: image digest disagreement")
    repository_root_path = _resolve_root_value(str(repository_root))
    hidden_test_root_path = _resolve_root_value(str(hidden_test_root))
    if repository_root_path == hidden_test_root_path:
        raise ValueError("host roots must be distinct")
    command_tuple = tuple(command)
    if command_tuple != SAFE_COMMAND:
        raise ValueError("invalid_sandbox_evidence: unsafe command")
    if _CONTAINER_NAME_PATTERN.fullmatch(container_name) is None:
        raise ValueError("invalid_sandbox_evidence: unsafe container name")
    env = _build_child_env(inherited_env)
    argv = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        ISOLATION_FLAGS["network"],
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{EXECUTION_USER['uid']}:{EXECUTION_USER['gid']}",
        "--cpus",
        str(RESOURCE_LIMITS["cpus"]),
        "--memory",
        str(RESOURCE_LIMITS["memory_bytes"]),
        "--pids-limit",
        str(RESOURCE_LIMITS["pids"]),
        "--tmpfs",
        f"{CONTAINER_PATHS['tmp']}:size={RESOURCE_LIMITS['tmpfs_size_bytes']}",
        "--mount",
        (
            "type=bind,"
            f"src={repository_root_path},"
            f"dst={CONTAINER_PATHS['repository']},"
            "readonly=false"
        ),
        "--mount",
        (
            "type=bind,"
            f"src={hidden_test_root_path},"
            f"dst={CONTAINER_PATHS['hidden_tests']},"
            "readonly=true"
        ),
    ]
    for key in evaluator_contract["environment_allowlist"]:
        argv.extend(["-e", key])
    argv.append(image_digest)
    argv.extend(command_tuple)
    return argv, env


def run_isolated_suite(
    *,
    evaluator_contract: Mapping[str, Any],
    image_digest: str,
    repository_root: str | Path,
    hidden_test_root: str | Path,
    command: Sequence[str],
    docker_runner: DockerRunner = subprocess.run,
    docker_cleanup_runner: DockerRunner = subprocess.run,
    inherited_env: Mapping[str, str] | None = None,
    container_name: str | None = None,
    execution_binding: IsolatedExecutionBinding | None = None,
) -> IsolatedSuiteResult:
    container_name = container_name or f"recallpack-eval-{secrets.token_hex(8)}"
    argv, env = build_docker_argv(
        evaluator_contract=evaluator_contract,
        image_digest=image_digest,
        repository_root=repository_root,
        hidden_test_root=hidden_test_root,
        command=command,
        container_name=container_name,
        inherited_env=inherited_env,
    )
    _validate_requested_execution_binding(
        execution_binding,
        argv=argv,
        docker_runner=docker_runner,
        docker_cleanup_runner=docker_cleanup_runner,
    )
    try:
        completed = docker_runner(
            argv,
            env=env,
            timeout=TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return _finalize_execution_result(
            IsolatedSuiteResult(
                exit_code=None,
                stdout="",
                stderr=str(exc),
                json_result=None,
                blocked=True,
                timed_out=False,
                failure_code="sandbox_unavailable",
                host_fallback_used=False,
                container_name=container_name,
            ),
            execution_binding,
        )
    except subprocess.TimeoutExpired as exc:
        cleanup_succeeded = _cleanup_container(
            container_name,
            cleanup_runner=docker_cleanup_runner,
            env=env,
        )
        if not cleanup_succeeded:
            raise RuntimeError(
                f"sandbox_cleanup_failed: container={container_name}"
            ) from exc
        return _finalize_execution_result(
            IsolatedSuiteResult(
                exit_code=None,
                stdout=_bounded_timeout_text(exc.stdout),
                stderr=_bounded_timeout_text(exc.stderr),
                json_result=None,
                blocked=True,
                timed_out=True,
                failure_code="sandbox_timeout",
                host_fallback_used=False,
                container_name=container_name,
                cleanup_attempted=True,
                cleanup_succeeded=True,
            ),
            execution_binding,
        )

    stdout = _coerce_text(completed.stdout)
    stderr = _coerce_text(completed.stderr)
    if completed.returncode >= 125:
        return _finalize_execution_result(
            IsolatedSuiteResult(
                exit_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                json_result=None,
                blocked=True,
                timed_out=False,
                failure_code="sandbox_unavailable",
                host_fallback_used=False,
                container_name=container_name,
            ),
            execution_binding,
        )
    json_result = _parse_json_result(stdout, returncode=completed.returncode)
    return _finalize_execution_result(
        IsolatedSuiteResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            json_result=json_result,
            blocked=False,
            timed_out=bool(json_result["timed_out"]),
            failure_code=None,
            host_fallback_used=False,
            container_name=container_name,
        ),
        execution_binding,
    )


def execution_invocation_sha256(
    *,
    argv: Sequence[str],
    variant_id: str,
    patch_sha256: str,
    repository_tree_sha256: str,
    hidden_test_tree_sha256: str,
    execution_nonce: str,
    production_identity: ProductionExecutionIdentity | None = None,
) -> str:
    payload = {
        "argv": list(argv),
        "variant_id": variant_id,
        "patch_sha256": patch_sha256,
        "repository_tree_sha256": repository_tree_sha256,
        "hidden_test_tree_sha256": hidden_test_tree_sha256,
        "execution_nonce": execution_nonce,
        "production_identity": (
            asdict(production_identity) if production_identity is not None else None
        ),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def has_valid_production_execution_receipt(
    result: IsolatedSuiteResult,
    *,
    expected_identity: ProductionExecutionIdentity,
) -> bool:
    receipt = result.execution_receipt
    binding = result.execution_binding
    if (
        type(receipt) is not _ProductionExecutionReceipt
        or type(binding) is not IsolatedExecutionBinding
        or binding.authority_mode not in {"production_docker", "patch_not_executed"}
        or type(expected_identity) is not ProductionExecutionIdentity
        or not execution_binding_matches_identity(binding, expected_identity)
    ):
        return False
    payload = _execution_receipt_payload(result)
    expected_payload_sha256 = hashlib.sha256(payload).hexdigest()
    expected_hmac = hmac.new(_RECEIPT_KEY, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(
        receipt.payload_sha256,
        expected_payload_sha256,
    ) and hmac.compare_digest(receipt.hmac_sha256, expected_hmac)


def _seal_production_nonexecution_result(
    result: IsolatedSuiteResult,
    *,
    expected_identity: ProductionExecutionIdentity,
) -> IsolatedSuiteResult:
    binding = result.execution_binding
    if (
        type(result) is not IsolatedSuiteResult
        or type(binding) is not IsolatedExecutionBinding
        or type(expected_identity) is not ProductionExecutionIdentity
        or binding.authority_mode != "patch_not_executed"
        or not execution_binding_matches_identity(binding, expected_identity)
        or binding.repository_tree_sha256
        != expected_identity.repository_snapshot_sha256
        or binding.hidden_test_tree_sha256 != expected_identity.hidden_test_tree_sha256
        or _SHA256_PATTERN.fullmatch(binding.patch_sha256) is None
        or _SHA256_PATTERN.fullmatch(binding.docker_argv_sha256) is None
        or not binding.execution_nonce
        or result.execution_receipt is not None
        or not result.blocked
        or result.exit_code is not None
        or result.stdout != ""
        or result.stderr != ""
        or result.json_result is not None
        or result.timed_out
        or not isinstance(result.failure_code, str)
        or not result.failure_code
        or result.failure_code in {"sandbox_timeout", "sandbox_unavailable"}
        or result.host_fallback_used
        or result.container_name is not None
        or result.cleanup_attempted
        or result.cleanup_succeeded is not None
    ):
        raise ValueError(
            "invalid_sandbox_evidence: production nonexecution result is malformed"
        )
    return _finalize_execution_result(result, binding)


def _validate_requested_execution_binding(
    binding: IsolatedExecutionBinding | None,
    *,
    argv: Sequence[str],
    docker_runner: DockerRunner,
    docker_cleanup_runner: DockerRunner,
) -> None:
    if binding is None:
        return
    if type(binding) is not IsolatedExecutionBinding:
        raise ValueError(
            "invalid_sandbox_evidence: production execution binding is invalid"
        )
    production_identity = _production_identity_from_binding(binding)
    if (
        binding.authority_mode != "production_docker"
        or docker_runner is not subprocess.run
        or docker_cleanup_runner is not subprocess.run
        or production_identity is None
        or not binding.variant_id
        or not binding.execution_nonce
        or any(
            _SHA256_PATTERN.fullmatch(value) is None
            for value in (
                binding.patch_sha256,
                binding.repository_tree_sha256,
                binding.hidden_test_tree_sha256,
                binding.docker_argv_sha256,
            )
        )
    ):
        raise ValueError(
            "invalid_sandbox_evidence: production execution binding is invalid"
        )
    expected = execution_invocation_sha256(
        argv=argv,
        variant_id=binding.variant_id,
        patch_sha256=binding.patch_sha256,
        repository_tree_sha256=binding.repository_tree_sha256,
        hidden_test_tree_sha256=binding.hidden_test_tree_sha256,
        execution_nonce=binding.execution_nonce,
        production_identity=production_identity,
    )
    if not hmac.compare_digest(binding.docker_argv_sha256, expected):
        raise ValueError(
            "invalid_sandbox_evidence: Docker invocation binding mismatch"
        )


def execution_binding_matches_identity(
    binding: IsolatedExecutionBinding,
    identity: ProductionExecutionIdentity,
) -> bool:
    return (
        type(binding) is IsolatedExecutionBinding
        and type(identity) is ProductionExecutionIdentity
        and _production_identity_from_binding(binding) == identity
    )


def _production_identity_from_binding(
    binding: IsolatedExecutionBinding,
) -> ProductionExecutionIdentity | None:
    if (
        _SHA256_PATTERN.fullmatch(binding.execution_manifest_sha256 or "") is None
        or not binding.scenario_id
        or not isinstance(binding.slot_index, int)
        or isinstance(binding.slot_index, bool)
        or binding.slot_index < 0
        or not isinstance(binding.attempt_no, int)
        or isinstance(binding.attempt_no, bool)
        or binding.attempt_no < 1
        or _SHA256_PATTERN.fullmatch(binding.repository_snapshot_sha256 or "") is None
        or _SHA256_PATTERN.fullmatch(binding.frozen_hidden_test_tree_sha256 or "") is None
    ):
        return None
    return ProductionExecutionIdentity(
        execution_manifest_sha256=binding.execution_manifest_sha256,
        scenario_id=binding.scenario_id,
        slot_index=binding.slot_index,
        attempt_no=binding.attempt_no,
        repository_snapshot_sha256=binding.repository_snapshot_sha256,
        hidden_test_tree_sha256=binding.frozen_hidden_test_tree_sha256,
    )


def _finalize_execution_result(
    result: IsolatedSuiteResult,
    binding: IsolatedExecutionBinding | None,
) -> IsolatedSuiteResult:
    if binding is None:
        return result
    bound = replace(result, execution_binding=binding)
    payload = _execution_receipt_payload(bound)
    receipt = _ProductionExecutionReceipt(
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        hmac_sha256=hmac.new(_RECEIPT_KEY, payload, hashlib.sha256).hexdigest(),
    )
    return replace(bound, execution_receipt=receipt)


def _execution_receipt_payload(result: IsolatedSuiteResult) -> bytes:
    binding = result.execution_binding
    if type(binding) is not IsolatedExecutionBinding:
        return b""
    return _canonical_json_bytes(
        {
            "binding": asdict(binding),
            "container_name": result.container_name,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "json_result": result.json_result,
            "blocked": result.blocked,
            "timed_out": result.timed_out,
            "failure_code": result.failure_code,
            "host_fallback_used": result.host_fallback_used,
            "cleanup_attempted": result.cleanup_attempted,
            "cleanup_succeeded": result.cleanup_succeeded,
        }
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _cleanup_container(
    container_name: str,
    *,
    cleanup_runner: DockerRunner,
    env: Mapping[str, str],
) -> bool:
    try:
        completed = cleanup_runner(
            ["docker", "rm", "-f", container_name],
            env=dict(env),
            timeout=CONTAINER_CLEANUP_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return completed.returncode == 0


def _validate_evaluator_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("environment_allowlist") != list(ENV_ALLOWLIST):
        raise ValueError("invalid_sandbox_evidence: environment allowlist disagreement")
    if contract.get("host_root_keys") != HOST_ROOT_KEYS:
        raise ValueError("invalid_sandbox_evidence: host root keys disagreement")
    if contract.get("host_path_policy") != HOST_PATH_POLICY:
        raise ValueError("invalid_sandbox_evidence: host path policy disagreement")
    if contract.get("container_paths") != CONTAINER_PATHS:
        raise ValueError("invalid_sandbox_evidence: container paths disagreement")
    if contract.get("resource_limits") != RESOURCE_LIMITS:
        raise ValueError("invalid_sandbox_evidence: resource limits disagreement")
    if contract.get("execution_user") != EXECUTION_USER:
        raise ValueError("invalid_sandbox_evidence: execution user disagreement")
    if contract.get("isolation_flags") != ISOLATION_FLAGS:
        raise ValueError("invalid_sandbox_evidence: isolation flags disagreement")
    image_digest = contract.get("image_digest")
    base_image_digest = contract.get("base_image_digest")
    if not _valid_digest(image_digest) or not _valid_digest(base_image_digest):
        raise ValueError("invalid_sandbox_evidence: digest format disagreement")
    if image_digest == base_image_digest:
        raise ValueError("invalid_sandbox_evidence: digest separation disagreement")


def _build_child_env(
    inherited_env: Mapping[str, str] | None,
) -> dict[str, str]:
    del inherited_env
    return dict(SAFE_ENVIRONMENT)


def _resolve_root_value(path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("host root must be a non-empty string")
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("host root must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("host root must exist") from exc
    if not resolved.is_dir():
        raise ValueError("host root must be a directory")
    if str(resolved) != path_value:
        raise ValueError("host root must equal its realpath")
    return resolved


def _parse_json_result(stdout: str, *, returncode: int) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_test_result") from exc
    _validate_json_result(payload, returncode=returncode)
    return payload


def _validate_json_result(payload: Any, *, returncode: int) -> None:
    if not isinstance(payload, dict) or set(payload) != _TEST_RESULT_KEYS:
        raise ValueError("invalid_test_result")
    tests = payload.get("tests")
    if not isinstance(tests, list) or len(tests) < 2:
        raise ValueError("invalid_test_result")

    full_suite_passed = payload.get("full_suite_passed")
    passed = payload.get("passed")
    failed = payload.get("failed")
    exit_code = payload.get("exit_code")
    timed_out = payload.get("timed_out")
    if not isinstance(full_suite_passed, bool) or not isinstance(timed_out, bool):
        raise ValueError("invalid_test_result")
    if not _is_plain_int(passed) or not _is_plain_int(failed) or not _is_plain_int(exit_code):
        raise ValueError("invalid_test_result")
    if passed < 0 or failed < 0 or exit_code != returncode:
        raise ValueError("invalid_test_result")

    seen_names: set[str] = set()
    network_probe_status: str | None = None
    computed_passed = 0
    computed_failed = 0
    for item in tests:
        if not isinstance(item, dict) or set(item) != _TEST_KEYS:
            raise ValueError("invalid_test_result")
        name = item.get("name")
        status = item.get("status")
        duration_ms = item.get("duration_ms")
        evidence_artifact_id = item.get("evidence_artifact_id")
        if (
            not isinstance(name, str)
            or not name
            or name in seen_names
            or not isinstance(status, str)
            or status not in _TEST_STATUSES
            or not _is_plain_int(duration_ms)
            or duration_ms < 0
            or not isinstance(evidence_artifact_id, str)
            or not evidence_artifact_id
        ):
            raise ValueError("invalid_test_result")
        seen_names.add(name)
        if status == "passed":
            computed_passed += 1
        elif status in {"failed", "error"}:
            computed_failed += 1
        if name == "network_probe":
            network_probe_status = status

    if passed != computed_passed or failed != computed_failed:
        raise ValueError("invalid_test_result")
    expected_full_suite_passed = (
        computed_passed == len(tests)
        and computed_failed == 0
        and not timed_out
        and exit_code == 0
    )
    if full_suite_passed != expected_full_suite_passed:
        raise ValueError("invalid_test_result")
    if (
        network_probe_status != "passed"
        or tests[0].get("name") != "network_probe"
        or sum(item.get("name") == "network_probe" for item in tests) != 1
    ):
        raise ValueError("invalid_sandbox_evidence")


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _bounded_timeout_text(value: str | bytes | None) -> str:
    text = _coerce_text(value)
    if len(text) <= TIMEOUT_OUTPUT_LIMIT:
        return text
    return text[:TIMEOUT_OUTPUT_LIMIT]


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_digest(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    suffix = value[7:]
    return len(suffix) == 64 and all(char in "0123456789abcdef" for char in suffix)

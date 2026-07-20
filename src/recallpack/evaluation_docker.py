from __future__ import annotations

import copy
import json
import hashlib
import re
import secrets
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from recallpack.evaluation_variants import (
    V4DiagnosticScenarioResult,
    V4DiagnosticVariantResult,
)
from recallpack.budget import canonical_json
from recallpack.isolation import (
    CONTAINER_PATHS,
    ENV_ALLOWLIST,
    EXECUTION_USER,
    HOST_PATH_POLICY,
    HOST_ROOT_KEYS,
    ISOLATION_FLAGS,
    RESOURCE_LIMITS,
    SAFE_COMMAND,
    IsolatedExecutionBinding,
    IsolatedSuiteResult,
    ProductionExecutionIdentity,
    build_docker_argv,
    execution_invocation_sha256,
    has_valid_production_execution_receipt,
    run_isolated_suite,
    _seal_production_nonexecution_result,
)


BUILD_CONTEXT_EXCLUSIONS = (
    ".git",
    ".git/**",
    ".env",
    ".env.*",
    "**/*.pem",
    "**/*.key",
    "**/*credential*",
    "**/*secret*",
    "dist",
    "docs/execution",
    "docs/submission",
    "fixtures",
    "**/__pycache__",
    "**/*.pyc",
    "**/.DS_Store",
    "hidden-tests",
    "scenarios",
    "evidence",
)
_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def canonical_generated_files_sha256(generated_files: list[dict[str, str]]) -> str:
    return hashlib.sha256(canonical_json(generated_files).encode("utf-8")).hexdigest()


def build_runtime_evaluator_contract(
    *,
    platform: str,
    image_digest: str,
    base_image_digest: str,
) -> dict[str, Any]:
    if platform not in {"linux/amd64", "linux/arm64"}:
        raise ValueError("invalid_sandbox_evidence: unsupported platform")
    if (
        _DIGEST_PATTERN.fullmatch(image_digest) is None
        or _DIGEST_PATTERN.fullmatch(base_image_digest) is None
        or image_digest == base_image_digest
    ):
        raise ValueError("invalid_sandbox_evidence: invalid image digest")
    return {
        "platform": platform,
        "image_digest": image_digest,
        "base_image_digest": base_image_digest,
        "dockerfile_artifact_id": "evaluator_dockerfile",
        "runner_artifact_id": "evaluator_runner",
        "build_context_root": "evaluation/",
        "build_context_exclusions": list(BUILD_CONTEXT_EXCLUSIONS),
        "environment_allowlist": list(ENV_ALLOWLIST),
        "host_root_keys": dict(HOST_ROOT_KEYS),
        "host_path_policy": dict(HOST_PATH_POLICY),
        "container_paths": dict(CONTAINER_PATHS),
        "resource_limits": dict(RESOURCE_LIMITS),
        "execution_user": dict(EXECUTION_USER),
        "isolation_flags": dict(ISOLATION_FLAGS),
        "build_record_artifact_id": "evaluator_image_build_record",
    }


def sandbox_evidence_from_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    execution_user = _mapping(contract.get("execution_user"), "execution_user")
    resources = _mapping(contract.get("resource_limits"), "resource_limits")
    isolation = _mapping(contract.get("isolation_flags"), "isolation_flags")
    host_paths = _mapping(contract.get("host_path_policy"), "host_path_policy")
    return {
        "platform": contract.get("platform"),
        "image_digest": contract.get("image_digest"),
        "base_image_digest": contract.get("base_image_digest"),
        "uid": execution_user.get("uid"),
        "gid": execution_user.get("gid"),
        "cpus": resources.get("cpus"),
        "memory_bytes": resources.get("memory_bytes"),
        "pids": resources.get("pids"),
        "network_none": isolation.get("network") == "none",
        "read_only_root": isolation.get("read_only_root"),
        "drop_all_capabilities": isolation.get("drop_all_capabilities"),
        "no_new_privileges": isolation.get("no_new_privileges"),
        "tmp_is_tmpfs": isolation.get("tmp_is_tmpfs"),
        "tmpfs_size_bytes": resources.get("tmpfs_size_bytes"),
        "repository_mount_mode": isolation.get("repository_mount_mode"),
        "hidden_test_mount_mode": isolation.get("hidden_test_mount_mode"),
        "repository_root_canonical": True,
        "hidden_test_root_canonical": True,
        "roots_distinct": host_paths.get("repository_and_hidden_tests_distinct"),
        "wall_timeout_seconds": resources.get("wall_timeout_seconds"),
    }


def run_v4_isolated_diagnostic_variants(
    result: V4DiagnosticScenarioResult,
    *,
    fixture_root: str | Path,
    hidden_test_root: str | Path,
    evaluator_contract: Mapping[str, Any],
    suite_runner: Callable[..., IsolatedSuiteResult] = run_isolated_suite,
    production_execution_identities: Mapping[
        str, ProductionExecutionIdentity
    ] | None = None,
    allowed_paths: set[str] | None = None,
) -> dict[str, IsolatedSuiteResult]:
    if type(result) is not V4DiagnosticScenarioResult:
        raise ValueError("invalid_run_reference: diagnostic result type is invalid")
    fixture = Path(fixture_root).resolve(strict=True)
    repository_snapshot = (fixture / "repo_snapshot").resolve(strict=True)
    hidden_tests = Path(hidden_test_root).resolve(strict=True)
    if not repository_snapshot.is_dir() or not hidden_tests.is_dir():
        raise ValueError("invalid_run_reference: evaluator roots are unavailable")
    if any(path.is_symlink() for path in repository_snapshot.rglob("*")):
        raise ValueError("invalid_run_reference: repository snapshot contains symlinks")
    production_mode = suite_runner is run_isolated_suite
    if production_mode:
        if (
            production_execution_identities is None
            or set(production_execution_identities) != set(result.variants)
        ):
            raise ValueError(
                "invalid_sandbox_evidence: production execution identities are required"
            )
        for identity in production_execution_identities.values():
            if (
                type(identity) is not ProductionExecutionIdentity
                or identity.scenario_id != result.scenario_id
            ):
                raise ValueError(
                    "invalid_sandbox_evidence: production execution identity mismatch"
                )
    elif production_execution_identities is not None:
        raise ValueError(
            "invalid_sandbox_evidence: injected runners cannot claim production identities"
        )
    resolved_allowed_paths = (
        _validated_explicit_allowed_paths(allowed_paths)
        if allowed_paths is not None
        else _allowed_paths(fixture)
    )
    isolated: dict[str, IsolatedSuiteResult] = {}
    repository_snapshot_sha256 = _directory_tree_sha256(repository_snapshot)
    hidden_test_tree_sha256 = _directory_tree_sha256(hidden_tests)
    if production_execution_identities is not None:
        frozen_digests = {
            (
                identity.repository_snapshot_sha256,
                identity.hidden_test_tree_sha256,
            )
            for identity in production_execution_identities.values()
        }
        if frozen_digests != {
            (repository_snapshot_sha256, hidden_test_tree_sha256)
        }:
            raise ValueError(
                "invalid_sandbox_evidence: production identity does not match frozen evaluator roots"
            )
    with tempfile.TemporaryDirectory(prefix="recallpack-v4-docker-") as temp_dir:
        temp_root = Path(temp_dir)
        for variant_id, variant in result.variants.items():
            _validate_frozen_execution_roots(
                repository_snapshot,
                hidden_tests,
                repository_snapshot_sha256=repository_snapshot_sha256,
                hidden_test_tree_sha256=hidden_test_tree_sha256,
            )
            production_identity = (
                production_execution_identities[variant_id]
                if production_execution_identities is not None
                else None
            )
            repository_root = temp_root / variant_id / "repo"
            shutil.copytree(repository_snapshot, repository_root)
            repository_root = repository_root.resolve(strict=True)
            if _directory_tree_sha256(repository_root) != repository_snapshot_sha256:
                raise ValueError(
                    "invalid_sandbox_evidence: frozen repository changed while being copied"
                )
            patch_sha256 = canonical_generated_files_sha256(variant.generated_files)
            execution_nonce = secrets.token_hex(16)
            if (
                variant.downstream.get("accepted") is not True
                or not variant.generated_files
            ):
                failure_code = str(
                    variant.downstream.get("error") or "patch_rejected"
                )
                nonexecution_authority_mode = (
                    "patch_not_executed"
                    if production_identity is not None
                    else "test_only_patch_not_executed"
                )
                repository_tree_sha256 = _directory_tree_sha256(repository_root)
                nonexecution_result = IsolatedSuiteResult(
                    exit_code=None,
                    stdout="",
                    stderr="",
                    json_result=None,
                    blocked=True,
                    timed_out=False,
                    failure_code=failure_code,
                    host_fallback_used=False,
                    execution_binding=IsolatedExecutionBinding(
                        variant_id=variant_id,
                        patch_sha256=patch_sha256,
                        repository_tree_sha256=repository_tree_sha256,
                        hidden_test_tree_sha256=hidden_test_tree_sha256,
                        execution_nonce=execution_nonce,
                        docker_argv_sha256=_nonexecution_invocation_sha256(
                            variant_id,
                            patch_sha256,
                            failure_code,
                            authority_mode=nonexecution_authority_mode,
                        ),
                        authority_mode=nonexecution_authority_mode,
                        execution_manifest_sha256=(
                            production_identity.execution_manifest_sha256
                            if production_identity is not None
                            else None
                        ),
                        scenario_id=(
                            production_identity.scenario_id
                            if production_identity is not None
                            else None
                        ),
                        slot_index=(
                            production_identity.slot_index
                            if production_identity is not None
                            else None
                        ),
                        attempt_no=(
                            production_identity.attempt_no
                            if production_identity is not None
                            else None
                        ),
                        repository_snapshot_sha256=(
                            repository_snapshot_sha256
                            if production_identity is not None else None
                        ),
                        frozen_hidden_test_tree_sha256=(
                            hidden_test_tree_sha256
                            if production_identity is not None else None
                        ),
                    ),
                )
                isolated[variant_id] = (
                    _seal_production_nonexecution_result(
                        nonexecution_result,
                        expected_identity=production_identity,
                    )
                    if production_identity is not None
                    else nonexecution_result
                )
                continue
            _apply_generated_files(
                repository_root,
                variant.generated_files,
                allowed_paths=resolved_allowed_paths,
            )
            _make_container_readable(repository_root)
            repository_tree_sha256 = _directory_tree_sha256(repository_root)
            runner_kwargs = {
                "evaluator_contract": evaluator_contract,
                "image_digest": str(evaluator_contract.get("image_digest")),
                "repository_root": str(repository_root.resolve(strict=True)),
                "hidden_test_root": str(hidden_tests),
                "command": SAFE_COMMAND,
            }
            if suite_runner is run_isolated_suite:
                container_name = f"recallpack-eval-{execution_nonce[:16]}"
                argv, _ = build_docker_argv(
                    **runner_kwargs,
                    container_name=container_name,
                )
                production_binding = IsolatedExecutionBinding(
                    variant_id=variant_id,
                    patch_sha256=patch_sha256,
                    repository_tree_sha256=repository_tree_sha256,
                    hidden_test_tree_sha256=hidden_test_tree_sha256,
                    execution_nonce=execution_nonce,
                    docker_argv_sha256=execution_invocation_sha256(
                        argv=argv,
                        variant_id=variant_id,
                        patch_sha256=patch_sha256,
                        repository_tree_sha256=repository_tree_sha256,
                        hidden_test_tree_sha256=hidden_test_tree_sha256,
                        execution_nonce=execution_nonce,
                        production_identity=production_identity,
                    ),
                    authority_mode="production_docker",
                    execution_manifest_sha256=(
                        production_identity.execution_manifest_sha256
                    ),
                    scenario_id=production_identity.scenario_id,
                    slot_index=production_identity.slot_index,
                    attempt_no=production_identity.attempt_no,
                    repository_snapshot_sha256=(
                        repository_snapshot_sha256
                    ),
                    frozen_hidden_test_tree_sha256=(
                        hidden_test_tree_sha256
                    ),
                )
                bound_result = suite_runner(
                    **runner_kwargs,
                    container_name=container_name,
                    execution_binding=production_binding,
                )
            else:
                suite_result = suite_runner(**runner_kwargs)
                bound_result = replace(
                    suite_result,
                    execution_binding=IsolatedExecutionBinding(
                        variant_id=variant_id,
                        patch_sha256=patch_sha256,
                        repository_tree_sha256=repository_tree_sha256,
                        hidden_test_tree_sha256=hidden_test_tree_sha256,
                        execution_nonce=execution_nonce,
                        docker_argv_sha256=_test_invocation_sha256(
                            image_digest=str(evaluator_contract.get("image_digest")),
                            repository_tree_sha256=repository_tree_sha256,
                            hidden_test_tree_sha256=hidden_test_tree_sha256,
                        ),
                        authority_mode="test_only_injected_runner",
                    ),
                )
            if bound_result.blocked:
                validate_retained_technical_failure(
                    bound_result,
                    expected_identity=production_identity,
                )
            else:
                validate_isolated_result(
                    bound_result,
                    expected_identity=production_identity,
                )
            _validate_frozen_execution_roots(
                repository_snapshot,
                hidden_tests,
                repository_snapshot_sha256=repository_snapshot_sha256,
                hidden_test_tree_sha256=hidden_test_tree_sha256,
            )
            isolated[variant_id] = bound_result
    return isolated


def run_frozen_isolated_variant(
    *,
    scenario_id: str,
    variant_id: str,
    repository_snapshot_root: str | Path,
    hidden_test_root: str | Path,
    generated_files: tuple[dict[str, str], ...],
    downstream: Mapping[str, Any],
    allowed_paths: tuple[str, ...],
    evaluator_contract: Mapping[str, Any],
    suite_runner: Callable[..., IsolatedSuiteResult] = run_isolated_suite,
    production_execution_identity: ProductionExecutionIdentity | None = None,
) -> IsolatedSuiteResult:
    """Run one frozen patch through the existing isolated evaluator contract.

    The adapter deliberately stages a repository without `gold.json` and uses
    only the caller's explicit frozen allowlist. It reuses the established
    runner/receipt implementation; it does not turn a test-only injected runner
    into production evidence.
    """
    if (
        not isinstance(scenario_id, str)
        or not scenario_id
        or not isinstance(variant_id, str)
        or not variant_id
        or not isinstance(downstream, Mapping)
    ):
        raise ValueError("invalid_run_reference: frozen variant identity is invalid")
    if (
        type(allowed_paths) is not tuple
        or not allowed_paths
        or len(allowed_paths) != len(set(allowed_paths))
    ):
        raise ValueError("invalid_run_reference: explicit writable path contract is invalid")
    resolved_allowed_paths = _validated_explicit_allowed_paths(set(allowed_paths))
    try:
        raw_source_root = Path(repository_snapshot_root)
    except TypeError as exc:
        raise ValueError(
            "invalid_run_reference: frozen repository root is unavailable"
        ) from exc
    if raw_source_root.is_symlink():
        raise ValueError("invalid_run_reference: frozen repository root is unavailable")
    try:
        source_root = raw_source_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            "invalid_run_reference: frozen repository root is unavailable"
        ) from exc
    if not source_root.is_dir():
        raise ValueError("invalid_run_reference: frozen repository root is unavailable")
    if any(path.is_symlink() for path in source_root.rglob("*")):
        raise ValueError("invalid_run_reference: frozen repository contains symlinks")
    with tempfile.TemporaryDirectory(prefix="recallpack-v4-frozen-evaluator-") as temp_dir:
        fixture_root = Path(temp_dir) / "fixture"
        fixture_root.mkdir()
        shutil.copytree(source_root, fixture_root / "repo_snapshot")
        synthetic_variant = V4DiagnosticVariantResult(
            variant_id=variant_id,
            selected_context=[],
            selected_source_refs=(),
            model_visible_context="[]",
            model_visible_context_sha256=hashlib.sha256(b"[]").hexdigest(),
            exact_token_count=0,
            budget_comparable=True,
            provider_traces=[],
            downstream=copy.deepcopy(dict(downstream)),
            generated_files=copy.deepcopy(list(generated_files)),
            execution_trace={"frozen_adapter": True},
        )
        synthetic_result = V4DiagnosticScenarioResult(
            scenario_id=scenario_id,
            variants={variant_id: synthetic_variant},
            strongest_baseline_variant_id=None,
            strongest_baseline_variant_ids=(),
            strongest_baseline_full_suite_passed=None,
            recallpack_full_suite_passed=None,
            classification="frozen_adapter",
            evidence_status="pre_isolation",
            evidence_bindings={},
            limitations=(
                "Frozen single-cell evaluator adapter; no claim is enabled by this result.",
            ),
        )
        identities = (
            {variant_id: production_execution_identity}
            if production_execution_identity is not None
            else None
        )
        return run_v4_isolated_diagnostic_variants(
            synthetic_result,
            fixture_root=fixture_root,
            hidden_test_root=hidden_test_root,
            evaluator_contract=evaluator_contract,
            suite_runner=suite_runner,
            production_execution_identities=identities,
            allowed_paths=resolved_allowed_paths,
        )[variant_id]


def seal_frozen_production_patch_rejection(
    *,
    scenario_id: str,
    variant_id: str,
    repository_snapshot_root: str | Path,
    generated_files: tuple[dict[str, str], ...],
    downstream: Mapping[str, Any],
    production_execution_identity: ProductionExecutionIdentity,
) -> IsolatedSuiteResult:
    """Seal an adverse patch result without resolving hidden-test files.

    A rejected patch is a completed model-output event, not a sandbox run. This
    path deliberately derives its hidden-test digest from the registered
    production identity and never receives a hidden-test root.
    """
    if (
        not isinstance(scenario_id, str)
        or not scenario_id
        or not isinstance(variant_id, str)
        or not variant_id
        or type(generated_files) is not tuple
        or generated_files
        or not isinstance(downstream, Mapping)
        or downstream.get("accepted") is not False
        or type(production_execution_identity) is not ProductionExecutionIdentity
        or production_execution_identity.scenario_id != scenario_id
    ):
        raise ValueError("invalid_run_reference: frozen patch rejection is invalid")
    failure_code = downstream.get("error")
    if (
        not isinstance(failure_code, str)
        or not failure_code
        or not failure_code.isascii()
        or len(failure_code) > 160
        or re.fullmatch(r"[A-Za-z0-9_.-]+", failure_code) is None
        or failure_code in {"sandbox_timeout", "sandbox_unavailable"}
    ):
        raise ValueError("invalid_run_reference: frozen patch rejection is invalid")
    try:
        raw_root = Path(repository_snapshot_root)
    except TypeError as exc:
        raise ValueError(
            "invalid_run_reference: frozen repository root is unavailable"
        ) from exc
    if raw_root.is_symlink():
        raise ValueError("invalid_run_reference: frozen repository root is unavailable")
    try:
        repository_root = raw_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            "invalid_run_reference: frozen repository root is unavailable"
        ) from exc
    if not repository_root.is_dir() or any(
        path.is_symlink() for path in repository_root.rglob("*")
    ):
        raise ValueError("invalid_run_reference: frozen repository root is unavailable")
    repository_tree_sha256 = _directory_tree_sha256(repository_root)
    if (
        repository_tree_sha256
        != production_execution_identity.repository_snapshot_sha256
    ):
        raise ValueError(
            "invalid_sandbox_evidence: production identity does not match frozen repository"
        )
    patch_sha256 = canonical_generated_files_sha256([])
    execution_nonce = secrets.token_hex(16)
    binding = IsolatedExecutionBinding(
        variant_id=variant_id,
        patch_sha256=patch_sha256,
        repository_tree_sha256=repository_tree_sha256,
        hidden_test_tree_sha256=production_execution_identity.hidden_test_tree_sha256,
        execution_nonce=execution_nonce,
        docker_argv_sha256=_nonexecution_invocation_sha256(
            variant_id,
            patch_sha256,
            failure_code,
            authority_mode="patch_not_executed",
        ),
        authority_mode="patch_not_executed",
        execution_manifest_sha256=(
            production_execution_identity.execution_manifest_sha256
        ),
        scenario_id=production_execution_identity.scenario_id,
        slot_index=production_execution_identity.slot_index,
        attempt_no=production_execution_identity.attempt_no,
        repository_snapshot_sha256=(
            production_execution_identity.repository_snapshot_sha256
        ),
        frozen_hidden_test_tree_sha256=(
            production_execution_identity.hidden_test_tree_sha256
        ),
    )
    return _seal_production_nonexecution_result(
        IsolatedSuiteResult(
            exit_code=None,
            stdout="",
            stderr="",
            json_result=None,
            blocked=True,
            timed_out=False,
            failure_code=failure_code,
            host_fallback_used=False,
            execution_binding=binding,
        ),
        expected_identity=production_execution_identity,
    )


def _directory_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError("invalid_sandbox_evidence: execution tree contains symlinks")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_dir():
            digest.update(b"directory\0" + relative + b"\0")
            continue
        if not path.is_file():
            raise ValueError("invalid_sandbox_evidence: execution tree entry is invalid")
        digest.update(b"file\0" + relative + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_frozen_execution_roots(
    repository_snapshot: Path,
    hidden_tests: Path,
    *,
    repository_snapshot_sha256: str,
    hidden_test_tree_sha256: str,
) -> None:
    if (
        _directory_tree_sha256(repository_snapshot) != repository_snapshot_sha256
        or _directory_tree_sha256(hidden_tests) != hidden_test_tree_sha256
    ):
        raise ValueError(
            "invalid_sandbox_evidence: frozen repository or hidden-test tree changed during execution"
        )


def _test_invocation_sha256(
    *,
    image_digest: str,
    repository_tree_sha256: str,
    hidden_test_tree_sha256: str,
) -> str:
    payload = {
        "mode": "test_only_injected_runner",
        "image_digest": image_digest,
        "command": list(SAFE_COMMAND),
        "repository_tree_sha256": repository_tree_sha256,
        "hidden_test_tree_sha256": hidden_test_tree_sha256,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _nonexecution_invocation_sha256(
    variant_id: str,
    patch_sha256: str,
    failure_code: str,
    *,
    authority_mode: str,
) -> str:
    payload = {
        "mode": authority_mode,
        "variant_id": variant_id,
        "patch_sha256": patch_sha256,
        "failure_code": failure_code,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def validate_retained_technical_failure(
    result: IsolatedSuiteResult,
    *,
    expected_identity: ProductionExecutionIdentity | None = None,
) -> None:
    binding = result.execution_binding
    timeout_cleanup_invalid = result.failure_code == "sandbox_timeout" and (
        not result.timed_out
        or not result.container_name
        or not result.cleanup_attempted
        or result.cleanup_succeeded is not True
    )
    unavailable_cleanup_invalid = result.failure_code == "sandbox_unavailable" and (
        result.timed_out
        or result.cleanup_attempted
        or result.cleanup_succeeded is not None
    )
    if (
        result.failure_code not in {"sandbox_timeout", "sandbox_unavailable"}
        or result.host_fallback_used
        or result.json_result is not None
        or type(binding) is not IsolatedExecutionBinding
        or binding.authority_mode
        not in {"production_docker", "test_only_injected_runner"}
        or timeout_cleanup_invalid
        or unavailable_cleanup_invalid
    ):
        raise ValueError("invalid_sandbox_evidence: technical attempt is malformed")
    if (
        binding.authority_mode == "production_docker"
        and (
            expected_identity is None
            or not has_valid_production_execution_receipt(
                result,
                expected_identity=expected_identity,
            )
        )
    ):
        raise ValueError(
            "invalid_sandbox_evidence: production execution receipt is invalid"
        )


def _allowed_paths(fixture_root: Path) -> set[str]:
    try:
        gold = json.loads((fixture_root / "gold.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_run_reference: fixture contract is unreadable") from exc
    paths = gold.get("allowed_edit_paths") if isinstance(gold, dict) else None
    if (
        not isinstance(paths, list)
        or not paths
        or any(not isinstance(path, str) or not path for path in paths)
        or len(paths) != len(set(paths))
    ):
        raise ValueError("invalid_run_reference: writable path contract is invalid")
    return set(paths)


def _validated_explicit_allowed_paths(value: Any) -> set[str]:
    if (
        type(value) is not set
        or not value
        or any(not isinstance(path, str) or not path for path in value)
    ):
        raise ValueError("invalid_run_reference: explicit writable path contract is invalid")
    canonical_paths: set[str] = set()
    for path in value:
        parsed = PurePosixPath(path)
        if (
            not path.isascii()
            or parsed.is_absolute()
            or parsed.as_posix() != path
            or any(part in {"", ".", ".."} for part in parsed.parts)
        ):
            raise ValueError(
                "invalid_run_reference: explicit writable path contract is invalid"
            )
        canonical_paths.add(path)
    if len(canonical_paths) != len(value):
        raise ValueError("invalid_run_reference: explicit writable path contract is invalid")
    return canonical_paths


def _apply_generated_files(
    repository_root: Path,
    generated_files: list[dict[str, str]],
    *,
    allowed_paths: set[str],
) -> None:
    if not generated_files:
        raise ValueError("invalid_patch_result: diagnostic patch is empty")
    seen: set[str] = set()
    for generated in generated_files:
        if type(generated) is not dict or set(generated) != {"path", "content"}:
            raise ValueError("invalid_patch_result: generated file is malformed")
        relative_path = generated["path"]
        content = generated["content"]
        if (
            not isinstance(relative_path, str)
            or relative_path not in allowed_paths
            or relative_path in seen
            or not isinstance(content, str)
        ):
            raise ValueError("invalid_patch_result: generated path is invalid")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or "." in path.parts or ".." in path.parts:
            raise ValueError("invalid_patch_result: generated path is invalid")
        seen.add(relative_path)
        target = repository_root / path.as_posix()
        resolved = target.resolve(strict=True)
        if (
            resolved == repository_root
            or repository_root not in resolved.parents
            or not resolved.is_file()
            or target.is_symlink()
        ):
            raise ValueError("invalid_patch_result: generated path escaped repository")
        resolved.write_text(content, encoding="utf-8")


def _make_container_readable(repository_root: Path) -> None:
    repository_root.chmod(0o755)
    for path in repository_root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)


def validate_isolated_result(
    result: Any,
    *,
    expected_identity: ProductionExecutionIdentity | None = None,
) -> None:
    if type(result) is not IsolatedSuiteResult:
        raise ValueError("invalid_sandbox_evidence: isolated result type is invalid")
    payload = result.json_result
    binding = result.execution_binding
    if (
        result.blocked
        or result.host_fallback_used
        or result.failure_code is not None
        or not isinstance(payload, dict)
        or result.exit_code != payload.get("exit_code")
        or result.timed_out != payload.get("timed_out")
        or type(binding) is not IsolatedExecutionBinding
        or not binding.variant_id
        or _SHA256_PATTERN.fullmatch(binding.patch_sha256) is None
        or _SHA256_PATTERN.fullmatch(binding.repository_tree_sha256) is None
        or _SHA256_PATTERN.fullmatch(binding.hidden_test_tree_sha256) is None
        or _SHA256_PATTERN.fullmatch(binding.docker_argv_sha256) is None
        or not binding.execution_nonce
        or binding.authority_mode
        not in {"production_docker", "test_only_injected_runner"}
    ):
        raise ValueError("invalid_sandbox_evidence: isolated execution did not close")
    if (
        binding.authority_mode == "production_docker"
        and (
            expected_identity is None
            or not has_valid_production_execution_receipt(
                result,
                expected_identity=expected_identity,
            )
        )
    ):
        raise ValueError(
            "invalid_sandbox_evidence: production execution receipt is invalid"
        )
    try:
        stdout_payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_sandbox_evidence: runner stdout is not JSON") from exc
    tests = payload.get("tests")
    if (
        stdout_payload != payload
        or not isinstance(tests, list)
        or not tests
        or not isinstance(tests[0], dict)
        or tests[0].get("name") != "network_probe"
        or tests[0].get("status") != "passed"
    ):
        raise ValueError("invalid_sandbox_evidence: network isolation is unproven")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"invalid_sandbox_evidence: {label} is malformed")
    return value

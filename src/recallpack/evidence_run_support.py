from __future__ import annotations

import difflib
from pathlib import PurePosixPath
from typing import Any, Mapping

from recallpack.evidence_common import _validate_catalog_artifact

_ALLOWED_TEST_EVIDENCE_KINDS = {"stdout", "stderr", "test_result"}


def _validate_patch(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    output_catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    resolve_output_artifact,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    patch = run.get("patch")
    if patch is None:
        orphan_kinds = {
            record.get("kind")
            for record in output_catalog.values()
            if isinstance(record, Mapping)
        } & {"patch_diff", "original_file", "patched_file"}
        if orphan_kinds:
            errors.append(
                (
                    "invalid_artifact_reference",
                    "/run_output_artifact_catalog",
                    "null patches cannot retain patch_diff or file sidecar artifacts",
                )
            )
        return errors
    if not isinstance(patch, Mapping):
        return errors

    original_files = patch.get("original_files")
    files = patch.get("files")
    if patch.get("accepted") is False:
        orphan_kinds = {
            record.get("kind")
            for record in output_catalog.values()
            if isinstance(record, Mapping)
        } & {"patch_diff", "original_file", "patched_file"}
        if (
            patch.get("diff_artifact_id") is not None
            or patch.get("diff_sha256") is not None
            or original_files
            or files
            or orphan_kinds
        ):
            errors.append(
                (
                    "invalid_artifact_reference",
                    "/run_output_artifact_catalog",
                    "rejected patches cannot retain patch_diff or file sidecar artifacts",
                )
            )
        return errors

    resolved, resolution_errors = resolve_output_artifact(
        output_catalog,
        artifact_bytes,
        patch.get("diff_artifact_id"),
        expected_kind="patch_diff",
        pointer="/patch/diff_artifact_id",
    )
    errors.extend(resolution_errors)
    if resolved is None:
        return errors
    if patch.get("diff_sha256") != resolved["record"].get("sha256"):
        errors.append(
            (
                "invalid_artifact_reference",
                "/patch/diff_sha256",
                "patch diff sha256 must equal the embedded patch_diff artifact hash",
            )
        )
    if patch.get("accepted") is True and not resolved["payload"].strip():
        errors.append(
            (
                "invalid_artifact_reference",
                "/patch/diff_artifact_id",
                "accepted patch diff artifact must be non-empty",
            )
        )

    comparison_contract = manifest.get("comparison_contract")
    writable_paths = (
        comparison_contract.get("writable_paths")
        if isinstance(comparison_contract, Mapping)
        else None
    )
    if not isinstance(files, list) or not isinstance(writable_paths, list):
        return errors
    original_artifact_ids = {
        artifact_id
        for artifact_id, record in output_catalog.items()
        if isinstance(record, Mapping) and record.get("kind") == "original_file"
    }
    patched_artifact_ids = {
        artifact_id
        for artifact_id, record in output_catalog.items()
        if isinstance(record, Mapping) and record.get("kind") == "patched_file"
    }
    if not isinstance(original_files, list):
        return errors
    original_contents, original_refs, original_errors = _resolve_file_sidecars(
        original_files,
        sidecar_kind="original_file",
        relative_directory="original-files",
        pointer="/patch/original_files",
        writable_paths=writable_paths,
        output_catalog=output_catalog,
        artifact_bytes=artifact_bytes,
        resolve_output_artifact=resolve_output_artifact,
    )
    errors.extend(original_errors)
    patched_contents, patched_refs, patched_errors = _resolve_file_sidecars(
        files,
        sidecar_kind="patched_file",
        relative_directory="patched-files",
        pointer="/patch/files",
        writable_paths=writable_paths,
        output_catalog=output_catalog,
        artifact_bytes=artifact_bytes,
        resolve_output_artifact=resolve_output_artifact,
    )
    errors.extend(patched_errors)
    if patch.get("accepted") is True:
        if original_refs != original_artifact_ids or patched_refs != patched_artifact_ids:
            errors.append(
                (
                    "invalid_artifact_reference",
                    "/run_output_artifact_catalog",
                    "original_file and patched_file artifacts must be referenced exactly once",
                )
            )
        if set(original_contents) != set(patched_contents):
            errors.append(
                (
                    "invalid_artifact_reference",
                    "/patch/files",
                    "original and patched file path sets must match",
                )
            )
        elif not errors:
            expected_diff = _canonical_patch_diff(original_contents, patched_contents)
            try:
                actual_diff = resolved["payload"].decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                actual_diff = ""
            if not expected_diff or actual_diff != expected_diff:
                errors.append(
                    (
                        "invalid_artifact_reference",
                        "/patch/diff_artifact_id",
                        "patch diff must equal the retained original/patched sidecar diff",
                    )
                )
    return errors


def _resolve_file_sidecars(
    files: list[Any],
    *,
    sidecar_kind: str,
    relative_directory: str,
    pointer: str,
    writable_paths: list[Any],
    output_catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    resolve_output_artifact,
) -> tuple[dict[str, str], set[str], list[tuple[str, str, str]]]:
    contents: dict[str, str] = {}
    referenced_artifact_ids: set[str] = set()
    errors: list[tuple[str, str, str]] = []
    for index, file in enumerate(files):
        if not isinstance(file, Mapping):
            continue
        path = file.get("path")
        if (
            not isinstance(path, str)
            or path not in writable_paths
            or not _safe_relative_path(path)
        ):
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"{pointer}/{index}/path",
                    "patched file path must be in the frozen writable allowlist",
                )
            )
            continue
        if path in contents:
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"{pointer}/{index}/path",
                    "file sidecar paths must be unique",
                )
            )
            continue
        expected_path_suffix = f"/{relative_directory}/{path}"
        matches = [
            (artifact_id, record)
            for artifact_id, record in output_catalog.items()
            if isinstance(record, Mapping)
            and record.get("kind") == sidecar_kind
            and isinstance(record.get("relative_path"), str)
            and record["relative_path"].endswith(expected_path_suffix)
            and record.get("sha256") == file.get("sha256")
            and record.get("bytes") == file.get("bytes")
        ]
        if len(matches) != 1:
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"{pointer}/{index}",
                    "patched file must resolve to exactly one content artifact",
                )
            )
            continue
        artifact_id, record = matches[0]
        referenced_artifact_ids.add(artifact_id)
        resolved_file, file_errors = resolve_output_artifact(
            output_catalog,
            artifact_bytes,
            artifact_id,
            expected_kind=sidecar_kind,
            pointer=f"{pointer}/{index}",
        )
        errors.extend(file_errors)
        if resolved_file is None:
            continue
        if file.get("sha256") != record.get("sha256") or file.get("bytes") != record.get(
            "bytes"
        ):
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"{pointer}/{index}",
                    "patched file hash and bytes must equal retained content evidence",
                )
            )
            continue
        try:
            contents[path] = resolved_file["payload"].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"{pointer}/{index}",
                    "file sidecar must contain UTF-8 text",
                )
            )
    return contents, referenced_artifact_ids, errors


def _canonical_patch_diff(
    originals: Mapping[str, str],
    patched: Mapping[str, str],
) -> str:
    parts: list[str] = []
    for path in sorted(originals):
        parts.extend(
            difflib.unified_diff(
                originals[path].splitlines(keepends=True),
                patched[path].splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
    return "".join(parts)


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and "." not in path.parts
        and ".." not in path.parts
        and path.as_posix() == value
    )


def _validate_test_result(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    output_catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    resolve_output_artifact,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    test_result = run.get("test_result")
    if not isinstance(test_result, Mapping):
        return errors

    for field_name, expected_kind in (
        ("test_result_artifact_id", "test_result"),
        ("stdout_artifact_id", "stdout"),
        ("stderr_artifact_id", "stderr"),
    ):
        errors.extend(
            resolve_output_artifact(
                output_catalog,
                artifact_bytes,
                test_result.get(field_name),
                expected_kind=expected_kind,
                pointer=f"/test_result/{field_name}",
            )[1]
        )

    tests = test_result.get("tests")
    if isinstance(tests, list):
        passed_count = 0
        failed_count = 0
        has_skip_or_error = False
        for index, item in enumerate(tests):
            if not isinstance(item, Mapping):
                continue
            status = item.get("status")
            if status == "passed":
                passed_count += 1
            elif status in {"failed", "error"}:
                failed_count += 1
                if status == "error":
                    has_skip_or_error = True
            elif status == "skipped":
                has_skip_or_error = True
            errors.extend(
                _resolve_test_evidence_artifact(
                    output_catalog,
                    artifact_bytes,
                    item.get("evidence_artifact_id"),
                    pointer=f"/test_result/tests/{index}/evidence_artifact_id",
                )[1]
            )
        if test_result.get("passed") != passed_count:
            errors.append(
                (
                    "invalid_test_result",
                    "/test_result/passed",
                    "test_result.passed must equal the number of passed tests",
                )
            )
        if test_result.get("failed") != failed_count:
            errors.append(
                (
                    "invalid_test_result",
                    "/test_result/failed",
                    "test_result.failed must equal the number of failed or error tests",
                )
            )
        expected_full_suite = (
            passed_count == len(tests)
            and failed_count == 0
            and not has_skip_or_error
            and test_result.get("exit_code") == 0
            and test_result.get("timed_out") is False
        )
        if test_result.get("full_suite_passed") != expected_full_suite:
            errors.append(
                (
                    "invalid_test_result",
                    "/test_result/full_suite_passed",
                    "full_suite_passed must be derived from the per-test results and process outcome",
                )
            )
    errors.extend(_validate_sandbox(test_result.get("sandbox"), manifest))
    return errors


def _validate_sandbox(
    sandbox: Any,
    manifest: Mapping[str, Any],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    evaluator = manifest.get("evaluator_contract")
    if not isinstance(sandbox, Mapping) or not isinstance(evaluator, Mapping):
        return errors

    execution_user = evaluator.get("execution_user")
    resource_limits = evaluator.get("resource_limits")
    isolation_flags = evaluator.get("isolation_flags")
    host_path_policy = evaluator.get("host_path_policy")
    if not all(
        isinstance(value, Mapping)
        for value in (execution_user, resource_limits, isolation_flags, host_path_policy)
    ):
        return errors

    expected = {
        "platform": evaluator.get("platform"),
        "image_digest": evaluator.get("image_digest"),
        "base_image_digest": evaluator.get("base_image_digest"),
        "uid": execution_user.get("uid"),
        "gid": execution_user.get("gid"),
        "cpus": resource_limits.get("cpus"),
        "memory_bytes": resource_limits.get("memory_bytes"),
        "pids": resource_limits.get("pids"),
        "network_none": isolation_flags.get("network") == "none",
        "read_only_root": isolation_flags.get("read_only_root"),
        "drop_all_capabilities": isolation_flags.get("drop_all_capabilities"),
        "no_new_privileges": isolation_flags.get("no_new_privileges"),
        "tmp_is_tmpfs": isolation_flags.get("tmp_is_tmpfs"),
        "tmpfs_size_bytes": resource_limits.get("tmpfs_size_bytes"),
        "repository_mount_mode": isolation_flags.get("repository_mount_mode"),
        "hidden_test_mount_mode": isolation_flags.get("hidden_test_mount_mode"),
        "repository_root_canonical": True,
        "hidden_test_root_canonical": True,
        "roots_distinct": host_path_policy.get("repository_and_hidden_tests_distinct"),
        "wall_timeout_seconds": resource_limits.get("wall_timeout_seconds"),
    }
    for field_name, expected_value in expected.items():
        if sandbox.get(field_name) != expected_value:
            errors.append(
                (
                    "invalid_sandbox_evidence",
                    f"/test_result/sandbox/{field_name}",
                    f"sandbox {field_name} must match the evaluator contract",
                )
            )
    return errors


def _validate_artifact_hashes(
    run: Mapping[str, Any],
    output_catalog: Mapping[str, Any],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    artifact_hashes = run.get("artifact_hashes")
    if not isinstance(artifact_hashes, Mapping):
        return errors
    if set(artifact_hashes) != set(output_catalog):
        errors.append(
            (
                "invalid_artifact_reference",
                "/artifact_hashes",
                "artifact_hashes must cover the embedded run_output_artifact_catalog exactly",
            )
        )
    for artifact_id, record in output_catalog.items():
        if not isinstance(record, Mapping):
            continue
        if artifact_hashes.get(artifact_id) != record.get("sha256"):
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"/artifact_hashes/{artifact_id.replace('~', '~0').replace('/', '~1')}",
                    "artifact_hashes values must equal the embedded output artifact hashes",
                )
            )
    return errors


def _resolve_output_artifact(
    output_catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    artifact_id: Any,
    *,
    expected_kind: str,
    pointer: str,
) -> tuple[dict[str, Any] | None, list[tuple[str, str, str]]]:
    errors: list[tuple[str, str, str]] = []
    if not isinstance(artifact_id, str) or artifact_id not in output_catalog:
        errors.append(
            (
                "invalid_artifact_reference",
                pointer,
                "artifact reference must resolve to the embedded run_output_artifact_catalog",
            )
        )
        return None, errors
    record = output_catalog[artifact_id]
    if not isinstance(record, Mapping) or record.get("kind") != expected_kind:
        errors.append(
            (
                "invalid_artifact_reference",
                pointer,
                f"artifact must resolve to kind {expected_kind}",
            )
        )
        return None, errors
    errors.extend(
        _validate_catalog_artifact(
            artifact_id,
            record,
            artifact_bytes,
            f"/run_output_artifact_catalog/{artifact_id.replace('~', '~0').replace('/', '~1')}",
        )
    )
    payload = artifact_bytes.get(artifact_id)
    if not isinstance(payload, (bytes, bytearray)):
        return None, errors
    return {"record": record, "payload": bytes(payload)}, errors


def _resolve_test_evidence_artifact(
    output_catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    artifact_id: Any,
    *,
    pointer: str,
) -> tuple[dict[str, Any] | None, list[tuple[str, str, str]]]:
    errors: list[tuple[str, str, str]] = []
    if not isinstance(artifact_id, str) or artifact_id not in output_catalog:
        errors.append(
            (
                "invalid_artifact_reference",
                pointer,
                "artifact reference must resolve to the embedded run_output_artifact_catalog",
            )
        )
        return None, errors
    record = output_catalog[artifact_id]
    if not isinstance(record, Mapping):
        errors.append(
            (
                "invalid_artifact_reference",
                pointer,
                "artifact reference must resolve to an embedded output artifact record",
            )
        )
        return None, errors
    if record.get("kind") not in _ALLOWED_TEST_EVIDENCE_KINDS:
        errors.append(
            (
                "invalid_artifact_reference",
                pointer,
                "per-test evidence must resolve to stdout, stderr, or test_result",
            )
        )
        return None, errors
    errors.extend(
        _validate_catalog_artifact(
            artifact_id,
            record,
            artifact_bytes,
            f"/run_output_artifact_catalog/{artifact_id.replace('~', '~0').replace('/', '~1')}",
        )
    )
    payload = artifact_bytes.get(artifact_id)
    if not isinstance(payload, (bytes, bytearray)):
        return None, errors
    return {"record": record, "payload": bytes(payload)}, errors


def _scenario_record(
    manifest: Mapping[str, Any],
    scenario_id: Any,
) -> Mapping[str, Any] | None:
    evidence_scenarios = manifest.get("evidence_scenarios")
    if not isinstance(evidence_scenarios, list):
        return None
    for scenario in evidence_scenarios:
        if isinstance(scenario, Mapping) and scenario.get("scenario_slot") == scenario_id:
            return scenario
    return None

from __future__ import annotations

import copy
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping
import uuid

from recallpack.evidence_review_protocol import (
    _compute_frozen_code_hashes_from_root_fd,
    derive_external_artifact_slots,
    validate_evaluation_review_seed,
)
from recallpack.review_json import (
    canonicalize_review_json,
    parse_review_json,
    review_json_sha256,
)
from recallpack.secure_files import (
    SecureFileError,
    canonical_relative_parts,
    open_canonical_root,
    open_directory_beneath,
    stable_read_beneath,
)


SEED_FILE = "evaluation-review-seed.json"
SEED_HASH_FILE = "evaluation-review-seed.sha256"
SLOTS_FILE = "external-artifact-slots.json"
REPORT_FILE = "review-seed-generation-report.json"
OUTPUT_FILES = (SEED_FILE, SEED_HASH_FILE, SLOTS_FILE, REPORT_FILE)


@dataclass(frozen=True)
class ReviewSeedGenerationResult:
    review_seed_sha256: str
    slot_count: int


def generate_review_seed_package(
    *,
    repository_root: Path,
    seed_draft: str,
    output_dir: str,
) -> ReviewSeedGenerationResult:
    _require_canonical_repository_root(Path(repository_root))
    draft_parts = canonical_relative_parts(seed_draft)
    output_parts = canonical_relative_parts(output_dir)
    _validate_output_location(output_parts)

    try:
        with open_canonical_root(Path(repository_root)) as root_fd:
            draft_bytes = stable_read_beneath(root_fd, "/".join(draft_parts))
            draft = parse_review_json(draft_bytes)
            if not isinstance(draft, Mapping):
                raise ValueError("4.1 invalid_review_seed / seed draft must be an object")
            seed: dict[str, Any] = copy.deepcopy(dict(draft))
            seed["code_hashes"] = _compute_frozen_code_hashes_from_root_fd(root_fd)
            seed["external_artifact_slots"] = derive_external_artifact_slots(seed)
            artifact_bytes = _load_seed_artifacts(root_fd, seed)
            validate_evaluation_review_seed(
                seed,
                artifact_bytes=artifact_bytes,
                repository_root_fd=root_fd,
            )
            payloads, seed_hash = _package_payloads(seed)
            _publish_package(root_fd, output_parts, payloads)
    except SecureFileError:
        raise

    return ReviewSeedGenerationResult(
        review_seed_sha256=seed_hash,
        slot_count=len(seed["external_artifact_slots"]),
    )


def _require_canonical_repository_root(repository_root: Path) -> None:
    if not repository_root.is_absolute():
        raise SecureFileError(
            "invalid_seed_generation_path: repository root must be absolute"
        )
    try:
        canonical = repository_root.resolve(strict=True)
    except OSError as exc:
        raise SecureFileError(
            "invalid_seed_generation_path: repository root does not exist"
        ) from exc
    if canonical != repository_root or repository_root.is_symlink():
        raise SecureFileError(
            "invalid_seed_generation_path: repository root must be canonical and non-symlinked"
        )


def _load_seed_artifacts(root_fd: int, seed: Mapping[str, Any]) -> dict[str, bytes]:
    catalog = seed.get("frozen_input_artifact_catalog")
    if not isinstance(catalog, Mapping):
        raise ValueError(
            "4.1 invalid_review_seed /frozen_input_artifact_catalog catalog must be an object"
        )
    result: dict[str, bytes] = {}
    for artifact_id, record in catalog.items():
        if not isinstance(artifact_id, str) or not isinstance(record, Mapping):
            raise ValueError(
                "4.1 invalid_review_seed /frozen_input_artifact_catalog invalid catalog record"
            )
        relative_path = record.get("relative_path")
        if not isinstance(relative_path, str):
            raise ValueError(
                f"4.1 invalid_review_seed /frozen_input_artifact_catalog/{artifact_id}/relative_path path missing"
            )
        result[artifact_id] = stable_read_beneath(root_fd, relative_path)
    return result


def _package_payloads(seed: Mapping[str, Any]) -> tuple[dict[str, bytes], str]:
    seed_bytes = canonicalize_review_json(seed)
    seed_hash = hashlib.sha256(seed_bytes).hexdigest()
    slots = seed["external_artifact_slots"]
    slots_bytes = canonicalize_review_json(slots)
    report = {
        "record_type": "review_seed_generation_report",
        "report_version": "review-seed-generation/4.1",
        "evaluation_review_seed_file": SEED_FILE,
        "evaluation_review_seed_sha256_file": SEED_HASH_FILE,
        "evaluation_review_seed_sha256": seed_hash,
        "evaluation_review_seed_bytes": len(seed_bytes),
        "external_artifact_slots_file": SLOTS_FILE,
        "external_artifact_slots_sha256": review_json_sha256(slots),
        "external_artifact_slots_bytes": len(slots_bytes),
        "external_artifact_slot_count": len(slots),
        "contains_external_content": False,
        "credentials_read": False,
        "network_calls_made": False,
        "authorizes_execution": False,
        "next_gate": "external_review_and_attestation",
    }
    return (
        {
            SEED_FILE: seed_bytes,
            SEED_HASH_FILE: f"{seed_hash}\n".encode("ascii"),
            SLOTS_FILE: slots_bytes,
            REPORT_FILE: canonicalize_review_json(report),
        },
        seed_hash,
    )


def _validate_output_location(parts: tuple[str, ...]) -> None:
    protected = (
        ("src", "recallpack"),
        ("evaluation", "runner"),
        ("specs", "001-recallpack-v4", "contracts"),
    )
    if any(parts[: len(prefix)] == prefix for prefix in protected):
        raise SecureFileError(
            "invalid_seed_generation_path: output cannot be inside a frozen input root"
        )


def _publish_package(
    root_fd: int,
    output_parts: tuple[str, ...],
    payloads: Mapping[str, bytes],
) -> None:
    parent_fd = open_directory_beneath(root_fd, output_parts[:-1])
    target_name = output_parts[-1]
    temporary_name = f".{target_name}.tmp-{uuid.uuid4().hex}"
    temporary_fd: int | None = None
    published = False
    try:
        if _entry_exists(parent_fd, target_name):
            raise FileExistsError("output target already exists")
        os.mkdir(temporary_name, mode=0o700, dir_fd=parent_fd)
        temporary_fd = os.open(
            temporary_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        for filename in OUTPUT_FILES:
            _write_exclusive_file(temporary_fd, filename, payloads[filename])
        os.fsync(temporary_fd)
        os.fsync(parent_fd)
        _rename_directory_noreplace(
            parent_fd,
            temporary_name,
            target_name,
        )
        published = True
        os.fsync(parent_fd)
    finally:
        if not published:
            _cleanup_temporary_directory(
                parent_fd,
                temporary_fd,
                temporary_name,
            )
        if temporary_fd is not None:
            os.close(temporary_fd)
        os.close(parent_fd)


def _write_exclusive_file(directory_fd: int, filename: str, payload: bytes) -> None:
    descriptor = os.open(
        filename,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while publishing review seed")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _entry_exists(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _rename_directory_noreplace(parent_fd: int, source: str, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    if hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(parent_fd, source_bytes, parent_fd, target_bytes, 1)
    elif hasattr(libc, "renameatx_np"):
        rename = libc.renameatx_np
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(parent_fd, source_bytes, parent_fd, target_bytes, 0x00000004)
    else:
        raise SecureFileError(
            "invalid_seed_generation_path: atomic no-replace rename is unavailable"
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError("output target already exists")
    raise OSError(error_number, "atomic review-seed publication failed")


def _cleanup_temporary_directory(
    parent_fd: int,
    temporary_fd: int | None,
    temporary_name: str,
) -> None:
    if temporary_fd is not None:
        for filename in OUTPUT_FILES:
            try:
                os.unlink(filename, dir_fd=temporary_fd)
            except FileNotFoundError:
                pass
    try:
        os.rmdir(temporary_name, dir_fd=parent_fd)
    except FileNotFoundError:
        pass

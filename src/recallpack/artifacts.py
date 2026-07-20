from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from recallpack.budget import canonical_json
from recallpack.tokenization import TokenCounter, default_tokenizer


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _ROOT / "specs" / "001-recallpack-v4" / "contracts" / "artifacts.schema.json"
_FILE_ORDER = ("recallpack.json", "PACK.md", "trace.json")
_PRIVATE_PATH_RE = re.compile(
    r"(^|[\s(\"'`])"
    r"(?:[A-Za-z]:\\|/(?:Users|home|private|var|tmp|etc|opt|Volumes|mnt|srv|root|proc|sys|dev))"
    r"(?:[\\/][^\s\"'`)]*)?",
    re.IGNORECASE,
)
_PRIVATE_URL_RE = re.compile(
    r"(?i)\bhttps?://(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|10(?:\.\d{1,3}){3}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2})\b"
)
_SECRET_RE = re.compile(
    r"(?ix)"
    r"(sk-[A-Za-z0-9_-]{20,})"
    r"|"
    r"(?:-----BEGIN [A-Z0-9_ ]+-----)"
)
_SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:api[_-]?key|token|secret|password|passwd|access[_-]?key|private[_-]?key)(?:$|_)"
)
_DANGEROUS_SOURCE_REF_RE = re.compile(
    r"(?i)(?:\.\.|^/|^[A-Za-z]:\\|^file:|^sqlite:|^ssh://[^/@]+@)"
)


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_compile_bundle_v4(
    bundle: dict[str, Any],
    tokenizer: TokenCounter | None = None,
) -> None:
    try:
        counter = tokenizer or default_tokenizer()
    except Exception as exc:
        raise ValueError(
            "invalid_compile_usage /trace/exact_token_count: exact tokenizer unavailable"
        ) from exc
    errors: list[tuple[str, str, str]] = []

    errors.extend(_schema_errors(bundle))

    pack = bundle.get("pack")
    trace = bundle.get("trace")
    pack_markdown = bundle.get("pack_markdown")
    files = bundle.get("files")
    if not isinstance(pack, dict) or not isinstance(trace, dict):
        _raise_validation_errors(errors)
        return

    pack_bytes = canonical_json(pack).encode("utf-8")
    expected_markdown = _render_pack_markdown(pack)
    expected_markdown_bytes = expected_markdown.encode("utf-8")
    trace_bytes = canonical_json(trace).encode("utf-8")

    if bundle.get("compile_id") != trace.get("compile_id"):
        errors.append(
            (
                "invalid_compile_reference",
                "/compile_id",
                "top-level compile_id must match trace.compile_id",
            )
        )

    pack_memory_ids = [
        memory.get("id")
        for memory in pack.get("memories", [])
        if isinstance(memory, dict)
    ]
    selected_ids = trace.get("selected_memory_ids")
    if pack_memory_ids != selected_ids:
        errors.append(
            (
                "invalid_compile_reference",
                "/trace/selected_memory_ids",
                "pack memory ids must equal trace.selected_memory_ids in order",
            )
        )

    errors.extend(_validate_candidate_order(trace))
    errors.extend(_validate_selected_and_omissions(trace))
    errors.extend(_validate_runtime_steps(trace))
    errors.extend(_validate_provider_traces(trace))

    if pack_markdown != expected_markdown:
        errors.append(
            (
                "invalid_compile_order",
                "/pack_markdown",
                "pack_markdown must be the deterministic rendering of pack",
            )
        )

    errors.extend(_validate_token_budget(trace, pack_bytes, counter))
    errors.extend(
        _validate_artifact_hashes_and_files(
            trace=trace,
            files=files,
            pack_bytes=pack_bytes,
            markdown_bytes=expected_markdown_bytes,
            trace_bytes=trace_bytes,
        )
    )
    errors.extend(_scan_for_sensitive_content(bundle))

    _raise_validation_errors(errors)


def build_compile_bundle_v4(
    *,
    compile_id: str,
    request: dict[str, Any],
    pack: dict[str, Any],
    compile_trace: dict[str, Any],
    tokenizer: TokenCounter | None = None,
) -> dict[str, Any]:
    try:
        counter = tokenizer or default_tokenizer()
        pack_bytes = canonical_json(pack).encode("utf-8")
        exact_token_count = counter.count(pack_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_compile_usage") from exc

    pack_markdown = _render_pack_markdown(pack)
    markdown_bytes = pack_markdown.encode("utf-8")
    candidate_scores = list(compile_trace.get("candidate_scores", []))
    has_candidates = bool(candidate_scores)
    runtime_steps = _compile_runtime_steps(has_candidates)
    trace = {
        "compile_id": compile_id,
        "request": dict(request),
        "memory_snapshot_seq": int(compile_trace.get("memory_snapshot_seq", 0)),
        "candidate_scores": candidate_scores,
        "reranked_memory_ids": list(compile_trace.get("reranked_memory_ids", [])),
        "selected_memory_ids": [memory["id"] for memory in pack["memories"]],
        "omissions": list(compile_trace.get("omissions", [])),
        "exact_token_count": exact_token_count,
        "tokenizer": {
            "encoding": "o200k_base",
            "package": "tiktoken",
            "package_version": "0.13.0",
            "exact": True,
        },
        "provider_traces": list(
            compile_trace.get("artifact_provider_traces", [])
        ),
        "runtime_steps": runtime_steps,
        "input_artifact_hashes": {
            "recallpack.json": _sha256_hex(pack_bytes),
            "PACK.md": _sha256_hex(markdown_bytes),
        },
    }
    trace_bytes = canonical_json(trace).encode("utf-8")
    bundle = {
        "schema_version": "4.0",
        "semantic_rules_version": "compile-semantic-rules/4.0",
        "compile_id": compile_id,
        "pack": pack,
        "pack_markdown": pack_markdown,
        "trace": trace,
        "files": [
            _file_record("recallpack.json", pack_bytes),
            _file_record("PACK.md", markdown_bytes),
            _file_record("trace.json", trace_bytes),
        ],
    }
    validate_compile_bundle_v4(bundle, tokenizer=counter)
    return bundle


def publish_compile_bundle_v4(
    bundle: dict[str, Any],
    artifact_root: Path,
    tokenizer: TokenCounter | None = None,
) -> dict[str, Any]:
    try:
        validate_compile_bundle_v4(bundle, tokenizer=tokenizer)
    except ValueError as exc:
        raise ValueError(f"artifact_validation_failed: {exc}") from exc

    compile_id = bundle["compile_id"]
    compiles_dir = Path(artifact_root) / "compiles"
    final_dir = compiles_dir / compile_id
    temp_dir: Path | None = None

    payloads = {
        "recallpack.json": canonical_json(bundle["pack"]).encode("utf-8"),
        "PACK.md": bundle["pack_markdown"].encode("utf-8"),
        "trace.json": canonical_json(bundle["trace"]).encode("utf-8"),
    }

    try:
        compiles_dir.mkdir(parents=True, exist_ok=True)
        _fsync_directory(compiles_dir)

        temp_dir = compiles_dir / f".{compile_id}.{secrets.token_hex(8)}.tmp"
        temp_dir.mkdir()
        _fsync_directory(compiles_dir)

        for name in _FILE_ORDER:
            path = temp_dir / name
            with path.open("wb") as handle:
                handle.write(payloads[name])
                handle.flush()
                os.fsync(handle.fileno())

        _fsync_directory(temp_dir)
        if final_dir.exists():
            raise FileExistsError(final_dir)
        os.rename(temp_dir, final_dir)
        temp_dir = None
        _fsync_directory(final_dir)
        _fsync_directory(compiles_dir)
    except FileExistsError as exc:
        if temp_dir is not None and temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise ValueError("artifact_publication_failed: compile_id collision") from exc
    except OSError as exc:
        if temp_dir is not None and temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise ValueError(f"artifact_publication_failed: {exc.__class__.__name__}") from exc

    return {
        "compile_id": compile_id,
        "files": list(bundle["files"]),
        "relative_directory": f"compiles/{compile_id}",
    }


def _schema_errors(bundle: dict[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    for error in _schema_validator().iter_errors(bundle):
        pointer = _json_pointer(error.absolute_path)
        code = _schema_error_code(pointer, error.message)
        errors.append((code, pointer, error.message))
    return errors


def _schema_error_code(pointer: str, message: str) -> str:
    if "trace_sha256" in message:
        return "artifact_hash_mismatch"
    if pointer.startswith("/trace/runtime_steps"):
        return "invalid_runtime_steps"
    if pointer.startswith("/trace/provider_traces") or pointer.startswith("/trace/exact_token_count"):
        return "invalid_compile_usage"
    if pointer.startswith("/trace") or pointer == "/compile_id":
        return "invalid_compile_reference"
    if pointer.startswith("/files"):
        return "artifact_hash_mismatch"
    return "artifact_hash_mismatch"


def _validate_candidate_order(trace: dict[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    candidates = trace.get("candidate_scores")
    reranked_ids = trace.get("reranked_memory_ids")
    if not isinstance(candidates, list) or not isinstance(reranked_ids, list):
        return errors

    seen_ids: set[str] = set()
    indexes: list[int] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        memory_id = candidate.get("memory_id")
        candidate_index = candidate.get("candidate_index")
        embedding_cosine = candidate.get("embedding_cosine")
        rerank_score = candidate.get("rerank_score")
        if memory_id in seen_ids:
            errors.append(
                (
                    "invalid_compile_order",
                    f"/trace/candidate_scores/{index}/memory_id",
                    "candidate memory ids must be unique",
                )
            )
        if isinstance(memory_id, str):
            seen_ids.add(memory_id)
        if isinstance(candidate_index, int):
            indexes.append(candidate_index)
        if not _is_finite_number(embedding_cosine):
            errors.append(
                (
                    "invalid_compile_order",
                    f"/trace/candidate_scores/{index}/embedding_cosine",
                    "embedding cosine scores must be finite",
                )
            )
        if rerank_score is not None and not _is_finite_number(rerank_score):
            errors.append(
                (
                    "invalid_compile_order",
                    f"/trace/candidate_scores/{index}/rerank_score",
                    "rerank scores must be finite",
                )
            )

    if indexes != list(range(len(candidates))):
        errors.append(
            (
                "invalid_compile_order",
                "/trace/candidate_scores",
                "candidate indexes must be contiguous 0..N-1 in list order",
            )
        )

    if candidates:
        sortable_candidates = [
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
            and isinstance(candidate.get("memory_id"), str)
            and _is_finite_number(candidate.get("rerank_score"))
            and isinstance(candidate.get("source_project_event_seq"), int)
        ]
        if len(sortable_candidates) == len(candidates):
            expected_order = sorted(
                sortable_candidates,
                key=lambda candidate: (
                    -float(candidate["rerank_score"]),
                    -int(candidate["source_project_event_seq"]),
                    str(candidate["memory_id"]),
                ),
            )
            expected_reranked_ids = [
                str(candidate["memory_id"]) for candidate in expected_order
            ]
        else:
            expected_reranked_ids = []
        if reranked_ids != expected_reranked_ids:
            errors.append(
                (
                    "invalid_compile_order",
                    "/trace/reranked_memory_ids",
                    "reranked ids must match deterministic rerank order",
                )
            )
    elif reranked_ids:
        errors.append(
            (
                "invalid_compile_order",
                "/trace/reranked_memory_ids",
                "empty candidates require an empty reranked list",
            )
        )

    return errors


def _validate_selected_and_omissions(trace: dict[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    reranked_ids = trace.get("reranked_memory_ids")
    selected_ids = trace.get("selected_memory_ids")
    omissions = trace.get("omissions")
    if (
        not isinstance(reranked_ids, list)
        or not isinstance(selected_ids, list)
        or not isinstance(omissions, list)
    ):
        return errors

    reranked_index = {memory_id: index for index, memory_id in enumerate(reranked_ids)}
    last_index = -1
    for index, memory_id in enumerate(selected_ids):
        if memory_id not in reranked_index:
            errors.append(
                (
                    "invalid_compile_reference",
                    f"/trace/selected_memory_ids/{index}",
                    "selected ids must reference reranked ids",
                )
            )
            continue
        current_index = reranked_index[memory_id]
        if current_index <= last_index:
            errors.append(
                (
                    "invalid_compile_order",
                    "/trace/selected_memory_ids",
                    "selected ids must preserve reranked order",
                )
            )
            break
        last_index = current_index

    seen_omissions: set[str] = set()
    valid_reasons = {
        ("embedding", "outside_top_20"),
        ("rerank", "rerank_order"),
        ("budget", "budget_overflow"),
        ("budget", "not_selected"),
    }
    for index, omission in enumerate(omissions):
        if not isinstance(omission, dict):
            continue
        memory_id = omission.get("memory_id")
        stage = omission.get("stage")
        reason = omission.get("reason")
        if memory_id in seen_omissions:
            errors.append(
                (
                    "invalid_compile_reference",
                    f"/trace/omissions/{index}/memory_id",
                    "omission ids must be unique",
                )
            )
        if memory_id in selected_ids:
            errors.append(
                (
                    "invalid_compile_reference",
                    f"/trace/omissions/{index}/memory_id",
                    "omissions must be disjoint from selected ids",
                )
            )
        if stage != "embedding" and memory_id not in reranked_index:
            errors.append(
                (
                    "invalid_compile_reference",
                    f"/trace/omissions/{index}/memory_id",
                    "rerank and budget omissions must reference reranked ids",
                )
            )
        if (stage, reason) not in valid_reasons:
            errors.append(
                (
                    "invalid_compile_order",
                    f"/trace/omissions/{index}",
                    "omission stage/reason pairing is invalid",
                )
            )
        if isinstance(memory_id, str):
            seen_omissions.add(memory_id)
    return errors


def _validate_runtime_steps(trace: dict[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    steps = trace.get("runtime_steps")
    candidates = trace.get("candidate_scores")
    if not isinstance(steps, list) or not isinstance(candidates, list):
        return errors

    if len(steps) != 7:
        errors.append(
            (
                "invalid_runtime_steps",
                "/trace/runtime_steps",
                "exactly seven runtime steps are required",
            )
        )
        return errors

    for index, step in enumerate(steps):
        if index in {2, 3} or not isinstance(step, dict):
            continue
        if step.get("status") != "succeeded":
            errors.append(
                (
                    "invalid_runtime_steps",
                    f"/trace/runtime_steps/{index}/status",
                    "only zero-candidate model steps may be skipped",
                )
            )

    embedding_step = steps[2] if isinstance(steps[2], dict) else {}
    rerank_step = steps[3] if isinstance(steps[3], dict) else {}
    embedding_status = embedding_step.get("status")
    rerank_status = rerank_step.get("status")
    if candidates:
        if embedding_status != "succeeded" or rerank_status != "succeeded":
            errors.append(
                (
                    "invalid_runtime_steps",
                    "/trace/runtime_steps",
                    "non-empty candidates require successful embedding and rerank steps",
                )
            )
    elif embedding_status != "skipped" or rerank_status != "skipped":
        errors.append(
            (
                "invalid_runtime_steps",
                "/trace/runtime_steps",
                "zero candidates require both model steps to be skipped",
            )
        )
    return errors


def _validate_provider_traces(trace: dict[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    provider_traces = trace.get("provider_traces")
    steps = trace.get("runtime_steps")
    candidates = trace.get("candidate_scores")
    if (
        not isinstance(provider_traces, list)
        or not isinstance(steps, list)
        or not isinstance(candidates, list)
    ):
        return errors

    roles = [item.get("role") for item in provider_traces if isinstance(item, dict)]
    allowed_roles = {"embedding", "rerank"}
    if any(role not in allowed_roles for role in roles):
        errors.append(
            (
                "invalid_runtime_steps",
                "/trace/provider_traces",
                "provider roles must be limited to embedding and rerank",
            )
        )

    has_candidates = bool(candidates)
    if has_candidates and roles.count("embedding") != 1:
        errors.append(
            (
                "invalid_runtime_steps",
                "/trace/provider_traces",
                "executed embedding requires exactly one embedding trace",
            )
        )
    if has_candidates and roles.count("rerank") != 1:
        errors.append(
            (
                "invalid_runtime_steps",
                "/trace/provider_traces",
                "executed rerank requires exactly one rerank trace",
            )
        )
    if not has_candidates and roles:
        errors.append(
            (
                "invalid_runtime_steps",
                "/trace/provider_traces",
                "zero-candidate compile must not contain provider traces",
            )
        )

    expected_models = {
        "embedding": ("text-embedding-v4", "candidate_memory_retrieval_query"),
        "rerank": (
            "qwen3-rerank",
            "precision_rerank_active_memory_candidates",
        ),
    }
    for index, provider_trace in enumerate(provider_traces):
        if not isinstance(provider_trace, dict):
            continue
        role = provider_trace.get("role")
        usage = provider_trace.get("token_usage")
        if role in expected_models:
            model_name, request_purpose = expected_models[role]
            if (
                provider_trace.get("model_name") != model_name
                or provider_trace.get("request_purpose") != request_purpose
            ):
                errors.append(
                    (
                        "invalid_compile_usage",
                        f"/trace/provider_traces/{index}",
                        "provider trace role, model, and purpose must agree",
                    )
                )
        if provider_trace.get("live") is True and provider_trace.get("request_id_present") is not True:
            errors.append(
                (
                    "invalid_runtime_steps",
                    f"/trace/provider_traces/{index}/request_id_present",
                    "live provider traces must declare request_id_present",
                )
            )
        if not isinstance(usage, dict):
            continue
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")
        if not all(
            isinstance(value, int) and value >= 0
            for value in (input_tokens, output_tokens, total_tokens)
        ):
            errors.append(
                (
                    "invalid_compile_usage",
                    f"/trace/provider_traces/{index}/token_usage",
                    "token usage values must be non-negative integers",
                )
            )
            continue
        if input_tokens + output_tokens != total_tokens:
            errors.append(
                (
                    "invalid_compile_usage",
                    f"/trace/provider_traces/{index}/token_usage/total_tokens",
                    "provider trace total_tokens must equal input_tokens + output_tokens",
                )
            )
    return errors


def _validate_token_budget(
    trace: dict[str, Any],
    pack_bytes: bytes,
    tokenizer: TokenCounter,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    request = trace.get("request")
    if not isinstance(request, dict):
        return errors
    try:
        exact_token_count = tokenizer.count(pack_bytes.decode("utf-8"))
    except Exception:
        return [
            (
                "invalid_compile_usage",
                "/trace/exact_token_count",
                "exact tokenizer failed while validating canonical recallpack.json",
            )
        ]
    reported = trace.get("exact_token_count")
    budget_tokens = request.get("budget_tokens")
    if exact_token_count != reported:
        errors.append(
            (
                "invalid_compile_usage",
                "/trace/exact_token_count",
                "exact_token_count must equal the canonical recallpack.json token count",
            )
        )
    if isinstance(budget_tokens, int) and exact_token_count > budget_tokens:
        errors.append(
            (
                "invalid_compile_usage",
                "/trace/request/budget_tokens",
                "exact_token_count must not exceed request.budget_tokens",
            )
        )
    return errors


def _validate_artifact_hashes_and_files(
    *,
    trace: dict[str, Any],
    files: Any,
    pack_bytes: bytes,
    markdown_bytes: bytes,
    trace_bytes: bytes,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    input_hashes = trace.get("input_artifact_hashes")
    if not isinstance(input_hashes, dict):
        return errors

    expected_bytes = {
        "recallpack.json": pack_bytes,
        "PACK.md": markdown_bytes,
        "trace.json": trace_bytes,
    }
    for name in ("recallpack.json", "PACK.md"):
        expected_hash = _sha256_hex(expected_bytes[name])
        if input_hashes.get(name) != expected_hash:
            errors.append(
                (
                    "artifact_hash_mismatch",
                    f"/trace/input_artifact_hashes/{name}",
                    f"{name} hash must match canonical artifact bytes",
                )
            )

    if not isinstance(files, list):
        return errors
    if [item.get("name") for item in files if isinstance(item, dict)] != list(_FILE_ORDER):
        errors.append(
            (
                "artifact_hash_mismatch",
                "/files",
                "files must use the exact literal filename order",
            )
        )
    for index, name in enumerate(_FILE_ORDER):
        if index >= len(files) or not isinstance(files[index], dict):
            continue
        item = files[index]
        payload = expected_bytes[name]
        if item.get("name") != name:
            errors.append(
                (
                    "artifact_hash_mismatch",
                    f"/files/{index}/name",
                    "file name must match the literal artifact contract",
                )
            )
        if item.get("bytes") != len(payload):
            errors.append(
                (
                    "artifact_hash_mismatch",
                    f"/files/{index}/bytes",
                    "file bytes must match the canonical payload length",
                )
            )
        if item.get("sha256") != _sha256_hex(payload):
            errors.append(
                (
                    "artifact_hash_mismatch",
                    f"/files/{index}/sha256",
                    "file sha256 must match the canonical payload hash",
                )
            )
    return errors


def _scan_for_sensitive_content(bundle: dict[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []

    def scan(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_pointer = f"{pointer}/{_escape_json_pointer(key)}"
                if isinstance(item, str) and _SECRET_KEY_RE.search(key) and item:
                    errors.append(
                        (
                            "secret_material_detected",
                            child_pointer,
                            "secret-bearing keys must not contain nonempty values",
                        )
                    )
                if key == "source_ref" and isinstance(item, str):
                    errors.extend(_validate_source_ref(item, child_pointer))
                scan(item, child_pointer)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                scan(item, f"{pointer}/{index}")
            return
        if not isinstance(value, str):
            return
        if _PRIVATE_PATH_RE.search(value) or _PRIVATE_URL_RE.search(value):
            errors.append(
                (
                    "private_path_detected",
                    pointer,
                    "private paths or loopback/private URLs are not allowed",
                )
            )
        if _SECRET_RE.search(value):
            errors.append(
                (
                    "secret_material_detected",
                    pointer,
                    "secret-shaped material is not allowed in artifacts",
                )
            )

    scan(bundle, "")
    return errors


def _validate_source_ref(value: str, pointer: str) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    if not re.fullmatch(r"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+", value):
        errors.append(
            (
                "invalid_compile_reference",
                pointer,
                "source_ref must match namespace:item",
            )
        )
    if _DANGEROUS_SOURCE_REF_RE.search(value):
        errors.append(
            (
                "private_path_detected",
                pointer,
                "source_ref must not contain paths or local transport schemes",
            )
        )
    return errors


def _step_executed(steps: list[Any], index: int) -> bool:
    if index >= len(steps) or not isinstance(steps[index], dict):
        return False
    return steps[index].get("status") == "succeeded"


def _render_pack_markdown(pack: dict[str, Any]) -> str:
    lines = ["# RecallPack", ""]
    for memory in pack.get("memories", []):
        if not isinstance(memory, dict):
            continue
        subject = str(memory.get("subject", ""))
        text = str(memory.get("text", ""))
        memory_id = str(memory.get("id", ""))
        memory_type = str(memory.get("type", ""))
        scope = str(memory.get("scope", ""))
        source_ref = str(memory.get("source_ref", ""))
        lines.extend(
            [
                f"## {subject}",
                "",
                text,
                "",
                f"- ID: `{memory_id}`",
                f"- Type: `{memory_type}`",
                f"- Scope: `{scope}`",
                f"- Source: `{source_ref}`",
                "- Lifecycle: `active`",
                "- Inclusion: `reranked_and_within_budget`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _compile_runtime_steps(has_candidates: bool) -> list[dict[str, Any]]:
    definitions = (
        ("validate_request", True, "succeeded"),
        ("load_active_snapshot", True, "succeeded"),
        ("embedding_top_20", False, "succeeded" if has_candidates else "skipped"),
        ("rerank", False, "succeeded" if has_candidates else "skipped"),
        ("budget_select", True, "succeeded"),
        ("render_artifacts", True, "succeeded"),
        ("publish_artifacts", True, "succeeded"),
    )
    return [
        {
            "index": index,
            "name": name,
            "status": status,
            "duration_ms": 0,
            "deterministic": deterministic,
        }
        for index, (name, deterministic, status) in enumerate(definitions)
    ]


def _file_record(name: str, payload: bytes) -> dict[str, Any]:
    return {"name": name, "sha256": _sha256_hex(payload), "bytes": len(payload)}


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _raise_validation_errors(errors: list[tuple[str, str, str]]) -> None:
    if not errors:
        return
    errors.sort(key=lambda item: (item[0], item[1]))
    message = "; ".join(
        f"{code} {pointer or '/'}: {detail}" for code, pointer, detail in errors
    )
    raise ValueError(message)


def _json_pointer(path: Any) -> str:
    parts = [str(part) for part in path]
    if not parts:
        return "/"
    return "/" + "/".join(_escape_json_pointer(part) for part in parts)


def _escape_json_pointer(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

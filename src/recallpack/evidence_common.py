from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _ROOT / "specs" / "001-recallpack-v4" / "contracts" / "evaluation.schema.json"
_SEMANTIC_RULES_VERSION = "4.0"
_V4_VARIANTS = (
    "raw_full_history",
    "semantic_rerank",
    "recency_aware",
    "recall_time_resolver",
    "recallpack",
)
_ARTIFACT_SIZE_LIMITS = {
    "fixture": 2_097_152,
    "source_ledger": 2_097_152,
    "source_ledger_hash": 2_097_152,
    "hidden_test_hash": 2_097_152,
    "label_hash": 2_097_152,
    "leakage_review": 2_097_152,
    "source_provenance": 2_097_152,
    "repository_snapshot": 67_108_864,
    "model_visible_snapshot": 67_108_864,
    "prompt_template": 2_097_152,
    "patch_provider_contract": 2_097_152,
    "runner_contract": 2_097_152,
    "model_visible_context": 2_097_152,
    "dockerfile": 1_048_576,
    "evaluator_runner": 1_048_576,
    "image_build_record": 1_048_576,
    "runtime_trace": 4_194_304,
    "evaluation_run": 4_194_304,
    "aggregate_report": 4_194_304,
    "test_result": 4_194_304,
    "patch_diff": 1_048_576,
    "original_file": 2_097_152,
    "patched_file": 2_097_152,
    "stdout": 1_048_576,
    "stderr": 1_048_576,
}
_TEXTUAL_INPUT_KINDS = frozenset(_ARTIFACT_SIZE_LIMITS) - {"repository_snapshot"}
_OUTPUT_ONLY_INPUT_KINDS = frozenset(
    {
        "runtime_trace",
        "evaluation_run",
        "aggregate_report",
        "model_visible_context",
        "patch_diff",
        "original_file",
        "patched_file",
        "stdout",
        "stderr",
        "test_result",
    }
)
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
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|passwd|credential)\s*[:=]\s*\S+"
)
_FROM_RE = re.compile(r"(?im)^\s*FROM\s+([^\s]+)(?:\s+AS\s+\S+)?\s*$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MODEL_VISIBLE_LEAK_RE = re.compile(
    r"(?i)("
    r"hidden[_ -]?test(?:[_ -]?(?:name|content|predicate))?\s*[=:]"
    r"|hidden test content"
    r"|gold[_ -]?(?:label|selected|source)\s*[=:]"
    r"|predicate\s*[=:]"
    r"|fail_if_[A-Za-z0-9_]+"
    r")"
)
_COPIED_SOURCE_RE = re.compile(r"(?i)\bcopied source text\b")


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _definition_validator(name: str) -> Draft202012Validator:
    schema = _schema()
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{name}",
        },
        format_checker=FormatChecker(),
    )


def _schema_errors(
    value: Any,
    definition_name: str,
    *,
    default_code: str | None = None,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    for error in _definition_validator(definition_name).iter_errors(value):
        pointer = _json_pointer(error.absolute_path)
        errors.append(
            (
                _schema_error_code(
                    definition_name,
                    pointer,
                    default_code=default_code,
                ),
                pointer,
                _bounded_detail(error.message),
            )
        )
    return errors


def _schema_error_code(
    definition_name: str,
    pointer: str,
    *,
    default_code: str | None = None,
) -> str:
    if definition_name in {
        "evaluationReviewSeed",
        "externalReviewAttestation",
        "executionManifest41",
        "requiredMemoryLabelLedger41",
        "leakageReview41",
        "modelVisibleSnapshot41",
        "sourceProvenance41",
        "fixtureBundle41",
        "hiddenTestBundle41",
        "seedReceipt41",
        "manifestRegistrationReceipt41",
    }:
        return default_code or "invalid_review_seed"
    if definition_name == "run":
        if pointer.startswith("/outcome"):
            return "invalid_run_outcome"
        if pointer.startswith("/relation_opportunities"):
            return "invalid_relation_evidence"
        if pointer == "/attempt_no":
            return "invalid_replacement"
        if pointer.startswith("/context_evidence"):
            return "invalid_context_evidence"
        if pointer.startswith("/provider_traces"):
            return "invalid_provider_trace"
        if pointer.startswith("/test_result/sandbox"):
            return "invalid_sandbox_evidence"
        if pointer.startswith("/test_result"):
            return "invalid_test_result"
        if (
            pointer.startswith("/run_output_artifact_catalog")
            or pointer.startswith("/artifact_hashes")
            or pointer.startswith("/patch")
        ):
            return "invalid_artifact_reference"
        if (
            pointer.startswith("/usage")
            or pointer.startswith("/latency_ms")
            or pointer.startswith("/metrics")
        ):
            return "invalid_run_arithmetic"
        if pointer.startswith("/failure/code"):
            return "invalid_failure_code"
        if pointer.startswith("/failure") or pointer.startswith("/designation"):
            return "invalid_designation"
        return default_code or "invalid_run_reference"

    if definition_name in {"sourceLedger", "imageBuildRecord"}:
        return default_code or "invalid_artifact_reference"

    if pointer.startswith("/claim_declarations"):
        return "invalid_claim_reference"
    if pointer.startswith("/execution_order") or pointer.startswith("/scenario_slots"):
        return "invalid_rung_grid"
    if pointer.startswith("/provider_settings") or pointer == "/descope_rung":
        return "invalid_rung_grid"
    if pointer.startswith("/input_artifact_catalog"):
        return "invalid_artifact_reference"
    if pointer.startswith("/comparison_contract") or pointer.startswith("/evaluator_contract"):
        return "invalid_artifact_reference"
    return "invalid_execution_manifest"


def _validate_catalog_artifact(
    artifact_id: str,
    record: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    pointer: str,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    payload = artifact_bytes.get(artifact_id)
    if not isinstance(payload, (bytes, bytearray)):
        errors.append(
            (
                "invalid_artifact_reference",
                pointer,
                "artifact bytes must exist for every input artifact id",
            )
        )
        return errors

    payload_bytes = bytes(payload)
    kind = record.get("kind")
    if record.get("bytes") != len(payload_bytes):
        errors.append(
            (
                "invalid_artifact_reference",
                f"{pointer}/bytes",
                "artifact bytes must match the catalog length",
            )
        )
    if record.get("sha256") != _sha256_hex(payload_bytes):
        errors.append(
            (
                "invalid_artifact_reference",
                f"{pointer}/sha256",
                "artifact sha256 must match the payload bytes",
            )
        )
    max_bytes = _ARTIFACT_SIZE_LIMITS.get(kind)
    if max_bytes is None:
        errors.append(
            (
                "invalid_artifact_reference",
                f"{pointer}/kind",
                "unsupported input artifact kind",
            )
        )
    elif len(payload_bytes) > max_bytes:
        errors.append(
            (
                "invalid_artifact_reference",
                f"{pointer}/bytes",
                "artifact exceeds the allowed byte ceiling",
            )
        )

    if kind in _TEXTUAL_INPUT_KINDS:
        try:
            text = payload_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            errors.append(
                (
                    "invalid_artifact_reference",
                    pointer,
                    "textual input artifacts must be valid UTF-8",
                )
            )
            return errors
        errors.extend(_scan_text(text, pointer))
        errors.extend(_scan_model_visible_text(kind, text, pointer))
        if kind == "source_ledger_hash" and not _SHA256_RE.fullmatch(text.strip()):
            errors.append(
                (
                    "invalid_artifact_reference",
                    pointer,
                    "source_ledger_hash payload must contain one sha256 hex digest",
                )
            )
    return errors


def _resolve_artifact(
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    artifact_id: Any,
    *,
    expected_kind: str,
    pointer: str,
) -> tuple[dict[str, Any] | None, list[tuple[str, str, str]]]:
    errors: list[tuple[str, str, str]] = []
    if not isinstance(artifact_id, str) or artifact_id not in catalog:
        errors.append(
            (
                "invalid_artifact_reference",
                pointer,
                "artifact reference must resolve to an input catalog record",
            )
        )
        return None, errors
    record = catalog[artifact_id]
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
            f"/input_artifact_catalog/{_escape_json_pointer(artifact_id)}",
        )
    )
    payload = artifact_bytes.get(artifact_id)
    if not isinstance(payload, (bytes, bytearray)):
        return None, errors
    return {"artifact_id": artifact_id, "payload": bytes(payload)}, errors


def _scan_text(value: str, pointer: str) -> list[tuple[str, str, str]]:
    if _PRIVATE_PATH_RE.search(value) or _PRIVATE_URL_RE.search(value):
        return [
            (
                "invalid_artifact_reference",
                pointer,
                "private path or private host content is not allowed",
            )
        ]
    if _SECRET_RE.search(value) or _SECRET_ASSIGNMENT_RE.search(value):
        return [("invalid_artifact_reference", pointer, "secret-like content is not allowed")]
    return []


def _scan_model_visible_text(
    kind: Any,
    value: str,
    pointer: str,
) -> list[tuple[str, str, str]]:
    if kind in {"model_visible_snapshot", "model_visible_context", "prompt_template"}:
        if _MODEL_VISIBLE_LEAK_RE.search(value):
            return [
                (
                    "invalid_artifact_reference",
                    pointer,
                    "model-visible artifacts must not contain hidden-test or gold-label leakage",
                )
            ]
        if _COPIED_SOURCE_RE.search(value):
            return [
                (
                    "invalid_artifact_reference",
                    pointer,
                    "model-visible artifacts must not copy upstream source text",
                )
            ]
    return []


def _normalize_relative_path(value: str) -> str:
    normalized = PurePosixPath(value).as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _raise_validation_errors(errors: Iterable[tuple[str, str, str]]) -> None:
    normalized = sorted(
        {
            (code, pointer or "/", _bounded_detail(detail))
            for code, pointer, detail in errors
        },
        key=lambda item: (item[0], item[1], item[2]),
    )
    if not normalized:
        return
    message = "\n".join(
        f"{_SEMANTIC_RULES_VERSION} {code} {pointer} {detail}"
        for code, pointer, detail in normalized
    )
    raise ValueError(message)


def _bounded_detail(value: str) -> str:
    sanitized = _SECRET_RE.sub("[redacted]", value)
    sanitized = _SECRET_ASSIGNMENT_RE.sub("[redacted]", sanitized)
    sanitized = _PRIVATE_PATH_RE.sub(
        lambda match: f"{match.group(1)}[private-path-redacted]",
        sanitized,
    )
    sanitized = _PRIVATE_URL_RE.sub("[private-host-redacted]", sanitized)
    return sanitized[:240]


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_json_payload(
    payload: bytes,
    *,
    pointer: str,
    code: str,
    detail: str,
    errors: list[tuple[str, str, str]],
) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append((code, pointer, detail))
        return None


def _json_pointer(path: Iterable[Any]) -> str:
    parts = [str(part) for part in path]
    if not parts:
        return "/"
    return "/" + "/".join(_escape_json_pointer(part) for part in parts)


def _escape_json_pointer(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")

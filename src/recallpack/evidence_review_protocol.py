from __future__ import annotations

import hashlib
import sqlite3
import threading
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from recallpack.evidence_common import _schema_errors
from recallpack.review_json import (
    canonicalize_review_json,
    parse_review_json,
    review_json_sha256,
)
from recallpack.secure_files import (
    SecureFileError,
    open_canonical_root,
    stable_read_beneath,
    walk_python_tree,
)


_PUBLIC_REGISTRY = {
    "projectodyssey": (
        "https://github.com/HomericIntelligence/Odyssey",
        "BSD-3-Clause",
    ),
    "deepagents": ("https://github.com/langchain-ai/deepagents", "MIT"),
    "graphiti": ("https://github.com/getzep/graphiti", "Apache-2.0"),
}
_PUBLIC_ORDER = tuple(_PUBLIC_REGISTRY)
_PUBLIC_WRITABLE_PATHS = {
    "projectodyssey": ("src/ci_policy.py", "pyproject.toml"),
    "deepagents": ("src/package_policy.py", "pyproject.toml"),
    "graphiti": ("src/backend_policy.py", "pyproject.toml"),
}
_BLIND_WRITABLE_PATHS = (
    "src/retry.py",
    "src/retry_policy.py",
    "src/auth.py",
    "src/config_loader.py",
    "pyproject.toml",
)
_COMMON_EXTERNAL_SLOTS = (
    ("required_memory_label_ledger", "post_outputs_fixed"),
    ("relation_label_ledger", "post_outputs_fixed"),
    ("leakage_review", "pre_run_eligibility_check"),
)
_BLIND_EXTERNAL_SLOTS = (
    ("fixture", "before_scenario_execution"),
    ("source_ledger", "before_scenario_execution"),
    ("model_visible_snapshot", "before_scenario_execution"),
    ("hidden_test_bundle", "after_model_output_fixed"),
)
_SENTINEL_DIGESTS = {character * 64 for character in "0123456789abcdef"}
_PROTOCOL_IDS = {"evaluation_review_seed", "external_review_attestation"}
_REGISTRATION_AUTHORITY = object()
_ELIGIBILITY_MINT_AUTHORITY = object()


@dataclass(frozen=True)
class DiagnosticExecutionManifest41:
    manifest: dict[str, Any]
    artifact_bytes: dict[str, bytes]


class EligibleExecutionManifest41:
    """Opaque proof that all pre-registration eligibility gates passed."""

    def __new__(cls) -> EligibleExecutionManifest41:
        raise TypeError("EligibleExecutionManifest41 cannot be constructed directly")


@dataclass(frozen=True)
class EligibilityBinding41:
    review_seed_sha256: str
    review_attestation_sha256: str
    execution_manifest_sha256: str
    ordered_leakage_review_sha256: tuple[str, ...]
    leakage_set_sha256: str
    eligibility_gate_version: str


@dataclass(frozen=True)
class EligibleRegistration41:
    review_seed_sha256: str
    execution_manifest_sha256: str
    review_attestation_sha256: str
    leakage_set_sha256: str
    eligibility_gate_version: str


@dataclass(frozen=True)
class _EligiblePayload41:
    manifest: dict[str, Any]
    artifact_bytes: dict[str, bytes]
    seed_receipt: dict[str, Any]


_ELIGIBILITY_GATE_VERSION = "pre_registration_leakage_v1"
_ELIGIBILITY_BINDINGS: weakref.WeakKeyDictionary[
    EligibleExecutionManifest41, EligibilityBinding41
] = weakref.WeakKeyDictionary()
_ELIGIBLE_PAYLOADS: weakref.WeakKeyDictionary[
    EligibleExecutionManifest41, _EligiblePayload41
] = weakref.WeakKeyDictionary()
_ELIGIBILITY_LOCK = threading.Lock()


# Compatibility alias for callers that only need diagnostic projection.
AssembledExecutionManifest = DiagnosticExecutionManifest41


class InMemoryManifestRegistry:
    """Thread-safe eligibility registration authority."""

    def __init__(self) -> None:
        # Legacy rows are intentionally retained as adverse history only.
        self._registrations: dict[str, str] = {}
        self._eligible_registrations: dict[str, EligibleRegistration41] = {}
        self._lock = threading.Lock()

    def _record_validated_registration(
        self,
        registration: EligibleRegistration41,
        authority: object,
    ) -> EligibleRegistration41:
        if authority is not _REGISTRATION_AUTHORITY:
            _fail(
                "invalid_manifest_binding",
                "/execution_manifest_sha256",
                "registration requires validated protocol authority",
            )
        with self._lock:
            if registration.review_seed_sha256 in self._registrations:
                _fail(
                    "review_seed_reuse",
                    "/review/review_seed_sha256",
                    "legacy registration permanently burns this seed",
                )
            current = self._eligible_registrations.get(
                registration.review_seed_sha256
            )
            if current is not None and current != registration:
                _fail("review_seed_reuse", "/review/review_seed_sha256", "seed already registered")
            self._eligible_registrations[registration.review_seed_sha256] = registration
        return registration

    def resolve(self, review_seed_sha256: str) -> EligibleRegistration41 | None:
        with self._lock:
            return self._eligible_registrations.get(review_seed_sha256)


class ManifestRegistry(Protocol):
    def _record_validated_registration(
        self,
        registration: EligibleRegistration41,
        authority: object,
    ) -> EligibleRegistration41: ...

    def resolve(self, review_seed_sha256: str) -> EligibleRegistration41 | None: ...


class SqliteManifestRegistry:
    """Durable compare-and-set authority for review seed registration."""

    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_seed_registrations (
                review_seed_sha256 TEXT PRIMARY KEY,
                execution_manifest_sha256 TEXT NOT NULL UNIQUE,
                CHECK(length(review_seed_sha256) = 64),
                CHECK(length(execution_manifest_sha256) = 64)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS eligible_review_seed_registrations (
                review_seed_sha256 TEXT PRIMARY KEY,
                execution_manifest_sha256 TEXT NOT NULL UNIQUE,
                review_attestation_sha256 TEXT NOT NULL,
                leakage_set_sha256 TEXT NOT NULL,
                eligibility_gate_version TEXT NOT NULL
                    CHECK(eligibility_gate_version = 'pre_registration_leakage_v1'),
                CHECK(length(review_seed_sha256) = 64),
                CHECK(length(execution_manifest_sha256) = 64),
                CHECK(length(review_attestation_sha256) = 64),
                CHECK(length(leakage_set_sha256) = 64)
            )
            """
        )

    def _record_validated_registration(
        self,
        registration: EligibleRegistration41,
        authority: object,
    ) -> EligibleRegistration41:
        if authority is not _REGISTRATION_AUTHORITY:
            _fail(
                "invalid_manifest_binding",
                "/execution_manifest_sha256",
                "registration requires validated protocol authority",
            )
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            legacy_row = connection.execute(
                "SELECT 1 FROM review_seed_registrations "
                "WHERE review_seed_sha256 = ?",
                (registration.review_seed_sha256,),
            ).fetchone()
            if legacy_row is not None:
                connection.execute("ROLLBACK")
                _fail(
                    "review_seed_reuse",
                    "/review/review_seed_sha256",
                    "legacy registration permanently burns this seed",
                )
            row = connection.execute(
                "SELECT review_seed_sha256, execution_manifest_sha256, "
                "review_attestation_sha256, leakage_set_sha256, eligibility_gate_version "
                "FROM eligible_review_seed_registrations "
                "WHERE review_seed_sha256 = ?",
                (registration.review_seed_sha256,),
            ).fetchone()
            current = None if row is None else EligibleRegistration41(*map(str, row))
            if current is not None and current != registration:
                connection.execute("ROLLBACK")
                _fail("review_seed_reuse", "/review/review_seed_sha256", "seed already registered")
            if row is None:
                connection.execute(
                    "INSERT INTO eligible_review_seed_registrations "
                    "(review_seed_sha256, execution_manifest_sha256, "
                    "review_attestation_sha256, leakage_set_sha256, "
                    "eligibility_gate_version) VALUES (?, ?, ?, ?, ?)",
                    (
                        registration.review_seed_sha256,
                        registration.execution_manifest_sha256,
                        registration.review_attestation_sha256,
                        registration.leakage_set_sha256,
                        registration.eligibility_gate_version,
                    ),
                )
            connection.execute("COMMIT")
            return registration
        except sqlite3.Error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def resolve(self, review_seed_sha256: str) -> EligibleRegistration41 | None:
        row = self._connection.execute(
            "SELECT review_seed_sha256, execution_manifest_sha256, "
            "review_attestation_sha256, leakage_set_sha256, eligibility_gate_version "
            "FROM eligible_review_seed_registrations "
            "WHERE review_seed_sha256 = ?",
            (review_seed_sha256,),
        ).fetchone()
        return None if row is None else EligibleRegistration41(*map(str, row))

    def close(self) -> None:
        self._connection.close()


def resolve_validated_registration(
    registry: ManifestRegistry,
    review_seed_sha256: str,
) -> EligibleRegistration41 | None:
    if type(registry) not in (InMemoryManifestRegistry, SqliteManifestRegistry):
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "untrusted manifest registry implementation",
        )
    return registry.resolve(review_seed_sha256)


def require_eligible_registration_41(
    registry: ManifestRegistry,
    manifest: Mapping[str, Any],
) -> EligibleRegistration41:
    expected_binding = _eligibility_binding_for_manifest(manifest)
    expected = EligibleRegistration41(
        review_seed_sha256=expected_binding.review_seed_sha256,
        execution_manifest_sha256=expected_binding.execution_manifest_sha256,
        review_attestation_sha256=expected_binding.review_attestation_sha256,
        leakage_set_sha256=expected_binding.leakage_set_sha256,
        eligibility_gate_version=expected_binding.eligibility_gate_version,
    )
    resolved = resolve_validated_registration(
        registry,
        expected.review_seed_sha256,
    )
    if resolved != expected:
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "manifest lacks the exact five-field eligible registration",
        )
    return expected


def derive_external_artifact_slots(seed: Mapping[str, Any]) -> list[dict[str, str]]:
    scenarios = seed.get("scenario_plan")
    if not isinstance(scenarios, list):
        _fail("invalid_review_seed", "/scenario_plan", "scenario_plan must be an array")
    result: list[dict[str, str]] = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, Mapping):
            _fail("invalid_review_seed", f"/scenario_plan/{index}", "scenario must be an object")
        slot = scenario.get("scenario_slot")
        evidence_class = scenario.get("evidence_class")
        if not isinstance(slot, str):
            _fail("invalid_review_seed", f"/scenario_plan/{index}/scenario_slot", "invalid slot")
        kinds = list(_COMMON_EXTERNAL_SLOTS)
        if evidence_class == "blind_holdout":
            kinds.extend(_BLIND_EXTERNAL_SLOTS)
        for kind, reveal_phase in kinds:
            result.append(
                {
                    "artifact_id": f"external__{slot}__{kind}",
                    "scenario_slot": slot,
                    "kind": kind,
                    "canonicalization": "rfc8785_json",
                    "reveal_phase": reveal_phase,
                    "custody_state": "sealed_external",
                }
            )
    return result


def validate_evaluation_review_seed(
    seed: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    repository_root: Path | None = None,
    repository_root_fd: int | None = None,
) -> None:
    if (
        isinstance(seed, Mapping)
        and isinstance(seed.get("scenario_plan"), list)
        and isinstance(seed.get("external_artifact_slots"), list)
    ):
        expected_slots = derive_external_artifact_slots(seed)
        if seed["external_artifact_slots"] != expected_slots:
            _fail(
                "external_artifact_set_mismatch",
                "/external_artifact_slots",
                "external slots must equal the validator-derived matrix",
            )
    errors = _schema_errors(seed, "evaluationReviewSeed", default_code="invalid_review_seed")
    if errors:
        _raise_review_errors(errors)
    _validate_timestamp(seed["created_at"], "/created_at", "invalid_review_seed")
    _validate_rung_scenarios(seed)
    _validate_seed_catalog(seed, artifact_bytes)
    _validate_seed_execution_contract(seed, artifact_bytes)
    _validate_public_scenarios(seed, artifact_bytes)
    if repository_root is not None and repository_root_fd is not None:
        _fail(
            "invalid_review_seed",
            "/code_hashes",
            "repository root path and descriptor are mutually exclusive",
        )
    expected_code_hashes = None
    if repository_root_fd is not None:
        expected_code_hashes = _compute_frozen_code_hashes_from_root_fd(
            repository_root_fd
        )
    elif repository_root is not None:
        expected_code_hashes = compute_frozen_code_hashes(repository_root)
    if expected_code_hashes is not None and seed["code_hashes"] != expected_code_hashes:
        _fail("invalid_review_seed", "/code_hashes", "frozen code hashes do not match repository")


def compute_frozen_code_hashes(repository_root: Path) -> dict[str, str]:
    try:
        with open_canonical_root(repository_root) as root_fd:
            return _compute_frozen_code_hashes_from_root_fd(root_fd)
    except SecureFileError as exc:
        _fail("invalid_review_seed", "/code_hashes", str(exc))


def _compute_frozen_code_hashes_from_root_fd(root_fd: int) -> dict[str, str]:
    try:
        runtime_files = walk_python_tree(root_fd, "src/recallpack")
        evaluator_files = [
            (
                "evaluation/Dockerfile",
                stable_read_beneath(root_fd, "evaluation/Dockerfile"),
            ),
            (
                "evaluation/.dockerignore",
                stable_read_beneath(root_fd, "evaluation/.dockerignore"),
            ),
            *walk_python_tree(root_fd, "evaluation/runner"),
        ]
        if not runtime_files or len(evaluator_files) < 3:
            _fail("invalid_review_seed", "/code_hashes", "frozen code roots are empty")
        schema_bytes = stable_read_beneath(
            root_fd,
            "specs/001-recallpack-v4/contracts/evaluation.schema.json",
        )
        dependency_bytes = stable_read_beneath(root_fd, "requirements-v4.txt")
    except SecureFileError as exc:
        _fail("invalid_review_seed", "/code_hashes", str(exc))
    return {
        "runtime_tree_sha256": _tree_hash_payloads(runtime_files),
        "evaluator_tree_sha256": _tree_hash_payloads(evaluator_files),
        "evaluation_schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "dependency_lock_sha256": hashlib.sha256(dependency_bytes).hexdigest(),
    }


def validate_external_review_attestation(
    attestation: Mapping[str, Any],
    seed: Mapping[str, Any],
    seed_receipt: Mapping[str, Any] | None = None,
) -> None:
    errors = _schema_errors(
        attestation,
        "externalReviewAttestation",
        default_code="invalid_review_attestation",
    )
    if errors:
        _raise_review_errors(errors)
    seed_hash = review_json_sha256(seed)
    if attestation["review_seed_sha256"] != seed_hash:
        _fail("review_seed_hash_mismatch", "/review_seed_sha256", "attestation binds another seed")
    _validate_timestamp(attestation["reviewed_at"], "/reviewed_at", "invalid_review_attestation")
    expected_slots = derive_external_artifact_slots(seed)
    expected_artifacts = [
        {key: value for key, value in slot.items() if key != "custody_state"}
        for slot in expected_slots
    ]
    actual = attestation["external_artifacts"]
    if len(actual) != len(expected_artifacts):
        _fail("invalid_review_attestation", "/external_artifacts", "slot coverage is incomplete")
    for index, (entry, expected) in enumerate(zip(actual, expected_artifacts, strict=True)):
        for field in (
            "artifact_id",
            "scenario_slot",
            "kind",
            "canonicalization",
            "reveal_phase",
        ):
            if entry.get(field) != expected[field]:
                _fail(
                    "invalid_review_attestation",
                    f"/external_artifacts/{index}/{field}",
                    "attested slot metadata does not match the derived slot",
                )
        if entry["content_sha256"] in _SENTINEL_DIGESTS:
            _fail(
                "invalid_review_attestation",
                f"/external_artifacts/{index}/content_sha256",
                "repeated-character sentinel digests are forbidden",
            )
    expected_scopes = [
        {"scenario_slot": slot["scenario_slot"], "kind": slot["kind"]}
        for slot in expected_slots
    ]
    if attestation["authorship_scopes"] != expected_scopes:
        _fail("invalid_review_attestation", "/authorship_scopes", "authorship scopes must be exact")
    if seed_receipt is not None:
        receipt_errors = _schema_errors(
            seed_receipt,
            "seedReceipt41",
            default_code="invalid_review_attestation",
        )
        if receipt_errors:
            _raise_review_errors(receipt_errors)
        _validate_timestamp(seed_receipt["received_at"], "/received_at", "invalid_review_attestation")
        if (
            seed_receipt["review_seed_sha256"] != seed_hash
            or seed_receipt["receipt_id"] != attestation["seed_receipt_id"]
            or review_json_sha256(seed_receipt) != attestation["seed_receipt_sha256"]
        ):
            _fail("invalid_review_attestation", "/seed_receipt_sha256", "seed receipt binding failed")
        if seed_receipt["received_at"] > attestation["reviewed_at"]:
            _fail("invalid_review_attestation", "/reviewed_at", "review predates seed receipt")


def assemble_execution_manifest_41(
    seed: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    seed_receipt: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    repository_root: Path | None = None,
) -> DiagnosticExecutionManifest41:
    repository_root = _require_repository_root(repository_root)
    validate_evaluation_review_seed(
        seed,
        artifact_bytes=artifact_bytes,
        repository_root=repository_root,
    )
    validate_external_review_attestation(attestation, seed, seed_receipt)
    return _assemble_projection(seed, attestation, artifact_bytes)


def _assemble_projection(
    seed: Mapping[str, Any],
    attestation: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> DiagnosticExecutionManifest41:
    seed_bytes = canonicalize_review_json(seed)
    attestation_bytes = canonicalize_review_json(attestation)
    seed_hash = hashlib.sha256(seed_bytes).hexdigest()
    attestation_hash = hashlib.sha256(attestation_bytes).hexdigest()
    attested = {
        (entry["scenario_slot"], entry["kind"]): entry
        for entry in attestation["external_artifacts"]
    }
    scenarios = [_assemble_scenario(item) for item in seed["scenario_plan"]]
    fixture_hashes: dict[str, str] = {}
    label_hashes: dict[str, str] = {}
    hidden_hashes: dict[str, str] = {}
    for item in seed["scenario_plan"]:
        slot = item["scenario_slot"]
        if item["evidence_class"] == "blind_holdout":
            fixture_hashes[slot] = attested[(slot, "fixture")]["content_sha256"]
            hidden_hashes[slot] = attested[(slot, "hidden_test_bundle")]["content_sha256"]
        else:
            fixture_hashes[slot] = item["fixture_sha256"]
            hidden_hashes[slot] = item["hidden_test_content_sha256"]
        label_hashes[slot] = attested[(slot, "relation_label_ledger")]["content_sha256"]

    catalog = {key: dict(value) for key, value in seed["frozen_input_artifact_catalog"].items()}
    protocol_records = {
        "evaluation_review_seed": _protocol_record(
            "evaluation_review_seed", "protocol/evaluation-review-seed.json", seed_bytes
        ),
        "external_review_attestation": _protocol_record(
            "external_review_attestation",
            "protocol/external-review-attestation.json",
            attestation_bytes,
        ),
    }
    catalog.update(protocol_records)
    assembled_bytes = dict(artifact_bytes)
    assembled_bytes.update(
        {
            "evaluation_review_seed": seed_bytes,
            "external_review_attestation": attestation_bytes,
        }
    )
    for entry in attestation["external_artifacts"]:
        wrapper = entry["content_sha256"].encode("ascii")
        artifact_id = entry["artifact_id"]
        catalog[artifact_id] = {
            "kind": "external_hash_reference",
            "origin": "attested_external_reference",
            "relative_path": (
                f"protocol/external-hashes/{entry['scenario_slot']}/{entry['kind']}.sha256"
            ),
            "sha256": hashlib.sha256(wrapper).hexdigest(),
            "bytes": 64,
            "sanitized": True,
            "content_policy": "sanitized_bounded",
            "scenario_slot": entry["scenario_slot"],
            "external_kind": entry["kind"],
            "content_sha256": entry["content_sha256"],
            "canonicalization": entry["canonicalization"],
            "reveal_phase": entry["reveal_phase"],
        }
        assembled_bytes[artifact_id] = wrapper
    leakage_hashes = {
        slot: attested[(slot, "leakage_review")]["content_sha256"]
        for slot in (item["scenario_slot"] for item in seed["scenario_plan"])
    }
    manifest = {
        "record_type": "execution_manifest",
        "manifest_version": "execution-manifest/4.1",
        "created_at": seed["created_at"],
        "descope_rung": seed["target_rung"],
        "semantic_rules_version": "4.1",
        "code_hashes": dict(seed["code_hashes"]),
        "scenario_slots": [item["scenario_slot"] for item in seed["scenario_plan"]],
        "evidence_scenarios": scenarios,
        "fixture_hashes": fixture_hashes,
        "label_hashes": label_hashes,
        "hidden_test_hashes": hidden_hashes,
        "variants": list(seed["variants"]),
        "provider_settings": dict(seed["provider_settings"]),
        "comparison_contract": dict(seed["comparison_contract"]),
        "evaluator_contract": dict(seed["evaluator_contract"]),
        "technical_failure_codes": list(seed["technical_failure_codes"]),
        "execution_order": [dict(item) for item in seed["execution_order"]],
        "input_artifact_catalog": catalog,
        "claim_declarations": [dict(item) for item in seed["claim_declarations"]],
        "review": {
            "reviewer_role": attestation["reviewer_role"],
            "review_seed_artifact_id": "evaluation_review_seed",
            "review_seed_sha256": seed_hash,
            "review_attestation_artifact_id": "external_review_attestation",
            "review_attestation_sha256": attestation_hash,
            "leakage_review_hashes": leakage_hashes,
        },
        "evaluator_image_digest": seed["evaluator_image_digest"],
    }
    manifest_errors = _schema_errors(
        manifest,
        "executionManifest41",
        default_code="review_seed_projection_mismatch",
    )
    if manifest_errors:
        _raise_review_errors(manifest_errors)
    return DiagnosticExecutionManifest41(
        manifest=manifest,
        artifact_bytes=assembled_bytes,
    )


def assemble_execution_manifest_projection_41(
    seed: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    seed_receipt: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    repository_root: Path | None = None,
) -> DiagnosticExecutionManifest41:
    return assemble_execution_manifest_41(
        seed,
        attestation,
        seed_receipt=seed_receipt,
        artifact_bytes=artifact_bytes,
        repository_root=repository_root,
    )


def register_execution_manifest_41(
    eligible: object,
    *,
    registry: ManifestRegistry,
    **legacy_arguments: Any,
) -> EligibleRegistration41:
    if type(registry) not in (InMemoryManifestRegistry, SqliteManifestRegistry):
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "registration requires a trusted built-in registry",
        )
    if type(eligible) is not EligibleExecutionManifest41:
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "registration requires an eligible execution-manifest capability",
        )
    if legacy_arguments:
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "registration does not accept caller-provided manifest inputs",
        )
    with _ELIGIBILITY_LOCK:
        binding = _ELIGIBILITY_BINDINGS.get(eligible)
        payload = _ELIGIBLE_PAYLOADS.get(eligible)
    if binding is None or payload is None:
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "eligible capability has no trusted process-local binding",
        )
    seed_hash = _validate_execution_manifest_projection(
        payload.manifest,
        payload.artifact_bytes,
        seed_receipt=payload.seed_receipt,
        require_code_hash_binding=False,
    )
    expected = _eligibility_binding_for_manifest(payload.manifest)
    if seed_hash != binding.review_seed_sha256 or expected != binding:
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "eligible capability binding no longer matches its manifest",
        )
    registration = EligibleRegistration41(
        review_seed_sha256=binding.review_seed_sha256,
        execution_manifest_sha256=binding.execution_manifest_sha256,
        review_attestation_sha256=binding.review_attestation_sha256,
        leakage_set_sha256=binding.leakage_set_sha256,
        eligibility_gate_version=binding.eligibility_gate_version,
    )
    return registry._record_validated_registration(
        registration,
        _REGISTRATION_AUTHORITY,
    )


def _eligibility_binding_for_manifest(
    manifest: Mapping[str, Any],
) -> EligibilityBinding41:
    try:
        review = manifest["review"]
        scenario_slots = manifest["scenario_slots"]
        leakage_hashes = review["leakage_review_hashes"]
        ordered_rows = [
            {
                "scenario_slot": slot,
                "leakage_review_sha256": leakage_hashes[slot],
            }
            for slot in scenario_slots
        ]
        seed_hash = review["review_seed_sha256"]
        attestation_hash = review["review_attestation_sha256"]
    except (KeyError, TypeError):
        _fail(
            "invalid_manifest_binding",
            "/review",
            "manifest lacks complete eligibility bindings",
        )
    if not isinstance(scenario_slots, list) or not all(
        isinstance(slot, str) for slot in scenario_slots
    ):
        _fail(
            "invalid_manifest_binding",
            "/scenario_slots",
            "scenario order is unavailable",
        )
    leakage_set = {
        "eligibility_gate_version": _ELIGIBILITY_GATE_VERSION,
        "ordered_leakage_reviews": ordered_rows,
    }
    return EligibilityBinding41(
        review_seed_sha256=str(seed_hash),
        review_attestation_sha256=str(attestation_hash),
        execution_manifest_sha256=review_json_sha256(manifest),
        ordered_leakage_review_sha256=tuple(
            str(row["leakage_review_sha256"]) for row in ordered_rows
        ),
        leakage_set_sha256=review_json_sha256(leakage_set),
        eligibility_gate_version=_ELIGIBILITY_GATE_VERSION,
    )


def _mint_eligible_execution_manifest_41(
    diagnostic: DiagnosticExecutionManifest41,
    seed_receipt: Mapping[str, Any],
    authority: object,
) -> EligibleExecutionManifest41:
    if authority is not _ELIGIBILITY_MINT_AUTHORITY:
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "eligible capability requires trusted custody authority",
        )
    if type(diagnostic) is not DiagnosticExecutionManifest41:
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "eligible mint requires the exact diagnostic projection type",
        )
    manifest = parse_review_json(canonicalize_review_json(diagnostic.manifest))
    receipt = parse_review_json(canonicalize_review_json(seed_receipt))
    payload = _EligiblePayload41(
        manifest=dict(manifest),
        artifact_bytes=dict(diagnostic.artifact_bytes),
        seed_receipt=dict(receipt),
    )
    binding = _eligibility_binding_for_manifest(payload.manifest)
    capability = object.__new__(EligibleExecutionManifest41)
    with _ELIGIBILITY_LOCK:
        _ELIGIBILITY_BINDINGS[capability] = binding
        _ELIGIBLE_PAYLOADS[capability] = payload
    return capability


def validate_execution_manifest_41(
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    repository_root: Path | None = None,
) -> None:
    repository_root = _require_repository_root(repository_root)
    _validate_execution_manifest_projection(
        manifest,
        artifact_bytes,
        repository_root=repository_root,
        require_code_hash_binding=True,
    )


def validate_registered_execution_manifest_41(
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    registry: ManifestRegistry,
) -> None:
    seed_hash = _validate_execution_manifest_projection(
        manifest,
        artifact_bytes,
        require_code_hash_binding=False,
    )
    registration = resolve_validated_registration(registry, seed_hash)
    expected = _eligibility_binding_for_manifest(manifest)
    if registration != EligibleRegistration41(
        review_seed_sha256=expected.review_seed_sha256,
        execution_manifest_sha256=expected.execution_manifest_sha256,
        review_attestation_sha256=expected.review_attestation_sha256,
        leakage_set_sha256=expected.leakage_set_sha256,
        eligibility_gate_version=expected.eligibility_gate_version,
    ):
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "manifest did not pass the repository-bound registration gate",
        )


def _validate_execution_manifest_projection(
    manifest: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    *,
    seed_receipt: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    require_code_hash_binding: bool = True,
) -> str:
    errors = _schema_errors(
        manifest,
        "executionManifest41",
        default_code="review_seed_projection_mismatch",
    )
    if errors:
        _raise_review_errors(errors)
    catalog = manifest.get("input_artifact_catalog")
    if not isinstance(catalog, Mapping):
        _fail("review_seed_projection_mismatch", "/input_artifact_catalog", "catalog missing")
    try:
        seed = parse_review_json(artifact_bytes["evaluation_review_seed"])
        attestation = parse_review_json(artifact_bytes["external_review_attestation"])
    except KeyError as exc:
        _fail("review_seed_projection_mismatch", "/input_artifact_catalog", f"missing {exc.args[0]}")
    seed_artifacts = {
        artifact_id: artifact_bytes[artifact_id]
        for artifact_id in seed["frozen_input_artifact_catalog"]
        if artifact_id in artifact_bytes
    }
    if require_code_hash_binding:
        repository_root = _require_repository_root(repository_root)
    validate_evaluation_review_seed(
        seed,
        artifact_bytes=seed_artifacts,
        repository_root=repository_root,
    )
    validate_external_review_attestation(attestation, seed, seed_receipt)
    expected = _assemble_projection(seed, attestation, seed_artifacts)
    if canonicalize_review_json(manifest) != canonicalize_review_json(expected.manifest):
        _fail(
            "review_seed_projection_mismatch",
            "/",
            "manifest is not the deterministic seed plus attestation projection",
        )
    for artifact_id, record in manifest["input_artifact_catalog"].items():
        payload = artifact_bytes.get(artifact_id)
        if payload is None:
            _fail("review_seed_projection_mismatch", f"/input_artifact_catalog/{artifact_id}", "artifact bytes missing")
        if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
            _fail("review_seed_projection_mismatch", f"/input_artifact_catalog/{artifact_id}", "artifact record mismatch")
        if expected.artifact_bytes.get(artifact_id) != payload:
            _fail("review_seed_projection_mismatch", f"/input_artifact_catalog/{artifact_id}", "artifact bytes differ from projection")
    return review_json_sha256(seed)


def assemble_execution_manifest_41_without_receipt(
    seed: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    repository_root: Path | None = None,
) -> DiagnosticExecutionManifest41:
    """Reassemble after receipt validation has occurred outside this pure projection."""

    repository_root = _require_repository_root(repository_root)
    validate_evaluation_review_seed(
        seed,
        artifact_bytes=artifact_bytes,
        repository_root=repository_root,
    )
    validate_external_review_attestation(attestation, seed)
    return _assemble_projection(seed, attestation, artifact_bytes)


def _require_repository_root(repository_root: Path | None) -> Path:
    if repository_root is None:
        _fail(
            "invalid_review_seed",
            "/code_hashes",
            "repository root is required for code-hash verification",
        )
    return repository_root


def _assemble_scenario(item: Mapping[str, Any]) -> dict[str, Any]:
    slot = item["scenario_slot"]

    def external(kind: str) -> str:
        return f"external__{slot}__{kind}"

    if item["evidence_class"] == "blind_holdout":
        fixture_id = external("fixture")
        return {
            "scenario_slot": slot,
            "evidence_class": "blind_holdout",
            "custody_state": "sealed_external",
            "fixture_artifact_id": fixture_id,
            "source_ledger_artifact_id": external("source_ledger"),
            "repository_snapshot_artifact_id": fixture_id,
            "model_visible_snapshot_artifact_id": external("model_visible_snapshot"),
            "hidden_test_hash_artifact_id": external("hidden_test_bundle"),
            "required_memory_label_hash_artifact_id": external("required_memory_label_ledger"),
            "relation_label_hash_artifact_id": external("relation_label_ledger"),
            "leakage_review_hash_artifact_id": external("leakage_review"),
            "provenance_artifact_id": None,
        }
    return {
        "scenario_slot": slot,
        "evidence_class": "source_backed_synthetic",
        "custody_state": "externally_reviewed_hashes_only",
        "fixture_artifact_id": item["fixture_artifact_id"],
        "source_ledger_artifact_id": item["source_ledger_artifact_id"],
        "repository_snapshot_artifact_id": item["repository_snapshot_artifact_id"],
        "model_visible_snapshot_artifact_id": item["model_visible_snapshot_artifact_id"],
        "hidden_test_hash_artifact_id": item["hidden_test_hash_artifact_id"],
        "required_memory_label_hash_artifact_id": external("required_memory_label_ledger"),
        "relation_label_hash_artifact_id": external("relation_label_ledger"),
        "leakage_review_hash_artifact_id": external("leakage_review"),
        "provenance_artifact_id": item["provenance_artifact_id"],
    }


def _protocol_record(kind: str, path: str, payload: bytes) -> dict[str, Any]:
    return {
        "kind": kind,
        "origin": "protocol_record",
        "relative_path": path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "sanitized": True,
        "content_policy": "sanitized_bounded",
    }


def _validate_rung_scenarios(seed: Mapping[str, Any]) -> None:
    scenarios = seed["scenario_plan"]
    rung = seed["target_rung"]
    classes = [item["evidence_class"] for item in scenarios]
    expected_classes = {
        "Full": ["source_backed_synthetic"] * 3 + ["blind_holdout"],
        "R1": ["source_backed_synthetic"] * 2 + ["blind_holdout"],
        "R2": ["source_backed_synthetic"] * 2,
    }[rung]
    if classes != expected_classes:
        _fail("invalid_scenario_identity", "/scenario_plan", "scenario class order is invalid")
    public_ids = [item["scenario_slot"] for item in scenarios if item["evidence_class"] != "blind_holdout"]
    if rung == "Full" and public_ids != list(_PUBLIC_ORDER):
        _fail("invalid_scenario_identity", "/scenario_plan", "Full registry order is fixed")
    if rung == "R1" and public_ids != list(_PUBLIC_ORDER[:2]):
        _fail("invalid_scenario_identity", "/scenario_plan", "R1 registry order is fixed")
    if rung == "R2":
        expected = [item for item in _PUBLIC_ORDER if item in public_ids]
        if public_ids != expected or len(set(public_ids)) != 2:
            _fail("invalid_scenario_identity", "/scenario_plan", "R2 IDs must be distinct registry order")


def _validate_seed_catalog(seed: Mapping[str, Any], artifact_bytes: Mapping[str, bytes]) -> None:
    catalog = seed["frozen_input_artifact_catalog"]
    expected_ids: set[str] = set()
    for scenario in seed["scenario_plan"]:
        if scenario["evidence_class"] == "source_backed_synthetic":
            expected_ids.update(
                scenario[field]
                for field in (
                    "fixture_artifact_id",
                    "source_ledger_artifact_id",
                    "repository_snapshot_artifact_id",
                    "model_visible_snapshot_artifact_id",
                    "hidden_test_hash_artifact_id",
                    "provenance_artifact_id",
                )
            )
    comparison = seed["comparison_contract"]
    expected_ids.update(
        comparison[field]
        for field in (
            "patch_provider_contract_artifact_id",
            "prompt_template_artifact_id",
            "runner_contract_artifact_id",
        )
    )
    evaluator = seed["evaluator_contract"]
    expected_ids.update(
        evaluator[field]
        for field in (
            "dockerfile_artifact_id",
            "runner_artifact_id",
            "build_record_artifact_id",
        )
    )
    if set(catalog) != expected_ids:
        _fail("invalid_review_seed", "/frozen_input_artifact_catalog", "catalog is not the exact frozen input set")
    paths: set[str] = set()
    for artifact_id, record in catalog.items():
        if artifact_id in _PROTOCOL_IDS or artifact_id.startswith("external__"):
            _fail("invalid_review_seed", f"/frozen_input_artifact_catalog/{artifact_id}", "reserved ID")
        path = record["relative_path"]
        if path == "protocol" or path.startswith("protocol/") or PurePosixPath(path).as_posix() != path:
            _fail("invalid_review_seed", f"/frozen_input_artifact_catalog/{artifact_id}/relative_path", "reserved or noncanonical path")
        if path in paths:
            _fail("invalid_review_seed", f"/frozen_input_artifact_catalog/{artifact_id}/relative_path", "duplicate path")
        paths.add(path)
        payload = artifact_bytes.get(artifact_id)
        if payload is None:
            _fail("invalid_artifact_reference", f"/frozen_input_artifact_catalog/{artifact_id}", "artifact bytes missing")
        if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
            _fail("invalid_artifact_reference", f"/frozen_input_artifact_catalog/{artifact_id}", "artifact bytes do not match record")


def _validate_seed_execution_contract(
    seed: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> None:
    from recallpack.evidence_execution_manifest import (
        _validate_claim_declarations,
        _validate_image_build_record,
        _validate_provider_settings,
        _validate_rung_grid,
    )

    semantic_view = {
        "descope_rung": seed["target_rung"],
        "scenario_slots": [item["scenario_slot"] for item in seed["scenario_plan"]],
        "evidence_scenarios": seed["scenario_plan"],
        "variants": seed["variants"],
        "provider_settings": seed["provider_settings"],
        "comparison_contract": seed["comparison_contract"],
        "evaluator_contract": seed["evaluator_contract"],
        "execution_order": seed["execution_order"],
        "claim_declarations": seed["claim_declarations"],
        "evaluator_image_digest": seed["evaluator_image_digest"],
    }
    errors = [
        *_validate_rung_grid(
            semantic_view,
            seed["scenario_plan"],
            seed["execution_order"],
        ),
        *_validate_provider_settings(semantic_view),
        *_validate_claim_declarations(semantic_view),
    ]
    expected_writable_paths = _expected_v41_writable_paths(seed["scenario_plan"])
    if seed["comparison_contract"].get("writable_paths") != expected_writable_paths:
        errors.append(
            (
                "unequal_comparison_contract",
                "/comparison_contract/writable_paths",
                "unequal_comparison_contract: writable paths must equal the "
                "selected scenario registry union",
            )
        )

    catalog = seed["frozen_input_artifact_catalog"]
    expected_references = (
        (
            seed["comparison_contract"]["patch_provider_contract_artifact_id"],
            "patch_provider_contract",
            "/comparison_contract/patch_provider_contract_artifact_id",
        ),
        (
            seed["comparison_contract"]["prompt_template_artifact_id"],
            "prompt_template",
            "/comparison_contract/prompt_template_artifact_id",
        ),
        (
            seed["comparison_contract"]["runner_contract_artifact_id"],
            "runner_contract",
            "/comparison_contract/runner_contract_artifact_id",
        ),
        (
            seed["evaluator_contract"]["dockerfile_artifact_id"],
            "dockerfile",
            "/evaluator_contract/dockerfile_artifact_id",
        ),
        (
            seed["evaluator_contract"]["runner_artifact_id"],
            "evaluator_runner",
            "/evaluator_contract/runner_artifact_id",
        ),
        (
            seed["evaluator_contract"]["build_record_artifact_id"],
            "image_build_record",
            "/evaluator_contract/build_record_artifact_id",
        ),
    )
    for artifact_id, expected_kind, pointer in expected_references:
        record = catalog.get(artifact_id)
        if not isinstance(record, Mapping) or record.get("kind") != expected_kind:
            errors.append(
                (
                    "invalid_artifact_reference",
                    pointer,
                    f"artifact must resolve to kind {expected_kind}",
                )
            )
    errors.extend(_validate_image_build_record(semantic_view, catalog, artifact_bytes))
    if errors:
        _raise_review_errors(
            [
                ("invalid_review_seed", pointer, detail)
                for _, pointer, detail in errors
            ]
        )


def _expected_v41_writable_paths(
    scenario_plan: list[Mapping[str, Any]],
) -> list[str]:
    paths: set[str] = set()
    for scenario in scenario_plan:
        if scenario.get("evidence_class") == "blind_holdout":
            paths.update(_BLIND_WRITABLE_PATHS)
            continue
        slot = scenario.get("scenario_slot")
        if slot not in _PUBLIC_WRITABLE_PATHS:
            _fail(
                "invalid_scenario_identity",
                "/scenario_plan",
                "public scenario has no frozen writable-path registry",
            )
        paths.update(_PUBLIC_WRITABLE_PATHS[str(slot)])
    return sorted(paths)


def _validate_public_scenarios(seed: Mapping[str, Any], artifact_bytes: Mapping[str, bytes]) -> None:
    seen_by_category: dict[str, set[str]] = {}
    for index, scenario in enumerate(seed["scenario_plan"]):
        if scenario["evidence_class"] == "blind_holdout":
            continue
        slot = scenario["scenario_slot"]
        for category in (
            "fixture",
            "source_ledger",
            "repository_snapshot",
            "model_visible_snapshot",
            "hidden_test_content",
            "provenance",
        ):
            field = f"{category}_sha256"
            value = scenario[field]
            if value in seen_by_category.setdefault(category, set()):
                _fail("invalid_scenario_identity", f"/scenario_plan/{index}/{field}", "cross-scenario digest alias")
            seen_by_category[category].add(value)
        for prefix, expected_kind in (
            ("fixture", "fixture"),
            ("source_ledger", "source_ledger"),
            ("repository_snapshot", "repository_snapshot"),
            ("model_visible_snapshot", "model_visible_snapshot"),
            ("hidden_test_hash", "hidden_test_hash"),
            ("provenance", "source_provenance"),
        ):
            artifact_id = scenario[f"{prefix}_artifact_id"]
            record = seed["frozen_input_artifact_catalog"].get(artifact_id)
            if record is None or record["kind"] != expected_kind:
                _fail("invalid_scenario_identity", f"/scenario_plan/{index}/{prefix}_artifact_id", "wrong artifact kind")
        for prefix in (
            "fixture",
            "source_ledger",
            "repository_snapshot",
            "model_visible_snapshot",
            "provenance",
        ):
            artifact_id = scenario[f"{prefix}_artifact_id"]
            record = seed["frozen_input_artifact_catalog"][artifact_id]
            if record["sha256"] != scenario[f"{prefix}_sha256"]:
                _fail(
                    "invalid_scenario_identity",
                    f"/scenario_plan/{index}/{prefix}_sha256",
                    f"{prefix} semantic digest differs from catalog bytes",
                )
        hidden = artifact_bytes[scenario["hidden_test_hash_artifact_id"]]
        if len(hidden) != 64 or hidden.decode("ascii", errors="ignore") != scenario["hidden_test_content_sha256"]:
            _fail("invalid_scenario_identity", f"/scenario_plan/{index}/hidden_test_content_sha256", "hidden hash wrapper mismatch")
        for prefix in ("fixture", "repository_snapshot"):
            payload = artifact_bytes[scenario[f"{prefix}_artifact_id"]]
            if hashlib.sha256(payload).hexdigest() != scenario[f"{prefix}_sha256"]:
                _fail(
                    "invalid_scenario_identity",
                    f"/scenario_plan/{index}/{prefix}_sha256",
                    f"{prefix} content digest mismatch",
                )
        source_ledger = _load_json_artifact(
            artifact_bytes[scenario["source_ledger_artifact_id"]],
            "sourceLedger",
            "invalid_scenario_identity",
        )
        snapshot = _load_json_artifact(
            artifact_bytes[scenario["model_visible_snapshot_artifact_id"]],
            "modelVisibleSnapshot41",
            "invalid_scenario_identity",
        )
        provenance = _load_json_artifact(
            artifact_bytes[scenario["provenance_artifact_id"]],
            "sourceProvenance41",
            "invalid_scenario_identity",
        )
        if source_ledger["scenario_slot"] != slot or snapshot["scenario_slot"] != slot or provenance["scenario_slot"] != slot:
            _fail("invalid_scenario_identity", f"/scenario_plan/{index}", "artifact scenario mismatch")
        source_hash = review_json_sha256(source_ledger)
        if source_hash != scenario["source_ledger_sha256"] or snapshot["source_ledger_sha256"] != source_hash:
            _fail("invalid_scenario_identity", f"/scenario_plan/{index}/source_ledger_sha256", "source ledger binding failed")
        expected_entries = [entry for entry in source_ledger["entries"] if entry["model_visible"]]
        events = snapshot["events"]
        for event_index, event in enumerate(events):
            _validate_timestamp(
                event["observed_at"],
                f"/scenario_plan/{index}/model_visible_snapshot/events/{event_index}/observed_at",
                "invalid_scenario_identity",
            )
        if [item["source_ref"] for item in expected_entries] != [event["source_ref"] for event in events]:
            _fail("invalid_scenario_identity", f"/scenario_plan/{index}/model_visible_snapshot_sha256", "snapshot order differs from ledger")
        for entry, event in zip(expected_entries, events, strict=True):
            if entry["event_sha256"] != review_json_sha256(event):
                _fail("invalid_scenario_identity", f"/scenario_plan/{index}/model_visible_snapshot_sha256", "event hash mismatch")
        summaries = [{"source_ref": event["source_ref"], "summary": event["summary"]} for event in events]
        repository_url, license_id = _PUBLIC_REGISTRY[slot]
        if provenance["repository_url"] != repository_url or provenance["license_id"] != license_id:
            _fail("invalid_scenario_identity", f"/scenario_plan/{index}/provenance_sha256", "registry provenance mismatch")
        if provenance["authored_summary_sha256"] != review_json_sha256(summaries):
            _fail("invalid_scenario_identity", f"/scenario_plan/{index}/provenance_sha256", "summary digest mismatch")
        if review_json_sha256(snapshot) != scenario["model_visible_snapshot_sha256"] or review_json_sha256(provenance) != scenario["provenance_sha256"]:
            _fail("invalid_scenario_identity", f"/scenario_plan/{index}", "scenario body hash mismatch")


def _load_json_artifact(payload: bytes, definition: str, code: str) -> Mapping[str, Any]:
    try:
        value = parse_review_json(payload)
    except ValueError:
        _fail(code, "/", "artifact is not valid closed JCS JSON")
    if canonicalize_review_json(value) != payload:
        _fail(code, "/", "artifact bytes are not RFC 8785 canonical JSON")
    errors = _schema_errors(value, definition, default_code=code)
    if errors:
        _raise_review_errors(errors)
    return value


def _validate_timestamp(value: str, pointer: str, code: str) -> None:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
            raise ValueError
    except (TypeError, ValueError):
        _fail(code, pointer, "timestamp must be an exact valid Gregorian UTC instant")


def _tree_hash_payloads(files: list[tuple[str, bytes]]) -> str:
    leaves: list[tuple[bytes, bytes]] = []
    normalized: set[str] = set()
    for relative, payload in files:
        if relative in normalized:
            _fail("invalid_review_seed", "/code_hashes", "duplicate normalized code path")
        normalized.add(relative)
        path_bytes = relative.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest().encode("ascii")
        leaves.append((path_bytes, path_bytes + b"\0" + digest + b"\n"))
    return hashlib.sha256(b"".join(leaf for _, leaf in sorted(leaves))).hexdigest()


def _fail(code: str, pointer: str, detail: str) -> None:
    _raise_review_errors([(code, pointer, detail)])


def _raise_review_errors(errors: list[tuple[str, str, str]]) -> None:
    normalized = sorted(set(errors), key=lambda item: (item[0], item[1], item[2]))
    if normalized:
        raise ValueError(
            "\n".join(
                f"4.1 {code} {pointer or '/'} {detail[:240]}"
                for code, pointer, detail in normalized
            )
        )

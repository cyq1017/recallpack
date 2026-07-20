from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from recallpack.evidence_common import _schema_errors
from recallpack.evidence_review_protocol import (
    EligibleExecutionManifest41,
    ManifestRegistry,
    _ELIGIBILITY_MINT_AUTHORITY,
    _fail,
    _load_json_artifact,
    _mint_eligible_execution_manifest_41,
    _raise_review_errors,
    _validate_timestamp,
    assemble_execution_manifest_projection_41,
    require_eligible_registration_41,
    validate_external_review_attestation,
)
from recallpack.review_json import (
    canonicalize_review_json,
    parse_review_json,
    review_json_sha256,
)
from recallpack.secure_files import (
    SecureFileError,
    open_canonical_root,
    stable_read_beneath,
)


_BUNDLE_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_PASS_REASON_CODES = [
    "no_copied_source_text",
    "no_hidden_test_content_model_visible",
    "no_gold_source_ids_model_visible",
    "no_required_labels_model_visible",
    "no_relation_labels_model_visible",
]
_REVEAL_RECORD_AUTHORITY = object()
_TRUSTED_LOADER_LOCK = threading.Lock()
_V4_REVIEW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "specs/001-recallpack-v4/reviews"
)
_V4_FILE_HASHES = {
    "phase2_instruction_file_sha256": "e9c802f6194943a24ffe67fb1f97c04e8452e16ea89747e68a018590bcbe7468",
    "matrix_file_sha256": "fbf7cd243bf1784debe4e26cf32038475c518a2aacb8cfc59fd95b137e3aeae1",
    "semantic_report_schema_file_sha256": "d8a2eee0f04a88d656f6530dc4ea30f04fbc4903274e7f9178b670c3a5463caa",
    "custody_report_schema_file_sha256": "3e4871a9eec48041a5b0fb10aac851f797e919fca8d2e3d0addaebf92cb55a28",
    "source_cards_file_sha256": "1ce7322b1434eba70aecea2547ab8fa1931b766601fdadde632091f14b712018",
    "source_package_inventory_file_sha256": "8834b3523b478269251c91473c1b916d4db65e6e4545804973d4c99fa85f9ea7",
}
_V4_REVIEW_FILES = {
    "matrix_file_sha256": "t053-semantic-adjudication-vectors-v4.json",
    "semantic_report_schema_file_sha256": "t053-semantic-adjudication-report.schema.v4.json",
    "custody_report_schema_file_sha256": "t053-phase2-custody-report.schema.v4.json",
    "source_cards_file_sha256": "t053-proposed-events-v3.json",
    "source_package_inventory_file_sha256": "t053-review-source-inventory-v3.json",
}
_EXTERNAL_BODY_KINDS = (
    "required_memory_label_ledger",
    "relation_label_ledger",
    "leakage_review",
)
_EXTERNAL_BODY_SUFFIXES = {
    "required_memory_label_ledger": "required-memory-label.json",
    "relation_label_ledger": "relation-label-ledger.json",
    "leakage_review": "leakage-review.json",
}


class _TrustedLeakageLoader41:
    def __new__(cls) -> _TrustedLeakageLoader41:
        raise TypeError("trusted leakage loader cannot be constructed directly")


@dataclass(frozen=True)
class _TrustedLeakagePayload41:
    review_seed_sha256: str
    seed_receipt_sha256: str
    review_attestation_sha256: str
    semantic_report: Mapping[str, Any]
    custody_report: Mapping[str, Any]
    external_bodies: Mapping[str, bytes]


_TRUSTED_LOADER_PAYLOADS: weakref.WeakKeyDictionary[
    _TrustedLeakageLoader41, _TrustedLeakagePayload41
] = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class ExecutionCellInputs:
    repository_snapshot_artifact_id: str
    model_visible_snapshot_artifact_id: str


@dataclass
class _AttemptState:
    scenario_slot: str
    output_sha256: str | None = None
    patch_sha256: str | None = None
    extraction_root: str | None = None
    extraction_root_destroyed: bool = False
    revealed: dict[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def output_fixed(self) -> bool:
        return self.output_sha256 is not None and self.patch_sha256 is not None


def open_external_custody_leakage_loader_41(
    external_custody_root: Path,
    *,
    expected_custody_report_jcs_sha256: str,
    expected_custody_report_bytes: int,
    seed: Mapping[str, Any],
    seed_receipt: Mapping[str, Any],
    attestation: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> _TrustedLeakageLoader41:
    """Validate externally held semantic evidence before minting a loader."""

    if (
        re.fullmatch(r"[0-9a-f]{64}", expected_custody_report_jcs_sha256)
        is None
        or expected_custody_report_bytes < 1
    ):
        _fail(
            "invalid_external_custody",
            "/phase_2_custody_report",
            "an independent exact custody-report hash and byte length are required",
        )
    validate_external_review_attestation(attestation, seed, seed_receipt)
    authority = _load_v4_review_authority()
    try:
        with open_canonical_root(Path(external_custody_root)) as root_fd:
            custody_bytes = stable_read_beneath(
                root_fd,
                "phase-2/phase-2-custody-report.json",
            )
            if (
                len(custody_bytes) != expected_custody_report_bytes
                or hashlib.sha256(custody_bytes).hexdigest()
                != expected_custody_report_jcs_sha256
            ):
                _fail(
                    "invalid_external_custody",
                    "/phase_2_custody_report",
                    "custody report does not match the independent anchor",
                )
            custody_report = _parse_canonical_external_json(
                custody_bytes,
                "/phase_2_custody_report",
            )
            _validate_closed_external_schema(
                custody_report,
                authority["custody_schema"],
                "/phase_2_custody_report",
            )

            semantic_bytes = stable_read_beneath(
                root_fd,
                "phase-2/semantic-adjudication-report.json",
            )
            semantic_report = _parse_canonical_external_json(
                semantic_bytes,
                "/semantic_adjudication_report",
            )
            _validate_closed_external_schema(
                semantic_report,
                authority["semantic_schema"],
                "/semantic_adjudication_report",
            )

            attestation_bytes = stable_read_beneath(
                root_fd,
                "phase-2/external-review-attestation.json",
            )
            external_attestation = _parse_canonical_external_json(
                attestation_bytes,
                "/external_review_attestation",
            )
            if external_attestation != attestation:
                _fail(
                    "invalid_external_custody",
                    "/external_review_attestation",
                    "external attestation bytes differ from the supplied protocol input",
                )

            inventory_bytes = stable_read_beneath(
                root_fd,
                "reviewer-source-package/source-inventory.json",
            )
            if (
                hashlib.sha256(inventory_bytes).hexdigest()
                != _V4_FILE_HASHES["source_package_inventory_file_sha256"]
            ):
                _fail(
                    "invalid_external_custody",
                    "/source_package_inventory_file_sha256",
                    "source inventory differs from the reviewed exact file",
                )
            inventory = _parse_external_json(
                inventory_bytes,
                "/source_package_inventory",
            )
            if inventory != authority["source_inventory"]:
                _fail(
                    "invalid_external_custody",
                    "/source_package_inventory",
                    "source inventory content differs from reviewed authority",
                )
            source_rows: list[dict[str, Any]] = []
            for source in inventory["sources"]:
                payload = stable_read_beneath(
                    root_fd,
                    f"reviewer-source-package/{source['reviewer_filename']}",
                )
                if (
                    len(payload) != source["bytes"]
                    or hashlib.sha256(payload).hexdigest() != source["sha256"]
                ):
                    _fail(
                        "invalid_external_custody",
                        f"/source_package_files/{source['source_id']}",
                        "reviewer source bytes differ from the frozen inventory",
                    )
                source_rows.append(
                    {
                        "source_id": source["source_id"],
                        "sha256": source["sha256"],
                        "bytes": source["bytes"],
                    }
                )

            scenario_slots = [item["scenario_slot"] for item in seed["scenario_plan"]]
            if scenario_slots != ["projectodyssey", "deepagents"]:
                _fail(
                    "invalid_external_custody",
                    "/scenario_plan",
                    "T053 V4 custody is frozen to the two reviewed R2 scenarios",
                )
            external_bodies: dict[str, bytes] = {}
            external_rows: list[dict[str, Any]] = []
            for scenario_slot in scenario_slots:
                for kind in _EXTERNAL_BODY_KINDS:
                    relative_path = (
                        f"phase-2/{scenario_slot}-"
                        f"{_EXTERNAL_BODY_SUFFIXES[kind]}"
                    )
                    payload = stable_read_beneath(root_fd, relative_path)
                    artifact_id = f"external__{scenario_slot}__{kind}"
                    external_bodies[artifact_id] = payload
                    external_rows.append(
                        {
                            "scenario_slot": scenario_slot,
                            "kind": kind,
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "bytes": len(payload),
                        }
                    )
    except SecureFileError as exc:
        _fail(
            "invalid_external_custody",
            "/external_custody_root",
            str(exc),
        )

    _validate_phase2_custody_report(
        custody_report,
        semantic_bytes=semantic_bytes,
        semantic_report=semantic_report,
        source_rows=source_rows,
        external_rows=external_rows,
        seed=seed,
        seed_receipt=seed_receipt,
        attestation=attestation,
    )
    _validate_attested_external_bodies(attestation, external_rows)
    _validate_semantic_report_41(
        semantic_report,
        authority=authority,
        seed=seed,
        artifact_bytes=dict(artifact_bytes or {}),
        external_bodies=external_bodies,
    )
    _validate_external_body_set_41(
        seed,
        attestation,
        artifact_bytes=dict(artifact_bytes or {}),
        external_bodies=external_bodies,
    )
    payload = _TrustedLeakagePayload41(
        review_seed_sha256=review_json_sha256(seed),
        seed_receipt_sha256=review_json_sha256(seed_receipt),
        review_attestation_sha256=review_json_sha256(attestation),
        semantic_report=semantic_report,
        custody_report=custody_report,
        external_bodies=external_bodies,
    )
    loader = object.__new__(_TrustedLeakageLoader41)
    with _TRUSTED_LOADER_LOCK:
        _TRUSTED_LOADER_PAYLOADS[loader] = payload
    return loader


def assemble_eligible_execution_manifest_41(
    seed: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    seed_receipt: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    repository_root: Path,
    leakage_loader: object,
) -> EligibleExecutionManifest41:
    diagnostic = assemble_execution_manifest_projection_41(
        seed,
        attestation,
        seed_receipt=seed_receipt,
        artifact_bytes=artifact_bytes,
        repository_root=repository_root,
    )
    if type(leakage_loader) is not _TrustedLeakageLoader41:
        _fail(
            "invalid_manifest_binding",
            "/leakage_loader",
            "production assembly requires the exact trusted leakage-loader type",
        )
    with _TRUSTED_LOADER_LOCK:
        trusted = _TRUSTED_LOADER_PAYLOADS.get(leakage_loader)
    if trusted is None:
        _fail(
            "invalid_manifest_binding",
            "/leakage_loader",
            "trusted leakage loader has no process-local custody binding",
        )
    expected = (
        review_json_sha256(seed),
        review_json_sha256(seed_receipt),
        review_json_sha256(attestation),
    )
    actual = (
        trusted.review_seed_sha256,
        trusted.seed_receipt_sha256,
        trusted.review_attestation_sha256,
    )
    if actual != expected:
        _fail(
            "invalid_manifest_binding",
            "/leakage_loader",
            "trusted loader belongs to different protocol inputs",
        )
    _validate_external_body_set_41(
        seed,
        attestation,
        artifact_bytes=artifact_bytes,
        external_bodies=trusted.external_bodies,
        manifest=diagnostic.manifest,
    )
    return _mint_eligible_execution_manifest_41(
        diagnostic,
        seed_receipt,
        _ELIGIBILITY_MINT_AUTHORITY,
    )


def _load_v4_review_authority() -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    try:
        with open_canonical_root(_V4_REVIEW_ROOT) as root_fd:
            for field, filename in _V4_REVIEW_FILES.items():
                payload = stable_read_beneath(root_fd, filename)
                if (
                    hashlib.sha256(payload).hexdigest()
                    != _V4_FILE_HASHES[field]
                ):
                    _fail(
                        "invalid_external_custody",
                        f"/{field}",
                        "local reviewed authority file changed",
                    )
                loaded[field] = _parse_external_json(payload, f"/{field}")
            instruction = stable_read_beneath(
                root_fd,
                "t053-external-review-phase2-prompt-v4.md",
            )
    except SecureFileError as exc:
        _fail(
            "invalid_external_custody",
            "/reviewed_authority",
            str(exc),
        )
    if (
        hashlib.sha256(instruction).hexdigest()
        != _V4_FILE_HASHES["phase2_instruction_file_sha256"]
    ):
        _fail(
            "invalid_external_custody",
            "/phase2_instruction_file_sha256",
            "local phase-2 instruction changed",
        )
    vectors = loaded["matrix_file_sha256"]
    expected_cases = {
        **{f"A{index}": "reject" for index in range(1, 8)},
        **{f"P{index}": "pass" for index in range(1, 7)},
    }
    actual_cases = {
        item.get("case_id"): item.get("expected_decision")
        for item in vectors.get("vectors", [])
        if isinstance(item, Mapping)
    }
    if actual_cases != expected_cases or len(vectors.get("vectors", [])) != 13:
        _fail(
            "invalid_external_custody",
            "/matrix_file_sha256",
            "semantic vector authority is incomplete or inconsistent",
        )
    source_cards = loaded["source_cards_file_sha256"]
    if [
        item.get("scenario_slot")
        for item in source_cards.get("scenarios", [])
    ] != ["projectodyssey", "deepagents"]:
        _fail(
            "invalid_external_custody",
            "/source_cards_file_sha256",
            "reviewed source-card scenario order is invalid",
        )
    for scenario in source_cards["scenarios"]:
        for item in scenario.get("events", []):
            if item.get("event_sha256") != review_json_sha256(item.get("event")):
                _fail(
                    "invalid_external_custody",
                    "/source_cards_file_sha256",
                    "reviewed source-card event hash is invalid",
                )
    return {
        "vectors": vectors,
        "semantic_schema": loaded["semantic_report_schema_file_sha256"],
        "custody_schema": loaded["custody_report_schema_file_sha256"],
        "source_cards": loaded["source_cards_file_sha256"],
        "source_inventory": loaded["source_package_inventory_file_sha256"],
        "case_decisions": expected_cases,
    }


def _parse_external_json(payload: bytes, pointer: str) -> Mapping[str, Any]:
    try:
        value = parse_review_json(payload)
    except ValueError:
        _fail(
            "invalid_external_custody",
            pointer,
            "external JSON is malformed or contains duplicate keys",
        )
    if not isinstance(value, Mapping):
        _fail(
            "invalid_external_custody",
            pointer,
            "external JSON root must be an object",
        )
    return value


def _parse_canonical_external_json(
    payload: bytes,
    pointer: str,
) -> Mapping[str, Any]:
    value = _parse_external_json(payload, pointer)
    if canonicalize_review_json(value) != payload:
        _fail(
            "invalid_external_custody",
            pointer,
            "generated external JSON must be exact RFC 8785 bytes",
        )
    return value


def _validate_closed_external_schema(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
    pointer: str,
) -> None:
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        suffix = "/".join(str(part) for part in first.absolute_path)
        _fail(
            "invalid_external_custody",
            f"{pointer}/{suffix}".rstrip("/"),
            first.message,
        )


def _validate_phase2_custody_report(
    report: Mapping[str, Any],
    *,
    semantic_bytes: bytes,
    semantic_report: Mapping[str, Any],
    source_rows: list[dict[str, Any]],
    external_rows: list[dict[str, Any]],
    seed: Mapping[str, Any],
    seed_receipt: Mapping[str, Any],
    attestation: Mapping[str, Any],
) -> None:
    expected_fields = {
        **_V4_FILE_HASHES,
        "review_seed_sha256": review_json_sha256(seed),
        "seed_receipt_sha256": review_json_sha256(seed_receipt),
        "semantic_report_jcs_sha256": hashlib.sha256(semantic_bytes).hexdigest(),
        "semantic_report_bytes": len(semantic_bytes),
    }
    for field, expected in expected_fields.items():
        if report.get(field) != expected:
            _fail(
                "invalid_external_custody",
                f"/{field}",
                "custody report binding mismatch",
            )
    if report.get("source_package_files") != source_rows:
        _fail(
            "invalid_external_custody",
            "/source_package_files",
            "source-package order or binding mismatch",
        )
    if report.get("external_artifacts") != external_rows:
        _fail(
            "invalid_external_custody",
            "/external_artifacts",
            "external body order or binding mismatch",
        )
    _validate_timestamp(
        report["authored_at"],
        "/authored_at",
        "invalid_external_custody",
    )
    _validate_timestamp(
        report["reviewed_at"],
        "/reviewed_at",
        "invalid_external_custody",
    )
    _validate_timestamp(
        semantic_report["reviewed_at"],
        "/semantic_adjudication_report/reviewed_at",
        "invalid_external_custody",
    )
    if (
        seed_receipt["received_at"] > semantic_report["reviewed_at"]
        or seed_receipt["received_at"] > report["authored_at"]
        or semantic_report["reviewed_at"] > report["authored_at"]
        or report["authored_at"] > report["reviewed_at"]
        or semantic_report["reviewed_at"] > report["reviewed_at"]
        or report["reviewed_at"] > attestation["reviewed_at"]
        or report.get("final_eligibility_verdict") != "pass"
    ):
        _fail(
            "invalid_external_custody",
            "/final_eligibility_verdict",
            "custody chronology and final pass verdict are required",
        )


def _validate_attested_external_bodies(
    attestation: Mapping[str, Any],
    external_rows: list[dict[str, Any]],
) -> None:
    expected = [
        (
            item["scenario_slot"],
            item["kind"],
            item["sha256"],
            item["bytes"],
        )
        for item in external_rows
    ]
    actual = [
        (
            item.get("scenario_slot"),
            item.get("kind"),
            item.get("content_sha256"),
            item.get("byte_length"),
        )
        for item in attestation.get("external_artifacts", [])
    ]
    if actual != expected:
        _fail(
            "invalid_external_custody",
            "/external_artifacts",
            "attestation does not bind the exact ordered external bodies",
        )


def _validate_semantic_report_41(
    report: Mapping[str, Any],
    *,
    authority: Mapping[str, Any],
    seed: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    external_bodies: Mapping[str, bytes],
) -> None:
    for field in (
        "matrix_file_sha256",
        "source_cards_file_sha256",
        "source_package_inventory_file_sha256",
    ):
        if report.get(field) != _V4_FILE_HASHES[field]:
            _fail(
                "invalid_external_custody",
                f"/{field}",
                "semantic report exact-file binding mismatch",
            )
    expected_source_rows = [
        {
            "source_id": source["source_id"],
            "sha256": source["sha256"],
            "bytes": source["bytes"],
            "hash_and_length_verified": True,
            "source_support_checked": True,
            "copying_checked": True,
        }
        for source in authority["source_inventory"]["sources"]
    ]
    if report.get("source_package_files") != expected_source_rows:
        _fail(
            "invalid_external_custody",
            "/source_package_files",
            "semantic report source-package verification is incomplete",
        )
    cards_by_slot = {
        item["scenario_slot"]: item
        for item in authority["source_cards"]["scenarios"]
    }
    reports = report.get("scenario_reports", [])
    expected_slots = [item["scenario_slot"] for item in seed["scenario_plan"]]
    if [item.get("scenario_slot") for item in reports] != expected_slots:
        _fail(
            "invalid_external_custody",
            "/scenario_reports",
            "semantic scenario order differs from the seed",
        )
    prompt_id = seed["comparison_contract"]["prompt_template_artifact_id"]
    prompt_bytes = artifact_bytes.get(prompt_id)
    if prompt_bytes is None:
        _fail(
            "invalid_external_custody",
            "/prompt_template_sha256",
            "seed-frozen prompt bytes are unavailable",
        )
    prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()
    case_decisions = authority["case_decisions"]
    for scenario, scenario_report in zip(
        seed["scenario_plan"],
        reports,
        strict=True,
    ):
        slot = scenario["scenario_slot"]
        cards = cards_by_slot.get(slot)
        if cards is None:
            _fail(
                "invalid_external_custody",
                f"/scenario_reports/{slot}",
                "scenario has no reviewed event cards",
            )
        expected_event_hashes = [item["event_sha256"] for item in cards["events"]]
        expected_events = [item["event"] for item in cards["events"]]
        snapshot_id = scenario["model_visible_snapshot_artifact_id"]
        snapshot_bytes = artifact_bytes.get(snapshot_id)
        if snapshot_bytes is None:
            _fail(
                "invalid_external_custody",
                f"/scenario_reports/{slot}/model_visible_snapshot_sha256",
                "seed-frozen snapshot bytes are unavailable",
            )
        snapshot = _load_json_artifact(
            snapshot_bytes,
            "modelVisibleSnapshot41",
            "invalid_external_custody",
        )
        if snapshot["events"] != expected_events:
            _fail(
                "invalid_external_custody",
                f"/scenario_reports/{slot}/events",
                "reviewed events differ from the seed-frozen snapshot",
            )
        leakage_id = f"external__{slot}__leakage_review"
        expected_report_fields = {
            "model_visible_snapshot_sha256": review_json_sha256(snapshot),
            "prompt_template_sha256": prompt_hash,
            "ordered_event_hashes": expected_event_hashes,
            "leakage_review_sha256": hashlib.sha256(
                external_bodies[leakage_id]
            ).hexdigest(),
            "final_verdict": "pass",
        }
        for field, expected in expected_report_fields.items():
            if scenario_report.get(field) != expected:
                _fail(
                    "invalid_external_custody",
                    f"/scenario_reports/{slot}/{field}",
                    "semantic scenario binding mismatch",
                )
        event_reports = scenario_report.get("events", [])
        if len(event_reports) != len(cards["events"]):
            _fail(
                "invalid_external_custody",
                f"/scenario_reports/{slot}/events",
                "semantic event count mismatch",
            )
        for card, event_report in zip(cards["events"], event_reports, strict=True):
            source_id = card["source_id"]
            expected_source_decision = "pass" if source_id is not None else "not_applicable"
            case_ids = event_report.get("applied_case_ids", [])
            if (
                event_report.get("source_ref") != card["event"]["source_ref"]
                or event_report.get("event_sha256") != card["event_sha256"]
                or event_report.get("decision") != "pass"
                or not case_ids
                or any(case_decisions.get(case_id) != "pass" for case_id in case_ids)
                or event_report.get("source_support_decision") != expected_source_decision
                or event_report.get("copying_decision") != expected_source_decision
                or event_report.get("metadata_derivation_decision") != "pass"
            ):
                _fail(
                    "invalid_external_custody",
                    f"/scenario_reports/{slot}/events/{card['event']['source_ref']}",
                    "semantic event adjudication is not an internally consistent pass",
                )
        whole_input = scenario_report.get("whole_input", {})
        whole_cases = whole_input.get("applied_case_ids", [])
        if (
            whole_input.get("decision") != "pass"
            or not whole_cases
            or any(case_decisions.get(case_id) != "pass" for case_id in whole_cases)
        ):
            _fail(
                "invalid_external_custody",
                f"/scenario_reports/{slot}/whole_input",
                "whole-input adjudication is not an internally consistent pass",
            )
    if report.get("final_verdict") != "pass":
        _fail(
            "invalid_external_custody",
            "/final_verdict",
            "semantic report did not pass",
        )


def _validate_external_body_set_41(
    seed: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    external_bodies: Mapping[str, bytes],
    manifest: Mapping[str, Any] | None = None,
) -> None:
    attested = {
        item["artifact_id"]: item for item in attestation["external_artifacts"]
    }
    expected_ids = [
        f"external__{scenario['scenario_slot']}__{kind}"
        for scenario in seed["scenario_plan"]
        for kind in _EXTERNAL_BODY_KINDS
    ]
    if list(external_bodies) != expected_ids:
        _fail(
            "invalid_external_custody",
            "/external_artifacts",
            "trusted loader body set or order mismatch",
        )
    prompt_id = seed["comparison_contract"]["prompt_template_artifact_id"]
    prompt_bytes = artifact_bytes.get(prompt_id)
    if prompt_bytes is None:
        _fail(
            "invalid_external_custody",
            "/prompt_template_sha256",
            "seed-frozen prompt bytes are unavailable",
        )
    for scenario in seed["scenario_plan"]:
        slot = scenario["scenario_slot"]
        ledger_bytes = artifact_bytes.get(scenario["source_ledger_artifact_id"])
        if ledger_bytes is None:
            _fail(
                "invalid_external_custody",
                f"/external_artifacts/{slot}/source_ledger_sha256",
                "seed-frozen source ledger bytes are unavailable",
            )
        ledger = _load_json_artifact(
            ledger_bytes,
            "sourceLedger",
            "invalid_external_custody",
        )
        values: dict[str, Mapping[str, Any]] = {}
        for kind in _EXTERNAL_BODY_KINDS:
            artifact_id = f"external__{slot}__{kind}"
            payload = external_bodies[artifact_id]
            entry = attested.get(artifact_id)
            if (
                entry is None
                or len(payload) != entry["byte_length"]
                or hashlib.sha256(payload).hexdigest() != entry["content_sha256"]
            ):
                _fail(
                    "invalid_external_custody",
                    f"/external_artifacts/{artifact_id}",
                    "external body differs from attestation",
                )
            definition = {
                "required_memory_label_ledger": "requiredMemoryLabelLedger41",
                "relation_label_ledger": "relationLabelLedger",
                "leakage_review": "leakageReview41",
            }[kind]
            values[kind] = _load_json_artifact(
                payload,
                definition,
                "invalid_external_custody",
            )
            if values[kind].get("scenario_slot") != slot:
                _fail(
                    "invalid_external_custody",
                    f"/external_artifacts/{artifact_id}/scenario_slot",
                    "external body scenario mismatch",
                )
        _validate_label_ledger(
            values["required_memory_label_ledger"],
            ledger,
            "required_memory_label_ledger",
        )
        _validate_label_ledger(
            values["relation_label_ledger"],
            ledger,
            "relation_label_ledger",
        )
        leakage = values["leakage_review"]
        if leakage["verdict"] != "pass" or leakage["reason_codes"] != _PASS_REASON_CODES:
            _fail(
                "invalid_external_custody",
                f"/external_artifacts/{slot}/leakage_review/reason_codes",
                "only the exact leakage pass set is eligible",
            )
        expected = {
            "fixture_sha256": scenario["fixture_sha256"],
            "source_ledger_sha256": scenario["source_ledger_sha256"],
            "model_visible_snapshot_sha256": scenario["model_visible_snapshot_sha256"],
            "prompt_template_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "relation_label_sha256": hashlib.sha256(
                external_bodies[f"external__{slot}__relation_label_ledger"]
            ).hexdigest(),
            "hidden_test_content_sha256": scenario["hidden_test_content_sha256"],
            "evaluator_image_digest": seed["evaluator_image_digest"],
        }
        for field, expected_value in expected.items():
            if leakage.get(field) != expected_value:
                _fail(
                    "invalid_external_custody",
                    f"/external_artifacts/{slot}/leakage_review/{field}",
                    "leakage body binding mismatch",
                )
        if manifest is not None:
            _validate_leakage_review(leakage, manifest, slot)


class RevealAuthority:
    """Manifest/slot/attempt-scoped reveal automaton."""

    def __init__(
        self,
        manifest: Mapping[str, Any],
        registered_manifest_sha256: str,
        attestation: Mapping[str, Any],
        *,
        artifact_bytes: Mapping[str, bytes] | None = None,
        registry: ManifestRegistry,
        registration_receipt: Mapping[str, Any],
    ) -> None:
        try:
            manifest_bytes = canonicalize_review_json(manifest)
            attestation_bytes = canonicalize_review_json(attestation)
            manifest_snapshot = parse_review_json(manifest_bytes)
            attestation_snapshot = parse_review_json(attestation_bytes)
        except ValueError:
            _fail(
                "invalid_manifest_binding",
                "/execution_manifest_sha256",
                "manifest and attestation must be canonicalizable protocol inputs",
            )
        if review_json_sha256(manifest_snapshot) != registered_manifest_sha256:
            _fail("invalid_reveal_phase", "/execution_manifest_sha256", "manifest hash is not registered input")
        self._manifest_bytes = manifest_bytes
        self._manifest = manifest_snapshot
        self._manifest_sha256 = registered_manifest_sha256
        self._attestation_bytes = attestation_bytes
        self._attestation = attestation_snapshot
        self._attestation_sha256 = hashlib.sha256(attestation_bytes).hexdigest()
        self._artifact_bytes = dict(artifact_bytes or {})
        try:
            seed = parse_review_json(self._artifact_bytes["evaluation_review_seed"])
        except (KeyError, ValueError):
            _fail(
                "invalid_manifest_binding",
                "/input_artifact_catalog/evaluation_review_seed",
                "registered seed bytes are unavailable",
            )
        registration = require_eligible_registration_41(
            registry,
            self._manifest,
        )
        if registration.execution_manifest_sha256 != registered_manifest_sha256:
            _fail(
                "invalid_manifest_binding",
                "/execution_manifest_sha256",
                "manifest is not registered",
            )
        validate_manifest_registration_receipt(
            registration_receipt,
            seed=seed,
            attestation=self._attestation,
            manifest=self._manifest,
            registry=registry,
        )
        self._slot_to_scenario = {
            item["slot_id"]: item["scenario_slot"]
            for item in self._manifest["execution_order"]
        }
        self._scenario_slots: dict[str, set[str]] = {}
        for slot_id, scenario in self._slot_to_scenario.items():
            self._scenario_slots.setdefault(scenario, set()).add(slot_id)
        self._attempts: dict[tuple[str, str, int], _AttemptState] = {}
        self._closed_scenarios: set[str] = set()
        self._extraction_root_owners: dict[str, tuple[str, str, int]] = {}
        self._retired_extraction_roots: set[str] = set()

    @property
    def manifest(self) -> Mapping[str, Any]:
        return parse_review_json(self._manifest_bytes)

    @property
    def manifest_sha256(self) -> str:
        return self._manifest_sha256

    @property
    def attestation(self) -> Mapping[str, Any]:
        return parse_review_json(self._attestation_bytes)

    @property
    def attestation_sha256(self) -> str:
        return self._attestation_sha256

    def begin_attempt(self, slot_id: str, attempt_no: int) -> None:
        scenario = self._slot_to_scenario.get(slot_id)
        if scenario is None or attempt_no not in (1, 2, 3):
            _fail("invalid_reveal_phase", "/attempt", "attempt is outside the registered grid")
        if scenario in self._closed_scenarios:
            _fail("invalid_reveal_phase", "/attempt", "closed scenario cannot begin another attempt")
        key = (self._manifest_sha256, slot_id, attempt_no)
        self._attempts.setdefault(key, _AttemptState(scenario_slot=scenario))

    def fix_model_output(
        self,
        slot_id: str,
        attempt_no: int,
        *,
        output_sha256: str,
        patch_sha256: str,
    ) -> None:
        state = self._state(slot_id, attempt_no)
        if re.fullmatch(r"[a-f0-9]{64}", output_sha256) is None or re.fullmatch(
            r"[a-f0-9]{64}", patch_sha256
        ) is None:
            _fail("invalid_reveal_phase", "/model_output", "output hashes must be lowercase SHA-256")
        scenario = _scenario(self._manifest, state.scenario_slot)
        required_reveals = {"leakage_review"}
        if scenario["evidence_class"] == "blind_holdout":
            required_reveals.update(
                {"fixture", "source_ledger", "model_visible_snapshot"}
            )
        if not required_reveals.issubset(state.revealed):
            _fail(
                "invalid_reveal_phase",
                "/model_output",
                "attempt has not completed its pre-output reveal phases",
            )
        if state.output_fixed and (state.output_sha256, state.patch_sha256) != (
            output_sha256,
            patch_sha256,
        ):
            _fail("invalid_reveal_phase", "/model_output", "immutable output cannot change")
        state.output_sha256 = output_sha256
        state.patch_sha256 = patch_sha256

    def close_scenario_outputs(self, scenario_slot: str) -> None:
        required = self._scenario_slots.get(scenario_slot, set())
        states = [
            state
            for state in self._attempts.values()
            if state.scenario_slot == scenario_slot
        ]
        fixed = {
            slot_id
            for (_, slot_id, _), state in self._attempts.items()
            if state.scenario_slot == scenario_slot and state.output_fixed
        }
        if fixed != required or any(not state.output_fixed for state in states):
            _fail(
                "invalid_reveal_phase",
                f"/scenarios/{scenario_slot}",
                "all predeclared claim-bearing cells must be immutable",
            )
        self._closed_scenarios.add(scenario_slot)

    def bind_extraction_root(self, slot_id: str, attempt_no: int, root: str) -> None:
        state = self._state(slot_id, attempt_no)
        key = (self._manifest_sha256, slot_id, attempt_no)
        if root in self._retired_extraction_roots or state.extraction_root_destroyed:
            _fail("invalid_reveal_phase", "/extraction_root", "destroyed root cannot be reused")
        owner = self._extraction_root_owners.get(root)
        if owner is not None and owner != key:
            _fail("invalid_reveal_phase", "/extraction_root", "attempt root belongs to another attempt")
        if state.extraction_root is not None and state.extraction_root != root:
            _fail("invalid_reveal_phase", "/extraction_root", "attempt root cannot change")
        state.extraction_root = root
        self._extraction_root_owners[root] = key

    def destroy_extraction_root(self, slot_id: str, attempt_no: int, root: str) -> None:
        state = self._state(slot_id, attempt_no)
        if state.extraction_root != root:
            _fail("invalid_reveal_phase", "/extraction_root", "root does not belong to attempt")
        state.extraction_root_destroyed = True
        self._retired_extraction_roots.add(root)

    def authorize_provider_action(
        self,
        slot_id: str,
        attempt_no: int,
        *,
        extraction_root: str | None = None,
    ) -> None:
        state = self._state(slot_id, attempt_no)
        scenario = _scenario(self._manifest, state.scenario_slot)
        required_reveals = {"leakage_review"}
        if scenario["evidence_class"] == "blind_holdout":
            required_reveals.update(
                {"fixture", "source_ledger", "model_visible_snapshot"}
            )
        if (
            not required_reveals.issubset(state.revealed)
            or state.output_fixed
            or state.scenario_slot in self._closed_scenarios
        ):
            _fail(
                "invalid_reveal_phase",
                "/provider_action",
                "provider action is outside the pre-output model-visible phase",
            )
        if any(
            state.extraction_root is not None and not state.extraction_root_destroyed
            for state in self._attempts.values()
        ):
            _fail(
                "invalid_reveal_phase",
                "/extraction_root",
                "hidden-test extraction root must be destroyed before provider action",
            )
        if extraction_root is not None and (
            extraction_root in self._extraction_root_owners
            or extraction_root in self._retired_extraction_roots
        ):
            _fail("invalid_reveal_phase", "/extraction_root", "revealed extraction root cannot reach provider")

    def assert_reveal_allowed(
        self,
        artifact_id: str,
        slot_id: str,
        attempt_no: int,
    ) -> Mapping[str, Any]:
        state = self._state(slot_id, attempt_no)
        entry = next(
            (
                item
                for item in self._attestation["external_artifacts"]
                if item["artifact_id"] == artifact_id
            ),
            None,
        )
        if entry is None or entry["scenario_slot"] != state.scenario_slot:
            _fail("invalid_reveal_phase", "/artifact_id", "artifact is outside this attempt")
        phase = entry["reveal_phase"]
        if phase == "pre_run_eligibility_check":
            if state.revealed or state.output_fixed:
                _fail("invalid_reveal_phase", "/reveal_phase", "pre-run eligibility phase is closed")
        elif phase == "before_scenario_execution":
            if "leakage_review" not in state.revealed or state.output_fixed:
                _fail("invalid_reveal_phase", "/reveal_phase", "scenario input phase is not active")
        elif phase == "after_model_output_fixed":
            if not state.output_fixed:
                _fail("invalid_reveal_phase", "/reveal_phase", "model output and patch are not immutable")
        elif phase == "post_outputs_fixed":
            if state.scenario_slot not in self._closed_scenarios:
                _fail("invalid_reveal_phase", "/reveal_phase", "scenario output barrier is open")
        else:
            _fail("invalid_reveal_phase", "/reveal_phase", "unknown reveal phase")
        return parse_review_json(canonicalize_review_json(entry))

    def _record_revealed(
        self,
        slot_id: str,
        attempt_no: int,
        kind: str,
        value: Mapping[str, Any],
        authority: object,
    ) -> None:
        if authority is not _REVEAL_RECORD_AUTHORITY:
            _fail("invalid_reveal_phase", "/reveal_phase", "reveal record requires loader authority")
        self._state(slot_id, attempt_no).revealed[kind] = value

    def source_ledger(
        self,
        slot_id: str,
        attempt_no: int,
    ) -> Mapping[str, Any] | None:
        state = self._state(slot_id, attempt_no)
        revealed = state.revealed.get("source_ledger")
        if revealed is not None:
            return revealed
        scenario = _scenario(self._manifest, state.scenario_slot)
        artifact_id = scenario["source_ledger_artifact_id"]
        payload = self._artifact_bytes.get(artifact_id)
        if payload is None:
            return None
        return _load_json_artifact(payload, "sourceLedger", "external_artifact_content_mismatch")

    def _state(self, slot_id: str, attempt_no: int) -> _AttemptState:
        key = (self._manifest_sha256, slot_id, attempt_no)
        state = self._attempts.get(key)
        if state is None:
            _fail("invalid_reveal_phase", "/attempt", "attempt has not begun")
        return state


def validate_revealed_external_artifact(
    artifact_id: str,
    payload: bytes,
    *,
    manifest: Mapping[str, Any],
    attestation: Mapping[str, Any],
    authority: RevealAuthority,
    slot_id: str,
    attempt_no: int,
) -> Mapping[str, Any]:
    if (
        review_json_sha256(manifest) != authority.manifest_sha256
        or review_json_sha256(attestation) != authority.attestation_sha256
    ):
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "reveal inputs differ from the authority-owned protocol snapshots",
        )
    entry = authority.assert_reveal_allowed(artifact_id, slot_id, attempt_no)
    if len(payload) != entry["byte_length"] or hashlib.sha256(payload).hexdigest() != entry["content_sha256"]:
        _fail(
            "external_artifact_content_mismatch",
            f"/external_artifacts/{artifact_id}",
            "revealed bytes do not match the attested length and digest",
        )
    kind = entry["kind"]
    if kind in {"fixture", "hidden_test_bundle"}:
        expected_purpose = "fixture" if kind == "fixture" else "hidden_tests"
        value = _validate_bundle(payload, expected_purpose=expected_purpose)
    else:
        definition = {
            "required_memory_label_ledger": "requiredMemoryLabelLedger41",
            "relation_label_ledger": "relationLabelLedger",
            "leakage_review": "leakageReview41",
            "source_ledger": "sourceLedger",
            "model_visible_snapshot": "modelVisibleSnapshot41",
        }[kind]
        value = _load_json_artifact(payload, definition, "external_artifact_content_mismatch")
    scenario_slot = entry["scenario_slot"]
    if value.get("scenario_slot") != scenario_slot:
        _fail("external_artifact_content_mismatch", "/scenario_slot", "revealed scenario mismatch")
    if kind == "source_ledger":
        _validate_source_ledger(value)
    elif kind == "model_visible_snapshot":
        _validate_model_visible_snapshot(value, authority.source_ledger(slot_id, attempt_no))
    elif kind in {"required_memory_label_ledger", "relation_label_ledger"}:
        _validate_label_ledger(value, authority.source_ledger(slot_id, attempt_no), kind)
    elif kind == "leakage_review":
        _validate_leakage_review(value, authority._manifest, scenario_slot)
    authority._record_revealed(
        slot_id,
        attempt_no,
        kind,
        value,
        _REVEAL_RECORD_AUTHORITY,
    )
    return value


def materialize_deterministic_bundle(
    artifact_id: str,
    payload: bytes,
    *,
    authority: RevealAuthority,
    slot_id: str,
    attempt_no: int,
    destination_root: Path,
    evaluator_owned_root: Path,
) -> list[Path]:
    entry = authority.assert_reveal_allowed(artifact_id, slot_id, attempt_no)
    if entry["kind"] not in {"fixture", "hidden_test_bundle"}:
        _fail(
            "external_artifact_content_mismatch",
            "/purpose",
            "only revealed file bundles can be materialized",
        )
    destination = _resolve_evaluator_owned_root(destination_root, evaluator_owned_root)
    if entry["kind"] == "hidden_test_bundle":
        authority.bind_extraction_root(slot_id, attempt_no, str(destination))
    value = validate_revealed_external_artifact(
        artifact_id,
        payload,
        manifest=authority.manifest,
        attestation=authority.attestation,
        authority=authority,
        slot_id=slot_id,
        attempt_no=attempt_no,
    )
    expected_purpose = "fixture" if entry["kind"] == "fixture" else "hidden_tests"
    return _materialize_validated_bundle(
        value,
        expected_purpose=expected_purpose,
        destination_root=destination_root,
        evaluator_owned_root=evaluator_owned_root,
    )


def _materialize_validated_bundle(
    bundle: Mapping[str, Any] | bytes,
    *,
    expected_purpose: str,
    destination_root: Path,
    evaluator_owned_root: Path,
) -> list[Path]:
    value = _validate_bundle(bundle, expected_purpose=expected_purpose)
    destination = _resolve_evaluator_owned_root(destination_root, evaluator_owned_root)
    if any(destination.iterdir()):
        _fail("invalid_bundle_path", "/destination_root", "disposable root must be empty")
    decoded: list[tuple[str, bytes]] = []
    aggregate = 0
    for index, item in enumerate(value["files"]):
        try:
            payload = base64.b64decode(item["content_base64"], validate=True)
        except (binascii.Error, ValueError):
            _fail("external_artifact_content_mismatch", f"/files/{index}/content_base64", "invalid base64")
        if base64.b64encode(payload).decode("ascii") != item["content_base64"]:
            _fail("external_artifact_content_mismatch", f"/files/{index}/content_base64", "base64 is not canonical")
        if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            _fail("external_artifact_content_mismatch", f"/files/{index}", "file hash or length mismatch")
        aggregate += len(payload)
        if aggregate > 16_777_216:
            _fail("external_artifact_content_mismatch", "/files", "aggregate bundle size exceeded")
        decoded.append((item["path"], payload))
    return _write_bundle_from_root_fd(destination, decoded)


def _resolve_evaluator_owned_root(
    destination_root: Path,
    evaluator_owned_root: Path,
) -> Path:
    if destination_root.is_symlink() or evaluator_owned_root.is_symlink():
        _fail("invalid_bundle_path", "/destination_root", "materialization root cannot be a symlink")
    try:
        destination = destination_root.resolve(strict=True)
        owned = evaluator_owned_root.resolve(strict=True)
    except OSError as exc:
        _fail(
            "invalid_bundle_path",
            "/destination_root",
            f"materialization root is unavailable: {exc.__class__.__name__}",
        )
    if destination != owned:
        _fail("invalid_bundle_path", "/destination_root", "materialization root is not evaluator-owned")
    if not destination.is_dir():
        _fail("invalid_bundle_path", "/destination_root", "materialization root must be a directory")
    return destination


def resolve_execution_cell_inputs(
    manifest: Mapping[str, Any],
    scenario_slot: str,
) -> ExecutionCellInputs:
    comparison = manifest.get("comparison_contract", {})
    for forbidden in (
        "repository_snapshot_artifact_id",
        "model_visible_snapshot_artifact_id",
    ):
        if forbidden in comparison:
            _fail("invalid_review_seed", f"/comparison_contract/{forbidden}", "global input authority is forbidden")
    scenario = _scenario(manifest, scenario_slot)
    if (
        scenario["evidence_class"] == "blind_holdout"
        and scenario["repository_snapshot_artifact_id"] != scenario["fixture_artifact_id"]
    ):
        _fail("invalid_scenario_identity", "/repository_snapshot_artifact_id", "blind repository must equal fixture")
    return ExecutionCellInputs(
        repository_snapshot_artifact_id=scenario["repository_snapshot_artifact_id"],
        model_visible_snapshot_artifact_id=scenario["model_visible_snapshot_artifact_id"],
    )


def validate_descendant_binding(
    descendant: Mapping[str, Any],
    manifest: Mapping[str, Any],
    registry: ManifestRegistry,
) -> None:
    manifest_hash = review_json_sha256(manifest)
    seed_hash = manifest["review"]["review_seed_sha256"]
    if (
        descendant.get("semantic_rules_version") != manifest["semantic_rules_version"]
        or descendant.get("execution_manifest_sha256") != manifest_hash
        or require_eligible_registration_41(
            registry,
            manifest,
        ).execution_manifest_sha256 != manifest_hash
    ):
        _fail("invalid_manifest_binding", "/execution_manifest_sha256", "descendant is not bound to registered final manifest")


def validate_manifest_registration_receipt(
    receipt: Mapping[str, Any],
    *,
    seed: Mapping[str, Any],
    attestation: Mapping[str, Any],
    manifest: Mapping[str, Any],
    registry: ManifestRegistry,
) -> None:
    errors = _schema_errors(
        receipt,
        "manifestRegistrationReceipt41",
        default_code="invalid_review_attestation",
    )
    if errors:
        _raise_review_errors(errors)
    _validate_timestamp(receipt["registered_at"], "/registered_at", "invalid_review_attestation")
    seed_hash = review_json_sha256(seed)
    attestation_hash = review_json_sha256(attestation)
    manifest_hash = review_json_sha256(manifest)
    registration = require_eligible_registration_41(
        registry,
        manifest,
    )
    if (
        registration.review_seed_sha256 != seed_hash
        or registration.review_attestation_sha256 != attestation_hash
        or registration.execution_manifest_sha256 != manifest_hash
    ):
        _fail(
            "invalid_manifest_binding",
            "/execution_manifest_sha256",
            "receipt inputs differ from the exact eligible registration",
        )
    if (
        receipt["review_seed_sha256"] != seed_hash
        or receipt["review_attestation_sha256"] != attestation_hash
        or receipt["execution_manifest_sha256"] != manifest_hash
    ):
        _fail("invalid_review_attestation", "/execution_manifest_sha256", "registration receipt binding failed")
    if receipt["registered_at"] < attestation["reviewed_at"]:
        _fail("invalid_review_attestation", "/registered_at", "registration predates review")


def _validate_bundle(
    bundle: Mapping[str, Any] | bytes,
    *,
    expected_purpose: str,
) -> Mapping[str, Any]:
    value = parse_review_json(bundle) if isinstance(bundle, bytes) else bundle
    if isinstance(bundle, bytes) and canonicalize_review_json(value) != bundle:
        _fail(
            "external_artifact_content_mismatch",
            "/",
            "bundle bytes are not RFC 8785 canonical JSON",
        )
    if not isinstance(value, Mapping):
        _fail("external_artifact_content_mismatch", "/", "bundle must be a closed object")
    if value.get("purpose") != expected_purpose:
        _fail("external_artifact_content_mismatch", "/purpose", "bundle purpose does not match slot kind")
    files = value.get("files")
    if not isinstance(files, list):
        _fail("invalid_bundle_path", "/files", "files must be an array")
    paths: list[str] = []
    collision_keys: set[str] = set()
    for index, item in enumerate(files):
        path = item.get("path") if isinstance(item, Mapping) else None
        if not isinstance(path, str) or not _canonical_bundle_path(path):
            _fail("invalid_bundle_path", f"/files/{index}/path", "path is not canonical ASCII POSIX")
        collision = _ascii_lower(path)
        if collision in collision_keys:
            _fail("invalid_bundle_path", f"/files/{index}/path", "ASCII-case path collision")
        collision_keys.add(collision)
        paths.append(path)
    if paths != sorted(paths, key=lambda item: item.encode("ascii")):
        _fail("invalid_bundle_path", "/files", "paths must be in ASCII byte order")
    definition = "fixtureBundle41" if expected_purpose == "fixture" else "hiddenTestBundle41"
    errors = _schema_errors(value, definition, default_code="external_artifact_content_mismatch")
    if errors:
        _raise_review_errors(errors)
    return value


def _canonical_bundle_path(path: str) -> bool:
    if not path or not path.isascii() or _BUNDLE_PATH_RE.fullmatch(path) is None:
        return False
    return all(segment not in {"", ".", ".."} for segment in path.split("/"))


def _ascii_lower(value: str) -> str:
    return value.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


def _write_bundle_from_root_fd(
    root: Path,
    decoded: list[tuple[str, bytes]],
) -> list[Path]:
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        file_flags |= os.O_NOFOLLOW
    try:
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        _fail(
            "invalid_bundle_path",
            "/destination_root",
            f"bundle root open failed: {exc.__class__.__name__}",
        )
    created_files: list[Path] = []
    created_directories: list[Path] = []
    try:
        for relative, payload in decoded:
            parts = relative.split("/")
            parent_fd = os.dup(root_fd)
            current = root
            try:
                for segment in parts[:-1]:
                    current = current / segment
                    try:
                        os.mkdir(segment, mode=0o700, dir_fd=parent_fd)
                        created_directories.append(current)
                    except FileExistsError:
                        pass
                    next_fd = os.open(segment, directory_flags, dir_fd=parent_fd)
                    os.close(parent_fd)
                    parent_fd = next_fd
                descriptor = os.open(
                    parts[-1],
                    file_flags,
                    0o600,
                    dir_fd=parent_fd,
                )
                target = root / relative
                created_files.append(target)
                with os.fdopen(descriptor, "wb") as output:
                    output.write(payload)
            finally:
                os.close(parent_fd)
    except OSError as exc:
        _rollback_bundle_materialization(created_files, created_directories)
        _fail(
            "invalid_bundle_path",
            "/destination_root",
            f"bundle materialization failed: {exc.__class__.__name__}",
        )
    finally:
        os.close(root_fd)
    return created_files


def _rollback_bundle_materialization(
    files: list[Path],
    directories: list[Path],
) -> None:
    for path in reversed(files):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    for path in reversed(directories):
        try:
            path.rmdir()
        except OSError:
            pass


def _validate_source_ledger(ledger: Mapping[str, Any]) -> None:
    refs = [entry["source_ref"] for entry in ledger["entries"]]
    if len(refs) != len(set(refs)):
        _fail("external_artifact_content_mismatch", "/entries", "source refs must be unique")


def _validate_model_visible_snapshot(
    snapshot: Mapping[str, Any],
    ledger: Mapping[str, Any] | None,
) -> None:
    if ledger is None:
        _fail("external_artifact_content_mismatch", "/source_ledger_sha256", "source ledger is unavailable")
    if snapshot["source_ledger_sha256"] != review_json_sha256(ledger):
        _fail("external_artifact_content_mismatch", "/source_ledger_sha256", "source ledger hash mismatch")
    expected = [entry for entry in ledger["entries"] if entry["model_visible"]]
    events = snapshot["events"]
    for index, event in enumerate(events):
        _validate_timestamp(
            event["observed_at"],
            f"/events/{index}/observed_at",
            "external_artifact_content_mismatch",
        )
    if [entry["source_ref"] for entry in expected] != [event["source_ref"] for event in events]:
        _fail("external_artifact_content_mismatch", "/events", "event order differs from source ledger")
    for index, (entry, event) in enumerate(zip(expected, events, strict=True)):
        if entry["event_sha256"] != review_json_sha256(event):
            _fail("external_artifact_content_mismatch", f"/events/{index}", "event hash mismatch")


def _validate_label_ledger(
    label: Mapping[str, Any],
    ledger: Mapping[str, Any] | None,
    kind: str,
) -> None:
    if ledger is None or label["source_ledger_sha256"] != review_json_sha256(ledger):
        _fail("external_artifact_content_mismatch", "/source_ledger_sha256", "label ledger source mismatch")
    source_refs = {entry["source_ref"] for entry in ledger["entries"]}
    if kind == "required_memory_label_ledger":
        refs = label["required_source_refs"]
        if refs != sorted(refs) or any(ref not in source_refs for ref in refs):
            _fail("external_artifact_content_mismatch", "/required_source_refs", "required refs are unsorted or unresolved")
        return
    opportunities: set[str] = set()
    for index, entry in enumerate(label["entries"]):
        if entry["opportunity_id"] in opportunities or not {
            entry["prior_source_ref"],
            entry["candidate_source_ref"],
        }.issubset(source_refs):
            _fail("external_artifact_content_mismatch", f"/entries/{index}", "relation refs are duplicated or unresolved")
        opportunities.add(entry["opportunity_id"])


def _validate_leakage_review(
    review: Mapping[str, Any],
    manifest: Mapping[str, Any],
    scenario_slot: str,
) -> None:
    if review["verdict"] != "pass" or review["reason_codes"] != _PASS_REASON_CODES:
        _fail("external_artifact_content_mismatch", "/reason_codes", "only the exact pass set is eligible")
    scenario = _scenario(manifest, scenario_slot)
    catalog = manifest["input_artifact_catalog"]
    expected = {
        "fixture_sha256": manifest["fixture_hashes"][scenario_slot],
        "source_ledger_sha256": _content_hash(catalog[scenario["source_ledger_artifact_id"]]),
        "model_visible_snapshot_sha256": _content_hash(catalog[scenario["model_visible_snapshot_artifact_id"]]),
        "prompt_template_sha256": catalog[manifest["comparison_contract"]["prompt_template_artifact_id"]]["sha256"],
        "relation_label_sha256": manifest["label_hashes"][scenario_slot],
        "hidden_test_content_sha256": manifest["hidden_test_hashes"][scenario_slot],
        "evaluator_image_digest": manifest["evaluator_image_digest"],
    }
    for field_name, value in expected.items():
        if review[field_name] != value:
            _fail(
                "external_artifact_content_mismatch",
                f"/{field_name}",
                "leakage review binding mismatch",
            )


def _content_hash(record: Mapping[str, Any]) -> str:
    return record.get("content_sha256", record["sha256"])


def _scenario(manifest: Mapping[str, Any], scenario_slot: str) -> Mapping[str, Any]:
    for scenario in manifest["evidence_scenarios"]:
        if scenario["scenario_slot"] == scenario_slot:
            return scenario
    _fail("invalid_scenario_identity", "/scenario_slot", "scenario is not in manifest")

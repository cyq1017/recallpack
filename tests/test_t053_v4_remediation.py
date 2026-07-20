from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recallpack.evidence import (
    InMemoryManifestRegistry,
    SqliteManifestRegistry,
    assemble_eligible_execution_manifest_41,
    assemble_execution_manifest_41,
    compute_frozen_code_hashes,
    open_external_custody_leakage_loader_41,
    register_execution_manifest_41,
    review_json_sha256,
)
from recallpack.evidence_review_protocol import resolve_validated_registration
from recallpack import evidence, evidence_custody, evidence_review_protocol
from recallpack.secure_files import open_canonical_root
from tests._v41_review_seed_fixtures import (
    build_attestation,
    build_external_contents,
    build_r2_seed,
    canonical_bytes,
    materialize_frozen_code_repository,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "specs/001-recallpack-v4/contracts/evaluation.schema.json"
ACCEPTED_EVENTS_PATH = (
    ROOT
    / "specs/001-recallpack-v4/reviews/t053-proposed-events-v3.json"
)
SOURCE_INVENTORY_PATH = (
    ROOT
    / "specs/001-recallpack-v4/reviews/t053-review-source-inventory-v3.json"
)
SOURCE_PACKAGE_ROOT = Path("/private/tmp/recallpack-t053-v3-review-sources")


class T053V4RemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seed, self.artifact_bytes = build_r2_seed()
        self._repository = tempfile.TemporaryDirectory()
        self.addCleanup(self._repository.cleanup)
        self.repository_root = Path(self._repository.name)
        materialize_frozen_code_repository(
            self.repository_root,
            SCHEMA_PATH.read_bytes(),
        )
        self.seed["code_hashes"] = compute_frozen_code_hashes(
            self.repository_root
        )
        seed_hash = review_json_sha256(self.seed)
        self.attestation, self.receipt = build_attestation(
            self.seed,
            seed_hash,
        )

    def _assemble_diagnostic(self):
        return assemble_execution_manifest_41(
            self.seed,
            self.attestation,
            seed_receipt=self.receipt,
            artifact_bytes=self.artifact_bytes,
            repository_root=self.repository_root,
        )

    def _accepted_protocol_inputs(self):
        seed = copy.deepcopy(self.seed)
        artifacts = dict(self.artifact_bytes)
        cards = json.loads(ACCEPTED_EVENTS_PATH.read_text(encoding="utf-8"))
        inventory = json.loads(SOURCE_INVENTORY_PATH.read_text(encoding="utf-8"))
        commits_by_slot = {
            slot: [
                item["commit"]
                for item in inventory["sources"]
                if item["source_id"].startswith(f"{slot}-")
            ]
            for slot in ("projectodyssey", "deepagents")
        }
        for scenario_cards in cards["scenarios"]:
            slot = scenario_cards["scenario_slot"]
            scenario = next(
                item for item in seed["scenario_plan"]
                if item["scenario_slot"] == slot
            )
            events = [item["event"] for item in scenario_cards["events"]]
            ledger = {
                "record_type": "source_ledger",
                "scenario_slot": slot,
                "entries": [
                    {
                        "source_ref": event["source_ref"],
                        "event_sha256": review_json_sha256(event),
                        "model_visible": True,
                    }
                    for event in events
                ],
            }
            ledger_bytes = canonical_bytes(ledger)
            ledger_hash = hashlib.sha256(ledger_bytes).hexdigest()
            fixture_bytes = canonical_bytes(
                {
                    "record_type": "fixture",
                    "scenario_slot": slot,
                    "events": events,
                }
            )
            snapshot_bytes = canonical_bytes(
                {
                    "record_type": "model_visible_snapshot",
                    "scenario_slot": slot,
                    "source_ledger_sha256": ledger_hash,
                    "events": events,
                }
            )
            summaries = [
                {"source_ref": event["source_ref"], "summary": event["summary"]}
                for event in events
            ]
            provenance = json.loads(
                artifacts[scenario["provenance_artifact_id"]]
            )
            provenance["commit_refs"] = commits_by_slot[slot]
            provenance["authored_summary_sha256"] = review_json_sha256(summaries)
            provenance_bytes = canonical_bytes(provenance)
            replacements = {
                scenario["fixture_artifact_id"]: fixture_bytes,
                scenario["source_ledger_artifact_id"]: ledger_bytes,
                scenario["model_visible_snapshot_artifact_id"]: snapshot_bytes,
                scenario["provenance_artifact_id"]: provenance_bytes,
            }
            for artifact_id, payload in replacements.items():
                artifacts[artifact_id] = payload
                seed["frozen_input_artifact_catalog"][artifact_id]["sha256"] = (
                    hashlib.sha256(payload).hexdigest()
                )
                seed["frozen_input_artifact_catalog"][artifact_id]["bytes"] = len(
                    payload
                )
            scenario["fixture_sha256"] = hashlib.sha256(fixture_bytes).hexdigest()
            scenario["source_ledger_sha256"] = ledger_hash
            scenario["model_visible_snapshot_sha256"] = hashlib.sha256(
                snapshot_bytes
            ).hexdigest()
            scenario["provenance_sha256"] = hashlib.sha256(
                provenance_bytes
            ).hexdigest()
        external = build_external_contents(seed, artifacts)
        seed_hash = review_json_sha256(seed)
        attestation, receipt = build_attestation(seed, seed_hash, external)
        receipt["received_at"] = "2026-07-18T00:02:00Z"
        attestation["seed_receipt_sha256"] = review_json_sha256(receipt)
        attestation["reviewed_at"] = "2026-07-18T00:07:00Z"
        return seed, artifacts, external, attestation, receipt, cards, inventory

    def _materialize_external_custody(
        self,
        root: Path,
        *,
        seed,
        artifacts,
        external,
        attestation,
        receipt,
        cards,
        inventory,
    ) -> bytes:
        source_root = root / "reviewer-source-package"
        phase2_root = root / "phase-2"
        source_root.mkdir(parents=True)
        phase2_root.mkdir(parents=True)
        (phase2_root / "external-review-attestation.json").write_bytes(
            canonical_bytes(attestation)
        )
        shutil.copyfile(SOURCE_INVENTORY_PATH, source_root / "source-inventory.json")
        for source in inventory["sources"]:
            shutil.copyfile(
                SOURCE_PACKAGE_ROOT / source["reviewer_filename"],
                source_root / source["reviewer_filename"],
            )
        suffixes = {
            "required_memory_label_ledger": "required-memory-label.json",
            "relation_label_ledger": "relation-label-ledger.json",
            "leakage_review": "leakage-review.json",
        }
        external_rows = []
        for scenario in seed["scenario_plan"]:
            slot = scenario["scenario_slot"]
            for kind, suffix in suffixes.items():
                artifact_id = f"external__{slot}__{kind}"
                payload = external[artifact_id]
                (phase2_root / f"{slot}-{suffix}").write_bytes(payload)
                external_rows.append(
                    {
                        "scenario_slot": slot,
                        "kind": kind,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "bytes": len(payload),
                    }
                )
        source_rows = [
            {
                "source_id": source["source_id"],
                "sha256": source["sha256"],
                "bytes": source["bytes"],
            }
            for source in inventory["sources"]
        ]
        semantic_source_rows = [
            {
                **row,
                "hash_and_length_verified": True,
                "source_support_checked": True,
                "copying_checked": True,
            }
            for row in source_rows
        ]
        cards_by_slot = {
            item["scenario_slot"]: item for item in cards["scenarios"]
        }
        prompt_id = seed["comparison_contract"]["prompt_template_artifact_id"]
        prompt_hash = hashlib.sha256(artifacts[prompt_id]).hexdigest()
        scenario_reports = []
        for scenario in seed["scenario_plan"]:
            slot = scenario["scenario_slot"]
            scenario_cards = cards_by_slot[slot]
            event_reports = []
            for card in scenario_cards["events"]:
                sourced = card["source_id"] is not None
                event_reports.append(
                    {
                        "source_ref": card["event"]["source_ref"],
                        "event_sha256": card["event_sha256"],
                        "applied_case_ids": ["P1" if sourced else "P5"],
                        "decision": "pass",
                        "rationale": "The event is source-supported or a neutral task constraint without scorer authority.",
                        "source_support_decision": "pass" if sourced else "not_applicable",
                        "copying_decision": "pass" if sourced else "not_applicable",
                        "metadata_derivation_decision": "pass",
                    }
                )
            scenario_reports.append(
                {
                    "scenario_slot": slot,
                    "model_visible_snapshot_sha256": scenario["model_visible_snapshot_sha256"],
                    "prompt_template_sha256": prompt_hash,
                    "ordered_event_hashes": [
                        card["event_sha256"] for card in scenario_cards["events"]
                    ],
                    "events": event_reports,
                    "whole_input": {
                        "applied_case_ids": ["P2" if slot == "projectodyssey" else "P4"],
                        "decision": "pass",
                        "rationale": "The complete composition exposes no benchmark-authored endpoint roles or hidden expectations.",
                    },
                    "leakage_review_sha256": hashlib.sha256(
                        external[f"external__{slot}__leakage_review"]
                    ).hexdigest(),
                    "final_verdict": "pass",
                }
            )
        semantic_report = {
            "record_type": "semantic_adjudication_report_v4",
            "semantic_rules_version": "4.1",
            "reviewer_id": "reviewer_test",
            "reviewed_at": "2026-07-18T00:04:00Z",
            "matrix_file_sha256": "fbf7cd243bf1784debe4e26cf32038475c518a2aacb8cfc59fd95b137e3aeae1",
            "source_cards_file_sha256": "1ce7322b1434eba70aecea2547ab8fa1931b766601fdadde632091f14b712018",
            "source_package_inventory_file_sha256": "8834b3523b478269251c91473c1b916d4db65e6e4545804973d4c99fa85f9ea7",
            "source_package_files": semantic_source_rows,
            "scenario_reports": scenario_reports,
            "honesty_confirmations": {
                "no_relation_ledger_used_for_summary_authoring": True,
                "no_required_memory_labels_used_for_summary_authoring": True,
                "no_hidden_test_content_used": True,
                "no_variant_output_used": True,
                "no_expected_patch_used": True,
                "source_bytes_reviewer_only": True,
                "complete_composition_reviewed": True,
            },
            "final_verdict": "pass",
        }
        semantic_bytes = canonical_bytes(semantic_report)
        (phase2_root / "semantic-adjudication-report.json").write_bytes(
            semantic_bytes
        )
        custody_report = {
            "record_type": "phase_2_custody_report_v4",
            "semantic_rules_version": "4.1",
            "review_seed_sha256": review_json_sha256(seed),
            "seed_receipt_sha256": review_json_sha256(receipt),
            "phase2_instruction_file_sha256": "e9c802f6194943a24ffe67fb1f97c04e8452e16ea89747e68a018590bcbe7468",
            "matrix_file_sha256": "fbf7cd243bf1784debe4e26cf32038475c518a2aacb8cfc59fd95b137e3aeae1",
            "semantic_report_schema_file_sha256": "d8a2eee0f04a88d656f6530dc4ea30f04fbc4903274e7f9178b670c3a5463caa",
            "custody_report_schema_file_sha256": "3e4871a9eec48041a5b0fb10aac851f797e919fca8d2e3d0addaebf92cb55a28",
            "source_cards_file_sha256": "1ce7322b1434eba70aecea2547ab8fa1931b766601fdadde632091f14b712018",
            "source_package_inventory_file_sha256": "8834b3523b478269251c91473c1b916d4db65e6e4545804973d4c99fa85f9ea7",
            "source_package_files": source_rows,
            "external_artifacts": external_rows,
            "semantic_report_jcs_sha256": hashlib.sha256(semantic_bytes).hexdigest(),
            "semantic_report_bytes": len(semantic_bytes),
            "authored_at": "2026-07-18T00:05:00Z",
            "reviewed_at": "2026-07-18T00:06:00Z",
            "final_eligibility_verdict": "pass",
        }
        custody_bytes = canonical_bytes(custody_report)
        (phase2_root / "phase-2-custody-report.json").write_bytes(custody_bytes)
        return custody_bytes

    def test_accepted_event_objects_are_the_exact_runtime_inputs(self) -> None:
        accepted = json.loads(
            ACCEPTED_EVENTS_PATH.read_text(encoding="utf-8")
        )
        for scenario in accepted["scenarios"]:
            slot = scenario["scenario_slot"]
            runtime_events = [
                json.loads(line)
                for line in (
                    ROOT
                    / "evaluation/scenarios"
                    / slot
                    / "authored-events.jsonl"
                ).read_text(encoding="utf-8").splitlines()
                if line
            ]
            expected_events = [item["event"] for item in scenario["events"]]
            with self.subTest(scenario_slot=slot):
                self.assertEqual(expected_events, runtime_events)

    def test_projection_has_diagnostic_type_without_registration_authority(self) -> None:
        diagnostic = self._assemble_diagnostic()
        self.assertEqual(
            "DiagnosticExecutionManifest41",
            type(diagnostic).__name__,
        )

    def test_raw_manifest_mapping_cannot_register(self) -> None:
        diagnostic = self._assemble_diagnostic()
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            register_execution_manifest_41(
                diagnostic.manifest,
                artifact_bytes=diagnostic.artifact_bytes,
                registry=InMemoryManifestRegistry(),
                seed_receipt=self.receipt,
                repository_root=self.repository_root,
            )

    def test_legacy_registration_row_never_resolves_as_eligible(self) -> None:
        registry = InMemoryManifestRegistry()
        seed_hash = review_json_sha256(self.seed)
        registry._registrations[seed_hash] = "a" * 64
        self.assertIsNone(resolve_validated_registration(registry, seed_hash))

    def test_legacy_registration_blocks_eligible_cas_in_both_registries(
        self,
    ) -> None:
        registration_type = evidence_review_protocol.EligibleRegistration41
        authority = evidence_review_protocol._REGISTRATION_AUTHORITY
        registration = registration_type(
            review_seed_sha256="1" * 64,
            execution_manifest_sha256="2" * 64,
            review_attestation_sha256="3" * 64,
            leakage_set_sha256="4" * 64,
            eligibility_gate_version="pre_registration_leakage_v1",
        )
        memory_registry = InMemoryManifestRegistry()
        memory_registry._registrations[registration.review_seed_sha256] = "9" * 64
        with self.assertRaisesRegex(ValueError, "review_seed_reuse"):
            memory_registry._record_validated_registration(
                registration,
                authority,
            )
        with tempfile.TemporaryDirectory() as directory:
            sqlite_registry = SqliteManifestRegistry(
                Path(directory) / "legacy-burned.sqlite3"
            )
            sqlite_registry._connection.execute(
                "INSERT INTO review_seed_registrations "
                "(review_seed_sha256, execution_manifest_sha256) VALUES (?, ?)",
                (registration.review_seed_sha256, "9" * 64),
            )
            with self.assertRaisesRegex(ValueError, "review_seed_reuse"):
                sqlite_registry._record_validated_registration(
                    registration,
                    authority,
                )
            self.assertIsNone(
                sqlite_registry.resolve(registration.review_seed_sha256)
            )
            sqlite_registry.close()
            reopened = SqliteManifestRegistry(
                Path(directory) / "legacy-burned.sqlite3"
            )
            self.assertIsNone(
                reopened.resolve(registration.review_seed_sha256)
            )
            with self.assertRaisesRegex(ValueError, "review_seed_reuse"):
                reopened._record_validated_registration(
                    registration,
                    authority,
                )
            reopened.close()

    def test_eligible_registries_reject_a_conflicting_five_field_binding(
        self,
    ) -> None:
        registration_type = evidence_review_protocol.EligibleRegistration41
        authority = evidence_review_protocol._REGISTRATION_AUTHORITY
        original = registration_type(
            review_seed_sha256="1" * 64,
            execution_manifest_sha256="2" * 64,
            review_attestation_sha256="3" * 64,
            leakage_set_sha256="4" * 64,
            eligibility_gate_version="pre_registration_leakage_v1",
        )
        conflicting = registration_type(
            review_seed_sha256=original.review_seed_sha256,
            execution_manifest_sha256=original.execution_manifest_sha256,
            review_attestation_sha256="5" * 64,
            leakage_set_sha256=original.leakage_set_sha256,
            eligibility_gate_version=original.eligibility_gate_version,
        )
        with tempfile.TemporaryDirectory() as directory:
            registries = (
                InMemoryManifestRegistry(),
                SqliteManifestRegistry(Path(directory) / "eligible-cas.sqlite3"),
            )
            for registry in registries:
                with self.subTest(registry=type(registry).__name__):
                    self.assertEqual(
                        original,
                        registry._record_validated_registration(
                            original,
                            authority,
                        ),
                    )
                    with self.assertRaisesRegex(ValueError, "review_seed_reuse"):
                        registry._record_validated_registration(
                            conflicting,
                            authority,
                        )
            registries[1].close()

    def test_eligible_capability_cannot_be_constructed_or_forged(self) -> None:
        capability_type = evidence_review_protocol.EligibleExecutionManifest41
        with self.assertRaises(TypeError):
            capability_type()
        forged = object.__new__(capability_type)
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            register_execution_manifest_41(
                forged,
                registry=InMemoryManifestRegistry(),
            )

    def test_production_assembly_rejects_caller_supplied_loader_values(self) -> None:
        assembler = getattr(
            evidence,
            "assemble_eligible_execution_manifest_41",
            None,
        )
        self.assertTrue(callable(assembler))
        for untrusted in ({}, lambda _slot: b"{}", object()):
            with self.subTest(loader_type=type(untrusted).__name__):
                with self.assertRaisesRegex(
                    ValueError,
                    "invalid_manifest_binding",
                ):
                    assembler(
                        self.seed,
                        self.attestation,
                        seed_receipt=self.receipt,
                        artifact_bytes=self.artifact_bytes,
                        repository_root=self.repository_root,
                        leakage_loader=untrusted,
                    )

    def test_trusted_loader_requires_an_independently_anchored_custody_report(
        self,
    ) -> None:
        opener = getattr(
            evidence,
            "open_external_custody_leakage_loader_41",
            None,
        )
        self.assertTrue(callable(opener))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ValueError,
                "invalid_external_custody",
            ):
                opener(
                    Path(directory),
                    expected_custody_report_jcs_sha256="0" * 64,
                    expected_custody_report_bytes=0,
                    seed=self.seed,
                    seed_receipt=self.receipt,
                    attestation=self.attestation,
                )

    @unittest.skipUnless(
        SOURCE_PACKAGE_ROOT.is_dir()
        and all(
            (SOURCE_PACKAGE_ROOT / name).is_file()
            for name in (
                "projectodyssey-old-policy.md",
                "projectodyssey-new-policy.md",
                "deepagents-old-package-policy.md",
                "deepagents-new-package-policy.md",
            )
        ),
        "exact reviewer source-byte package is not present",
    )
    def test_external_custody_is_the_only_path_to_eligible_registration(self) -> None:
        (
            seed,
            artifacts,
            external,
            attestation,
            receipt,
            cards,
            inventory,
        ) = self._accepted_protocol_inputs()
        with tempfile.TemporaryDirectory() as directory:
            custody_bytes = self._materialize_external_custody(
                Path(directory),
                seed=seed,
                artifacts=artifacts,
                external=external,
                attestation=attestation,
                receipt=receipt,
                cards=cards,
                inventory=inventory,
            )
            loader = open_external_custody_leakage_loader_41(
                Path(directory),
                expected_custody_report_jcs_sha256=hashlib.sha256(
                    custody_bytes
                ).hexdigest(),
                expected_custody_report_bytes=len(custody_bytes),
                seed=seed,
                seed_receipt=receipt,
                attestation=attestation,
                artifact_bytes=artifacts,
            )
            eligible = assemble_eligible_execution_manifest_41(
                seed,
                attestation,
                seed_receipt=receipt,
                artifact_bytes=artifacts,
                repository_root=self.repository_root,
                leakage_loader=loader,
            )
            registry = InMemoryManifestRegistry()
            registration = register_execution_manifest_41(
                eligible,
                registry=registry,
            )
            sqlite_path = Path(directory) / "eligible.sqlite3"
            sqlite_registry = SqliteManifestRegistry(sqlite_path)
            sqlite_registration = register_execution_manifest_41(
                eligible,
                registry=sqlite_registry,
            )
            sqlite_registry.close()
            reopened = SqliteManifestRegistry(sqlite_path)
            self.assertEqual(
                sqlite_registration,
                reopened.resolve(sqlite_registration.review_seed_sha256),
            )
            reopened.close()
        self.assertEqual(review_json_sha256(seed), registration.review_seed_sha256)
        self.assertEqual(
            "pre_registration_leakage_v1",
            registration.eligibility_gate_version,
        )
        self.assertEqual(
            registration,
            resolve_validated_registration(
                registry,
                registration.review_seed_sha256,
            ),
        )

    @unittest.skipUnless(
        SOURCE_PACKAGE_ROOT.is_dir(),
        "exact reviewer source-byte package is not present",
    )
    def test_custody_anchor_is_checked_before_report_parsing(self) -> None:
        (
            seed,
            artifacts,
            external,
            attestation,
            receipt,
            cards,
            inventory,
        ) = self._accepted_protocol_inputs()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custody_bytes = self._materialize_external_custody(
                root,
                seed=seed,
                artifacts=artifacts,
                external=external,
                attestation=attestation,
                receipt=receipt,
                cards=cards,
                inventory=inventory,
            )
            (root / "phase-2/phase-2-custody-report.json").write_bytes(
                custody_bytes + b"\n"
            )
            with self.assertRaisesRegex(
                ValueError,
                "does not match the independent anchor",
            ):
                open_external_custody_leakage_loader_41(
                    root,
                    expected_custody_report_jcs_sha256=hashlib.sha256(
                        custody_bytes
                    ).hexdigest(),
                    expected_custody_report_bytes=len(custody_bytes),
                    seed=seed,
                    seed_receipt=receipt,
                    attestation=attestation,
                    artifact_bytes=artifacts,
                )

    @unittest.skipUnless(
        SOURCE_PACKAGE_ROOT.is_dir(),
        "exact reviewer source-byte package is not present",
    )
    def test_semantic_reject_cannot_mint_a_trusted_loader(self) -> None:
        (
            seed,
            artifacts,
            external,
            attestation,
            receipt,
            cards,
            inventory,
        ) = self._accepted_protocol_inputs()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._materialize_external_custody(
                root,
                seed=seed,
                artifacts=artifacts,
                external=external,
                attestation=attestation,
                receipt=receipt,
                cards=cards,
                inventory=inventory,
            )
            semantic_path = root / "phase-2/semantic-adjudication-report.json"
            semantic = json.loads(semantic_path.read_bytes())
            semantic["final_verdict"] = "reject"
            semantic_bytes = canonical_bytes(semantic)
            semantic_path.write_bytes(semantic_bytes)
            custody_path = root / "phase-2/phase-2-custody-report.json"
            custody = json.loads(custody_path.read_bytes())
            custody["semantic_report_jcs_sha256"] = hashlib.sha256(
                semantic_bytes
            ).hexdigest()
            custody["semantic_report_bytes"] = len(semantic_bytes)
            custody_bytes = canonical_bytes(custody)
            custody_path.write_bytes(custody_bytes)
            with self.assertRaisesRegex(ValueError, "semantic report did not pass"):
                open_external_custody_leakage_loader_41(
                    root,
                    expected_custody_report_jcs_sha256=hashlib.sha256(
                        custody_bytes
                    ).hexdigest(),
                    expected_custody_report_bytes=len(custody_bytes),
                    seed=seed,
                    seed_receipt=receipt,
                    attestation=attestation,
                    artifact_bytes=artifacts,
                )

    @unittest.skipUnless(
        SOURCE_PACKAGE_ROOT.is_dir(),
        "exact reviewer source-byte package is not present",
    )
    def test_custody_chronology_violation_cannot_mint_a_loader(self) -> None:
        (
            seed,
            artifacts,
            external,
            attestation,
            receipt,
            cards,
            inventory,
        ) = self._accepted_protocol_inputs()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._materialize_external_custody(
                root,
                seed=seed,
                artifacts=artifacts,
                external=external,
                attestation=attestation,
                receipt=receipt,
                cards=cards,
                inventory=inventory,
            )
            custody_path = root / "phase-2/phase-2-custody-report.json"
            custody = json.loads(custody_path.read_bytes())
            custody["authored_at"] = "2026-07-18T00:01:00Z"
            custody_bytes = canonical_bytes(custody)
            custody_path.write_bytes(custody_bytes)
            with self.assertRaisesRegex(
                ValueError,
                "custody chronology and final pass verdict are required",
            ):
                open_external_custody_leakage_loader_41(
                    root,
                    expected_custody_report_jcs_sha256=hashlib.sha256(
                        custody_bytes
                    ).hexdigest(),
                    expected_custody_report_bytes=len(custody_bytes),
                    seed=seed,
                    seed_receipt=receipt,
                    attestation=attestation,
                    artifact_bytes=artifacts,
                )

    @unittest.skipUnless(
        SOURCE_PACKAGE_ROOT.is_dir(),
        "exact reviewer source-byte package is not present",
    )
    def test_semantic_review_must_precede_custody_authorship(self) -> None:
        (
            seed,
            artifacts,
            external,
            attestation,
            receipt,
            cards,
            inventory,
        ) = self._accepted_protocol_inputs()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._materialize_external_custody(
                root,
                seed=seed,
                artifacts=artifacts,
                external=external,
                attestation=attestation,
                receipt=receipt,
                cards=cards,
                inventory=inventory,
            )
            custody_path = root / "phase-2/phase-2-custody-report.json"
            custody = json.loads(custody_path.read_bytes())
            custody["authored_at"] = "2026-07-18T00:03:00Z"
            custody_bytes = canonical_bytes(custody)
            custody_path.write_bytes(custody_bytes)
            with self.assertRaisesRegex(
                ValueError,
                "custody chronology and final pass verdict are required",
            ):
                open_external_custody_leakage_loader_41(
                    root,
                    expected_custody_report_jcs_sha256=hashlib.sha256(
                        custody_bytes
                    ).hexdigest(),
                    expected_custody_report_bytes=len(custody_bytes),
                    seed=seed,
                    seed_receipt=receipt,
                    attestation=attestation,
                    artifact_bytes=artifacts,
                )

    @unittest.skipUnless(
        SOURCE_PACKAGE_ROOT.is_dir(),
        "exact reviewer source-byte package is not present",
    )
    def test_seed_receipt_must_precede_semantic_review(self) -> None:
        (
            seed,
            artifacts,
            external,
            attestation,
            receipt,
            cards,
            inventory,
        ) = self._accepted_protocol_inputs()
        receipt["received_at"] = "2026-07-18T00:04:30Z"
        attestation["seed_receipt_sha256"] = review_json_sha256(receipt)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custody_bytes = self._materialize_external_custody(
                root,
                seed=seed,
                artifacts=artifacts,
                external=external,
                attestation=attestation,
                receipt=receipt,
                cards=cards,
                inventory=inventory,
            )
            with self.assertRaisesRegex(
                ValueError,
                "custody chronology and final pass verdict are required",
            ):
                open_external_custody_leakage_loader_41(
                    root,
                    expected_custody_report_jcs_sha256=hashlib.sha256(
                        custody_bytes
                    ).hexdigest(),
                    expected_custody_report_bytes=len(custody_bytes),
                    seed=seed,
                    seed_receipt=receipt,
                    attestation=attestation,
                    artifact_bytes=artifacts,
                )

    def test_secure_root_rejects_a_symlinked_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            actual = parent / "actual"
            actual.mkdir()
            linked = parent / "linked"
            linked.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "root.*symlink"):
                with open_canonical_root(linked):
                    self.fail("symlinked root must not open")

    def test_reviewed_authority_file_symlink_cannot_be_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "authority"
            root.mkdir()
            filenames = set(evidence_custody._V4_REVIEW_FILES.values()) | {
                "t053-external-review-phase2-prompt-v4.md"
            }
            for filename in filenames:
                shutil.copyfile(
                    evidence_custody._V4_REVIEW_ROOT / filename,
                    root / filename,
                )
            filename = next(iter(evidence_custody._V4_REVIEW_FILES.values()))
            copied = root / filename
            outside = parent / "outside-authority"
            shutil.copyfile(copied, outside)
            copied.unlink()
            copied.symlink_to(outside)
            with patch.object(evidence_custody, "_V4_REVIEW_ROOT", root):
                with self.assertRaisesRegex(ValueError, "invalid_external_custody"):
                    evidence_custody._load_v4_review_authority()

    @unittest.skipUnless(
        SOURCE_PACKAGE_ROOT.is_dir(),
        "exact reviewer source-byte package is not present",
    )
    def test_external_attestation_substitution_cannot_mint_a_loader(self) -> None:
        (
            seed,
            artifacts,
            external,
            attestation,
            receipt,
            cards,
            inventory,
        ) = self._accepted_protocol_inputs()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custody_bytes = self._materialize_external_custody(
                root,
                seed=seed,
                artifacts=artifacts,
                external=external,
                attestation=attestation,
                receipt=receipt,
                cards=cards,
                inventory=inventory,
            )
            external_attestation = copy.deepcopy(attestation)
            external_attestation["reviewer_id"] = "substituted_reviewer"
            (root / "phase-2/external-review-attestation.json").write_bytes(
                canonical_bytes(external_attestation)
            )
            with self.assertRaisesRegex(
                ValueError,
                "external attestation bytes differ",
            ):
                open_external_custody_leakage_loader_41(
                    root,
                    expected_custody_report_jcs_sha256=hashlib.sha256(
                        custody_bytes
                    ).hexdigest(),
                    expected_custody_report_bytes=len(custody_bytes),
                    seed=seed,
                    seed_receipt=receipt,
                    attestation=attestation,
                    artifact_bytes=artifacts,
                )

    @unittest.skipUnless(
        SOURCE_PACKAGE_ROOT.is_dir(),
        "exact reviewer source-byte package is not present",
    )
    def test_symlinked_reviewer_source_cannot_mint_a_loader(self) -> None:
        (
            seed,
            artifacts,
            external,
            attestation,
            receipt,
            cards,
            inventory,
        ) = self._accepted_protocol_inputs()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custody_bytes = self._materialize_external_custody(
                root,
                seed=seed,
                artifacts=artifacts,
                external=external,
                attestation=attestation,
                receipt=receipt,
                cards=cards,
                inventory=inventory,
            )
            filename = inventory["sources"][0]["reviewer_filename"]
            copied = root / "reviewer-source-package" / filename
            copied.unlink()
            copied.symlink_to(SOURCE_PACKAGE_ROOT / filename)
            with self.assertRaisesRegex(ValueError, "invalid_external_custody"):
                open_external_custody_leakage_loader_41(
                    root,
                    expected_custody_report_jcs_sha256=hashlib.sha256(
                        custody_bytes
                    ).hexdigest(),
                    expected_custody_report_bytes=len(custody_bytes),
                    seed=seed,
                    seed_receipt=receipt,
                    attestation=attestation,
                    artifact_bytes=artifacts,
                )


if __name__ == "__main__":
    unittest.main()

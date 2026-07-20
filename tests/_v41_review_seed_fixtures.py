from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from tests._v4_evidence_manifest_fixtures import (
    build_comparison_contract,
    build_evaluator_contract,
)


PUBLIC_REGISTRY = {
    "projectodyssey": (
        "https://github.com/HomericIntelligence/Odyssey",
        "BSD-3-Clause",
    ),
    "deepagents": ("https://github.com/langchain-ai/deepagents", "MIT"),
    "graphiti": ("https://github.com/getzep/graphiti", "Apache-2.0"),
}

EXTERNAL_KINDS = (
    ("required_memory_label_ledger", "post_outputs_fixed"),
    ("relation_label_ledger", "post_outputs_fixed"),
    ("leakage_review", "pre_run_eligibility_check"),
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def materialize_frozen_code_repository(root: Path, schema_bytes: bytes) -> None:
    (root / "src/recallpack").mkdir(parents=True)
    (root / "src/recallpack/runtime.py").write_text("RUNTIME = 'frozen'\n")
    (root / "evaluation/runner").mkdir(parents=True)
    (root / "evaluation/runner/run.py").write_text("print('frozen evaluator')\n")
    (root / "evaluation/Dockerfile").write_text("FROM scratch\n")
    (root / "evaluation/.dockerignore").write_text(".git\n")
    schema = root / "specs/001-recallpack-v4/contracts/evaluation.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_bytes(schema_bytes)
    (root / "requirements-v4.txt").write_text("jsonschema==4.26.0\n")


def artifact(kind: str, path: str, payload: bytes) -> dict[str, Any]:
    return {
        "kind": kind,
        "origin": "seed_frozen",
        "relative_path": path,
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
        "sanitized": True,
        "content_policy": "sanitized_bounded",
    }


def external_slots(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for scenario in scenarios:
        slot = scenario["scenario_slot"]
        kinds = list(EXTERNAL_KINDS)
        if scenario["evidence_class"] == "blind_holdout":
            kinds.extend(
                (
                    ("fixture", "before_scenario_execution"),
                    ("source_ledger", "before_scenario_execution"),
                    ("model_visible_snapshot", "before_scenario_execution"),
                    ("hidden_test_bundle", "after_model_output_fixed"),
                )
            )
        for kind, phase in kinds:
            result.append(
                {
                    "artifact_id": f"external__{slot}__{kind}",
                    "scenario_slot": slot,
                    "kind": kind,
                    "canonicalization": "rfc8785_json",
                    "reveal_phase": phase,
                    "custody_state": "sealed_external",
                }
            )
    return result


def _scenario_artifacts(slot: str, marker: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    events = [
        {
            "source_ref": f"{slot}:turn-001",
            "observed_at": "2026-07-01T00:00:00Z",
            "actor": "user",
            "kind": "message",
            "summary": f"Old policy for {slot}.",
            "model_visible": True,
            "authored_summary": True,
        },
        {
            "source_ref": f"{slot}:turn-002",
            "observed_at": "2026-07-02T00:00:00Z",
            "actor": "assistant",
            "kind": "message",
            "summary": f"New policy for {slot} supersedes the old policy.",
            "model_visible": True,
            "authored_summary": True,
        },
    ]
    source_ledger = {
        "record_type": "source_ledger",
        "scenario_slot": slot,
        "entries": [
            {
                "source_ref": event["source_ref"],
                "event_sha256": sha256_bytes(canonical_bytes(event)),
                "model_visible": True,
            }
            for event in events
        ],
    }
    source_ledger_bytes = canonical_bytes(source_ledger)
    source_ledger_sha = sha256_bytes(source_ledger_bytes)
    snapshot = {
        "record_type": "model_visible_snapshot",
        "scenario_slot": slot,
        "source_ledger_sha256": source_ledger_sha,
        "events": events,
    }
    summaries = [
        {"source_ref": event["source_ref"], "summary": event["summary"]}
        for event in events
    ]
    repository_url, license_id = PUBLIC_REGISTRY[slot]
    provenance = {
        "record_type": "source_provenance",
        "scenario_slot": slot,
        "evidence_class": "source_backed_synthetic",
        "production_trace": False,
        "copied_source_text": False,
        "authored_summaries": True,
        "repository_url": repository_url,
        "commit_refs": [marker * 40],
        "license_id": license_id,
        "authored_summary_sha256": sha256_bytes(canonical_bytes(summaries)),
    }
    payloads = {
        f"fixture_{slot}": canonical_bytes(
            {"record_type": "fixture", "scenario_slot": slot, "events": events}
        ),
        f"ledger_{slot}": source_ledger_bytes,
        f"repo_{slot}": f"repository snapshot {slot}".encode(),
        f"snapshot_{slot}": canonical_bytes(snapshot),
        f"hidden_hash_{slot}": sha256_bytes(f"hidden tests {slot}".encode()).encode(),
        f"provenance_{slot}": canonical_bytes(provenance),
    }
    scenario = {
        "scenario_slot": slot,
        "evidence_class": "source_backed_synthetic",
        "fixture_artifact_id": f"fixture_{slot}",
        "fixture_sha256": sha256_bytes(payloads[f"fixture_{slot}"]),
        "source_ledger_artifact_id": f"ledger_{slot}",
        "source_ledger_sha256": source_ledger_sha,
        "repository_snapshot_artifact_id": f"repo_{slot}",
        "repository_snapshot_sha256": sha256_bytes(payloads[f"repo_{slot}"]),
        "model_visible_snapshot_artifact_id": f"snapshot_{slot}",
        "model_visible_snapshot_sha256": sha256_bytes(payloads[f"snapshot_{slot}"]),
        "hidden_test_hash_artifact_id": f"hidden_hash_{slot}",
        "hidden_test_content_sha256": payloads[f"hidden_hash_{slot}"].decode(),
        "provenance_artifact_id": f"provenance_{slot}",
        "provenance_sha256": sha256_bytes(payloads[f"provenance_{slot}"]),
    }
    return scenario, payloads


def build_r2_seed() -> tuple[dict[str, Any], dict[str, bytes]]:
    scenarios = []
    payloads: dict[str, bytes] = {}
    for slot, marker in (("projectodyssey", "1"), ("deepagents", "2")):
        scenario, scenario_payloads = _scenario_artifacts(slot, marker)
        scenarios.append(scenario)
        payloads.update(scenario_payloads)

    evaluator = build_evaluator_contract()
    dockerfile = f"FROM python@{evaluator['base_image_digest']}\n".encode()
    runner = b"print('runner')\n"
    image_build_record = canonical_bytes(
        {
            "record_type": "image_build_record",
            "builder": "docker_buildx",
            "platform": evaluator["platform"],
            "build_context_root": evaluator["build_context_root"],
            "build_context_sha256": sha256_bytes(b"evaluation-build-context"),
            "dockerfile_artifact_id": "dockerfile",
            "dockerfile_sha256": sha256_bytes(dockerfile),
            "runner_artifact_id": "runner",
            "runner_sha256": sha256_bytes(runner),
            "dockerfile_from_base_image_digest": evaluator["base_image_digest"],
            "output_image_digest": evaluator["image_digest"],
        }
    )
    common = {
        "patch_contract": b"patch provider contract",
        "prompt_template": b"Generate a patch from selected context only.",
        "runner_contract": b"runner contract",
        "dockerfile": dockerfile,
        "runner": runner,
        "image_build_record": image_build_record,
    }
    payloads.update(common)
    kinds = {
        "patch_contract": "patch_provider_contract",
        "prompt_template": "prompt_template",
        "runner_contract": "runner_contract",
        "dockerfile": "dockerfile",
        "runner": "evaluator_runner",
        "image_build_record": "image_build_record",
    }
    catalog: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        slot = scenario["scenario_slot"]
        for artifact_id, kind, path in (
            (f"fixture_{slot}", "fixture", f"scenarios/{slot}/fixture.json"),
            (f"ledger_{slot}", "source_ledger", f"scenarios/{slot}/source-ledger.json"),
            (f"repo_{slot}", "repository_snapshot", f"scenarios/{slot}/repo.snapshot"),
            (f"snapshot_{slot}", "model_visible_snapshot", f"scenarios/{slot}/model-visible.json"),
            (f"hidden_hash_{slot}", "hidden_test_hash", f"scenarios/{slot}/hidden.sha256"),
            (f"provenance_{slot}", "source_provenance", f"scenarios/{slot}/provenance.json"),
        ):
            catalog[artifact_id] = artifact(kind, path, payloads[artifact_id])
    for artifact_id, kind in kinds.items():
        catalog[artifact_id] = artifact(kind, f"evaluation/{artifact_id}", payloads[artifact_id])

    comparison = deepcopy(build_comparison_contract())
    comparison.pop("repository_snapshot_artifact_id")
    comparison.pop("model_visible_snapshot_artifact_id")
    comparison["writable_paths"] = [
        "pyproject.toml",
        "src/ci_policy.py",
        "src/package_policy.py",
    ]
    execution_order = []
    index = 0
    variants = [
        "raw_full_history",
        "semantic_rerank",
        "recency_aware",
        "recall_time_resolver",
        "recallpack",
    ]
    for scenario in scenarios:
        for variant in variants:
            for repetition in range(1, 4):
                execution_order.append(
                    {
                        "slot_id": f"slot_{scenario['scenario_slot']}_{variant}_{repetition}",
                        "slot_index": index,
                        "scenario_slot": scenario["scenario_slot"],
                        "variant_id": variant,
                        "repetition": repetition,
                        "planned_designation": "headline",
                    }
                )
                index += 1
    seed = {
        "record_type": "evaluation_review_seed",
        "review_seed_version": "review-seed/4.1",
        "semantic_rules_version": "4.1",
        "created_at": "2026-07-15T00:00:00Z",
        "target_rung": "R2",
        "code_hashes": {
            "runtime_tree_sha256": "5" * 64,
            "evaluator_tree_sha256": "6" * 64,
            "evaluation_schema_sha256": "7" * 64,
            "dependency_lock_sha256": "8" * 64,
        },
        "scenario_plan": scenarios,
        "variants": variants,
        "provider_settings": {
            "mode": "live",
            "provider_family": "qwen_cloud",
            "deterministic_fallback": False,
            "models": {
                "memory_decision": "qwen3.7-plus-2026-05-26",
                "embedding": "text-embedding-v4",
                "rerank": "qwen3-rerank",
                "patch_generation": "qwen3.7-plus-2026-05-26",
            },
            "temperature": 0,
            "seed": 7,
            "endpoint_region": "cn-beijing",
        },
        "comparison_contract": comparison,
        "evaluator_contract": evaluator,
        "technical_failure_codes": [
            "sandbox_unavailable",
            "sandbox_timeout",
            "provider_timeout",
        ],
        "execution_order": execution_order,
        "claim_declarations": [
            {
                "claim_id": "claim_structural_runtime",
                "claim_type": "structural_runtime",
                "activation_rule_id": "structural_runtime_gate",
                "eligible_rungs": ["Full", "R1", "R2", "Floor"],
                "statement": "The runtime contract stayed intact.",
                "rerunnable_command": "python -m unittest",
                "limitations": ["R2 has no blind holdout."],
            }
        ],
        "evaluator_image_digest": evaluator["image_digest"],
        "frozen_input_artifact_catalog": catalog,
        "external_artifact_slots": external_slots(scenarios),
    }
    return seed, payloads


def build_full_seed() -> tuple[dict[str, Any], dict[str, bytes]]:
    seed, payloads = build_r2_seed()
    graphiti, graphiti_payloads = _scenario_artifacts("graphiti", "3")
    payloads.update(graphiti_payloads)
    catalog = seed["frozen_input_artifact_catalog"]
    slot = "graphiti"
    for artifact_id, kind, path in (
        (f"fixture_{slot}", "fixture", f"scenarios/{slot}/fixture.json"),
        (f"ledger_{slot}", "source_ledger", f"scenarios/{slot}/source-ledger.json"),
        (f"repo_{slot}", "repository_snapshot", f"scenarios/{slot}/repo.snapshot"),
        (f"snapshot_{slot}", "model_visible_snapshot", f"scenarios/{slot}/model-visible.json"),
        (f"hidden_hash_{slot}", "hidden_test_hash", f"scenarios/{slot}/hidden.sha256"),
        (f"provenance_{slot}", "source_provenance", f"scenarios/{slot}/provenance.json"),
    ):
        catalog[artifact_id] = artifact(kind, path, payloads[artifact_id])
    blind = {"scenario_slot": "blind_holdout_a", "evidence_class": "blind_holdout"}
    seed["target_rung"] = "Full"
    seed["scenario_plan"] = [*seed["scenario_plan"], graphiti, blind]
    seed["comparison_contract"]["writable_paths"] = [
        "pyproject.toml",
        "src/auth.py",
        "src/backend_policy.py",
        "src/ci_policy.py",
        "src/config_loader.py",
        "src/package_policy.py",
        "src/retry.py",
        "src/retry_policy.py",
    ]
    seed["external_artifact_slots"] = external_slots(seed["scenario_plan"])
    seed["execution_order"] = []
    index = 0
    for scenario in seed["scenario_plan"]:
        for variant in seed["variants"]:
            for repetition in range(1, 4):
                seed["execution_order"].append(
                    {
                        "slot_id": f"slot_{scenario['scenario_slot']}_{variant}_{repetition}",
                        "slot_index": index,
                        "scenario_slot": scenario["scenario_slot"],
                        "variant_id": variant,
                        "repetition": repetition,
                        "planned_designation": "headline",
                    }
                )
                index += 1
    seed["claim_declarations"] = [
        seed["claim_declarations"][0],
        {
            "claim_id": "claim_downstream_superiority",
            "claim_type": "downstream_superiority",
            "activation_rule_id": "sc005_downstream_superiority",
            "eligible_rungs": ["Full"],
            "statement": "RecallPack beats the strongest non-lifecycle baseline.",
            "rerunnable_command": "python -m unittest",
            "limitations": ["Raw history is non-comparable."],
        },
        {
            "claim_id": "claim_false_supersession",
            "claim_type": "false_supersession_rate",
            "activation_rule_id": "sc002_false_supersession",
            "eligible_rungs": ["Full"],
            "statement": "False supersession remains zero.",
            "rerunnable_command": "python -m unittest",
            "limitations": ["Population thresholds apply."],
        },
    ]
    return seed, payloads


def deterministic_bundle(slot: str, purpose: str, files: dict[str, bytes]) -> dict[str, Any]:
    import base64

    return {
        "record_type": "deterministic_file_bundle",
        "bundle_version": "deterministic-file-bundle/4.1",
        "scenario_slot": slot,
        "purpose": purpose,
        "files": [
            {
                "path": path,
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "content_base64": base64.b64encode(payload).decode("ascii"),
            }
            for path, payload in sorted(files.items(), key=lambda item: item[0].encode("ascii"))
        ],
    }


def build_external_contents(
    seed: dict[str, Any],
    artifact_bytes: dict[str, bytes],
) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    prompt_id = seed["comparison_contract"]["prompt_template_artifact_id"]
    prompt_hash = sha256_bytes(artifact_bytes[prompt_id])
    for scenario in seed["scenario_plan"]:
        slot = scenario["scenario_slot"]
        if scenario["evidence_class"] == "blind_holdout":
            events = [
                {
                    "source_ref": f"{slot}:turn-001",
                    "observed_at": "2026-07-03T00:00:00Z",
                    "actor": "user",
                    "kind": "message",
                    "summary": "Blind old policy.",
                    "model_visible": True,
                    "authored_summary": True,
                },
                {
                    "source_ref": f"{slot}:turn-002",
                    "observed_at": "2026-07-04T00:00:00Z",
                    "actor": "assistant",
                    "kind": "message",
                    "summary": "Blind replacement policy.",
                    "model_visible": True,
                    "authored_summary": True,
                },
            ]
            source = {
                "record_type": "source_ledger",
                "scenario_slot": slot,
                "entries": [
                    {
                        "source_ref": event["source_ref"],
                        "event_sha256": sha256_bytes(canonical_bytes(event)),
                        "model_visible": True,
                    }
                    for event in events
                ],
            }
            fixture = deterministic_bundle(slot, "fixture", {"src/retry.py": b"def retry(): pass\n"})
            hidden = deterministic_bundle(slot, "hidden_tests", {"test_retry.py": b"assert True\n"})
            snapshot = {
                "record_type": "model_visible_snapshot",
                "scenario_slot": slot,
                "source_ledger_sha256": sha256_bytes(canonical_bytes(source)),
                "events": events,
            }
            source_bytes = canonical_bytes(source)
            fixture_bytes = canonical_bytes(fixture)
            snapshot_bytes = canonical_bytes(snapshot)
            hidden_bytes = canonical_bytes(hidden)
            contents[f"external__{slot}__fixture"] = fixture_bytes
            contents[f"external__{slot}__source_ledger"] = source_bytes
            contents[f"external__{slot}__model_visible_snapshot"] = snapshot_bytes
            contents[f"external__{slot}__hidden_test_bundle"] = hidden_bytes
            source_hash = sha256_bytes(source_bytes)
            fixture_hash = sha256_bytes(fixture_bytes)
            snapshot_hash = sha256_bytes(snapshot_bytes)
            hidden_hash = sha256_bytes(hidden_bytes)
        else:
            source_bytes = artifact_bytes[scenario["source_ledger_artifact_id"]]
            source = json.loads(source_bytes)
            source_hash = scenario["source_ledger_sha256"]
            fixture_hash = scenario["fixture_sha256"]
            snapshot_hash = scenario["model_visible_snapshot_sha256"]
            hidden_hash = scenario["hidden_test_content_sha256"]
        refs = [entry["source_ref"] for entry in source["entries"]]
        required = {
            "record_type": "required_memory_label_ledger",
            "scenario_slot": slot,
            "source_ledger_sha256": source_hash,
            "required_source_refs": sorted(refs[-1:]),
        }
        relation = {
            "record_type": "relation_label_ledger",
            "scenario_slot": slot,
            "source_ledger_sha256": source_hash,
            "entries": [
                {
                    "opportunity_id": f"opp_{slot}_1",
                    "prior_source_ref": refs[0],
                    "candidate_source_ref": refs[1],
                    "relation_kind": "true_supersession",
                }
            ],
        }
        leakage = {
            "record_type": "leakage_review",
            "scenario_slot": slot,
            "fixture_sha256": fixture_hash,
            "source_ledger_sha256": source_hash,
            "model_visible_snapshot_sha256": snapshot_hash,
            "prompt_template_sha256": prompt_hash,
            "relation_label_sha256": sha256_bytes(canonical_bytes(relation)),
            "hidden_test_content_sha256": hidden_hash,
            "evaluator_image_digest": seed["evaluator_image_digest"],
            "verdict": "pass",
            "reason_codes": [
                "no_copied_source_text",
                "no_hidden_test_content_model_visible",
                "no_gold_source_ids_model_visible",
                "no_required_labels_model_visible",
                "no_relation_labels_model_visible",
            ],
        }
        contents[f"external__{slot}__required_memory_label_ledger"] = canonical_bytes(required)
        contents[f"external__{slot}__relation_label_ledger"] = canonical_bytes(relation)
        contents[f"external__{slot}__leakage_review"] = canonical_bytes(leakage)
    return contents


def build_seed_receipt(seed_sha256: str) -> dict[str, Any]:
    return {
        "record_type": "seed_receipt",
        "receipt_version": "review-receipt/4.1",
        "sequence": 1,
        "receipt_id": "seed_receipt_test",
        "review_seed_sha256": seed_sha256,
        "received_at": "2026-07-15T00:01:00Z",
        "receiver_role": "external-reviewer",
        "assurance": "procedural",
    }


def build_attestation(
    seed: dict[str, Any],
    seed_sha256: str,
    external_contents: dict[str, bytes] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = build_seed_receipt(seed_sha256)
    artifacts = []
    scopes = []
    for index, slot in enumerate(seed["external_artifact_slots"], start=1):
        artifacts.append(
            {
                "artifact_id": slot["artifact_id"],
                "scenario_slot": slot["scenario_slot"],
                "kind": slot["kind"],
                "content_sha256": sha256_bytes(
                    external_contents[slot["artifact_id"]]
                    if external_contents is not None
                    else f"external-{index}".encode()
                ),
                "canonicalization": slot["canonicalization"],
                "byte_length": (
                    len(external_contents[slot["artifact_id"]])
                    if external_contents is not None
                    else index + 10
                ),
                "reveal_phase": slot["reveal_phase"],
            }
        )
        scopes.append(
            {"scenario_slot": slot["scenario_slot"], "kind": slot["kind"]}
        )
    attestation = {
        "record_type": "external_review_attestation",
        "attestation_version": "review-attestation/4.1",
        "review_seed_sha256": seed_sha256,
        "seed_receipt_id": receipt["receipt_id"],
        "seed_receipt_sha256": sha256_bytes(canonical_bytes(receipt)),
        "reviewer_id": "reviewer_test",
        "reviewer_role": "external-reviewer",
        "reviewed_at": "2026-07-15T00:02:00Z",
        "external_artifacts": artifacts,
        "authorship_scopes": scopes,
        "no_variant_output_access_before_authorship": True,
        "external_custody_until_reveal": True,
    }
    return attestation, receipt

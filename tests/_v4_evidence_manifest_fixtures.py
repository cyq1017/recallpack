from __future__ import annotations

from tests._v4_evidence_common import (
    BUILD_CONTEXT_EXCLUSIONS,
    DEFAULT_LEAKAGE_REVIEW_TEXT,
    DEFAULT_MODEL_VISIBLE_SNAPSHOT_TEXT,
    DEFAULT_PROMPT_TEMPLATE_TEXT,
    DEFAULT_WRITABLE_PATHS,
    ENV_ALLOWLIST,
    V4_VARIANTS,
    artifact,
    canonical_sha256,
    canonical_json_bytes,
    digest,
    sha,
)

def _resolve_full_holdout(
    manifest: dict[str, object],
    holdout_bundle: dict[str, object] | None,
) -> dict[str, object] | None:
    if holdout_bundle is not None:
        return holdout_bundle
    for scenario in manifest.get("evidence_scenarios", []):
        artifact_id = scenario.get("source_ledger_artifact_id")
        if isinstance(artifact_id, str) and artifact_id.endswith("_hash"):
            raise ValueError("simulated_external_holdout is required for Full manifest fixtures")
    return None


def build_source_ledger(
    slot: str,
    *,
    duplicate_source_refs: bool = False,
    model_visible_flags: tuple[bool, bool, bool, bool] = (True, False, False, False),
) -> dict[str, object]:
    second_source_ref = f"{slot}:turn-001" if duplicate_source_refs else f"{slot}:turn-002"
    return {
        "record_type": "source_ledger",
        "scenario_slot": slot,
        "entries": [
            {
                "source_ref": f"{slot}:turn-001",
                "event_sha256": sha("a"),
                "model_visible": model_visible_flags[0],
            },
            {
                "source_ref": second_source_ref,
                "event_sha256": sha("b"),
                "model_visible": model_visible_flags[1],
            },
            {
                "source_ref": f"{slot}:turn-003",
                "event_sha256": sha("c"),
                "model_visible": model_visible_flags[2],
            },
            {
                "source_ref": f"{slot}:turn-004",
                "event_sha256": sha("d"),
                "model_visible": model_visible_flags[3],
            },
        ],
    }


def build_source_ledgers() -> dict[str, dict[str, object]]:
    return {
        "projectodyssey": build_source_ledger("projectodyssey"),
        "deepagents": build_source_ledger("deepagents"),
        "graphiti": build_source_ledger("graphiti"),
    }


def build_relation_label_ledger(
    slot: str,
    source_ledger: dict[str, object],
    *,
    entries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    refs = [
        entry["source_ref"]
        for entry in source_ledger["entries"]
        if isinstance(entry, dict) and isinstance(entry.get("source_ref"), str)
    ]
    ledger_entries = entries
    if ledger_entries is None:
        ledger_entries = [
            {
                "opportunity_id": f"opp_{slot}_hard_1",
                "prior_source_ref": refs[0],
                "candidate_source_ref": refs[1],
                "relation_kind": "hard_negative",
            },
            {
                "opportunity_id": f"opp_{slot}_true_1",
                "prior_source_ref": refs[2],
                "candidate_source_ref": refs[3],
                "relation_kind": "true_supersession",
            },
        ]
    return {
        "record_type": "relation_label_ledger",
        "scenario_slot": slot,
        "source_ledger_sha256": canonical_sha256(source_ledger),
        "entries": ledger_entries,
    }


def build_relation_label_ledgers(
    source_ledgers: dict[str, dict[str, object]] | None = None,
) -> dict[str, dict[str, object]]:
    ledgers = source_ledgers or build_source_ledgers()
    return {
        slot: build_relation_label_ledger(slot, ledger)
        for slot, ledger in ledgers.items()
    }


def build_simulated_external_holdout_bundle(
    slot: str = "holdout-a",
) -> dict[str, object]:
    # Contract-test-only helper. This simulates externally held custody so local
    # fixtures can exercise reveal-time validation without claiming real
    # headline holdout custody inside the implementation workspace.
    source_ledger = build_source_ledger(slot)
    relation_label_ledger = build_relation_label_ledger(slot, source_ledger)
    return {
        "scenario_slot": slot,
        "custody_kind": "simulated_external_contract_test_only",
        "source_ledger": source_ledger,
        "relation_label_ledger": relation_label_ledger,
        "source_ledger_sha256": canonical_sha256(source_ledger),
        "relation_label_ledger_sha256": canonical_sha256(relation_label_ledger),
    }


def build_comparison_contract() -> dict[str, object]:
    return {
        "budget_tokens": 512,
        "tokenizer": {
            "encoding": "o200k_base",
            "package": "tiktoken",
            "package_version": "0.13.0",
            "exact": True,
        },
        "repository_snapshot_artifact_id": "repo_snapshot",
        "patch_provider_contract_artifact_id": "patch_contract",
        "model_visible_snapshot_artifact_id": "model_visible_snapshot",
        "prompt_template_artifact_id": "prompt_template",
        "runner_contract_artifact_id": "runner_contract",
        "writable_paths": list(DEFAULT_WRITABLE_PATHS),
        "hidden_test_visibility": "after_model_output_fixed",
        "budget_scope": "budget_comparable_variants_only",
        "variant_input_policy": "identical_across_budget_comparable_variants",
        "variant_comparability": {
            "raw_full_history": {
                "budget_comparable": False,
                "budget_policy": "unbounded_reference",
                "headline_comparator_eligible": False,
            },
            "semantic_rerank": {
                "budget_comparable": True,
                "budget_policy": "exact_512_max",
                "headline_comparator_eligible": True,
            },
            "recency_aware": {
                "budget_comparable": True,
                "budget_policy": "exact_512_max",
                "headline_comparator_eligible": True,
            },
            "recall_time_resolver": {
                "budget_comparable": True,
                "budget_policy": "exact_512_max",
                "headline_comparator_eligible": True,
            },
            "recallpack": {
                "budget_comparable": True,
                "budget_policy": "exact_512_max",
                "headline_comparator_eligible": False,
            },
        },
        "variant_provider_role_contract": {
            "raw_full_history": {
                "required_roles": ["patch_generation"],
                "allowed_roles": ["patch_generation"],
                "repeatable_roles": [],
                "singleton_roles": ["patch_generation"],
            },
            "semantic_rerank": {
                "required_roles": ["embedding", "rerank", "patch_generation"],
                "allowed_roles": ["embedding", "rerank", "patch_generation"],
                "repeatable_roles": ["embedding"],
                "singleton_roles": ["rerank", "patch_generation"],
            },
            "recency_aware": {
                "required_roles": ["embedding", "rerank", "patch_generation"],
                "allowed_roles": ["embedding", "rerank", "patch_generation"],
                "repeatable_roles": ["embedding"],
                "singleton_roles": ["rerank", "patch_generation"],
            },
            "recall_time_resolver": {
                "required_roles": [
                    "memory_decision",
                    "embedding",
                    "rerank",
                    "patch_generation",
                ],
                "allowed_roles": [
                    "memory_decision",
                    "embedding",
                    "rerank",
                    "patch_generation",
                ],
                "repeatable_roles": ["memory_decision", "embedding"],
                "singleton_roles": ["rerank", "patch_generation"],
            },
            "recallpack": {
                "required_roles": [
                    "memory_decision",
                    "embedding",
                    "rerank",
                    "patch_generation",
                ],
                "allowed_roles": [
                    "memory_decision",
                    "embedding",
                    "rerank",
                    "patch_generation",
                ],
                "repeatable_roles": ["memory_decision", "embedding"],
                "singleton_roles": ["rerank", "patch_generation"],
            },
        },
    }


def build_evaluator_contract() -> dict[str, object]:
    return {
        "platform": "linux/amd64",
        "image_digest": digest("1"),
        "base_image_digest": digest("2"),
        "dockerfile_artifact_id": "dockerfile",
        "runner_artifact_id": "runner",
        "build_context_root": "evaluation/",
        "build_context_exclusions": list(BUILD_CONTEXT_EXCLUSIONS),
        "environment_allowlist": list(ENV_ALLOWLIST),
        "host_root_keys": {
            "repository": "RECALLPACK_EVALUATOR_REPO_ROOT",
            "hidden_tests": "RECALLPACK_EVALUATOR_HIDDEN_TEST_ROOT",
        },
        "host_path_policy": {
            "mount_source_rule": "realpath_equals_configured_root",
            "configured_roots_must_be_absolute": True,
            "repository_and_hidden_tests_distinct": True,
            "symlink_escape": "reject",
            "record_resolved_paths": False,
        },
        "container_paths": {
            "repository": "/workspace/repo",
            "hidden_tests": "/workspace/hidden-tests",
            "tmp": "/tmp",
        },
        "resource_limits": {
            "cpus": 1,
            "memory_bytes": 1073741824,
            "pids": 128,
            "wall_timeout_seconds": 120,
            "tmpfs_size_bytes": 67108864,
        },
        "execution_user": {
            "username": "recallpack",
            "uid": 65532,
            "gid": 65532,
            "non_root": True,
        },
        "isolation_flags": {
            "network": "none",
            "read_only_root": True,
            "drop_all_capabilities": True,
            "no_new_privileges": True,
            "docker_socket_mounted": False,
            "tmp_is_tmpfs": True,
            "repository_mount_mode": "rw",
            "hidden_test_mount_mode": "ro",
        },
        "build_record_artifact_id": "image_build_record",
    }


def build_public_provenance(slot: str, char: str) -> dict[str, object]:
    return {
        "source_urls": [f"https://example.com/{slot}"],
        "commit_refs": [f"{char * 7}"],
        "license_id": "Apache-2.0",
        "authored_summary_sha256": sha(char),
    }


def _build_image_build_record_for_manifest(manifest: dict[str, object]) -> dict[str, object]:
    dockerfile_bytes = (
        f"FROM ghcr.io/recallpack/base@{manifest['evaluator_contract']['base_image_digest']}\n"
    ).encode("utf-8")
    runner_bytes = b"print('runner placeholder')\n"
    return {
        "record_type": "image_build_record",
        "builder": "docker_buildx",
        "platform": "linux/amd64",
        "build_context_root": "evaluation/",
        "build_context_sha256": sha("c"),
        "dockerfile_artifact_id": "dockerfile",
        "dockerfile_sha256": artifact("dockerfile", "evaluation/Dockerfile", dockerfile_bytes)[
            "sha256"
        ],
        "runner_artifact_id": "runner",
        "runner_sha256": artifact(
            "evaluator_runner",
            "evaluation/runner/run_tests.py",
            runner_bytes,
        )["sha256"],
        "dockerfile_from_base_image_digest": manifest["evaluator_contract"][
            "base_image_digest"
        ],
        "output_image_digest": manifest["evaluator_contract"]["image_digest"],
    }


def build_image_build_record() -> dict[str, object]:
    manifest = {"evaluator_contract": build_evaluator_contract()}
    return _build_image_build_record_for_manifest(manifest)


def build_execution_input_artifact_bytes(
    manifest: dict[str, object],
    *,
    source_ledgers: dict[str, dict[str, object]] | None = None,
    simulated_external_holdout: dict[str, object] | None = None,
    model_visible_snapshot_text: str = DEFAULT_MODEL_VISIBLE_SNAPSHOT_TEXT,
    prompt_template_text: str = DEFAULT_PROMPT_TEMPLATE_TEXT,
    leakage_review_text: str = DEFAULT_LEAKAGE_REVIEW_TEXT,
) -> dict[str, bytes]:
    ledgers = source_ledgers or build_source_ledgers()
    holdout_bundle = _resolve_full_holdout(manifest, simulated_external_holdout)
    artifact_bytes: dict[str, bytes] = {
        "repo_snapshot": b"repository snapshot placeholder",
        "patch_contract": b"patch provider contract placeholder",
        "model_visible_snapshot": model_visible_snapshot_text.encode("utf-8"),
        "prompt_template": prompt_template_text.encode("utf-8"),
        "runner_contract": b"runner contract placeholder",
        "dockerfile": (
            f"FROM ghcr.io/recallpack/base@{manifest['evaluator_contract']['base_image_digest']}\n"
        ).encode("utf-8"),
        "runner": b"print('runner placeholder')\n",
    }
    artifact_bytes["image_build_record"] = canonical_json_bytes(
        _build_image_build_record_for_manifest(manifest)
    )
    for scenario in manifest["evidence_scenarios"]:
        slot = scenario["scenario_slot"]
        artifact_bytes[scenario["fixture_artifact_id"]] = f"fixture {slot}".encode("utf-8")
        artifact_bytes[scenario["label_hash_artifact_id"]] = scenario[
            "relation_label_ledger_sha256"
        ].encode("utf-8")
        artifact_bytes[scenario["hidden_test_hash_artifact_id"]] = sha("2").encode("utf-8")
        artifact_bytes[scenario["leakage_review_artifact_id"]] = leakage_review_text.encode(
            "utf-8"
        )
        source_ledger_artifact_id = scenario["source_ledger_artifact_id"]
        if source_ledger_artifact_id.endswith("_hash"):
            if holdout_bundle is not None and slot == holdout_bundle["scenario_slot"]:
                artifact_bytes[source_ledger_artifact_id] = holdout_bundle[
                    "source_ledger_sha256"
                ].encode("utf-8")
            else:
                source_ledger_key = slot
                if source_ledger_key not in ledgers:
                    source_ledger_key = source_ledger_artifact_id.removeprefix(
                        "ledger_"
                    ).removesuffix("_hash")
                artifact_bytes[source_ledger_artifact_id] = canonical_sha256(
                    ledgers[source_ledger_key]
                ).encode("utf-8")
        else:
            source_ledger_key = slot
            if source_ledger_key not in ledgers:
                source_ledger_key = source_ledger_artifact_id.removeprefix("ledger_")
            artifact_bytes[source_ledger_artifact_id] = canonical_json_bytes(
                ledgers[source_ledger_key]
            )
    return artifact_bytes


def build_input_artifact_catalog(
    manifest: dict[str, object],
    *,
    source_ledgers: dict[str, dict[str, object]] | None = None,
    simulated_external_holdout: dict[str, object] | None = None,
) -> dict[str, object]:
    payloads = build_execution_input_artifact_bytes(
        manifest,
        source_ledgers=source_ledgers,
        simulated_external_holdout=simulated_external_holdout,
    )
    catalog = {
        "repo_snapshot": artifact(
            "repository_snapshot",
            "snapshots/repo.tar",
            payloads["repo_snapshot"],
        ),
        "patch_contract": artifact(
            "patch_provider_contract",
            "contracts/patch.md",
            payloads["patch_contract"],
        ),
        "model_visible_snapshot": artifact(
            "model_visible_snapshot",
            "snapshots/model-visible.txt",
            payloads["model_visible_snapshot"],
        ),
        "prompt_template": artifact(
            "prompt_template",
            "prompts/patch.txt",
            payloads["prompt_template"],
        ),
        "runner_contract": artifact(
            "runner_contract",
            "contracts/runner.md",
            payloads["runner_contract"],
        ),
        "dockerfile": artifact(
            "dockerfile",
            "evaluation/Dockerfile",
            payloads["dockerfile"],
        ),
        "runner": artifact(
            "evaluator_runner",
            "evaluation/runner/run_tests.py",
            payloads["runner"],
        ),
        "image_build_record": artifact(
            "image_build_record",
            "evaluation/image-build-record.json",
            payloads["image_build_record"],
        ),
    }
    for scenario in manifest["evidence_scenarios"]:
        scenario_slot = scenario["scenario_slot"]
        fixture_artifact_id = scenario["fixture_artifact_id"]
        label_artifact_id = scenario["label_hash_artifact_id"]
        hidden_artifact_id = scenario["hidden_test_hash_artifact_id"]
        leakage_artifact_id = scenario["leakage_review_artifact_id"]
        ledger_artifact_id = scenario["source_ledger_artifact_id"]

        catalog[fixture_artifact_id] = artifact(
            "fixture",
            f"fixtures/{scenario_slot}.json",
            payloads[fixture_artifact_id],
        )
        catalog[label_artifact_id] = artifact(
            "label_hash",
            f"labels/{scenario_slot}.sha256",
            payloads[label_artifact_id],
        )
        catalog[hidden_artifact_id] = artifact(
            "hidden_test_hash",
            f"hidden/{scenario_slot}.sha256",
            payloads[hidden_artifact_id],
        )
        catalog[leakage_artifact_id] = artifact(
            "leakage_review",
            f"reviews/{scenario_slot}.md",
            payloads[leakage_artifact_id],
        )
        if ledger_artifact_id.endswith("_hash"):
            catalog[ledger_artifact_id] = artifact(
                "source_ledger_hash",
                f"ledgers/{scenario_slot}.sha256",
                payloads[ledger_artifact_id],
            )
        else:
            catalog[ledger_artifact_id] = artifact(
                "source_ledger",
                f"ledgers/{scenario_slot}.json",
                payloads[ledger_artifact_id],
            )
    return catalog


def build_full_execution_manifest(
    *,
    source_ledgers: dict[str, dict[str, object]] | None = None,
    relation_label_ledgers: dict[str, dict[str, object]] | None = None,
    simulated_external_holdout: dict[str, object] | None = None,
) -> dict[str, object]:
    if simulated_external_holdout is None:
        raise ValueError("simulated_external_holdout is required for Full manifest fixtures")
    source_ledgers = source_ledgers or build_source_ledgers()
    relation_label_ledgers = relation_label_ledgers or build_relation_label_ledgers(
        source_ledgers
    )
    holdout_bundle = simulated_external_holdout
    scenario_slots = ["projectodyssey", "deepagents", "graphiti", "holdout-a"]
    execution_order = []
    slot_index = 0
    for scenario_slot in scenario_slots:
        for variant_id in V4_VARIANTS:
            for repetition in range(1, 4):
                execution_order.append(
                    {
                        "slot_id": f"slot_{scenario_slot}_{variant_id}_{repetition}",
                        "slot_index": slot_index,
                        "scenario_slot": scenario_slot,
                        "variant_id": variant_id,
                        "repetition": repetition,
                        "planned_designation": "headline",
                    }
                )
                slot_index += 1
    manifest = {
        "record_type": "execution_manifest",
        "manifest_version": "v4-full",
        "created_at": "2026-07-12T00:00:00Z",
        "descope_rung": "Full",
        "semantic_rules_version": "4.0",
        "code_hashes": {"app": sha("7")},
        "scenario_slots": scenario_slots,
        "evidence_scenarios": [
            {
                "scenario_slot": "projectodyssey",
                "evidence_class": "source_backed_synthetic",
                "custody_state": "externally_reviewed",
                "fixture_artifact_id": "fixture_projectodyssey",
                "label_hash_artifact_id": "label_projectodyssey",
                "hidden_test_hash_artifact_id": "hidden_projectodyssey",
                "leakage_review_artifact_id": "leakage_projectodyssey",
                "source_ledger_artifact_id": "ledger_projectodyssey",
                "relation_label_ledger_sha256": canonical_sha256(
                    relation_label_ledgers["projectodyssey"]
                ),
                "provenance": build_public_provenance("projectodyssey", "5"),
            },
            {
                "scenario_slot": "deepagents",
                "evidence_class": "source_backed_synthetic",
                "custody_state": "externally_reviewed",
                "fixture_artifact_id": "fixture_deepagents",
                "label_hash_artifact_id": "label_deepagents",
                "hidden_test_hash_artifact_id": "hidden_deepagents",
                "leakage_review_artifact_id": "leakage_deepagents",
                "source_ledger_artifact_id": "ledger_deepagents",
                "relation_label_ledger_sha256": canonical_sha256(
                    relation_label_ledgers["deepagents"]
                ),
                "provenance": build_public_provenance("deepagents", "6"),
            },
            {
                "scenario_slot": "graphiti",
                "evidence_class": "source_backed_synthetic",
                "custody_state": "revealed_for_scoring",
                "fixture_artifact_id": "fixture_graphiti",
                "label_hash_artifact_id": "label_graphiti",
                "hidden_test_hash_artifact_id": "hidden_graphiti",
                "leakage_review_artifact_id": "leakage_graphiti",
                "source_ledger_artifact_id": "ledger_graphiti",
                "relation_label_ledger_sha256": canonical_sha256(
                    relation_label_ledgers["graphiti"]
                ),
                "provenance": build_public_provenance("graphiti", "8"),
            },
            {
                "scenario_slot": "holdout-a",
                "evidence_class": "blind_holdout",
                "custody_state": "sealed_external",
                "fixture_artifact_id": "fixture_holdout",
                "label_hash_artifact_id": "label_holdout",
                "hidden_test_hash_artifact_id": "hidden_holdout",
                "leakage_review_artifact_id": "leakage_holdout",
                "source_ledger_artifact_id": "ledger_holdout_hash",
                "relation_label_ledger_sha256": holdout_bundle["relation_label_ledger_sha256"],
                "provenance": None,
            },
        ],
        "fixture_hashes": {slot: sha("8") for slot in scenario_slots},
        "label_hashes": {
            "projectodyssey": canonical_sha256(relation_label_ledgers["projectodyssey"]),
            "deepagents": canonical_sha256(relation_label_ledgers["deepagents"]),
            "graphiti": canonical_sha256(relation_label_ledgers["graphiti"]),
            "holdout-a": holdout_bundle["relation_label_ledger_sha256"],
        },
        "hidden_test_hashes": {slot: sha("a") for slot in scenario_slots},
        "variants": list(V4_VARIANTS),
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
        "comparison_contract": build_comparison_contract(),
        "evaluator_contract": build_evaluator_contract(),
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
                "limitations": ["Requires exact manifest coverage."],
            },
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
        ],
        "review": {
            "reviewer_role": "external-reviewer",
            "manifest_review_sha256": sha("b"),
            "leakage_review_hashes": {slot: sha("c") for slot in scenario_slots},
        },
        "evaluator_image_digest": digest("1"),
    }
    manifest["input_artifact_catalog"] = build_input_artifact_catalog(
        manifest,
        source_ledgers=source_ledgers,
        simulated_external_holdout=holdout_bundle,
    )
    return manifest


def build_floor_execution_manifest(
    *,
    source_ledgers: dict[str, dict[str, object]] | None = None,
    relation_label_ledgers: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    source_ledgers = source_ledgers or {"diag-project-a": build_source_ledger("diag-project-a")}
    relation_label_ledgers = relation_label_ledgers or {
        "diag-project-a": build_relation_label_ledger(
            "diag-project-a",
            source_ledgers["diag-project-a"],
            entries=[],
        )
    }
    manifest = {
        "record_type": "execution_manifest",
        "manifest_version": "v4-floor-diag",
        "created_at": "2026-07-12T00:00:00Z",
        "descope_rung": "Floor",
        "semantic_rules_version": "4.0",
        "code_hashes": {"app": sha("d")},
        "scenario_slots": ["diag-project-a"],
        "evidence_scenarios": [
            {
                "scenario_slot": "diag-project-a",
                "evidence_class": "deterministic_diagnostic",
                "custody_state": "workspace_diagnostic",
                "fixture_artifact_id": "fixture_projectodyssey",
                "label_hash_artifact_id": "label_projectodyssey",
                "hidden_test_hash_artifact_id": "hidden_projectodyssey",
                "leakage_review_artifact_id": "leakage_projectodyssey",
                "source_ledger_artifact_id": "ledger_projectodyssey",
                "relation_label_ledger_sha256": canonical_sha256(
                    relation_label_ledgers["diag-project-a"]
                ),
                "provenance": None,
            }
        ],
        "fixture_hashes": {"diag-project-a": sha("e")},
        "label_hashes": {
            "diag-project-a": canonical_sha256(relation_label_ledgers["diag-project-a"])
        },
        "hidden_test_hashes": {"diag-project-a": sha("0")},
        "variants": list(V4_VARIANTS),
        "provider_settings": {
            "mode": "fake",
            "provider_family": "deterministic_fake",
            "deterministic_fallback": True,
            "models": {
                "memory_decision": "deterministic-memory",
                "embedding": "deterministic-embedding",
                "rerank": "deterministic-rerank",
                "patch_generation": "deterministic-patch",
            },
            "temperature": 0,
            "seed": 7,
            "endpoint_region": "offline",
        },
        "comparison_contract": build_comparison_contract(),
        "evaluator_contract": build_evaluator_contract(),
        "technical_failure_codes": [
            "sandbox_unavailable",
            "sandbox_timeout",
            "provider_timeout",
        ],
        "execution_order": [],
        "claim_declarations": [
            {
                "claim_id": "claim_structural_runtime",
                "claim_type": "structural_runtime",
                "activation_rule_id": "structural_runtime_gate",
                "eligible_rungs": ["Full", "R1", "R2", "Floor"],
                "statement": "The frozen runtime and evaluator contract executed deterministically.",
                "rerunnable_command": "PYTHONPATH=src .venv/bin/python3 -m unittest tests.test_hero_evaluation",
                "limitations": [
                    "Floor is diagnostic-only.",
                    "No live or superiority claim is allowed.",
                ],
            }
        ],
        "review": {
            "reviewer_role": "implementation-review",
            "manifest_review_sha256": sha("1"),
            "leakage_review_hashes": {"diag-project-a": sha("2")},
        },
        "evaluator_image_digest": digest("1"),
    }
    for index, variant_id in enumerate(V4_VARIANTS):
        manifest["execution_order"].append(
            {
                "slot_id": f"slot_diag-{variant_id}",
                "slot_index": index,
                "scenario_slot": "diag-project-a",
                "variant_id": variant_id,
                "repetition": 1,
                "planned_designation": "diagnostic",
            }
        )
    manifest["input_artifact_catalog"] = build_input_artifact_catalog(
        manifest,
        source_ledgers=source_ledgers,
    )
    return manifest
